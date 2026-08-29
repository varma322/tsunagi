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
 * The outcome of one read of the platform SMS store.
 *
 * A list alone could not carry this: an empty one meant both "nothing new
 * arrived" and "this app is no longer allowed to look", which are opposite
 * facts about a phone's health. The dashboard needs them apart.
 */
sealed interface InboxRead {
    /** The store was queried. [messages] is everything it returned. */
    data class Read(val messages: List<InboxMessage>) : InboxRead

    /** The store could not be read at all, so nothing was ruled out. */
    data class Unavailable(val reason: String) : InboxRead
}

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
     * Messages the platform stored after [cutoff], oldest first.
     *
     * Answers [InboxRead.Unavailable] when the store cannot be read — a
     * revoked permission, or a device with no SMS provider — because a sweep
     * that could not run must never be reported as a sweep that found nothing
     * wrong.
     */
    suspend fun since(cutoff: Long, limit: Int): InboxRead

    companion object {
        /** Used where no platform inbox is available, such as in tests. */
        val Empty = InboxSource { _, _ -> InboxRead.Read(emptyList()) }
    }
}
