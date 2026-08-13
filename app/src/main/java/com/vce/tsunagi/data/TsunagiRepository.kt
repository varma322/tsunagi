package com.vce.tsunagi.data

import android.util.Log
import com.vce.tsunagi.data.local.DeviceDao
import com.vce.tsunagi.data.local.DeviceEntity
import com.vce.tsunagi.data.local.MessageDao
import com.vce.tsunagi.data.local.MessageEntity
import com.vce.tsunagi.data.local.SyncStatus
import com.vce.tsunagi.data.remote.ApiFactory
import com.vce.tsunagi.data.remote.BatchRequest
import com.vce.tsunagi.data.remote.MessageUpload
import com.vce.tsunagi.data.remote.RegisterRequest
import com.vce.tsunagi.data.remote.TsunagiApi
import java.io.IOException
import java.time.Instant
import kotlinx.coroutines.flow.Flow
import retrofit2.HttpException

/** Outcome of one sync pass, mapped to a WorkManager result by the worker. */
sealed interface SyncOutcome {
    /** Nothing to do: no pending messages, or the app is not configured yet. */
    data class Idle(val reason: String) : SyncOutcome

    data class Success(val uploaded: Int) : SyncOutcome

    /** Transient problem; worth retrying with backoff. */
    data class Retry(val reason: String) : SyncOutcome

    /** Permanent problem; retrying unchanged will not help. */
    data class Failure(val reason: String) : SyncOutcome
}

