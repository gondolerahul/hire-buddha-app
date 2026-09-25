package com.hirebuddha.dialer.telecom

import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.telecom.Call
import android.telecom.InCallService
import androidx.core.app.NotificationCompat
import com.hirebuddha.dialer.HireBuddhaApp
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.data.api.LeadLookupDto
import com.hirebuddha.dialer.data.repo.CampaignRepository
import com.hirebuddha.dialer.run.RunController
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Default-dialer InCallService (ROLE_DIALER). Campaign calls are driven by the run
 * orchestrator; any other call (a normal incoming call, a call from our dial pad) gets
 * the minimal [InCallActivity] UI, as the role requires.
 */
@AndroidEntryPoint
class HbInCallService : InCallService() {

    @Inject lateinit var registry: CallRegistry
    @Inject lateinit var runController: RunController
    @Inject lateinit var campaigns: CampaignRepository

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    /**
     * A run pauses when the rep *answers* a real call, not when one rings: declining a
     * call should cost the run nothing. It used to pause on the ring, so a declined spam
     * call quietly ended the afternoon's calling.
     */
    private val pauseOnAnswer = object : Call.Callback() {
        override fun onStateChanged(call: Call, state: Int) {
            if (state == Call.STATE_ACTIVE) {
                runController.onIncomingCallDuringRun()
                call.unregisterCallback(this)
            } else if (state == Call.STATE_DISCONNECTED) {
                call.unregisterCallback(this)
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        registry.attach(this)
    }

    override fun onDestroy() {
        scope.cancel()
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
            call.registerCallback(pauseOnAnswer)
            showIncomingCall(number, lead = null)
            // Put the lead's name on the heads-up too — it is all a rep sees while using
            // another app. Only re-post while it is still ringing, or it would reappear.
            if (number != null) scope.launch {
                val lead = campaigns.lookupLead(number) ?: return@launch
                if (call.state == Call.STATE_RINGING) showIncomingCall(number, lead)
            }
        } else {
            startActivity(Intent(this, InCallActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        }
    }

    override fun onCallRemoved(call: Call) {
        super.onCallRemoved(call)
        call.unregisterCallback(pauseOnAnswer)
        registry.onCallRemoved(call)
        if (registry.calls.value.none { it.state == CallState.RINGING }) {
            getSystemService(NotificationManager::class.java).cancel(NOTIFICATION_INCOMING)
        }
    }

    private fun showIncomingCall(number: String?, lead: LeadLookupDto?) {
        val intent = Intent(this, InCallActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        val pending = PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification = NotificationCompat.Builder(this, HireBuddhaApp.CHANNEL_CALLS)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(lead?.contactName ?: number ?: "Incoming call")
            .setContentText(
                when {
                    lead != null -> "Lead · ${lead.campaignName ?: "a campaign"}"
                    number != null -> "Incoming call"
                    else -> "Unknown number"
                }
            )
            .setOnlyAlertOnce(true)
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
