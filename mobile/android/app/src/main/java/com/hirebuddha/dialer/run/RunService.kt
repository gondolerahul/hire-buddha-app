package com.hirebuddha.dialer.run

import android.app.Notification
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.ServiceInfo
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import com.hirebuddha.dialer.HireBuddhaApp
import com.hirebuddha.dialer.MainActivity
import com.hirebuddha.dialer.core.DialerLog
import com.hirebuddha.dialer.R
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

/** Foreground service (type phoneCall) that keeps a campaign run alive off-screen. */
@AndroidEntryPoint
class RunService : LifecycleService() {

    @Inject lateinit var controller: RunController

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        try {
            ServiceCompat.startForeground(
                this, NOTIFICATION_ID, notification(controller.state.value),
                ServiceInfo.FOREGROUND_SERVICE_TYPE_PHONE_CALL,
            )
        } catch (e: Exception) {
            // Android 14+ refuses a phoneCall foreground service unless the app holds
            // ROLE_DIALER. Report it and stop cleanly instead of crashing the app.
            DialerLog.e(TAG, "Foreground service refused; is the app still the default phone app?", e)
            controller.stop()
            controller.flushLogs()
            stopSelf()
            return START_NOT_STICKY
        }
        lifecycleScope.launch {
            controller.state.collectLatest { s ->
                androidx.core.app.NotificationManagerCompat.from(this@RunService).let { nm ->
                    if (nm.areNotificationsEnabled()) {
                        runCatching { nm.notify(NOTIFICATION_ID, notification(s)) }
                    }
                }
            }
        }
        // Ship diagnostics while the run is in progress, not only at the end.
        lifecycleScope.launch {
            while (true) {
                kotlinx.coroutines.delay(LOG_FLUSH_INTERVAL_MS)
                controller.flushLogs()
            }
        }
        controller.execute(lifecycleScope) {
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun notification(s: RunUiState): Notification {
        val open = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java).putExtra(MainActivity.EXTRA_OPEN_RUN, true)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val text = when (s.step) {
            Step.IN_CONVERSATION -> "AI is talking to ${s.lead?.name ?: "the lead"}"
            Step.CALLING_LEAD -> "Calling ${s.lead?.name ?: "lead"}"
            Step.WAITING_NEXT -> "Next lead shortly"
            Step.IDLE -> s.message ?: "Idle"
            else -> "Connecting…"
        }
        return NotificationCompat.Builder(this, HireBuddhaApp.CHANNEL_RUN)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(s.campaignName ?: "Campaign run")
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setContentIntent(open)
            .build()
    }

    private companion object {
        const val NOTIFICATION_ID = 7
        const val TAG = "RunService"
        const val LOG_FLUSH_INTERVAL_MS = 30_000L
    }
}
