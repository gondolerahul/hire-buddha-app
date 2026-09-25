package com.hirebuddha.dialer.run

import android.app.Notification
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import com.hirebuddha.dialer.HireBuddhaApp
import com.hirebuddha.dialer.MainActivity
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.core.DialerLog
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

/**
 * Foreground service (type phoneCall) that keeps a campaign run alive off-screen.
 *
 * Reps put the phone down. For minutes at a time this notification *is* the app
 * (FR-E8, docs 11 screen 26), so it carries a live timer and the three controls that
 * matter rather than being a static "running" label.
 */
@AndroidEntryPoint
class RunService : LifecycleService() {

    @Inject lateinit var controller: RunController

    /** Notification actions arrive here; nothing else may drive the run from outside. */
    private val actions = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            when (intent?.action) {
                ACTION_TOGGLE_MUTE -> controller.command(UserCommand.TOGGLE_MUTE)
                ACTION_PAUSE -> controller.pause()
                ACTION_HANG_UP -> controller.command(UserCommand.HANG_UP)
                ACTION_SKIP -> controller.command(UserCommand.SKIP)
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        val filter = IntentFilter().apply {
            addAction(ACTION_TOGGLE_MUTE)
            addAction(ACTION_PAUSE)
            addAction(ACTION_HANG_UP)
            addAction(ACTION_SKIP)
        }
        ContextCompat.registerReceiver(this, actions, filter, ContextCompat.RECEIVER_NOT_EXPORTED)
    }

    override fun onDestroy() {
        runCatching { unregisterReceiver(actions) }
        super.onDestroy()
    }

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
                NotificationManagerCompat.from(this@RunService).let { nm ->
                    if (nm.areNotificationsEnabled()) runCatching { nm.notify(NOTIFICATION_ID, notification(s)) }
                }
            }
        }
        // Re-post once a second while a conversation is live so the timer actually ticks.
        lifecycleScope.launch {
            while (true) {
                delay(1_000)
                val s = controller.state.value
                if (s.step == Step.IN_CONVERSATION) {
                    NotificationManagerCompat.from(this@RunService).let { nm ->
                        if (nm.areNotificationsEnabled()) runCatching { nm.notify(NOTIFICATION_ID, notification(s)) }
                    }
                }
            }
        }
        // Ship diagnostics while the run is in progress, not only at the end.
        lifecycleScope.launch {
            while (true) {
                delay(LOG_FLUSH_INTERVAL_MS)
                controller.flushLogs()
            }
        }
        controller.execute(lifecycleScope) {
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
        return START_NOT_STICKY
    }

    private fun action(name: String, requestCode: Int): PendingIntent =
        PendingIntent.getBroadcast(
            this, requestCode,
            Intent(name).setPackage(packageName),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

    private fun notification(s: RunUiState): Notification {
        val open = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java).putExtra(MainActivity.EXTRA_OPEN_RUN, true)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val lead = s.lead?.name ?: "the lead"
        val elapsed = s.conversationStartedAt?.let { (System.currentTimeMillis() - it) / 1000 }
        val title = when (s.step) {
            Step.IN_CONVERSATION -> elapsed?.let { "In conversation · %d:%02d".format(it / 60, it % 60) }
                ?: "In conversation"
            Step.CALLING_LEAD -> "Ringing $lead"
            Step.MERGING -> "Bringing everyone together"
            Step.WAITING_NEXT -> "Next lead shortly"
            Step.FETCHING_LEAD -> "Finding the next lead"
            Step.IDLE -> s.campaignName ?: "Campaign run"
            else -> "Connecting ${s.agentName?.substringBefore(' ') ?: "the agent"}"
        }
        val text = when (s.step) {
            Step.IN_CONVERSATION -> "$lead · ${s.campaignName ?: "campaign"}"
            else -> listOfNotNull(s.campaignName, s.lastOutcome).joinToString(" · ").ifBlank { "Working through the list" }
        }

        val builder = NotificationCompat.Builder(this, HireBuddhaApp.CHANNEL_RUN)
            .setSmallIcon(R.drawable.ic_notification)
            .setColor(0xFFEDAB48.toInt())
            .setColorized(false)
            .setContentTitle(title)
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setContentIntent(open)

        s.lead?.let { lead ->
            val total = s.callsMade + 1 + lead.remaining
            builder.setProgress(total, s.callsMade, false)
            builder.setSubText("${s.callsMade} of $total called")
        }

        // Only offer what applies right now: a notification full of dead buttons is worse
        // than one with none.
        when (s.step) {
            Step.IN_CONVERSATION -> {
                builder.addAction(
                    if (s.muted) R.drawable.ic_mic else R.drawable.ic_mic_off,
                    if (s.muted) "Unmute" else "Mute",
                    action(ACTION_TOGGLE_MUTE, 1),
                )
                builder.addAction(R.drawable.ic_pause, "Pause run", action(ACTION_PAUSE, 2))
                builder.addAction(R.drawable.ic_phone_end, "End call", action(ACTION_HANG_UP, 3))
            }
            Step.IDLE -> Unit
            else -> {
                builder.addAction(R.drawable.ic_skip, "Skip lead", action(ACTION_SKIP, 4))
                builder.addAction(R.drawable.ic_pause, "Pause run", action(ACTION_PAUSE, 2))
            }
        }
        return builder.build()
    }

    private companion object {
        const val NOTIFICATION_ID = 7
        const val TAG = "RunService"
        const val LOG_FLUSH_INTERVAL_MS = 30_000L
        const val ACTION_TOGGLE_MUTE = "com.hirebuddha.dialer.action.TOGGLE_MUTE"
        const val ACTION_PAUSE = "com.hirebuddha.dialer.action.PAUSE"
        const val ACTION_HANG_UP = "com.hirebuddha.dialer.action.HANG_UP"
        const val ACTION_SKIP = "com.hirebuddha.dialer.action.SKIP"
    }
}
