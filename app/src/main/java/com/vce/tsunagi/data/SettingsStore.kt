package com.vce.tsunagi.data

import android.content.Context
import android.content.SharedPreferences
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.distinctUntilChanged

data class TsunagiSettings(
    val serverUrl: String = "",
    val deviceName: String = "",
    val setupKey: String = "",
    val lastSyncAt: Long? = null,
    val lastSyncError: String? = null,
    /** Days to keep messages after the server confirms them; 0 keeps forever. */
    val retentionDays: Int = DEFAULT_RETENTION_DAYS,
    /**
     * How far the inbox sweep has read, as a platform store timestamp. Null
     * until the first sweep, which is what tells it to start from a bounded
     * look-back rather than the whole of the phone's message history.
     */
    val lastBackfillAt: Long? = null,
    /**
     * When the sweep last read the platform store successfully. Distinct from
     * [lastBackfillAt], which only moves when something was there to examine:
     * this one answers "is the safety net still working", which is what the
     * server is told.
     */
    val lastSweptAt: Long? = null,
    /** False when the user has paused uploading. Capture continues regardless. */
    val syncEnabled: Boolean = true,
    /**
     * When set, messages received while sync is paused are held back on resume
     * rather than uploaded. Off by default, so a pause only delays a sync.
     */
    val excludePausedMessages: Boolean = false,
    /** When the current pause began, or null when sync is running. */
    val pausedSince: Long? = null,
    /**
     * A finished pause whose messages are still to be held back, as
     * [received-at from, received-at to]. Set on resume when
     * [excludePausedMessages] is on, and cleared once the next sync has applied
     * it -- after the sweep, so a message the sweep recovers on resume is caught
     * too. Null when there is nothing to exclude.
     */
    val excludeFrom: Long? = null,
    val excludeTo: Long? = null,
) {
    val isConfigured: Boolean
        get() = serverUrl.isNotBlank() && deviceName.isNotBlank()

    /** A pause window is waiting to be applied on the next sync. */
    val hasPendingExclusion: Boolean
        get() = excludeFrom != null && excludeTo != null

    companion object {
        const val DEFAULT_RETENTION_DAYS = 30
    }
}

/**
 * The slice of settings the sync engine reads and writes. Keeping it an
 * interface lets the sync logic be tested without an Android [Context].
 */
interface SyncSettings {
    fun snapshot(): TsunagiSettings

    /**
     * Forget the enrolment code once it has been spent. Codes are single-use
     * server-side, so keeping one only leaves a dead secret on the phone.
     */
    fun clearEnrolmentCode()

    /** Advance the inbox sweep watermark after a completed sweep. */
    fun recordBackfill(at: Long)

    /** Note that the platform store could still be read, at [at]. */
    fun recordSweep(at: Long)

    /** Drop the pending pause-exclusion window once a sync has applied it. */
    fun clearExclusionWindow()
}

/**
 * User-entered configuration plus sync bookkeeping.
 *
 * Backed by app-private [SharedPreferences]: the setup key and server URL are
 * configuration rather than relational data, and keeping them out of Room means
 * the sync worker can read them without opening the database.
 */
class SettingsStore(context: Context) : SyncSettings {

    private val prefs: SharedPreferences =
        context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    var serverUrl: String
        get() = prefs.getString(KEY_SERVER_URL, "").orEmpty()
        set(value) = prefs.edit().putString(KEY_SERVER_URL, value.trim()).apply()

    var deviceName: String
        get() = prefs.getString(KEY_DEVICE_NAME, "").orEmpty()
        set(value) = prefs.edit().putString(KEY_DEVICE_NAME, value.trim()).apply()

    var setupKey: String
        get() = prefs.getString(KEY_SETUP_KEY, "").orEmpty()
        set(value) = prefs.edit().putString(KEY_SETUP_KEY, value.trim()).apply()

    var lastSyncAt: Long?
        get() = prefs.getLong(KEY_LAST_SYNC_AT, 0L).takeIf { it > 0L }
        set(value) = prefs.edit().putLong(KEY_LAST_SYNC_AT, value ?: 0L).apply()

    var lastSyncError: String?
        get() = prefs.getString(KEY_LAST_SYNC_ERROR, null)
        set(value) = prefs.edit().putString(KEY_LAST_SYNC_ERROR, value).apply()

    var retentionDays: Int
        get() = prefs.getInt(KEY_RETENTION_DAYS, TsunagiSettings.DEFAULT_RETENTION_DAYS)
        set(value) = prefs.edit().putInt(KEY_RETENTION_DAYS, value.coerceAtLeast(0)).apply()

    var lastBackfillAt: Long?
        get() = prefs.getLong(KEY_LAST_BACKFILL_AT, 0L).takeIf { it > 0L }
        set(value) = prefs.edit().putLong(KEY_LAST_BACKFILL_AT, value ?: 0L).apply()

    var lastSweptAt: Long?
        get() = prefs.getLong(KEY_LAST_SWEPT_AT, 0L).takeIf { it > 0L }
        set(value) = prefs.edit().putLong(KEY_LAST_SWEPT_AT, value ?: 0L).apply()

    var syncEnabled: Boolean
        get() = prefs.getBoolean(KEY_SYNC_ENABLED, true)
        set(value) = prefs.edit().putBoolean(KEY_SYNC_ENABLED, value).apply()

