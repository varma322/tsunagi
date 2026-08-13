package com.vce.tsunagi.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.vce.tsunagi.data.TsunagiSettings
import com.vce.tsunagi.data.local.MessageEntity
import com.vce.tsunagi.sync.BatteryOptimization
import com.vce.tsunagi.ui.theme.TsunagiWarning
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val timeFormatter: DateTimeFormatter =
    DateTimeFormatter.ofPattern("MMM d, HH:mm:ss").withZone(ZoneId.systemDefault())

private val smsPermissions = arrayOf(Manifest.permission.RECEIVE_SMS, Manifest.permission.READ_SMS)

@Composable
fun HomeScreen(
    state: HomeUiState,
    onSave: (String, String, String, Int) -> Unit,
    onSyncNow: () -> Unit,
    onForgetDevice: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    var permissionsGranted by remember {
        mutableStateOf(
            smsPermissions.all {
                ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED
            }
        )
    }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { results -> permissionsGranted = results.values.all { it } }

    // The exemption is granted on a system screen rather than through a result
    // callback, so the only reliable moment to re-read it is on the way back.
    var batteryExempt by remember { mutableStateOf(BatteryOptimization.isExempt(context)) }
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                batteryExempt = BatteryOptimization.isExempt(context)
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item { Header() }

        if (!permissionsGranted) {
            item {
                PermissionCard(onGrant = { permissionLauncher.launch(smsPermissions) })
            }
        }

        if (!batteryExempt) {
            item {
                BatteryCard(onExempt = { BatteryOptimization.requestExemption(context) })
            }
        }

        item { StatusCard(state = state, onSyncNow = onSyncNow, onForget = onForgetDevice) }

        item { SettingsCard(state = state, onSave = onSave) }

        if (state.recent.isNotEmpty()) {
            item {
                Text(
                    text = "Recent messages",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            items(state.recent, key = { it.id }) { message -> MessageRow(message) }
        }
    }
}

@Composable
private fun Header() {
    Column {
        Text(
            text = "Tsunagi",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
        )
        Text(
            text = "SMS Synchronization",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun PermissionCard(onGrant: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer,
        )
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                text = "SMS permission required",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
            Text(
                text = "Tsunagi cannot capture messages until SMS access is granted.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
            Button(onClick = onGrant) { Text("Grant permission") }
        }
    }
}

@Composable
private fun BatteryCard(onExempt: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerHigh,
        )
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                text = "Battery optimization is on",
                style = MaterialTheme.typography.titleMedium,
            )
            Text(
                text = "Android may put Tsunagi to sleep, and a sleeping app is not told " +
                    "about incoming SMS at all. Messages missed this way are picked up by " +
                    "the next inbox check, but they arrive late. Turning optimization off " +
                    "for Tsunagi keeps capture immediate.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Button(onClick = onExempt) { Text("Allow background activity") }
        }
    }
}

@Composable
private fun StatusCard(state: HomeUiState, onSyncNow: () -> Unit, onForget: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainer,
        )
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                StatusDot(
                    color = if (state.isRegistered) {
                        MaterialTheme.colorScheme.tertiary
                    } else {
                        TsunagiWarning
                    }
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    text = if (state.isRegistered) "Registered" else "Not registered",
                    style = MaterialTheme.typography.titleMedium,
                )
            }

            state.deviceId?.let { id ->
                Text(
                    text = id,
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }

            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

            Row(horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                Metric("Captured", state.totalCaptured.toString())
                Metric("Synced", state.synced.toString(), MaterialTheme.colorScheme.tertiary)
                Metric("Pending", state.pending.toString(), TsunagiWarning)
                Metric("Failed", state.failed.toString(), MaterialTheme.colorScheme.error)
            }

            val lastSync = state.settings.lastSyncAt
            Text(
                text = if (lastSync != null) {
                    "Last sync: ${timeFormatter.format(Instant.ofEpochMilli(lastSync))}"
                } else {
                    "Last sync: never"
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            state.settings.lastSyncError?.let { error ->
                Text(
                    text = error,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }

            // Set aside rather than queued, so it would otherwise leave no
            // trace: the counts above would look healthy while messages were
            // quietly never delivered.
            if (state.quarantined > 0) {
                Text(
                    text = "${state.quarantined} message(s) the server permanently refused. " +
                        "They are stored on this phone but will not be uploaded.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onSyncNow, enabled = !state.isSyncing) {
                    if (state.isSyncing) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(16.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimary,
                        )
                        Spacer(Modifier.width(8.dp))
                        Text("Syncing")
                    } else {
                        Icon(Icons.Filled.Sync, contentDescription = null, Modifier.size(18.dp))
                        Spacer(Modifier.width(8.dp))
                        Text("Sync now")
                    }
                }
                if (state.isRegistered) {
                    OutlinedButton(onClick = onForget) { Text("Re-register") }
                }
            }
        }
    }
}

