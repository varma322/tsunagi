package com.vce.tsunagi

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.vce.tsunagi.sms.SmsInbox
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Runs the inbox sweep's query against the platform SMS provider.
 *
 * This is the part no unit test can reach. The sweep is the app's only defence
 * against a broadcast that never arrives, and it is built on a projection of
 * column names and a LIMIT smuggled into the sort order — the kind of thing
 * that is either right or throws on the first real query, with nothing in
 * between. A fake inbox proves the sweep's logic and says nothing about
 * whether it can read an inbox at all.
 */
@RunWith(AndroidJUnit4::class)
class SmsInboxTest {

    private lateinit var inbox: SmsInbox

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        InstrumentationRegistry.getInstrumentation().uiAutomation.grantRuntimePermission(
            context.packageName,
            android.Manifest.permission.READ_SMS,
        )
        inbox = SmsInbox(context)
    }

    @Test
    fun theQueryRunsAgainstTheRealProvider() = runTest {
        // Asserting on content would depend on what happens to be on the
        // device. What is being proved is that the projection resolves, the
        // selection binds, and the sort order parses — a wrong column name
        // throws here rather than silently returning nothing.
        val found = inbox.since(cutoff = 0L, limit = 50)

        assertTrue("a real query returns at most the limit", found.size <= 50)
    }

    @Test
    fun theLimitIsHonoured() = runTest {
        // The LIMIT rides on the sort order, which the platform provider is
        // not obliged to honour. SmsInbox stops reading at the limit itself
        // for that reason; this is what proves the cap holds either way.
        val found = inbox.since(cutoff = 0L, limit = 1)

        assertTrue("asked for one, got ${found.size}", found.size <= 1)
    }

    @Test
    fun aFutureCutoffMatchesNothing() = runTest {
        val ahead = System.currentTimeMillis() + 365L * 24 * 60 * 60 * 1000

        assertTrue(inbox.since(cutoff = ahead, limit = 50).isEmpty())
    }

    @Test
    fun everyMessageReadCarriesAUsableSenderAndTimestamp() = runTest {
        // The sweep derives an id from these, and the server rejects a blank
        // sender outright, so a message read with neither is a message that
        // would be stored and then permanently refused.
        inbox.since(cutoff = 0L, limit = 50).forEach {
            assertTrue("blank sender read from the provider", it.sender.isNotBlank())
            assertTrue("non-positive receivedAt for ${it.sender}", it.receivedAt > 0L)
            assertTrue("non-positive storedAt for ${it.sender}", it.storedAt > 0L)
        }
    }
}
