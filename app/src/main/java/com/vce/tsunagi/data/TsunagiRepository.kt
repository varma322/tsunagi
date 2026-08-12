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
import java.util.UUID
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
) {

    fun observeDevice(): Flow<DeviceEntity?> = deviceDao.observe()

    fun observeStatusCounts() = messageDao.observeStatusCounts()

    fun observeRecent(limit: Int = 20): Flow<List<MessageEntity>> = messageDao.observeRecent(limit)

    fun observeTotal(): Flow<Int> = messageDao.observeTotal()

    suspend fun pendingCount(): Int = messageDao.pendingCount()

    /**
     * Stores a captured SMS. Returns false when this id was already stored,
     * which happens if the SMS broadcast is delivered more than once.
     */
    suspend fun captureSms(sender: String, body: String, receivedAt: Long): Boolean {
        val rowId = messageDao.insert(
            MessageEntity(
                id = UUID.randomUUID().toString(),
                sender = sender,
                body = body,
                receivedAt = receivedAt,
            )
        )
        return rowId != -1L
    }

    suspend fun currentDevice(): DeviceEntity? = deviceDao.get()

    suspend fun forgetDevice() = deviceDao.clear()

    /**
     * Runs one sync pass: registers the device if needed, then uploads every
     * pending message in batches.
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

        // A crash mid-upload can strand rows in UPLOADING; put them back in line.
        messageDao.requeueStranded()

        val device = when (val registration = ensureRegistered(api, config)) {
            is Registration.Ready -> registration.device
            is Registration.Problem -> return registration.outcome
        }

        var uploaded = 0
        while (true) {
            val batch = messageDao.pendingBatch(BATCH_SIZE)
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
            } catch (error: HttpException) {
                messageDao.markFailed(ids, "HTTP ${error.code()}")
                return handleHttpError(error, "upload")
            } catch (error: IOException) {
                messageDao.markFailed(ids, error.message)
                return SyncOutcome.Retry("Network error: ${error.message}")
            }
        }

        prune(config.retentionDays)

        return if (uploaded == 0) {
            SyncOutcome.Idle("No pending messages.")
        } else {
            SyncOutcome.Success(uploaded)
        }
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
    private suspend fun handleHttpError(error: HttpException, stage: String): SyncOutcome {
        val code = error.code()
        return when {
            code == 401 && stage == "upload" -> {
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
    }
}