@Composable
private fun SettingsCard(state: HomeUiState, onSave: (String, String, String, Int) -> Unit) {
    var serverUrl by rememberSaveable(state.settings.serverUrl) {
        mutableStateOf(state.settings.serverUrl)
    }
    var deviceName by rememberSaveable(state.settings.deviceName) {
        mutableStateOf(state.settings.deviceName)
    }
    var setupKey by rememberSaveable(state.settings.setupKey) {
        mutableStateOf(state.settings.setupKey)
    }
    var retention by rememberSaveable(state.settings.retentionDays) {
        mutableStateOf(state.settings.retentionDays.toString())
    }

    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainer,
        )
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("Server", style = MaterialTheme.typography.titleMedium)

            OutlinedTextField(
                value = serverUrl,
                onValueChange = { serverUrl = it },
                label = { Text("Server URL") },
                placeholder = { Text("https://tsunagi.example.com") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = deviceName,
                onValueChange = { deviceName = it },
                label = { Text("Device name") },
                placeholder = { Text("Office Phone") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            if (!state.isRegistered) {
                OutlinedTextField(
                    value = setupKey,
                    onValueChange = { setupKey = it },
                    label = { Text("Enrolment code") },
                    placeholder = { Text("ABCD-EFGH") },
                    supportingText = {
                        Text(
                            "Generate this on the dashboard under Devices. It registers this " +
                                "phone once, then is discarded."
                        )
                    },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            OutlinedTextField(
                value = retention,
                onValueChange = { input -> retention = input.filter(Char::isDigit).take(4) },
                label = { Text("Keep messages for (days)") },
                supportingText = {
                    Text(
                        if (retention.toIntOrNull()?.let { it > 0 } == true) {
                            "Synced messages are deleted from this phone after " +
                                "$retention days. The server keeps its copy."
                        } else {
                            "0 keeps every message on this phone forever."
                        }
                    )
                },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                modifier = Modifier.fillMaxWidth(),
            )

            Button(
                onClick = {
                    onSave(
                        serverUrl,
                        deviceName,
                        setupKey,
                        retention.toIntOrNull() ?: TsunagiSettings.DEFAULT_RETENTION_DAYS,
                    )
                },
                enabled = serverUrl.isNotBlank() && deviceName.isNotBlank(),
            ) {
                Text("Save and sync")
            }
        }
    }
}

@Composable
private fun Metric(label: String, value: String, valueColor: Color = Color.Unspecified) {
    Column {
        Text(
            text = value,
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Bold,
            color = valueColor,
        )
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun StatusDot(color: Color) {
    Surface(
        modifier = Modifier.size(8.dp).clip(CircleShape),
        color = color,
        content = {},
    )
}

@Composable
private fun MessageRow(message: MessageEntity) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceContainerLow,
        )
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = message.sender,
                    style = MaterialTheme.typography.bodyMedium,
                    fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Medium,
                )
                Text(
                    text = message.syncStatus.name.lowercase(),
                    style = MaterialTheme.typography.labelSmall,
                    color = statusColor(message),
                )
            }
            Text(
                text = message.body,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
            )
            Text(
                text = timeFormatter.format(Instant.ofEpochMilli(message.receivedAt)),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun statusColor(message: MessageEntity): Color = when (message.syncStatus.name) {
    "SYNCED" -> MaterialTheme.colorScheme.tertiary
    "FAILED" -> MaterialTheme.colorScheme.error
    else -> TsunagiWarning
}
