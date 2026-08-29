package com.vce.tsunagi

import com.vce.tsunagi.data.remote.CheckInRequest
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Pins the JSON the phone sends to what the server accepts.
 *
 * Nothing else catches a rename here. Kotlin properties are camelCase and the
 * API is snake_case, so a mismatch compiles, serializes, and is rejected as a
 * 422 by a server the developer is not looking at — on a phone, in the field.
 */
class CheckInRequestTest {

    private val json = Json { encodeDefaults = true }

    @Test
    fun `the report serializes to the field names the API documents`() {
        val encoded = json.encodeToString(
            CheckInRequest(
                capturePermitted = true,
                inboxReadable = false,
                batteryExempt = true,
                lastCapturedAt = "2026-08-29T09:11:03Z",
                lastSweptAt = "2026-08-29T09:28:41Z",
            )
        )

        assertEquals(
            """{"capture_permitted":true,"inbox_readable":false,"battery_exempt":true,""" +
                """"last_captured_at":"2026-08-29T09:11:03Z",""" +
                """"last_swept_at":"2026-08-29T09:28:41Z"}""",
            encoded,
        )
    }

    @Test
    fun `a phone with nothing captured yet sends nulls rather than omitting them`() {
        val encoded = json.encodeToString(
            CheckInRequest(
                capturePermitted = true,
                inboxReadable = true,
                batteryExempt = false,
                lastCapturedAt = null,
                lastSweptAt = null,
            )
        )

        assertEquals(
            """{"capture_permitted":true,"inbox_readable":true,"battery_exempt":false,""" +
                """"last_captured_at":null,"last_swept_at":null}""",
            encoded,
        )
    }
}
