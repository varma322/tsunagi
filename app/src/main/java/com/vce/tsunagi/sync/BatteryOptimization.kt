package com.vce.tsunagi.sync

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings
import android.util.Log
import androidx.core.content.getSystemService

/**
 * Whether the system is allowed to put this app to sleep.
 *
 * This matters more than it looks. An optimized app can be moved into the
 * stopped state — by a force-stop, or by a vendor battery manager deciding it
 * has been idle — and a stopped app receives no broadcasts at all. There is no
 * callback for it and nothing appears in the log, so an SMS simply never
 * arrives. The inbox sweep exists to recover those; an exemption is what stops
 * them happening.
 */
object BatteryOptimization {

    fun isExempt(context: Context): Boolean {
        val power = context.getSystemService<PowerManager>() ?: return false
        return power.isIgnoringBatteryOptimizations(context.packageName)
    }

    /**
     * Opens the exemption prompt for this app, falling back to the system's
     * full battery optimization list when the direct request is unavailable —
     * some vendor builds remove it, and a list the user can navigate is better
     * than a button that does nothing.
     */
    fun requestExemption(context: Context) {
        val direct = Intent(
            Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
            Uri.fromParts("package", context.packageName, null),
        )
        if (start(context, direct)) return

        val list = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
        if (start(context, list)) return

        Log.w(TAG, "no settings screen available to request a battery exemption")
    }

    private fun start(context: Context, intent: Intent): Boolean = try {
        context.startActivity(intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        true
    } catch (error: ActivityNotFoundException) {
        false
    }

    private const val TAG = "BatteryOptimization"
}
