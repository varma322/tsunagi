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
 */
enum class SyncStatus {
    PENDING,
    UPLOADING,
    SYNCED,
    FAILED,
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
