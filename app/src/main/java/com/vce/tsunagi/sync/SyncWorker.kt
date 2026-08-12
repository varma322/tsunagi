package com.vce.tsunagi.sync

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.vce.tsunagi.TsunagiApplication
import com.vce.tsunagi.data.SyncOutcome

/**
 * Drains the local message queue to the server.
 *
 * Uploads are at-least-once: a message stays queued until the server confirms
 * it, and the server deduplicates by the client-generated id.
 */
class SyncWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val container = TsunagiApplication.container(applicationContext)
        val settings = container.settings

        return when (val outcome = container.repository.sync()) {
            is SyncOutcome.Success -> {
                Log.i(TAG, "uploaded ${outcome.uploaded} message(s)")
                settings.recordSyncSuccess(System.currentTimeMillis())
                Result.success()
            }

            is SyncOutcome.Idle -> {
                Log.d(TAG, "nothing to sync: ${outcome.reason}")
                Result.success()
            }

            is SyncOutcome.Retry -> {
                Log.w(TAG, "sync will retry: ${outcome.reason}")
                settings.recordSyncFailure(outcome.reason)
                Result.retry()
            }

            is SyncOutcome.Failure -> {
                // Retrying unchanged cannot succeed; the periodic worker picks
                // this up again once the user fixes the configuration.
                Log.e(TAG, "sync failed: ${outcome.reason}")
                settings.recordSyncFailure(outcome.reason)
                Result.failure()
            }
        }
    }

    private companion object {
        const val TAG = "SyncWorker"
    }
}
