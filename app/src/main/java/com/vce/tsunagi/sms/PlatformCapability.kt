package com.vce.tsunagi.sms

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import com.vce.tsunagi.data.CaptureCapability
import com.vce.tsunagi.data.CaptureCapabilitySource
import com.vce.tsunagi.sync.BatteryOptimization

/**
 * Reads the phone's own capture permissions and power exemption.
 *
 * Both are checked live rather than remembered from the last prompt: a user can
 * revoke either from system settings at any time, and the app is given no
 * callback when they do. Asking each pass is what makes a revocation visible on
 * the dashboard within one sync interval instead of never.
 */
class PlatformCapability(context: Context) : CaptureCapabilitySource {

    private val context = context.applicationContext

    override fun snapshot(): CaptureCapability = CaptureCapability(
        permitted = granted(Manifest.permission.RECEIVE_SMS) &&
            granted(Manifest.permission.READ_SMS),
        batteryExempt = BatteryOptimization.isExempt(context),
    )

    private fun granted(permission: String): Boolean =
        ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED
}
