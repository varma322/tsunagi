package com.vce.tsunagi

import android.app.Application
import android.content.Context
import com.vce.tsunagi.data.SettingsStore
import com.vce.tsunagi.data.TsunagiRepository
import com.vce.tsunagi.data.local.TsunagiDatabase
import com.vce.tsunagi.sms.SmsInbox
import com.vce.tsunagi.sync.SyncScheduler

/**
 * Manual dependency container.
 *
 * The graph is small enough that a DI framework would cost more than it saves,
 * and [SmsReceiver][com.vce.tsunagi.sms.SmsReceiver] plus
 * [SyncWorker][com.vce.tsunagi.sync.SyncWorker] need to reach it from a bare
 * Context rather than an injected scope.
 */
class AppContainer(context: Context) {

    private val database = TsunagiDatabase.get(context)

    val settings = SettingsStore(context)

    val repository = TsunagiRepository(
        deviceDao = database.deviceDao(),
        messageDao = database.messageDao(),
        settings = settings,
        inbox = SmsInbox(context),
    )
}

class TsunagiApplication : Application() {

    val container: AppContainer by lazy { AppContainer(this) }

    override fun onCreate() {
        super.onCreate()
        SyncScheduler.ensurePeriodicSync(this)
    }

    companion object {
        /**
         * Falls back to building a container when the Context does not belong
         * to this Application, which happens for receivers in some test and
         * restore paths.
         */
        fun container(context: Context): AppContainer =
            when (val app = context.applicationContext) {
                is TsunagiApplication -> app.container
                else -> AppContainer(context)
            }
    }
}
