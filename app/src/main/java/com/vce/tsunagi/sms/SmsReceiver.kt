package com.vce.tsunagi.sms

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.provider.Telephony
import android.telephony.SmsMessage
import android.util.Log
import com.vce.tsunagi.TsunagiApplication
import com.vce.tsunagi.sync.SyncScheduler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

/**
 * Captures incoming SMS and queues them for upload.
 *
 * onReceive runs on the main thread with a short lifetime, so the database
 * write is moved into a coroutine held open by goAsync().
 */
class SmsReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        // Logged before any filtering: if a message never reaches the app at
        // all, the absence of this line is the evidence. Only metadata is
        // recorded -- never message contents.
        Log.i(TAG, "broadcast action=${intent.action}")

        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return

        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent)
        if (parts == null) {
            Log.w(TAG, "broadcast carried no parsable PDUs")
            return
        }
        Log.i(TAG, "received ${parts.size} PDU part(s)")
        parts.forEachIndexed { index, part ->
            Log.i(
                TAG,
                "  part $index from=${part.displayOriginatingAddress ?: part.originatingAddress} " +
                    "bodyChars=${(part.displayMessageBody ?: part.messageBody)?.length ?: 0}",
            )
        }

        val captured = assemble(parts)
        if (captured.isEmpty()) {
            Log.w(TAG, "PDUs assembled into zero messages")
            return
        }
        Log.i(TAG, "assembled ${captured.size} message(s)")

        val repository = TsunagiApplication.container(context).repository
        val pendingResult = goAsync()
        val appContext = context.applicationContext

        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            try {
                var stored = 0
                for (message in captured) {
                    // Per message, not per broadcast: one that cannot be
                    // stored must not take the rest of the broadcast with it.
                    try {
                        if (repository.captureSms(
                                message.sender,
                                message.body,
                                message.receivedAt,
                            )
                        ) {
                            stored++
                        }
                    } catch (error: Exception) {
                        Log.e(TAG, "failed to store message from ${message.sender}", error)
                    }
                }
                Log.i(TAG, "stored $stored of ${captured.size} message(s)")
                // Always, even when nothing was stored. A message that only
                // looked like a duplicate still deserves a pass, and the sweep
                // that runs with it is what recovers anything dropped here.
                SyncScheduler.syncNow(appContext)
            } catch (error: Exception) {
                // Never let a capture failure crash the system broadcast.
                Log.e(TAG, "failed to store incoming SMS", error)
            } finally {
                pendingResult.finish()
            }
        }
    }

    /**
     * A long SMS arrives as several PDUs that must be stitched back together.
     * Parts of one message share an originating address and arrive in order.
     */
    private fun assemble(parts: Array<SmsMessage>): List<CapturedSms> {
        val assembled = mutableListOf<CapturedSms>()
        var currentSender: String? = null
        var currentBody = StringBuilder()
        var currentTimestamp = 0L

        fun flush() {
            val sender = currentSender ?: return
            // Stored even when the body came back empty. Dropping it here lost
            // the message with nothing recorded but a count, and an empty body
            // is something the server accepts and the user can see.
            assembled += CapturedSms(sender, currentBody.toString(), currentTimestamp)
        }

        for (part in parts) {
            // Blank counts as absent, not just null. An empty originating
            // address reaches the server as a sender it rejects outright, and
            // a rejected message used to stall every message behind it.
            val sender = part.displayOriginatingAddress?.takeIf(String::isNotBlank)
                ?: part.originatingAddress?.takeIf(String::isNotBlank)
                ?: UNKNOWN_SENDER
            if (sender != currentSender) {
                flush()
                currentSender = sender
                currentBody = StringBuilder()
                currentTimestamp = part.timestampMillis
            }
            currentBody.append(part.displayMessageBody ?: part.messageBody.orEmpty())
        }
        flush()

        return assembled
    }

    private data class CapturedSms(val sender: String, val body: String, val receivedAt: Long)

    private companion object {
        const val TAG = "SmsReceiver"
        const val UNKNOWN_SENDER = "unknown"
    }
}
