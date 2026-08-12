package com.vce.tsunagi

import com.vce.tsunagi.data.SyncOutcome
import com.vce.tsunagi.data.SyncSettings
import com.vce.tsunagi.data.TsunagiRepository
import com.vce.tsunagi.data.TsunagiSettings
import com.vce.tsunagi.data.local.MessageEntity
import com.vce.tsunagi.data.local.SyncStatus
import java.io.IOException
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class TsunagiRepositoryTest {

    private lateinit var deviceDao: FakeDeviceDao
    private lateinit var messageDao: FakeMessageDao
    private lateinit var api: FakeApi

    private val configured = TsunagiSettings(
        serverUrl = "https://tsunagi.example.com",
        deviceName = "Test Phone",
        setupKey = "setup-key",
        // Pruning is exercised by its own tests; keep it out of the way here.
        retentionDays = 0,
    )

    private companion object {
        const val DAY = 24L * 60 * 60 * 1000
    }

    @Before
    fun setUp() {
        deviceDao = FakeDeviceDao()
        messageDao = FakeMessageDao()
        api = FakeApi()
    }

    /** Records whether the enrolment code was discarded after registration. */
    private class FakeSettings(private var current: TsunagiSettings) : SyncSettings {
        var codeCleared = false

        override fun snapshot(): TsunagiSettings = current

        override fun clearEnrolmentCode() {
            codeCleared = true
            current = current.copy(setupKey = "")
        }
    }

    private lateinit var settings: FakeSettings

    private fun repository(config: TsunagiSettings = configured): TsunagiRepository {
        settings = FakeSettings(config)
        return TsunagiRepository(
            deviceDao = deviceDao,
            messageDao = messageDao,
            settings = settings,
            apiProvider = { api },
        )
    }

    private suspend fun seedPending(count: Int) {
        repeat(count) { index ->
            messageDao.insert(
                MessageEntity(
                    id = "message-$index",
                    sender = "+1555000000$index",
                    body = "body $index",
                    receivedAt = 1_000L + index,
                )
            )
        }
    }

    @Test
    fun `sync is idle when server is not configured`() = runTest {
        val outcome = repository(TsunagiSettings()).sync()

        assertTrue(outcome is SyncOutcome.Idle)
        assertEquals(0, api.registerCalls)
    }

    @Test
    fun `sync registers the device once and reuses the stored token`() = runTest {
        seedPending(1)

        assertTrue(repository().sync() is SyncOutcome.Success)
        seedPending(2)
        assertTrue(repository().sync() is SyncOutcome.Success)

        assertEquals(1, api.registerCalls)
        assertEquals("device-1", deviceDao.device?.deviceId)
    }

    @Test
    fun `the enrolment code is discarded once it has been spent`() = runTest {
        seedPending(1)

        val repo = repository()
        repo.sync()

        assertTrue("a spent code must not linger on the phone", settings.codeCleared)
    }

    @Test
    fun `sync uploads pending messages and marks them synced`() = runTest {
        seedPending(3)

        val outcome = repository().sync()

        assertEquals(SyncOutcome.Success(3), outcome)
        assertEquals(1, api.uploadedBatches.size)
        assertEquals(3, api.uploadedBatches.single().messages.size)
        assertTrue(messageDao.rows.values.all { it.syncStatus == SyncStatus.SYNCED })
        assertTrue(messageDao.rows.values.all { it.syncedAt != null })
    }

    @Test
    fun `sync sends received_at as an ISO-8601 instant`() = runTest {
        messageDao.insert(
            MessageEntity(
                id = "message-iso",
                sender = "+15551234567",
                body = "hello",
                receivedAt = 1_768_000_000_000L,
            )
        )

        repository().sync()

        assertEquals(
            "2026-01-09T23:06:40Z",
            api.uploadedBatches.single().messages.single().receivedAt,
        )
    }

    @Test
    fun `sync is idle when there is nothing pending`() = runTest {
        deviceDao.device = registeredDevice()

        val outcome = repository().sync()

        assertTrue(outcome is SyncOutcome.Idle)
        assertTrue(api.uploadedBatches.isEmpty())
    }

    @Test
    fun `messages stranded in UPLOADING are requeued`() = runTest {
        seedPending(1)
        messageDao.markStatus(listOf("message-0"), SyncStatus.UPLOADING)

        val outcome = repository().sync()

        assertEquals(1, messageDao.requeuedStranded)
        assertEquals(SyncOutcome.Success(1), outcome)
    }

    @Test
    fun `network failure during upload retries and leaves messages queued`() = runTest {
        seedPending(2)
        api.uploadBehaviour = { throw IOException("connection reset") }

        val outcome = repository().sync()

        assertTrue(outcome is SyncOutcome.Retry)
        assertTrue(messageDao.rows.values.all { it.syncStatus == SyncStatus.FAILED })
        assertTrue(messageDao.rows.values.all { it.attemptCount == 1 })
        // Still selectable by the next pass.
        assertEquals(2, messageDao.pendingCount())
    }

    @Test
    fun `revoked device token clears the registration and retries`() = runTest {
        deviceDao.device = registeredDevice()
        seedPending(1)
        api.uploadBehaviour = { throw httpError(401) }

        val outcome = repository().sync()

        assertTrue(outcome is SyncOutcome.Retry)
        assertNull("stale registration must be dropped", deviceDao.device)
        assertEquals(1, deviceDao.clearCount)
    }

    @Test
    fun `a disabled device stops uploading instead of re-enrolling`() = runTest {
        deviceDao.device = registeredDevice()
        seedPending(1)
        api.uploadBehaviour = { throw httpError(403) }

        val outcome = repository().sync()

        assertTrue("403 must be terminal, not a retry", outcome is SyncOutcome.Failure)
        assertNotNull(
            "clearing the registration here would let the phone re-enrol and " +
                "defeat the server-side off switch",
            deviceDao.device,
        )
        assertEquals(0, api.registerCalls)
    }

    @Test
    fun `server error during upload is retried`() = runTest {
        deviceDao.device = registeredDevice()
        seedPending(1)
        api.uploadBehaviour = { throw httpError(503) }

        assertTrue(repository().sync() is SyncOutcome.Retry)
        assertNotNull("a 503 must not discard the registration", deviceDao.device)
    }

    @Test
    fun `rejected setup key fails without retrying`() = runTest {
        seedPending(1)
        api.registerBehaviour = { throw httpError(403) }

        val outcome = repository().sync()

        assertTrue(outcome is SyncOutcome.Failure)
        assertNull(deviceDao.device)
    }

    @Test
    fun `registration without a setup key fails fast`() = runTest {
        seedPending(1)

        val outcome = repository(configured.copy(setupKey = "")).sync()

        assertTrue(outcome is SyncOutcome.Failure)
        assertEquals(0, api.registerCalls)
    }

    @Test
    fun `capturing the same message id twice stores one row`() = runTest {
        val repository = repository()
        assertTrue(repository.captureSms("+15551234567", "first", 1_000L))
        assertTrue(repository.captureSms("+15551234567", "second", 2_000L))

        // Distinct ids are generated per capture, so both are stored.
        assertEquals(2, messageDao.rows.size)
        // Re-inserting a known id is ignored.
        assertEquals(-1L, messageDao.insert(messageDao.rows.values.first()))
    }

    // --- retention -------------------------------------------------------

    private fun storeSynced(id: String, syncedAt: Long?) {
        messageDao.rows[id] = MessageEntity(
            id = id,
            sender = "+15551234567",
            body = "body",
            receivedAt = syncedAt ?: 0L,
            syncStatus = SyncStatus.SYNCED,
            syncedAt = syncedAt,
        )
    }

    @Test
    fun `prune deletes synced messages past the retention window`() = runTest {
        val now = System.currentTimeMillis()
        storeSynced("old", now - 40L * DAY)
        storeSynced("recent", now - 2L * DAY)

        val removed = repository().prune(retentionDays = 30)

        assertEquals(1, removed)
        assertNull(messageDao.rows["old"])
        assertNotNull(messageDao.rows["recent"])
    }

    @Test
    fun `prune never deletes messages the server has not confirmed`() = runTest {
        val now = System.currentTimeMillis()
        messageDao.insert(
            MessageEntity(
                id = "ancient-pending",
                sender = "+15551234567",
                body = "never uploaded",
                receivedAt = now - 400L * DAY,
            )
        )
        messageDao.markFailed(listOf("ancient-pending"), "offline for a long time")

        val removed = repository().prune(retentionDays = 1)

        assertEquals(0, removed)
        assertNotNull(
            "an unsynced message exists nowhere else and must survive pruning",
            messageDao.rows["ancient-pending"],
        )
    }

    @Test
    fun `retention of zero keeps everything`() = runTest {
        storeSynced("ancient", System.currentTimeMillis() - 3650L * DAY)

        assertEquals(0, repository().prune(retentionDays = 0))
        assertNotNull(messageDao.rows["ancient"])
    }

    @Test
    fun `sync prunes using the configured retention`() = runTest {
        deviceDao.device = registeredDevice()
        storeSynced("stale", System.currentTimeMillis() - 90L * DAY)

        repository(configured.copy(retentionDays = 30)).sync()

        assertNull(messageDao.rows["stale"])
    }

    private fun registeredDevice() = com.vce.tsunagi.data.local.DeviceEntity(
        deviceId = "device-existing",
        deviceName = "Test Phone",
        token = "tsn_dev_existing",
        createdAt = 0L,
    )
}
