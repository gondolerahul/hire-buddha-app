package com.hirebuddha.dialer.data.notify

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.hirebuddha.dialer.MainActivity
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.core.DialerLog
import com.hirebuddha.dialer.data.api.AppVersionDto
import com.hirebuddha.dialer.data.api.CallbackDto
import com.hirebuddha.dialer.data.repo.CampaignRepository
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent
import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit

/**
 * The lock-screen surfaces other than the run itself (wireframe 26): callback reminders
 * and the sideload update prompt. Both used to exist only inside the app, which a rep
 * with the phone face-down on a desk never sees.
 */
object AppNotifications {
    const val CHANNEL_REMINDERS = "callback_reminders"
    const val CHANNEL_UPDATES = "app_updates"
    private const val UPDATE_NOTIFICATION_ID = 7_301

    fun createChannels(context: Context) {
        val nm = context.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_REMINDERS, "Callback reminders", NotificationManager.IMPORTANCE_HIGH)
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_UPDATES, "App updates", NotificationManager.IMPORTANCE_DEFAULT)
        )
    }

    /**
     * One reminder per promised callback, at its time. Only the id is stored with the job:
     * the lead's name is fetched when it fires, so a callback that was moved or cleared in
     * the meantime is not announced, and no lead details sit in WorkManager's database.
     */
    fun scheduleCallbackReminders(context: Context, callbacks: List<CallbackDto>) {
        val now = Instant.now()
        val work = WorkManager.getInstance(context)
        callbacks.forEach { cb ->
            val due = cb.callbackAt?.let(::parseUtc) ?: return@forEach
            if (due.isBefore(now)) return@forEach
            val request = OneTimeWorkRequestBuilder<CallbackReminderWorker>()
                .setInitialDelay(Duration.between(now, due).toMillis(), TimeUnit.MILLISECONDS)
                .setInputData(workDataOf(KEY_CALL to cb.campaignCallId, KEY_DUE to cb.callbackAt))
                .addTag(TAG_REMINDER)
                .build()
            // REPLACE: a callback rescheduled to a new time replaces its old reminder.
            work.enqueueUniqueWork("callback_${cb.campaignCallId}", ExistingWorkPolicy.REPLACE, request)
        }
    }

    /** Once per version: the prompt is useful the first time and noise after that. */
    fun notifyUpdateOnce(context: Context, update: AppVersionDto) {
        if (!update.updateAvailable || update.updateRequired) return
        val url = update.downloadUrl ?: return
        val prefs = context.getSharedPreferences("notifications", Context.MODE_PRIVATE)
        if (prefs.getInt("update_notified", 0) >= update.latestVersionCode) return
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) return
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) return
        val open = PendingIntent.getActivity(
            context, UPDATE_NOTIFICATION_ID,
            Intent(Intent.ACTION_VIEW, Uri.parse(url)),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_UPDATES)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("Version ${update.latestVersionName} is ready to install")
            .setContentText("Tap to download")
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        runCatching { NotificationManagerCompat.from(context).notify(UPDATE_NOTIFICATION_ID, notification) }
            .onSuccess { prefs.edit().putInt("update_notified", update.latestVersionCode).apply() }
    }

    internal fun parseUtc(iso: String): Instant? = runCatching {
        LocalDateTime.parse(iso.removeSuffix("Z").substringBefore('+')).toInstant(ZoneOffset.UTC)
    }.getOrNull()

    internal const val KEY_CALL = "campaign_call_id"
    internal const val KEY_DUE = "callback_at"
    private const val TAG_REMINDER = "callback_reminder"
}

@EntryPoint
@InstallIn(SingletonComponent::class)
interface ReminderEntryPoint {
    fun campaigns(): CampaignRepository
}

class CallbackReminderWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val id = inputData.getString(AppNotifications.KEY_CALL) ?: return Result.success()
        val scheduledFor = inputData.getString(AppNotifications.KEY_DUE)
        val repo = EntryPointAccessors.fromApplication(applicationContext, ReminderEntryPoint::class.java).campaigns()
        // Fresh from the server: the callback may have been made, moved or cleared since.
        val cb = repo.callbacks(withinHours = 1).firstOrNull { it.campaignCallId == id }
        if (cb == null || cb.callbackAt != scheduledFor) {
            DialerLog.i("Reminders", "Callback reminder skipped: no longer due at that time")
            return Result.success()
        }
        if (!NotificationManagerCompat.from(applicationContext).areNotificationsEnabled()) return Result.success()
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(applicationContext, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) return Result.success()
        val at = AppNotifications.parseUtc(cb.callbackAt!!)
            ?.atZone(ZoneId.systemDefault())?.format(DateTimeFormatter.ofPattern("HH:mm"))
        val open = PendingIntent.getActivity(
            applicationContext, id.hashCode(),
            Intent(applicationContext, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val who = cb.contactName ?: cb.phoneMasked
        val notification = NotificationCompat.Builder(applicationContext, AppNotifications.CHANNEL_REMINDERS)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(at?.let { "Callback due at $it" } ?: "Callback due")
            .setContentText(listOfNotNull(who, cb.note?.takeIf { it.isNotBlank() }).joinToString(" — "))
            .setSubText(cb.campaignName)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            // A lead's name on a locked screen: show that a callback is due, not whose.
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPublicVersion(
                NotificationCompat.Builder(applicationContext, AppNotifications.CHANNEL_REMINDERS)
                    .setSmallIcon(R.drawable.ic_notification)
                    .setContentTitle(at?.let { "Callback due at $it" } ?: "Callback due")
                    .build()
            )
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        runCatching { NotificationManagerCompat.from(applicationContext).notify(id.hashCode(), notification) }
        return Result.success()
    }
}
