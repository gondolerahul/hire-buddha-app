package com.hirebuddha.dialer.telecom

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.telecom.Call
import android.telecom.DisconnectCause
import android.telecom.InCallService
import android.telecom.PhoneAccountHandle
import android.telecom.TelecomManager
import android.util.Log
import androidx.core.content.ContextCompat
import com.hirebuddha.dialer.data.settings.AppSettings
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Live registry of telecom calls, fed by [HbInCallService]. Calls carry an app-local id so
 * the orchestrator can refer to them across state changes and conference re-parenting.
 */
@Singleton
class CallRegistry @Inject constructor(
    @ApplicationContext private val context: Context,
    private val settings: AppSettings,
) : CallControl {

    private val ids = ConcurrentHashMap<Call, String>()
    private val byId = ConcurrentHashMap<String, Call>()
    private val counter = AtomicInteger()
    private val _calls = MutableStateFlow<List<CallSnapshot>>(emptyList())
    override val calls: StateFlow<List<CallSnapshot>> = _calls.asStateFlow()

    @Volatile var service: InCallService? = null
        private set

    /** Numbers the orchestrator is placing; incoming-call UI ignores these. */
    private val expectedOutgoing = ConcurrentHashMap.newKeySet<String>()

    private val callback = object : Call.Callback() {
        override fun onStateChanged(call: Call, state: Int) = publish()
        override fun onDetailsChanged(call: Call, details: Call.Details) = publish()
        override fun onParentChanged(call: Call, parent: Call?) = publish()
        override fun onChildrenChanged(call: Call, children: MutableList<Call>) = publish()
        override fun onConferenceableCallsChanged(call: Call, conferenceableCalls: MutableList<Call>) = publish()
    }

    fun attach(service: InCallService) { this.service = service }
    fun detach(service: InCallService) { if (this.service === service) this.service = null }

    fun onCallAdded(call: Call) {
        val id = "c${counter.incrementAndGet()}"
        ids[call] = id
        byId[id] = call
        call.registerCallback(callback)
        publish()
    }

    fun onCallRemoved(call: Call) {
        call.unregisterCallback(callback)
        ids.remove(call)?.let { id ->
            byId.remove(id)
            // Keep the final state visible: StateFlow conflation could otherwise hide the
            // DISCONNECTED transition (and its cause) from the orchestrator.
            ended.addLast(snapshot(call, id).copy(state = CallState.DISCONNECTED))
            while (ended.size > MAX_ENDED) ended.removeFirst()
        }
        publish()
    }

    fun call(id: String): Call? = byId[id]

    fun isCampaignNumber(number: String?): Boolean =
        number != null && expectedOutgoing.any { PhoneNumbers.sameNumber(it, number) }

    private val ended = java.util.concurrent.ConcurrentLinkedDeque<CallSnapshot>()

    private fun publish() {
        _calls.value = ids.entries.map { (call, id) -> snapshot(call, id) } + ended.toList()
    }

    private fun snapshot(call: Call, id: String): CallSnapshot {
        val details = call.details
        return CallSnapshot(
            id = id,
            number = details.handle?.schemeSpecificPart,
            state = mapState(call.state),
            outgoing = details.callDirection == Call.Details.DIRECTION_OUTGOING,
            isConference = details.hasProperty(Call.Details.PROPERTY_CONFERENCE),
            parentId = call.parent?.let { ids[it] },
            childIds = call.children.mapNotNull { ids[it] },
            canMerge = details.can(Call.Details.CAPABILITY_MERGE_CONFERENCE) || call.conferenceableCalls.isNotEmpty(),
            disconnectCause = if (call.state == Call.STATE_DISCONNECTED) mapCause(details.disconnectCause) else null,
        )
    }

    @Suppress("DEPRECATION")
    private fun mapState(state: Int) = when (state) {
        Call.STATE_NEW, Call.STATE_CONNECTING, Call.STATE_SELECT_PHONE_ACCOUNT -> CallState.NEW
        Call.STATE_DIALING, Call.STATE_PULLING_CALL -> CallState.DIALING
        Call.STATE_RINGING -> CallState.RINGING
        Call.STATE_ACTIVE -> CallState.ACTIVE
        Call.STATE_HOLDING -> CallState.HOLDING
        Call.STATE_DISCONNECTED, Call.STATE_DISCONNECTING -> CallState.DISCONNECTED
        else -> CallState.OTHER
    }

    private fun mapCause(cause: DisconnectCause?): LeadFailureCause = when (cause?.code) {
        DisconnectCause.BUSY -> LeadFailureCause.BUSY
        DisconnectCause.REJECTED -> LeadFailureCause.REJECTED
        DisconnectCause.MISSED, DisconnectCause.REMOTE, DisconnectCause.LOCAL, DisconnectCause.CANCELED -> LeadFailureCause.NO_ANSWER
        DisconnectCause.RESTRICTED -> LeadFailureCause.FAILED
        DisconnectCause.ERROR -> if (cause.reason?.contains("INVALID", ignoreCase = true) == true) LeadFailureCause.INVALID
                                  else LeadFailureCause.UNREACHABLE
        else -> LeadFailureCause.FAILED
    }

    // ── CallControl ──────────────────────────────────────────────────────

    override suspend fun placeCall(number: String): String? {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CALL_PHONE) != PackageManager.PERMISSION_GRANTED) {
            Log.w(TAG, "CALL_PHONE not granted")
            return null
        }
        val telecom = context.getSystemService(TelecomManager::class.java)
        val known = ids.values.toSet()
        val extras = Bundle()
        SimAccounts.handle(context, settings.current().phoneAccountId)?.let {
            extras.putParcelable(TelecomManager.EXTRA_PHONE_ACCOUNT_HANDLE, it)
        }
        expectedOutgoing += number
        return try {
            telecom.placeCall(Uri.fromParts("tel", number, null), extras)
            withTimeoutOrNull(10_000) {
                calls.map { list ->
                    list.firstOrNull { it.id !in known && it.outgoing && PhoneNumbers.sameNumber(it.number, number) }
                }.filterNotNull().first().id
            }
        } catch (e: SecurityException) {
            Log.w(TAG, "placeCall refused: ${e.message}")
            null
        }
    }

    fun clearExpectedNumbers() = expectedOutgoing.clear()

    override fun hold(callId: String) { byId[callId]?.hold() }
    override fun unhold(callId: String) { byId[callId]?.unhold() }

    override fun conference(callId: String, otherCallId: String): Boolean {
        val a = byId[callId] ?: return false
        val b = byId[otherCallId] ?: return false
        return when {
            a.conferenceableCalls.contains(b) || b.conferenceableCalls.contains(a) -> { a.conference(b); true }
            a.details.can(Call.Details.CAPABILITY_MERGE_CONFERENCE) -> { a.mergeConference(); true }
            b.details.can(Call.Details.CAPABILITY_MERGE_CONFERENCE) -> { b.mergeConference(); true }
            else -> { a.conference(b); true }  // some IMS stacks accept it without advertising
        }
    }

    override suspend fun playDtmf(callId: String, sequence: String) {
        for (c in sequence) {
            val call = byId[callId] ?: return
            call.playDtmfTone(c)
            delay(DTMF_TONE_MS)
            call.stopDtmfTone()
            delay(DTMF_GAP_MS)
        }
    }

    override fun disconnect(callId: String) { byId[callId]?.disconnect() }

    override fun setMuted(muted: Boolean) { service?.setMuted(muted) }

    private companion object {
        const val TAG = "CallRegistry"
        const val DTMF_TONE_MS = 150L
        const val DTMF_GAP_MS = 100L
        const val MAX_ENDED = 10
    }
}

