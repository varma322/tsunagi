package com.vce.tsunagi.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.TypeConverter
import kotlinx.coroutines.flow.Flow

class SyncStatusConverter {
    @TypeConverter
    fun toStatus(value: String): SyncStatus = SyncStatus.valueOf(value)

    @TypeConverter
    fun fromStatus(status: SyncStatus): String = status.name
}

@Dao
interface DeviceDao {
    @Query("SELECT * FROM device WHERE row_id = :id LIMIT 1")
    suspend fun get(id: Int = DeviceEntity.SINGLETON_ID): DeviceEntity?

    @Query("SELECT * FROM device WHERE row_id = :id LIMIT 1")
    fun observe(id: Int = DeviceEntity.SINGLETON_ID): Flow<DeviceEntity?>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(device: DeviceEntity)

    @Query("DELETE FROM device")
    suspend fun clear()
}

@Dao
interface MessageDao {
    /**
     * Ignores an id that is already stored: the SMS broadcast can be delivered
     * more than once for a single message, and the inbox sweep re-reads
     * messages the broadcast already captured. Both resolve to the same
     * derived id, so both land here and are dropped.
     */
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(message: MessageEntity): Long

    @Query("SELECT * FROM messages WHERE id = :id")
    suspend fun find(id: String): MessageEntity?

    /**
     * Whether an equivalent message is already stored near this timestamp.
     *
     * The derived id is the primary defence against duplicates, but it only
     * holds when both sightings agree on the timestamp. A broadcast reports the
     * service centre's timestamp while the platform inbox may record when the
     * message was written to the provider, so the sweep needs a second check
     * that tolerates the two disagreeing by a few minutes.
     */
    @Query(
        """
        SELECT EXISTS(
            SELECT 1 FROM messages
            WHERE sender = :sender
              AND body = :body
              AND received_at BETWEEN :from AND :to
        )
        """
    )
    suspend fun existsNear(sender: String, body: String, from: Long, to: Long): Boolean

    @Query(
        """
        SELECT * FROM messages
        WHERE sync_status IN ('PENDING', 'FAILED')
        ORDER BY received_at ASC
        LIMIT :limit
        """
    )
    suspend fun pendingBatch(limit: Int): List<MessageEntity>

    @Query("SELECT COUNT(*) FROM messages WHERE sync_status IN ('PENDING', 'FAILED')")
    suspend fun pendingCount(): Int

    @Query("UPDATE messages SET sync_status = :status WHERE id IN (:ids)")
    suspend fun markStatus(ids: List<String>, status: SyncStatus)

    @Query(
        """
        UPDATE messages
        SET sync_status = 'SYNCED', synced_at = :syncedAt, last_error = NULL
        WHERE id IN (:ids)
        """
    )
    suspend fun markSynced(ids: List<String>, syncedAt: Long)

    @Query(
        """
        UPDATE messages
        SET sync_status = 'FAILED',
            attempt_count = attempt_count + 1,
            last_error = :error
        WHERE id IN (:ids)
        """
    )
    suspend fun markFailed(ids: List<String>, error: String?)

    /**
     * Removes a permanently rejected message from the queue.
     *
     * Without this a message the server will never accept is re-selected by
     * [pendingBatch] on every pass, and — because uploads go up in batches —
     * takes every message behind it down too. Setting it aside is what keeps
     * one bad message from stopping the queue for good.
     */
    @Query(
        """
        UPDATE messages
        SET sync_status = 'QUARANTINED',
            attempt_count = attempt_count + 1,
            last_error = :error
        WHERE id IN (:ids)
        """
    )
    suspend fun quarantine(ids: List<String>, error: String?)

    @Query("SELECT COUNT(*) FROM messages WHERE sync_status = 'QUARANTINED'")
    suspend fun quarantinedCount(): Int

    /** Recovers rows stranded in UPLOADING by a process death mid-upload. */
    @Query("UPDATE messages SET sync_status = 'PENDING' WHERE sync_status = 'UPLOADING'")
    suspend fun requeueStranded(): Int

    /**
     * Drops confirmed-synced messages past the retention window. Only rows the
     * server has acknowledged are eligible, so pruning can never lose a message
     * that has not been stored elsewhere.
     */
    @Query(
        """
        DELETE FROM messages
        WHERE sync_status = 'SYNCED' AND synced_at IS NOT NULL AND synced_at < :cutoff
        """
    )
    suspend fun deleteSyncedBefore(cutoff: Long): Int

    @Query("SELECT sync_status, COUNT(*) AS count FROM messages GROUP BY sync_status")
    fun observeStatusCounts(): Flow<List<SyncStatusCount>>

    @Query("SELECT * FROM messages ORDER BY received_at DESC LIMIT :limit")
    fun observeRecent(limit: Int): Flow<List<MessageEntity>>

    @Query("SELECT COUNT(*) FROM messages")
    fun observeTotal(): Flow<Int>
}
