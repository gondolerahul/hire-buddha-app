package com.hirebuddha.dialer.telecom

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.telecom.Call
import android.telecom.InCallService
import androidx.core.app.NotificationCompat
import com.hirebuddha.dialer.HireBuddhaApp
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.run.RunController
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * Default-dialer InCallService (ROLE_DIALER). Campaign calls are driven by the run
 * orchestrator; any other call (a normal incoming call, a call from our dial pad) gets
 * the minimal [InCallActivity] UI, as the role requires.
 */
@AndroidEntryPoint
class HbInCallService : InCallService() {

    @Inject lateinit var registry: CallRegistry
    @Inject lateinit var runController: RunController

    override fun onCreate() {
        super.onCreate()
        registry.attach(this)
    }

    override fun onDestroy() {
        registry.detach(this)
        super.onDestroy()
    }

    override fun onCallAdded(call: Call) {
        super.onCallAdded(call)
        registry.onCallAdded(call)
        val number = call.details.handle?.schemeSpecificPart
        val campaignCall = runController.isRunActive() && registry.isCampaignNumber(number)
        if (campaignCall) return
        if (call.state == Call.STATE_RINGING) {
            runController.onIncomingCallDuringRun()
            showIncomingCall(number)
        } else {
            startActivity(Intent(this, InCallActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }

    override fun onCallRemoved(call: Call) {
        super.onCallRemoved(call)
        registry.onCallRemoved(call)
        if (registry.calls.value.none { it.state == CallState.RINGING }) {
            getSystemService(NotificationManager::class.java).cancel(NOTIFICATION_INCOMING)
        }
    }

    private fun showIncomingCall(number: String?) {
        val intent = Intent(this, InCallActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val pending = PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification = NotificationCompat.Builder(this, HireBuddhaApp.CHANNEL_CALLS)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("Incoming call")
            .setContentText(number ?: "Unknown number")
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setOngoing(true)
            .setFullScreenIntent(pending, true)
            .setContentIntent(pending)
            .build()
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_INCOMING, notification)
    }

    private companion object {
        const val NOTIFICATION_INCOMING = 42
    }
}
