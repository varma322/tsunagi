package com.vce.tsunagi

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.vce.tsunagi.data.MessageIdentity
import com.vce.tsunagi.data.local.MessageDao
import com.vce.tsunagi.data.local.MessageEntity
import com.vce.tsunagi.data.local.SyncStatus
import com.vce.tsunagi.data.local.TsunagiDatabase
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Exercises the message queries against real SQLite.
 *
 * The sync logic is covered by unit tests with a fake DAO, which cannot catch a
 * query that is wrong rather than a query that is called wrongly — a mistyped
 * column, a BETWEEN that excludes its bounds, a status filter that does not
 * actually exclude the status it names. Those only appear here.
 */
@RunWith(AndroidJUnit4::class)
class MessageDaoTest {

    private lateinit var database: TsunagiDatabase
    private lateinit var dao: MessageDao

    @Before
    fun setUp() {
        database = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(),
            TsunagiDatabase::class.java,
        ).build()
        dao = database.messageDao()
    }

    @After
    fun tearDown() = database.close()

    private fun message(
        sender: String = "AX-AIRTEL",
        body: String = "your code is 4821",
        receivedAt: Long = 1_000L,
        status: SyncStatus = SyncStatus.PENDING,
    ) = MessageEntity(
        id = MessageIdentity.of(sender, body, receivedAt),
        sender = sender,
        body = body,
        receivedAt = receivedAt,
        syncStatus = status,
    )

    @Test
    fun insertingTheSameMessageTwiceStoresOneRow() = runTest {
        assertTrue(dao.insert(message()) != -1L)
        assertEquals(-1L, dao.insert(message()))

        assertEquals(1, dao.pendingCount())
    }

    @Test
    fun idsNearReturnsEachMatchingRowNewestLast() = runTest {
        // Two distinct messages with identical text, minutes apart -- the sweep
        // relies on getting both ids back, not a yes/no, so it can match each
        // to at most one and keep a resend that shares its body with the first.
        dao.insert(message(receivedAt = 60_000L))
        dao.insert(message(receivedAt = 180_000L))

        val ids = dao.idsNear("AX-AIRTEL", "your code is 4821", 0L, 600_000L)

        assertEquals("both distinct rows must come back", 2, ids.size)
        assertEquals(ids.toSet().size, ids.size)
        assertEquals(
            listOf(
                MessageIdentity.of("AX-AIRTEL", "your code is 4821", 60_000L),
                MessageIdentity.of("AX-AIRTEL", "your code is 4821", 180_000L),
            ),
            ids,
        )
    }

    @Test
    fun idsNearHonoursTheWindowSenderAndBody() = runTest {
        dao.insert(message(receivedAt = 60_000L))

        assertEquals(1, dao.idsNear("AX-AIRTEL", "your code is 4821", 30_000L, 90_000L).size)
        // BETWEEN includes its bounds.
        assertEquals(1, dao.idsNear("AX-AIRTEL", "your code is 4821", 60_000L, 90_000L).size)
        assertEquals(1, dao.idsNear("AX-AIRTEL", "your code is 4821", 30_000L, 60_000L).size)
        assertTrue(dao.idsNear("AX-AIRTEL", "your code is 4821", 90_000L, 120_000L).isEmpty())
        assertTrue(dao.idsNear("VM-AIRTEL", "your code is 4821", 0L, 600_000L).isEmpty())
        assertTrue(dao.idsNear("AX-AIRTEL", "different text", 0L, 600_000L).isEmpty())
    }

    @Test
    fun excludeReceivedBetweenHoldsBackOnlyPendingMessagesInsideTheWindow() = runTest {
        val before = message(body = "before", receivedAt = 1_000L)
        val inside = message(body = "inside", receivedAt = 5_000L)
        val after = message(body = "after", receivedAt = 9_000L)
        val syncedInside = message(body = "already synced", receivedAt = 6_000L)
        listOf(before, inside, after, syncedInside).forEach { dao.insert(it) }
        dao.markSynced(listOf(syncedInside.id), 6_000L)

        val held = dao.excludeReceivedBetween(2_000L, 8_000L)

        assertEquals("only the one pending row inside the window", 1, held)
        assertEquals(SyncStatus.EXCLUDED, dao.find(inside.id)?.syncStatus)
        assertEquals(SyncStatus.PENDING, dao.find(before.id)?.syncStatus)
        assertEquals(SyncStatus.PENDING, dao.find(after.id)?.syncStatus)
        assertEquals(
            "an already-synced message is not pulled back",
            SyncStatus.SYNCED,
            dao.find(syncedInside.id)?.syncStatus,
        )
        // The held-back message must no longer be offered for upload.
        assertTrue(dao.pendingBatch(100).none { it.id == inside.id })
    }

    @Test
    fun quarantineTakesAMessageOutOfTheQueue() = runTest {
        dao.insert(message())
        val id = MessageIdentity.of("AX-AIRTEL", "your code is 4821", 1_000L)

        dao.quarantine(listOf(id), "HTTP 422")

        assertEquals(0, dao.pendingCount())
        assertTrue(dao.pendingBatch(100).isEmpty())
        assertEquals(1, dao.quarantinedCount())
        assertEquals(SyncStatus.QUARANTINED, dao.find(id)?.syncStatus)
    }

    @Test
    fun quarantineRecordsTheAttemptAndTheReason() = runTest {
        dao.insert(message())
        val id = MessageIdentity.of("AX-AIRTEL", "your code is 4821", 1_000L)

        dao.quarantine(listOf(id), "HTTP 422")

        val row = dao.find(id)
        assertEquals(1, row?.attemptCount)
        assertEquals("HTTP 422", row?.lastError)
    }

    @Test
    fun aQuarantinedMessageNeverBlocksTheOnesBehindIt() = runTest {
        // The bug this guards: the queue is ordered oldest first, so a message
        // stuck at its head stops everything after it.
        dao.insert(message(body = "poison", receivedAt = 1_000L))
        dao.insert(message(body = "innocent", receivedAt = 2_000L))
        dao.quarantine(
            listOf(MessageIdentity.of("AX-AIRTEL", "poison", 1_000L)),
            "HTTP 422",
        )

        val queue = dao.pendingBatch(100)

        assertEquals(1, queue.size)
        assertEquals("innocent", queue.single().body)
    }

    @Test
    fun theQueueIsOldestFirstAndCoversFailedRows() = runTest {
        dao.insert(message(body = "third", receivedAt = 3_000L))
        dao.insert(message(body = "first", receivedAt = 1_000L, status = SyncStatus.FAILED))
        dao.insert(message(body = "second", receivedAt = 2_000L))
        dao.insert(message(body = "done", receivedAt = 0L, status = SyncStatus.SYNCED))

        assertEquals(
            listOf("first", "second", "third"),
            dao.pendingBatch(100).map { it.body },
        )
    }

    @Test
    fun strandedUploadsAreReturnedToTheQueue() = runTest {
        dao.insert(message(status = SyncStatus.UPLOADING))

        assertEquals(1, dao.requeueStranded())
        assertEquals(1, dao.pendingCount())
    }
}
