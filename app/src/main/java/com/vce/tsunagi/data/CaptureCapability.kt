package com.vce.tsunagi.data

/**
 * What the phone is currently permitted to do, as opposed to what it has done.
 *
 * The server cannot work any of this out. From its side a phone that has had
 * its SMS permission revoked looks exactly like one nobody has texted: both
 * check in on time and upload nothing.
 */
data class CaptureCapability(
    /** RECEIVE_SMS and READ_SMS are both still granted. */
    val permitted: Boolean,
    /**
     * Exempt from battery optimization. Not required for capture, but an
     * optimized app can be parked in the stopped state, and a stopped app is
     * handed no broadcast at all.
     */
    val batteryExempt: Boolean,
)

/**
 * Reports [CaptureCapability]. An interface so the sync logic can be tested
 * without a Context, the same reason [InboxSource] is one.
 */
fun interface CaptureCapabilitySource {

    fun snapshot(): CaptureCapability

    companion object {
        /**
         * Reports a phone with nothing wrong. Used where no platform state is
         * reachable, such as in tests of the upload path.
         */
        val Healthy = CaptureCapabilitySource {
            CaptureCapability(permitted = true, batteryExempt = true)
        }
    }
}