object PhoneNumbers {
    /** Compares by the last 10 digits (Indian mobiles / DIDs), tolerating +91 / 0 prefixes. */
    fun sameNumber(a: String?, b: String?): Boolean {
        val da = a?.filter(Char::isDigit).orEmpty()
        val db = b?.filter(Char::isDigit).orEmpty()
        if (da.isEmpty() || db.isEmpty()) return false
        return da.takeLast(10) == db.takeLast(10)
    }
}

object SimAccounts {
    data class Sim(val id: String, val label: String, val handle: PhoneAccountHandle)

    fun list(context: Context): List<Sim> {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_PHONE_STATE) != PackageManager.PERMISSION_GRANTED) {
            return emptyList()
        }
        val telecom = context.getSystemService(TelecomManager::class.java)
        return telecom.callCapablePhoneAccounts.mapIndexed { i, handle ->
            val account = telecom.getPhoneAccount(handle)
            val label = account?.label?.toString()?.takeIf { it.isNotBlank() } ?: "SIM ${i + 1}"
            Sim(id = "${handle.componentName.flattenToString()}|${handle.id}", label = "SIM ${i + 1} · $label", handle = handle)
        }
    }

    fun handle(context: Context, id: String?): PhoneAccountHandle? =
        id?.let { wanted -> list(context).firstOrNull { it.id == wanted }?.handle }
}