    var excludePausedMessages: Boolean
        get() = prefs.getBoolean(KEY_EXCLUDE_PAUSED, false)
        set(value) = prefs.edit().putBoolean(KEY_EXCLUDE_PAUSED, value).apply()

    var pausedSince: Long?
        get() = prefs.getLong(KEY_PAUSED_SINCE, 0L).takeIf { it > 0L }
        set(value) = prefs.edit().putLong(KEY_PAUSED_SINCE, value ?: 0L).apply()

    private var excludeFrom: Long?
        get() = prefs.getLong(KEY_EXCLUDE_FROM, 0L).takeIf { it > 0L }
        set(value) = prefs.edit().putLong(KEY_EXCLUDE_FROM, value ?: 0L).apply()

    private var excludeTo: Long?
        get() = prefs.getLong(KEY_EXCLUDE_TO, 0L).takeIf { it > 0L }
        set(value) = prefs.edit().putLong(KEY_EXCLUDE_TO, value ?: 0L).apply()

    override fun snapshot(): TsunagiSettings = TsunagiSettings(
        serverUrl = serverUrl,
        deviceName = deviceName,
        setupKey = setupKey,
        lastSyncAt = lastSyncAt,
        lastSyncError = lastSyncError,
        retentionDays = retentionDays,
        lastBackfillAt = lastBackfillAt,
        lastSweptAt = lastSweptAt,
        syncEnabled = syncEnabled,
        excludePausedMessages = excludePausedMessages,
        pausedSince = pausedSince,
        excludeFrom = excludeFrom,
        excludeTo = excludeTo,
    )

    fun observe(): Flow<TsunagiSettings> = callbackFlow {
        trySend(snapshot())
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { _, _ ->
            trySend(snapshot())
        }
        prefs.registerOnSharedPreferenceChangeListener(listener)
        awaitClose { prefs.unregisterOnSharedPreferenceChangeListener(listener) }
    }.distinctUntilChanged()

    fun updateConnection(
        serverUrl: String,
        deviceName: String,
        setupKey: String,
        retentionDays: Int,
    ) {
        prefs.edit()
            .putString(KEY_SERVER_URL, serverUrl.trim())
            .putString(KEY_DEVICE_NAME, deviceName.trim())
            .putString(KEY_SETUP_KEY, setupKey.trim())
            .putInt(KEY_RETENTION_DAYS, retentionDays.coerceAtLeast(0))
            .apply()
    }

    override fun clearEnrolmentCode() {
        prefs.edit().remove(KEY_SETUP_KEY).apply()
    }

    /** Stop uploading. Capture keeps running; the queue simply stops draining. */
    fun pauseSync() {
        prefs.edit()
            .putBoolean(KEY_SYNC_ENABLED, false)
            .putLong(KEY_PAUSED_SINCE, System.currentTimeMillis())
            .apply()
    }

    /**
     * Resume uploading. When the paused session is not to be synced, the span it
     * covered is recorded for the next sync to hold back -- after its sweep, so
     * a message the broadcast missed and the sweep recovers on resume is held
     * back too rather than slipping out.
     */
    fun resumeSync() {
        val since = pausedSince
        val edit = prefs.edit()
            .putBoolean(KEY_SYNC_ENABLED, true)
            .putLong(KEY_PAUSED_SINCE, 0L)
        if (excludePausedMessages && since != null) {
            edit.putLong(KEY_EXCLUDE_FROM, since)
                .putLong(KEY_EXCLUDE_TO, System.currentTimeMillis())
        }
        edit.apply()
    }

    override fun clearExclusionWindow() {
        prefs.edit().putLong(KEY_EXCLUDE_FROM, 0L).putLong(KEY_EXCLUDE_TO, 0L).apply()
    }

    override fun recordBackfill(at: Long) {
        prefs.edit().putLong(KEY_LAST_BACKFILL_AT, at).apply()
    }

    override fun recordSweep(at: Long) {
        prefs.edit().putLong(KEY_LAST_SWEPT_AT, at).apply()
    }

    fun recordSyncSuccess(at: Long) {
        prefs.edit()
            .putLong(KEY_LAST_SYNC_AT, at)
            .remove(KEY_LAST_SYNC_ERROR)
            .apply()
    }

    fun recordSyncFailure(error: String) {
        prefs.edit().putString(KEY_LAST_SYNC_ERROR, error).apply()
    }

    private companion object {
        const val FILE = "tsunagi_settings"
        const val KEY_SERVER_URL = "server_url"
        const val KEY_DEVICE_NAME = "device_name"
        const val KEY_SETUP_KEY = "setup_key"
        const val KEY_LAST_SYNC_AT = "last_sync_at"
        const val KEY_LAST_SYNC_ERROR = "last_sync_error"
        const val KEY_RETENTION_DAYS = "retention_days"
        const val KEY_LAST_BACKFILL_AT = "last_backfill_at"
        const val KEY_LAST_SWEPT_AT = "last_swept_at"
        const val KEY_SYNC_ENABLED = "sync_enabled"
        const val KEY_EXCLUDE_PAUSED = "exclude_paused_messages"
        const val KEY_PAUSED_SINCE = "paused_since"
        const val KEY_EXCLUDE_FROM = "exclude_from"
        const val KEY_EXCLUDE_TO = "exclude_to"
    }
}
