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
    fun existsNearFindsAMessageInsideTheWindow() = runTest {
        dao.insert(message(receivedAt = 60_000L))

        assertTrue(
            dao.existsNear("AX-AIRTEL", "your code is 4821", 30_000L, 90_000L)
        )
    }

    @Test
    fun existsNearIncludesItsBounds() = runTest {
        dao.insert(message(receivedAt = 60_000L))

        assertTrue("lower bound", dao.existsNear("AX-AIRTEL", "your code is 4821", 60_000L, 90_000L))
        assertTrue("upper bound", dao.existsNear("AX-AIRTEL", "your code is 4821", 30_000L, 60_000L))
    }

    @Test
    fun existsNearRejectsAMessageOutsideTheWindow() = runTest {
        dao.insert(message(receivedAt = 60_000L))

        assertFalse(
            dao.existsNear("AX-AIRTEL", "your code is 4821", 90_000L, 120_000L)
        )
    }

    @Test
    fun existsNearDistinguishesSenderAndBody() = runTest {
        dao.insert(message(receivedAt = 60_000L))

        assertFalse(
            "a different sender is a different message",
            dao.existsNear("VM-AIRTEL", "your code is 4821", 30_000L, 90_000L),
        )
        assertFalse(
            "a different body is a different message",
            dao.existsNear("AX-AIRTEL", "your code is 9999", 30_000L, 90_000L),
        )
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
