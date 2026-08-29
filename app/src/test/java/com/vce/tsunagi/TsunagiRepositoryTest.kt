package com.vce.tsunagi

import com.vce.tsunagi.data.CaptureCapability
import com.vce.tsunagi.data.CaptureCapabilitySource
import com.vce.tsunagi.data.InboxMessage
import com.vce.tsunagi.data.InboxRead
import com.vce.tsunagi.data.InboxSource
import com.vce.tsunagi.data.SyncOutcome
import com.vce.tsunagi.data.SyncSettings
import com.vce.tsunagi.data.TsunagiRepository
import com.vce.tsunagi.data.TsunagiSettings
import com.vce.tsunagi.data.local.MessageEntity
import com.vce.tsunagi.data.local.SyncStatus
import com.vce.tsunagi.data.remote.BatchResponse
import java.io.IOException
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
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
        var backfillWatermark: Long? = null
        var sweptAt: Long? = null

        override fun snapshot(): TsunagiSettings = current

        override fun clearEnrolmentCode() {
            codeCleared = true
            current = current.copy(setupKey = "")
        }

        override fun recordBackfill(at: Long) {
            backfillWatermark = at
            current = current.copy(lastBackfillAt = at)
        }

        override fun recordSweep(at: Long) {
            sweptAt = at
            current = current.copy(lastSweptAt = at)
        }
    }

    private lateinit var settings: FakeSettings

    private fun repository(
        config: TsunagiSettings = configured,
        inbox: InboxSource = InboxSource.Empty,
        capability: CaptureCapabilitySource = CaptureCapabilitySource.Healthy,
    ): TsunagiRepository {
        settings = FakeSettings(config)
        return TsunagiRepository(
            deviceDao = deviceDao,
            messageDao = messageDao,
            settings = settings,
            apiProvider = { api },
            inbox = inbox,
            capability = capability,
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

    // --- presence --------------------------------------------------------

    @Test
    fun `an idle phone still checks in so it does not look dead`() = runTest {
        deviceDao.device = registeredDevice()

        repository().sync()

        assertEquals(
            "without a check-in the server never hears from a quiet phone and " +
                "reports it offline forever",
            1,
            api.checkIns.size,
        )
    }

    @Test
    fun `a phone that uploaded still reports its health`() = runTest {
        // Uploading refreshes last_seen by itself, so this used to be skipped.
        // It no longer can be: a phone can be busy draining its queue and have
        // already lost the permission that fills it, and health reported only
        // when idle would go stale on exactly the devices worth watching.
        deviceDao.device = registeredDevice()
        seedPending(1)

        repository().sync()

        assertEquals(1, api.uploadedBatches.size)
        assertEquals(1, api.checkIns.size)
    }

    @Test
    fun `a check-in refused with 403 reports the device was switched off`() = runTest {
        deviceDao.device = registeredDevice()
        api.checkInBehaviour = { throw httpError(403) }

        val outcome = repository().sync()

        assertTrue("a disabled phone must learn its state", outcome is SyncOutcome.Failure)
        assertNotNull("403 must not drop the registration", deviceDao.device)
    }

    @Test
    fun `a check-in refused with 401 re-enrols`() = runTest {
        deviceDao.device = registeredDevice()
        api.checkInBehaviour = { throw httpError(401) }

        val outcome = repository().sync()

        assertTrue(outcome is SyncOutcome.Retry)
        assertNull("an unknown token must be discarded", deviceDao.device)
    }

    @Test
    fun `a failed check-in does not mask a successful upload`() = runTest {
        deviceDao.device = registeredDevice()
        seedPending(2)
        api.checkInBehaviour = { throw httpError(500) }

        val outcome = repository().sync()

        assertEquals(SyncOutcome.Success(2), outcome)
    }

    @Test
    fun `a server too old for capture health falls back to the heartbeat`() = runTest {
        // Updating the app before the server must not start reporting failures
        // for a feature the server has never heard of.
        deviceDao.device = registeredDevice()
        api.checkInBehaviour = { throw httpError(404) }

        val outcome = repository().sync()

        assertTrue(outcome is SyncOutcome.Idle)
        assertEquals("presence still has to be reported somehow", 1, api.heartbeats)
    }

    // --- capture health --------------------------------------------------

    @Test
    fun `a healthy phone reports that it can still capture`() = runTest {
        deviceDao.device = registeredDevice()
        messageDao.insert(
            MessageEntity(id = "m", sender = "+1555", body = "hi", receivedAt = 4_000L)
        )

        repository(inbox = inboxOf(InboxMessage("+1555", "hi", 4_000L, 4_000L))).sync()

        val report = api.checkIns.single()
        assertTrue(report.capturePermitted)
        assertTrue(report.inboxReadable)
        assertTrue(report.batteryExempt)
        assertNotNull("the newest message is what says a phone is not silent", report.lastCapturedAt)
    }

    @Test
    fun `a revoked SMS permission is reported`() = runTest {
        // The case the whole check-in exists for: the app still runs, still
        // answers, and captures nothing.
        deviceDao.device = registeredDevice()

        repository(
            capability = CaptureCapabilitySource {
                CaptureCapability(permitted = false, batteryExempt = true)
            },
        ).sync()

        assertFalse(api.checkIns.single().capturePermitted)
    }

    @Test
    fun `an unreadable inbox is reported as a broken sweep, not a quiet one`() = runTest {
        deviceDao.device = registeredDevice()

        repository(inbox = { _, _ -> InboxRead.Unavailable("SMS permission denied") }).sync()

        assertFalse(
            "an empty sweep and a refused sweep must not report the same thing",
            api.checkIns.single().inboxReadable,
        )
    }

    @Test
    fun `battery optimization is reported even when capture works`() = runTest {
        deviceDao.device = registeredDevice()

        repository(
            capability = CaptureCapabilitySource {
                CaptureCapability(permitted = true, batteryExempt = false)
            },
        ).sync()

        val report = api.checkIns.single()
        assertTrue(report.capturePermitted)
        assertFalse("an optimized app can be parked where no broadcast arrives", report.batteryExempt)
    }

    @Test
    fun `a phone with no messages reports no capture time rather than a wrong one`() = runTest {
        deviceDao.device = registeredDevice()

        repository().sync()

        assertNull(api.checkIns.single().lastCapturedAt)
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
    fun `a message delivered twice by the broadcast is stored once`() = runTest {
        val repository = repository()

        assertTrue(repository.captureSms("+15551234567", "your code is 4821", 1_000L))
        assertFalse(
            "a repeated broadcast must not add a second row",
            repository.captureSms("+15551234567", "your code is 4821", 1_000L),
        )

        assertEquals(1, messageDao.rows.size)
    }

    @Test
    fun `distinct messages from one sender are kept apart`() = runTest {
        val repository = repository()

        assertTrue(repository.captureSms("+15551234567", "first", 1_000L))
        assertTrue(repository.captureSms("+15551234567", "second", 2_000L))
        // Same text, later moment: a genuine repeat, not a duplicate delivery.
        assertTrue(repository.captureSms("+15551234567", "first", 3_000L))

        assertEquals(3, messageDao.rows.size)
    }

    // --- capture recovery ------------------------------------------------

    private fun inboxOf(vararg messages: InboxMessage) =
        InboxSource { cutoff, _ -> InboxRead.Read(messages.filter { it.storedAt > cutoff }) }

    /**
     * A repository whose sweep has already run once, so it reads from a fixed
     * watermark. Without one the sweep starts from a look-back measured
     * against the real clock, and no fixed test timestamp falls inside it.
     */
    private fun sweeping(vararg messages: InboxMessage) = repository(
        config = configured.copy(lastBackfillAt = 1L),
        inbox = inboxOf(*messages),
    )

    @Test
    fun `the sweep recovers a message the broadcast never delivered`() = runTest {
        deviceDao.device = registeredDevice()

        val outcome = sweeping(
            InboxMessage(
                sender = "AX-AIRTEL",
                body = "your code is 4821",
                receivedAt = 5_000L,
                storedAt = 5_000L,
            )
        ).sync()

        assertEquals(SyncOutcome.Success(1), outcome)
        assertEquals(1, messageDao.rows.size)
        assertEquals("AX-AIRTEL", messageDao.rows.values.single().sender)
    }

    @Test
    fun `the sweep does not re-store what the broadcast already captured`() = runTest {
        deviceDao.device = registeredDevice()
        val repository = sweeping(
            InboxMessage(
                sender = "AX-AIRTEL",
                body = "your code is 4821",
                receivedAt = 5_000L,
                storedAt = 5_000L,
            )
        )
        repository.captureSms("AX-AIRTEL", "your code is 4821", 5_000L)

        repository.sync()

        assertEquals(1, messageDao.rows.size)
    }

    @Test
    fun `the sweep tolerates the inbox and the broadcast disagreeing on the time`() = runTest {
        deviceDao.device = registeredDevice()
        // The platform recorded no service centre time, so its timestamp is
        // the moment it stored the message rather than the one the broadcast
        // reported. The derived ids differ; the message is still the same one.
        val repository = sweeping(
            InboxMessage(
                sender = "AX-AIRTEL",
                body = "your code is 4821",
                receivedAt = 65_000L,
                storedAt = 65_000L,
            )
        )
        repository.captureSms("AX-AIRTEL", "your code is 4821", 5_000L)

        repository.sync()

        assertEquals(1, messageDao.rows.size)
    }

    @Test
    fun `a message far from any capture is not mistaken for one`() = runTest {
        deviceDao.device = registeredDevice()
        // Same sender and text, but hours apart: a genuine repeat that the
        // tolerance window must not swallow.
        val repository = sweeping(
            InboxMessage("AX-AIRTEL", "your code is 4821", 5_000L + 4 * 60 * 60 * 1000, 9_000L)
        )
        repository.captureSms("AX-AIRTEL", "your code is 4821", 5_000L)

        repository.sync()

        assertEquals(2, messageDao.rows.size)
    }

    @Test
    fun `a recovered message uploads on the same pass`() = runTest {
        deviceDao.device = registeredDevice()

        val outcome = sweeping(
            InboxMessage("AX-AIRTEL", "code 1", 5_000L, 5_000L),
            InboxMessage("AX-AIRTEL", "code 2", 6_000L, 6_000L),
        ).sync()

        assertEquals(SyncOutcome.Success(2), outcome)
        assertEquals(2, api.uploadedBatches.single().messages.size)
        assertTrue(messageDao.rows.values.all { it.syncStatus == SyncStatus.SYNCED })
    }

    @Test
    fun `the sweep watermark advances so the next pass does not re-read`() = runTest {
        deviceDao.device = registeredDevice()

        sweeping(InboxMessage("AX-AIRTEL", "code 1", 5_000L, 7_000L)).sync()

        assertEquals(7_000L, settings.backfillWatermark)
    }

    @Test
    fun `a first sweep does not upload the phone's whole message history`() = runTest {
        deviceDao.device = registeredDevice()
        val now = System.currentTimeMillis()
        // No watermark yet, so the look-back decides. A message from last year
        // predates the install and must not be swept up on first run.
        val outcome = repository(
            inbox = inboxOf(
                InboxMessage("AX-AIRTEL", "ancient", now - 365 * DAY, now - 365 * DAY),
                InboxMessage("AX-AIRTEL", "recent", now - 60_000L, now - 60_000L),
            )
        ).sync()

        assertEquals(SyncOutcome.Success(1), outcome)
        assertEquals("recent", messageDao.rows.values.single().body)
    }

    // --- a message the server will never accept --------------------------

    @Test
    fun `a message the server permanently refuses is set aside`() = runTest {
        deviceDao.device = registeredDevice()
        seedPending(1)
        api.uploadBehaviour = { throw httpError(422) }

        val outcome = repository().sync()

        assertEquals(SyncOutcome.Idle("No pending messages."), outcome)
        assertEquals(SyncStatus.QUARANTINED, messageDao.rows.values.single().syncStatus)
        // Out of the queue, so it cannot be selected again.
        assertEquals(0, messageDao.pendingCount())
    }

    @Test
    fun `one refused message does not block the rest of the queue`() = runTest {
        deviceDao.device = registeredDevice()
        seedPending(3)
        val poison = messageDao.rows.values.first { it.body == "body 1" }.id
        api.uploadBehaviour = { request ->
            if (request.messages.any { it.id == poison }) throw httpError(422)
            BatchResponse(
                accepted = request.messages.size,
                created = request.messages.size,
                duplicates = 0,
            )
        }

        val outcome = repository().sync()

        // The two innocent messages still went up.
        assertEquals(SyncOutcome.Success(2), outcome)
        assertEquals(
            SyncStatus.QUARANTINED,
            messageDao.rows.getValue(poison).syncStatus,
        )
        assertTrue(
            messageDao.rows.values
                .filter { it.id != poison }
                .all { it.syncStatus == SyncStatus.SYNCED },
        )
        assertEquals(0, messageDao.pendingCount())
    }

    @Test
    fun `several refused messages are each set aside`() = runTest {
        deviceDao.device = registeredDevice()
        seedPending(5)
        val poison = messageDao.rows.values
            .filter { it.body == "body 1" || it.body == "body 3" }
            .map { it.id }
            .toSet()
        api.uploadBehaviour = { request ->
            if (request.messages.any { it.id in poison }) throw httpError(422)
            BatchResponse(
                accepted = request.messages.size,
                created = request.messages.size,
                duplicates = 0,
            )
        }

        val outcome = repository().sync()

        assertEquals(SyncOutcome.Success(3), outcome)
        assertEquals(2, messageDao.quarantinedCount())
        assertEquals(0, messageDao.pendingCount())
    }

    @Test
    fun `a disabled device is not mistaken for a bad message`() = runTest {
        deviceDao.device = registeredDevice()
        seedPending(3)
        api.uploadBehaviour = { throw httpError(403) }

        val outcome = repository().sync()

        assertTrue(outcome is SyncOutcome.Failure)
        // Nothing quarantined: the device is at fault, not the messages.
        assertTrue(messageDao.rows.values.none { it.syncStatus == SyncStatus.QUARANTINED })
        assertEquals(3, messageDao.pendingCount())
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
