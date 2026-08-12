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
        if (intent.action != Telephony.Sms.Intents.SMS_RECEIVED_ACTION) return

        val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
        val captured = assemble(parts)
        if (captured.isEmpty()) return

        val repository = TsunagiApplication.container(context).repository
        val pendingResult = goAsync()
        val appContext = context.applicationContext

        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            try {
                var stored = 0
                for (message in captured) {
                    if (repository.captureSms(message.sender, message.body, message.receivedAt)) {
                        stored++
                    }
                }
                if (stored > 0) {
                    Log.i(TAG, "captured $stored message(s)")
                    SyncScheduler.syncNow(appContext)
                }
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
            if (currentBody.isNotEmpty()) {
                assembled += CapturedSms(sender, currentBody.toString(), currentTimestamp)
            }
        }

        for (part in parts) {
            val sender = part.displayOriginatingAddress ?: part.originatingAddress ?: UNKNOWN_SENDER
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
