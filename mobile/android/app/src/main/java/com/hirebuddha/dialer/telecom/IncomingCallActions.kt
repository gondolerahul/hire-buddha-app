package com.hirebuddha.dialer.telecom

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.telecom.Call
import android.telecom.VideoProfile
import com.hirebuddha.dialer.core.DialerLog
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent

@EntryPoint
@InstallIn(SingletonComponent::class)
interface CallRegistryEntryPoint {
    fun registry(): CallRegistry
}

/**
 * Answer and Decline on the incoming-call notification, for the rep who is in another
 * app when a call arrives — the full-screen UI only takes over a locked phone.
 */
class IncomingCallActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val registry = EntryPointAccessors.fromApplication(context, CallRegistryEntryPoint::class.java).registry()
        val ringing = registry.calls.value.firstOrNull { it.state == CallState.RINGING } ?: return
        val call = registry.call(ringing.id) ?: return
        when (intent.action) {
            ACTION_ANSWER -> {
                DialerLog.i("IncomingCall", "Answered from the notification")
                call.answer(VideoProfile.STATE_AUDIO_ONLY)
                context.startActivity(Intent(context, InCallActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
            ACTION_DECLINE -> {
                DialerLog.i("IncomingCall", "Declined from the notification")
                if (Build.VERSION.SDK_INT >= 30) call.reject(Call.REJECT_REASON_DECLINED)
                else @Suppress("DEPRECATION") call.reject(false, null)
            }
        }
    }

    companion object {
        const val ACTION_ANSWER = "com.hirebuddha.dialer.ANSWER"
        const val ACTION_DECLINE = "com.hirebuddha.dialer.DECLINE"
    }
}
