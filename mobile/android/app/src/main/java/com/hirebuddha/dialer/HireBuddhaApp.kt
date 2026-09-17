package com.hirebuddha.dialer

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import androidx.work.Configuration
import dagger.hilt.android.HiltAndroidApp

@HiltAndroidApp
class HireBuddhaApp : Application(), Configuration.Provider {

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().setMinimumLoggingLevel(android.util.Log.INFO).build()

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_RUN, getString(R.string.channel_run), NotificationManager.IMPORTANCE_LOW)
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_CALLS, getString(R.string.channel_calls), NotificationManager.IMPORTANCE_HIGH)
        )
    }

    companion object {
        const val CHANNEL_RUN = "campaign_run"
        const val CHANNEL_CALLS = "incoming_calls"
    }
}
