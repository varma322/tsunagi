package com.vce.tsunagi.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.flow.Flow

object SyncScheduler {

    private const val IMMEDIATE_WORK = "tsunagi-sync-now"
    private const val PERIODIC_WORK = "tsunagi-sync-periodic"

    private val networkRequired = Constraints.Builder()
        .setRequiredNetworkType(NetworkType.CONNECTED)
        .build()

    /** Queues an upload attempt, typically right after an SMS is captured. */
    fun syncNow(context: Context) {
        val request = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(networkRequired)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()

        // APPEND_OR_REPLACE rather than KEEP: a message captured while a sync is
        // already running still needs a pass of its own afterwards.
        WorkManager.getInstance(context)
            .enqueueUniqueWork(IMMEDIATE_WORK, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
    }

    /**
     * Safety net for messages captured while offline, or left behind by a run
     * that exhausted its retries.
     */
    fun ensurePeriodicSync(context: Context) {
        val request = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(networkRequired)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 1, TimeUnit.MINUTES)
            .build()

        WorkManager.getInstance(context)
            .enqueueUniquePeriodicWork(PERIODIC_WORK, ExistingPeriodicWorkPolicy.KEEP, request)
    }

    fun observeSyncWork(context: Context): Flow<List<WorkInfo>> =
        WorkManager.getInstance(context).getWorkInfosForUniqueWorkFlow(IMMEDIATE_WORK)
}
