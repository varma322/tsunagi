package com.vce.tsunagi.data

import java.util.UUID

/**
 * Derives a message's id from its content.
 *
 * A random id per capture makes every sighting of a message look new, which
 * defeats deduplication in both directions: a broadcast delivered twice stores
 * two rows, and the inbox sweep re-uploads everything the broadcast already
 * caught. Deriving the id from the message means the same SMS always resolves
 * to the same id, on this phone and on the server.
 *
 * The result is a name-based UUID so it stays a valid UUID, which is what the
 * server's message id column expects.
 */
object MessageIdentity {

    /**
     * NUL, which cannot appear in a decoded SMS. That is what makes the join
     * unambiguous: with a printable separator, a body containing it could
     * collide two distinct messages onto one id and silently drop one.
     */
    private val SEPARATOR = Char(0)

    fun of(sender: String, body: String, receivedAt: Long): String =
        UUID.nameUUIDFromBytes(
            "$sender$SEPARATOR$body$SEPARATOR$receivedAt".toByteArray(Charsets.UTF_8)
        ).toString()
}
