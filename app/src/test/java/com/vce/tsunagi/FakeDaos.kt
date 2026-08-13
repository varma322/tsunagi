package com.vce.tsunagi

import com.vce.tsunagi.data.local.DeviceDao
import com.vce.tsunagi.data.local.DeviceEntity
import com.vce.tsunagi.data.local.MessageDao
import com.vce.tsunagi.data.local.MessageEntity
import com.vce.tsunagi.data.local.SyncStatus
import com.vce.tsunagi.data.local.SyncStatusCount
import com.vce.tsunagi.data.remote.BatchRequest
import com.vce.tsunagi.data.remote.BatchResponse
import com.vce.tsunagi.data.remote.HealthResponse
import com.vce.tsunagi.data.remote.IdentityResponse
import com.vce.tsunagi.data.remote.RegisterRequest
import com.vce.tsunagi.data.remote.RegisterResponse
import com.vce.tsunagi.data.remote.TsunagiApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response

class FakeDeviceDao : DeviceDao {
    var device: DeviceEntity? = null
    var clearCount = 0

    override suspend fun get(id: Int): DeviceEntity? = device
    override fun observe(id: Int): Flow<DeviceEntity?> = flowOf(device)
    override suspend fun upsert(device: DeviceEntity) {
        this.device = device
    }

    override suspend fun clear() {
        device = null
        clearCount++
    }
}

class FakeMessageDao : MessageDao {
    val rows = linkedMapOf<String, MessageEntity>()
    var requeuedStranded = 0

    override suspend fun insert(message: MessageEntity): Long {
        if (rows.containsKey(message.id)) return -1L
        rows[message.id] = message
        return rows.size.toLong()
    }

    override suspend fun find(id: String): MessageEntity? = rows[id]

    override suspend fun existsNear(
        sender: String,
        body: String,
        from: Long,
        to: Long,
    ): Boolean = rows.values.any {
        it.sender == sender && it.body == body && it.receivedAt in from..to
    }

    override suspend fun pendingBatch(limit: Int): List<MessageEntity> =
        rows.values
            .filter { it.syncStatus == SyncStatus.PENDING || it.syncStatus == SyncStatus.FAILED }
            .sortedBy { it.receivedAt }
            .take(limit)

    override suspend fun pendingCount(): Int = pendingBatch(Int.MAX_VALUE).size

    override suspend fun markStatus(ids: List<String>, status: SyncStatus) {
        ids.forEach { id -> rows[id]?.let { rows[id] = it.copy(syncStatus = status) } }
    }

    override suspend fun markSynced(ids: List<String>, syncedAt: Long) {
        ids.forEach { id ->
            rows[id]?.let {
                rows[id] = it.copy(
                    syncStatus = SyncStatus.SYNCED,
                    syncedAt = syncedAt,
                    lastError = null,
                )
            }
        }
    }

    override suspend fun markFailed(ids: List<String>, error: String?) {
        ids.forEach { id ->
            rows[id]?.let {
                rows[id] = it.copy(
                    syncStatus = SyncStatus.FAILED,
                    attemptCount = it.attemptCount + 1,
                    lastError = error,
                )
            }
        }
    }

    override suspend fun quarantine(ids: List<String>, error: String?) {
        ids.forEach { id ->
            rows[id]?.let {
                rows[id] = it.copy(
                    syncStatus = SyncStatus.QUARANTINED,
                    attemptCount = it.attemptCount + 1,
                    lastError = error,
                )
            }
        }
    }

    override suspend fun quarantinedCount(): Int =
        rows.values.count { it.syncStatus == SyncStatus.QUARANTINED }

    override suspend fun deleteSyncedBefore(cutoff: Long): Int {
        val doomed = rows.values.filter {
            it.syncStatus == SyncStatus.SYNCED && it.syncedAt != null && it.syncedAt < cutoff
        }
        doomed.forEach { rows.remove(it.id) }
        return doomed.size
    }

    override suspend fun requeueStranded(): Int {
        val stranded = rows.values.filter { it.syncStatus == SyncStatus.UPLOADING }
        stranded.forEach { rows[it.id] = it.copy(syncStatus = SyncStatus.PENDING) }
        requeuedStranded += stranded.size
        return stranded.size
    }

    override fun observeStatusCounts(): Flow<List<SyncStatusCount>> = flowOf(
        rows.values.groupBy { it.syncStatus }.map { SyncStatusCount(it.key, it.value.size) }
    )

    override fun observeRecent(limit: Int): Flow<List<MessageEntity>> =
        flowOf(rows.values.sortedByDescending { it.receivedAt }.take(limit))

    override fun observeTotal(): Flow<Int> = flowOf(rows.size)
}

/** Scripted API whose behaviour each test overrides as needed. */
open class FakeApi : TsunagiApi {
    val uploadedBatches = mutableListOf<BatchRequest>()
    var registerCalls = 0
    var registerBehaviour: () -> RegisterResponse = {
        RegisterResponse(deviceId = "device-1", token = "tsn_dev_token")
    }
    var uploadBehaviour: (BatchRequest) -> BatchResponse = { request ->
        BatchResponse(accepted = request.messages.size, created = request.messages.size, duplicates = 0)
    }

    var heartbeats = 0
    var heartbeatBehaviour: () -> IdentityResponse = {
        IdentityResponse(kind = "device", scope = "device", name = "Test Phone", id = "device-1")
    }

    override suspend fun health(): HealthResponse = HealthResponse("ok", "1.0.0")

    override suspend fun heartbeat(authorization: String): IdentityResponse {
        heartbeats++
        return heartbeatBehaviour()
    }

    override suspend fun register(
        authorization: String,
        body: RegisterRequest,
    ): RegisterResponse {
        registerCalls++
        return registerBehaviour()
    }

    override suspend fun uploadBatch(
        authorization: String,
        body: BatchRequest,
    ): BatchResponse {
        uploadedBatches += body
        return uploadBehaviour(body)
    }
}

fun httpError(code: Int): HttpException =
    HttpException(
        Response.error<Unit>(code, "{}".toResponseBody("application/json".toMediaType()))
    )
