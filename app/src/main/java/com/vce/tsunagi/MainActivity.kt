package com.vce.tsunagi

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.vce.tsunagi.ui.HomeScreen
import com.vce.tsunagi.ui.MainViewModel
import com.vce.tsunagi.ui.theme.TsunagiTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            TsunagiTheme {
                val viewModel: MainViewModel = viewModel(factory = MainViewModel.Factory)
                val state by viewModel.uiState.collectAsStateWithLifecycle()

                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    HomeScreen(
                        state = state,
                        onSave = viewModel::saveConnection,
                        onSyncNow = viewModel::syncNow,
                        onForgetDevice = viewModel::forgetDevice,
                        onSetSyncEnabled = viewModel::setSyncEnabled,
                        onSetExcludePaused = viewModel::setExcludePausedMessages,
                        modifier = Modifier.padding(innerPadding),
                    )
                }
            }
        }
    }
}
