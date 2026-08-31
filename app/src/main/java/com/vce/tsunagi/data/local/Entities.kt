package com.vce.tsunagi.data.local

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * Where a captured message sits in the upload pipeline.
 *
 * PENDING -> UPLOADING -> SYNCED, with FAILED feeding back into the queue on
 * the next retry.
 *
 * QUARANTINED is the terminal exit: a message the server has permanently
 * refused. It leaves the queue so it cannot block the messages behind it, but
 * the row is kept so the rejection stays visible and diagnosable.
 */
enum class SyncStatus {
    PENDING,
    UPLOADING,
    SYNCED,
    FAILED,
    QUARANTINED,

    /**
     * Captured locally but deliberately never uploaded: it arrived while sync
     * was paused and the user chose not to sync a paused session. Kept so the
     * message is not lost on the phone, excluded from [MessageDao.pendingBatch]
     * so it never leaves.
     */
    EXCLUDED,
}

/**
 * This device's server identity. At most one row exists; [SINGLETON_ID] keeps
 * re-registration from accumulating stale rows.
 */
@Entity(tableName = "device")
data class DeviceEntity(
    @PrimaryKey
    @ColumnInfo(name = "row_id")
    val rowId: Int = SINGLETON_ID,
    @ColumnInfo(name = "device_id") val deviceId: String,
    @ColumnInfo(name = "device_name") val deviceName: String,
    @ColumnInfo(name = "token") val token: String,
    @ColumnInfo(name = "created_at") val createdAt: Long,
) {
    companion object {
        const val SINGLETON_ID = 1
    }
}

/**
 * A captured SMS. The id is generated here rather than by the server so a
 * retry after a lost response resolves to the same row on both sides.
 *
 * The id is derived from the message itself rather than drawn at random, so
 * the same SMS seen twice — a repeated broadcast, or a broadcast the inbox
 * sweep also finds — collapses onto one row instead of uploading twice. See
 * [com.vce.tsunagi.data.MessageIdentity].
 */
@Entity(
    tableName = "messages",
    indices = [Index("sync_status"), Index("received_at")],
)
data class MessageEntity(
    @PrimaryKey val id: String,
    @ColumnInfo(name = "sender") val sender: String,
    @ColumnInfo(name = "body") val body: String,
    @ColumnInfo(name = "received_at") val receivedAt: Long,
    @ColumnInfo(name = "sync_status") val syncStatus: SyncStatus = SyncStatus.PENDING,
    @ColumnInfo(name = "synced_at") val syncedAt: Long? = null,
    @ColumnInfo(name = "attempt_count") val attemptCount: Int = 0,
    @ColumnInfo(name = "last_error") val lastError: String? = null,
)

/** Row count per [SyncStatus], used by the status screen. */
data class SyncStatusCount(
    @ColumnInfo(name = "sync_status") val syncStatus: SyncStatus,
    @ColumnInfo(name = "count") val count: Int,
)
