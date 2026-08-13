package com.vce.tsunagi.data

/**
 * A message already delivered to the phone, read back from the platform SMS
 * store rather than from a live broadcast.
 */
data class InboxMessage(
    val sender: String,
    val body: String,
    /**
     * The service centre timestamp, which is what a live broadcast reports.
     * Matching on it is what lets a swept message recognise itself as one the
     * broadcast already captured.
     */
    val receivedAt: Long,
    /**
     * When the platform wrote the message to its own store. Drives the sweep
     * watermark, because unlike [receivedAt] it always moves forward.
     */
    val storedAt: Long,
)

/**
 * Reads messages the phone has already received.
 *
 * The live broadcast is best-effort: it does not arrive at all while the app
 * sits in the stopped state, and it can be lost to process death between
 * delivery and the database write. Reading the platform's own copy is the only
 * way to notice a message that was missed, so this is the app's safety net
 * rather than its primary path.
 *
 * Kept as an interface so the sync logic can be tested without a Context.
 */
fun interface InboxSource {

    /**
     * Messages the platform stored after [cutoff], oldest first. Returns an
     * empty list when the inbox cannot be read at all — a revoked permission
     * or a device with no SMS provider — since a sweep that cannot run must
     * not be reported as a sweep that found nothing wrong.
     */
    suspend fun since(cutoff: Long, limit: Int): List<InboxMessage>

    companion object {
        /** Used where no platform inbox is available, such as in tests. */
        val Empty = InboxSource { _, _ -> emptyList() }
    }
}
