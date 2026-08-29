package com.vce.tsunagi.sms

import android.content.Context
import android.provider.Telephony
import android.util.Log
import com.vce.tsunagi.data.InboxMessage
import com.vce.tsunagi.data.InboxRead
import com.vce.tsunagi.data.InboxSource
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Reads delivered messages back out of the platform SMS provider.
 *
 * This exists because the live broadcast cannot be relied on by itself. It is
 * not delivered at all while the app is in the stopped state — which is where
 * a force-stop or an aggressive battery manager puts it, with no callback and
 * no log line to say so — and it can also be lost to process death between
 * delivery and the database write. Neither case is detectable from inside the
 * receiver, so the only way to notice a miss is to compare against the copy
 * the platform keeps.
 */
class SmsInbox(context: Context) : InboxSource {

    private val resolver = context.applicationContext.contentResolver

    override suspend fun since(cutoff: Long, limit: Int): InboxRead =
        withContext(Dispatchers.IO) { read(cutoff, limit) }

    private fun read(cutoff: Long, limit: Int): InboxRead {
        val found = mutableListOf<InboxMessage>()
        try {
            resolver.query(
                Telephony.Sms.Inbox.CONTENT_URI,
                arrayOf(
                    Telephony.Sms.ADDRESS,
                    Telephony.Sms.BODY,
                    Telephony.Sms.DATE,
                    Telephony.Sms.DATE_SENT,
                ),
                "${Telephony.Sms.DATE} > ?",
                arrayOf(cutoff.toString()),
                "${Telephony.Sms.DATE} ASC LIMIT $limit",
            )?.use { cursor ->
                val addressColumn = cursor.getColumnIndexOrThrow(Telephony.Sms.ADDRESS)
                val bodyColumn = cursor.getColumnIndexOrThrow(Telephony.Sms.BODY)
                val dateColumn = cursor.getColumnIndexOrThrow(Telephony.Sms.DATE)
                val sentColumn = cursor.getColumnIndexOrThrow(Telephony.Sms.DATE_SENT)

                // The LIMIT rides on the sort order, which the platform
                // provider honours but is not obliged to. Stopping here too
                // keeps a phone with a huge inbox from being read into memory
                // whole if it is ignored. Rows arrive oldest first, so the
                // watermark still advances over exactly what was examined.
                while (found.size < limit && cursor.moveToNext()) {
                    val storedAt = cursor.getLong(dateColumn)
                    // DATE_SENT is the service centre timestamp, which is what
                    // the broadcast reports and therefore what a message must
                    // be matched on. Some devices and some messages leave it
                    // at zero, so fall back to the store time.
                    val sentAt = cursor.getLong(sentColumn).takeIf { it > 0L } ?: storedAt
                    found += InboxMessage(
                        sender = cursor.getString(addressColumn)?.takeIf(String::isNotBlank)
                            ?: UNKNOWN_SENDER,
                        body = cursor.getString(bodyColumn).orEmpty(),
                        receivedAt = sentAt,
                        storedAt = storedAt,
                    )
                }
            }
        } catch (error: SecurityException) {
            // READ_SMS revoked after it was granted. Reporting nothing found
            // would advance the watermark past messages never examined, and
            // would tell the server this phone is fine when it has just lost
            // its only defence against a missed broadcast.
            Log.w(TAG, "cannot read the SMS inbox: permission denied")
            return InboxRead.Unavailable("SMS permission denied")
        } catch (error: Exception) {
            Log.e(TAG, "failed to read the SMS inbox", error)
            return InboxRead.Unavailable(error.message ?: error.javaClass.simpleName)
        }
        return InboxRead.Read(found)
    }

    private companion object {
        const val TAG = "SmsInbox"
        const val UNKNOWN_SENDER = "unknown"
    }
}
