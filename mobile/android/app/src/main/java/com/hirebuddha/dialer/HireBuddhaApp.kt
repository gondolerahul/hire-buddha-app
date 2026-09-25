package com.hirebuddha.dialer

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import androidx.work.Configuration
import com.hirebuddha.dialer.core.DialerLog
import com.hirebuddha.dialer.data.logs.LogRepository
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject

@HiltAndroidApp
class HireBuddhaApp : Application(), Configuration.Provider {

    @Inject lateinit var logs: LogRepository

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().setMinimumLoggingLevel(android.util.Log.INFO).build()

    override fun onCreate() {
        super.onCreate()
        DialerLog.install(logs)
        logs.schedulePeriodicUpload()
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            DialerLog.e("Crash", "Uncaught exception on ${thread.name}", error)
            runCatching { kotlinx.coroutines.runBlocking { logs.flush() } }
            previous?.uncaughtException(thread, error)
        }
        DialerLog.i("App", "App started", "version" to BuildConfig.VERSION_NAME, "build" to BuildConfig.VERSION_CODE)
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_RUN, getString(R.string.channel_run), NotificationManager.IMPORTANCE_LOW)
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_CALLS, getString(R.string.channel_calls), NotificationManager.IMPORTANCE_HIGH)
        )
        com.hirebuddha.dialer.data.notify.AppNotifications.createChannels(this)
    }

    companion object {
        const val CHANNEL_RUN = "campaign_run"
        const val CHANNEL_CALLS = "incoming_calls"
    }
}