class TsunagiRepository(
    private val deviceDao: DeviceDao,
    private val messageDao: MessageDao,
    private val settings: SyncSettings,
    private val apiProvider: (String) -> TsunagiApi = ApiFactory::create,
    private val inbox: InboxSource = InboxSource.Empty,
) {

    fun observeDevice(): Flow<DeviceEntity?> = deviceDao.observe()

    fun observeStatusCounts() = messageDao.observeStatusCounts()

    fun observeRecent(limit: Int = 20): Flow<List<MessageEntity>> = messageDao.observeRecent(limit)

    fun observeTotal(): Flow<Int> = messageDao.observeTotal()

    suspend fun pendingCount(): Int = messageDao.pendingCount()

    /**
     * Stores a captured SMS. Returns false when this message was already
     * stored, which happens if the SMS broadcast is delivered more than once,
     * or if [backfill] re-reads a message the broadcast already caught.
     *
     * The id is derived from the message rather than drawn at random, which is
     * what makes that check work at all: two sightings of one SMS produce the
     * same id and collapse onto one row.
     */
    suspend fun captureSms(sender: String, body: String, receivedAt: Long): Boolean {
        val rowId = messageDao.insert(
            MessageEntity(
                id = MessageIdentity.of(sender, body, receivedAt),
                sender = sender,
                body = body,
                receivedAt = receivedAt,
            )
        )
        return rowId != -1L
    }

    /**
     * Recovers messages the live broadcast never delivered.
     *
     * The broadcast is best-effort: none arrive while the app sits in the
     * stopped state, where a force-stop or a battery manager can park it
     * silently, and one can be lost to process death between delivery and the
     * write. Neither is visible from the receiver, so the queue is reconciled
     * against the platform's own copy instead of trusting that every broadcast
     * arrived.
     *
     * Returns the number of messages recovered.
     */
    suspend fun backfill(): Int {
        val now = System.currentTimeMillis()
        val watermark = settings.snapshot().lastBackfillAt
            // A first sweep starts from a bounded look-back. Reading from zero
            // would upload the phone's entire message history on install,
            // which is a surprise rather than a recovery.
            ?: (now - INITIAL_BACKFILL_LOOKBACK_MILLIS)

        // Re-read a little of what was already swept: the watermark is a
        // provider timestamp, and a message can be written to the store just
        // behind one already read. The id check makes the overlap free.
        val cutoff = (watermark - BACKFILL_OVERLAP_MILLIS).coerceAtLeast(0)

        val candidates = inbox.since(cutoff, BACKFILL_SCAN_LIMIT)
        if (candidates.isEmpty()) return 0

        var recovered = 0
        for (candidate in candidates) {
            if (storeIfMissing(candidate)) recovered++
        }

        // Advance only as far as what was actually examined. A sweep cut short
        // by the scan limit leaves the rest for the next pass rather than
        // stepping over it.
        val examined = candidates.maxOf { it.storedAt }
        settings.recordBackfill(examined)

        if (recovered > 0) {
            Log.w(
                TAG,
                "inbox sweep recovered $recovered message(s) the broadcast did not deliver",
            )
        }
        return recovered
    }

    /** True when the message was missing and has now been stored. */
    private suspend fun storeIfMissing(candidate: InboxMessage): Boolean {
        // The derived id catches the ordinary case, where both sightings agree
        // on the timestamp. They disagree when the platform did not record a
        // service centre time, so fall back to matching on content near the
        // same moment rather than storing a second copy.
        val near = messageDao.existsNear(
            sender = candidate.sender,
            body = candidate.body,
            from = candidate.receivedAt - BACKFILL_MATCH_WINDOW_MILLIS,
            to = candidate.receivedAt + BACKFILL_MATCH_WINDOW_MILLIS,
        )
        if (near) return false
        return captureSms(candidate.sender, candidate.body, candidate.receivedAt)
    }

    suspend fun currentDevice(): DeviceEntity? = deviceDao.get()

    suspend fun forgetDevice() = deviceDao.clear()

    /**
     * Runs one sync pass: recovers anything the broadcast missed, registers
     * the device if needed, then uploads every pending message in batches.
     */
    suspend fun sync(): SyncOutcome {
        val config = settings.snapshot()
        if (!config.isConfigured) {
            return SyncOutcome.Idle("Server URL and device name are not set yet.")
        }

        val api = try {
            apiProvider(config.serverUrl)
        } catch (error: IllegalArgumentException) {
            return SyncOutcome.Failure("Invalid server URL: ${error.message}")
        }

        // Before uploading, not after: a message recovered here should leave
        // on this pass rather than waiting for the next one.
        try {
            backfill()
        } catch (error: Exception) {
            // The sweep is a safety net. If it fails, the messages the
            // broadcast did deliver must still go up.
            Log.e(TAG, "inbox sweep failed", error)
        }

        // A crash mid-upload can strand rows in UPLOADING; put them back in line.
        messageDao.requeueStranded()

        val device = when (val registration = ensureRegistered(api, config)) {
            is Registration.Ready -> registration.device
            is Registration.Problem -> return registration.outcome
        }

        var uploaded = 0
        // Narrowed to a single message once the server rejects a batch on its
        // contents, so the offender can be found rather than guessed at.
        var batchSize = BATCH_SIZE

        while (true) {
            val batch = messageDao.pendingBatch(batchSize)
            if (batch.isEmpty()) break

            val ids = batch.map { it.id }
            messageDao.markStatus(ids, SyncStatus.UPLOADING)
            try {
                api.uploadBatch(
                    authorization = ApiFactory.bearer(device.token),
                    body = BatchRequest(messages = batch.map(::toUpload)),
                )
                messageDao.markSynced(ids, System.currentTimeMillis())
                uploaded += batch.size
            } catch (error: IOException) {
                messageDao.markFailed(ids, error.message)
                return SyncOutcome.Retry("Network error: ${error.message}")
            } catch (error: HttpException) {
                if (!blamesTheMessage(error.code())) {
                    // The connection or the credential is at fault, which
                    // applies to every message equally. Nothing to isolate.
                    messageDao.markFailed(ids, "HTTP ${error.code()}")
                    return handleHttpError(error, "upload")
                }

                if (batch.size > 1) {
                    // One of these is unacceptable and the rest are innocent,
                    // but the response does not say which. Requeue and retry
                    // one at a time to find out.
                    messageDao.markFailed(ids, "HTTP ${error.code()}")
                    Log.w(TAG, "batch of ${batch.size} refused (HTTP ${error.code()}); isolating")
                    batchSize = 1
                    continue
                }

                // Isolated and still refused, so retrying it unchanged will
                // never succeed. Set it aside; leaving it queued would block
                // every message behind it for good.
                messageDao.quarantine(
                    ids,
                    "Server permanently refused this message (HTTP ${error.code()})",
                )
                Log.e(
                    TAG,
                    "quarantined message from ${batch.first().sender} " +
                        "after HTTP ${error.code()}",
                )
                // The offender is out of the queue, so the rest can go back to
                // travelling together. A second bad message will narrow it
                // again; the cost is one wasted batch per offender, not a
                // permanent drop to one request per message.
                batchSize = BATCH_SIZE
            }
        }

        prune(config.retentionDays)

        if (uploaded == 0) {
            // Nothing to upload, but still check in. Without this the server
            // only ever hears from a phone that has traffic, so a healthy but
            // quiet device is indistinguishable from a dead one — and a device
            // switched off server-side would not find out until its next SMS.
            heartbeat(api, device)?.let { return it }
            return SyncOutcome.Idle("No pending messages.")
        }
        return SyncOutcome.Success(uploaded)
    }

    /** Returns null when the check-in succeeded, or the outcome to report. */
    private suspend fun heartbeat(api: TsunagiApi, device: DeviceEntity): SyncOutcome? =
        try {
            api.heartbeat(ApiFactory.bearer(device.token))
            null
        } catch (error: HttpException) {
            handleHttpError(error, "heartbeat")
        } catch (error: IOException) {
            SyncOutcome.Retry("Network error: ${error.message}")
        }

    /**
     * Drops locally stored messages the server has already confirmed, so a
     * long-running install does not grow without bound. Only SYNCED rows are
     * eligible, so nothing is deleted that is not safely on the server.
     */
    suspend fun prune(retentionDays: Int): Int {
        if (retentionDays <= 0) return 0
        val cutoff = System.currentTimeMillis() - retentionDays.toLong() * MILLIS_PER_DAY
        val removed = messageDao.deleteSyncedBefore(cutoff)
        if (removed > 0) {
            Log.i(TAG, "pruned $removed synced message(s) older than $retentionDays days")
        }
        return removed
    }

    private sealed interface Registration {
        data class Ready(val device: DeviceEntity) : Registration
        data class Problem(val outcome: SyncOutcome) : Registration
    }

    private suspend fun ensureRegistered(
        api: TsunagiApi,
        config: TsunagiSettings,
    ): Registration {
        deviceDao.get()?.let { return Registration.Ready(it) }

        if (config.setupKey.isBlank()) {
            return Registration.Problem(
                SyncOutcome.Failure("A setup key is required to register this device.")
            )
        }

        return try {
            val response = api.register(
                authorization = ApiFactory.bearer(config.setupKey),
                body = RegisterRequest(deviceName = config.deviceName),
            )
            val device = DeviceEntity(
                deviceId = response.deviceId,
                deviceName = config.deviceName,
                token = response.token,
                createdAt = System.currentTimeMillis(),
            )
            deviceDao.upsert(device)
            // The code is spent now; the device token replaces it. Holding on
            // to it would leave a useless secret sitting in settings.
            settings.clearEnrolmentCode()
            Log.i(TAG, "registered device ${response.deviceId}")
            Registration.Ready(device)
        } catch (error: HttpException) {
            Registration.Problem(handleHttpError(error, "registration"))
        } catch (error: IOException) {
            Registration.Problem(SyncOutcome.Retry("Network error: ${error.message}"))
        }
    }

    /**
     * 401 during upload means the token is unrecognised — usually the server's
     * database was reset — so the registration is dropped and the next pass
     * enrols again.
     *
     * 403 is different and must never trigger re-enrolment: the server knows
     * this device and has deliberately switched it off. Registering again would
     * walk straight back in under a new id and defeat the admin's decision.
     */
    /**
     * Whether a status names the batch's contents as the problem rather than
     * the connection or the credential.
     *
     * 422 is the one that matters in practice: the batch endpoint validates
     * every message before storing any, so one message the server will not
     * accept — an empty sender, an unrepresentable timestamp — rejects the
     * whole request, and will keep doing so on every retry.
     *
     * 401 and 403 are excluded because they are about this device, not this
     * message, and 408 and 429 because they are worth retrying unchanged.
     */
    private fun blamesTheMessage(code: Int): Boolean =
        code in 400..499 && code !in setOf(401, 403, 408, 429)

    private suspend fun handleHttpError(error: HttpException, stage: String): SyncOutcome {
        val code = error.code()
        return when {
            // Not during registration: a 401 there means the enrolment code was
            // refused, and dropping the record would just loop.
            code == 401 && stage != "registration" -> {
                deviceDao.clear()
                SyncOutcome.Retry("Device token rejected; will re-register.")
            }
            code == 403 ->
                SyncOutcome.Failure(
                    "This device has been turned off on the server. Ask an administrator " +
                        "to re-enable it."
                )
            code == 401 ->
                SyncOutcome.Failure("Server rejected credentials during $stage (HTTP $code).")
            code == 429 || code >= 500 ->
                SyncOutcome.Retry("Server unavailable during $stage (HTTP $code).")
            else -> SyncOutcome.Failure("Server refused $stage (HTTP $code).")
        }
    }

    private fun toUpload(message: MessageEntity) = MessageUpload(
        id = message.id,
        sender = message.sender,
        body = message.body,
        receivedAt = Instant.ofEpochMilli(message.receivedAt).toString(),
    )

    private companion object {
        const val TAG = "TsunagiRepository"
        const val BATCH_SIZE = 100
        const val MILLIS_PER_DAY = 24L * 60 * 60 * 1000

        /** How far back a first sweep reads, before any watermark exists. */
        const val INITIAL_BACKFILL_LOOKBACK_MILLIS = MILLIS_PER_DAY

        /** Re-read window, covering a message stored just behind the watermark. */
        const val BACKFILL_OVERLAP_MILLIS = 10L * 60 * 1000

        /** How far apart two sightings of one message may report its time. */
        const val BACKFILL_MATCH_WINDOW_MILLIS = 10L * 60 * 1000

        /** Bounds one sweep, so a long backlog is worked through over several. */
        const val BACKFILL_SCAN_LIMIT = 500
    }
}
