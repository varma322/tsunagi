package com.vce.tsunagi.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelProvider.AndroidViewModelFactory.Companion.APPLICATION_KEY
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.work.WorkInfo
import com.vce.tsunagi.TsunagiApplication
import com.vce.tsunagi.data.TsunagiSettings
import com.vce.tsunagi.data.local.MessageEntity
import com.vce.tsunagi.data.local.SyncStatus
import com.vce.tsunagi.sync.SyncScheduler
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class HomeUiState(
    val settings: TsunagiSettings = TsunagiSettings(),
    val deviceId: String? = null,
    val counts: Map<SyncStatus, Int> = emptyMap(),
    val totalCaptured: Int = 0,
    val recent: List<MessageEntity> = emptyList(),
    val isSyncing: Boolean = false,
) {
    val isRegistered: Boolean get() = deviceId != null
    val pending: Int
        get() = counts.getOrElse(SyncStatus.PENDING) { 0 } +
            counts.getOrElse(SyncStatus.UPLOADING) { 0 }
    val synced: Int get() = counts.getOrElse(SyncStatus.SYNCED) { 0 }
    val failed: Int get() = counts.getOrElse(SyncStatus.FAILED) { 0 }

    /** Permanently refused by the server, and no longer in the upload queue. */
    val quarantined: Int get() = counts.getOrElse(SyncStatus.QUARANTINED) { 0 }

    /** Captured while paused and deliberately never uploaded. */
    val excluded: Int get() = counts.getOrElse(SyncStatus.EXCLUDED) { 0 }

    val syncEnabled: Boolean get() = settings.syncEnabled
}

class MainViewModel(application: Application) : AndroidViewModel(application) {

    private val container = TsunagiApplication.container(application)

    val uiState: StateFlow<HomeUiState> = combine(
        container.settings.observe(),
        container.repository.observeDevice(),
        container.repository.observeStatusCounts(),
        container.repository.observeTotal(),
        container.repository.observeRecent(),
    ) { settings, device, counts, total, recent ->
        HomeUiState(
            settings = settings,
            deviceId = device?.deviceId,
            counts = counts.associate { it.syncStatus to it.count },
            totalCaptured = total,
            recent = recent,
        )
    }.combine(SyncScheduler.observeSyncWork(application)) { state, workInfos ->
        state.copy(isSyncing = workInfos.any { it.state == WorkInfo.State.RUNNING })
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = HomeUiState(),
    )

    fun saveConnection(
        serverUrl: String,
        deviceName: String,
        setupKey: String,
        retentionDays: Int,
    ) {
        container.settings.updateConnection(serverUrl, deviceName, setupKey, retentionDays)
        SyncScheduler.syncNow(getApplication())
    }

    fun syncNow() = SyncScheduler.syncNow(getApplication())

    /** Pause or resume uploading. Resuming kicks off a sync straight away. */
    fun setSyncEnabled(enabled: Boolean) {
        if (enabled) {
            container.settings.resumeSync()
            SyncScheduler.syncNow(getApplication())
        } else {
            container.settings.pauseSync()
        }
    }

    /** Whether a paused session's messages are held back rather than uploaded. */
    fun setExcludePausedMessages(enabled: Boolean) {
        container.settings.excludePausedMessages = enabled
    }

    /** Drops the stored registration so the next sync registers again. */
    fun forgetDevice() {
        viewModelScope.launch { container.repository.forgetDevice() }
    }

    companion object {
        val Factory: ViewModelProvider.Factory = viewModelFactory {
            initializer {
                val app = checkNotNull(this[APPLICATION_KEY])
                MainViewModel(app)
            }
        }
    }
}
