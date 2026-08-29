package com.vce.tsunagi

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.vce.tsunagi.data.SyncSettings
import com.vce.tsunagi.data.TsunagiRepository
import com.vce.tsunagi.data.TsunagiSettings
import com.vce.tsunagi.data.local.SyncStatus
import com.vce.tsunagi.data.local.TsunagiDatabase
import com.vce.tsunagi.sms.SmsInbox
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * The inbox sweep end to end: the real SMS provider, the real deduplication,
 * and real SQLite.
 *
 * The unit tests prove the sweep's logic against a fake inbox, which is a
 * fixture that agrees with the code's assumptions by construction. What has to
 * hold in production is different — that messages a provider actually returns
 * can be stored, and that sweeping twice does not upload everything twice.
 * Getting the second one wrong duplicates a user's whole inbox on the server,
 * and no fake would show it.
 */
@RunWith(AndroidJUnit4::class)
class BackfillTest {

    private lateinit var database: TsunagiDatabase
    private lateinit var repository: TsunagiRepository
    private lateinit var settings: RecordingSettings

    /** Starts with no watermark so the look-back applies, as on a fresh install. */
    private class RecordingSettings : SyncSettings {
        var watermark: Long? = null

        override fun snapshot() = TsunagiSettings(lastBackfillAt = watermark)
        override fun clearEnrolmentCode() = Unit
        override fun recordBackfill(at: Long) {
            watermark = at
        }

        override fun recordSweep(at: Long) = Unit
    }

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        InstrumentationRegistry.getInstrumentation().uiAutomation.grantRuntimePermission(
            context.packageName,
            android.Manifest.permission.READ_SMS,
        )
        database = Room.inMemoryDatabaseBuilder(context, TsunagiDatabase::class.java).build()
        settings = RecordingSettings()
        repository = TsunagiRepository(
            deviceDao = database.deviceDao(),
            messageDao = database.messageDao(),
            settings = settings,
            inbox = SmsInbox(context),
        )
    }

    @After
    fun tearDown() = database.close()

    @Test
    fun sweepingTwiceDoesNotStoreAnythingTwice() = runTest {
        val first = repository.backfill()
        val storedAfterFirst = database.messageDao().pendingCount()

        // On an inbox with nothing in the look-back window the comparison
        // below is 0 against 0, which proves nothing. Skip rather than pass:
        // a green run here has to mean deduplication was actually exercised.
        assumeTrue("needs messages in the inbox to be meaningful", first.recovered > 0)

        val second = repository.backfill()

        assertEquals("a second sweep must recover nothing", 0, second.recovered)
        assertEquals(
            "the row count must not move on a repeat sweep",
            storedAfterFirst,
            database.messageDao().pendingCount(),
        )
        assertEquals(first.recovered, storedAfterFirst)
    }

    @Test
    fun aSweepOfTheRealProviderReportsItselfReadable() = runTest {
        // The health the phone reports rests on this: a sweep that read the
        // store says so, and only a sweep that could not says otherwise.
        assertTrue("a granted permission must read as readable", repository.backfill().readable)
    }

    @Test
    fun aSweptMessageIsQueuedForUpload() = runTest {
        repository.backfill()

        // Whatever the provider held, everything taken from it must be
        // upload-ready. A row stored in any other state would never leave.
        val queued = database.messageDao().pendingBatch(500)
        assertEquals(database.messageDao().pendingCount(), queued.size)
        assertTrue(queued.all { it.syncStatus == SyncStatus.PENDING })
    }

    @Test
    fun everySweptMessageIsAcceptableToTheServer() = runTest {
        repository.backfill()

        // The server requires a non-empty sender and a representable instant.
        // A message failing either is one the batch endpoint rejects, and a
        // rejected message used to stall the whole queue.
        database.messageDao().pendingBatch(500).forEach {
            assertTrue("blank sender from the provider", it.sender.isNotBlank())
            assertTrue("non-positive receivedAt from ${it.sender}", it.receivedAt > 0L)
        }
    }

    @Test
    fun theWatermarkAdvancesPastWhatWasRead() = runTest {
        val sweep = repository.backfill()

        // With nothing in the look-back window nothing was examined, and the
        // watermark deliberately does not step over what it has not read — so
        // there is no advance to assert on. Skip rather than pass.
        assumeTrue("needs messages in the inbox to be meaningful", sweep.recovered > 0)

        val advanced = settings.watermark
        assertTrue("the sweep must record how far it read", advanced != null)
        assertTrue("the watermark must not sit in the future", advanced!! <= System.currentTimeMillis())
    }
}
