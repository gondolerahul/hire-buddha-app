package com.hirebuddha.dialer.telecom

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.telecom.Call
import android.telecom.DisconnectCause
import android.telecom.InCallService
import android.telecom.PhoneAccountHandle
import android.telecom.TelecomManager
import android.telephony.SubscriptionManager
import android.util.Log
import androidx.core.content.ContextCompat
import com.hirebuddha.dialer.core.DialerLog
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
        lastLogged[id] = mapState(call.state)
        call.registerCallback(callback)
        DialerLog.i(
            TAG, "Call added", "call" to id,
            "number" to DialerLog.maskNumber(call.details?.handle?.schemeSpecificPart),
            "outgoing" to (call.details?.callDirection == Call.Details.DIRECTION_OUTGOING),
            "detail" to describe(call),
        )
        publish()
    }

    fun onCallRemoved(call: Call) {
        call.unregisterCallback(callback)
        DialerLog.i(
            TAG, "Call removed", "call" to ids[call],
            "cause" to call.details?.disconnectCause?.toString()?.take(200),
        )
        ids.remove(call)?.let { id ->
            byId.remove(id)
            lastLogged.remove(id)
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
    private val lastLogged = ConcurrentHashMap<String, CallState>()

    private fun publish() {
        val live = ids.entries.map { (call, id) -> snapshot(call, id) }
        live.forEach { s ->
            if (lastLogged.put(s.id, s.state) != s.state) {
                DialerLog.i(
                    TAG, "Call state", "call" to s.id, "state" to s.state, "conference" to s.isConference,
                    "parent" to s.parentId, "children" to s.childIds.joinToString("|"),
                    "can_merge" to s.canMerge, "cause" to s.disconnectCause,
                )
            }
        }
        _calls.value = live + ended.toList()
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
            canRespondViaText = details.can(Call.Details.CAPABILITY_RESPOND_VIA_TEXT),
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

    override suspend fun placeCall(number: String): String? = place(number, campaign = true)

    /**
     * A call the rep dials for themselves (the Phone screen, a tel: link). Not recorded
     * as a campaign number, so the run never treats it as a lead leg and never hangs it
     * up when a run finishes.
     */
    suspend fun placePersonalCall(number: String): String? = place(number, campaign = false)

    private suspend fun place(number: String, campaign: Boolean): String? {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CALL_PHONE) != PackageManager.PERMISSION_GRANTED) {
            Log.w(TAG, "CALL_PHONE not granted")
            return null
        }
        val telecom = context.getSystemService(TelecomManager::class.java)
        // Every id we have already seen, including calls that have ended: the snapshot
        // list keeps those around, and a recent call to this same number (a previous
        // lead, or the verification call) must never be mistaken for the new one.
        val known = calls.value.map { it.id }.toSet() + ids.values
        val extras = Bundle()
        SimAccounts.handle(context, settings.current().phoneAccountId)?.let {
            extras.putParcelable(TelecomManager.EXTRA_PHONE_ACCOUNT_HANDLE, it)
        }
        if (campaign) expectedOutgoing += number
        return try {
            telecom.placeCall(Uri.fromParts("tel", number, null), extras)
            withTimeoutOrNull(10_000) {
                calls.map { list -> PlacedCall.pick(list, known, number) }.filterNotNull().first().id
            }.also { DialerLog.i(TAG, "Placed call", "call" to it, "number" to DialerLog.maskNumber(number)) }
        } catch (e: SecurityException) {
            Log.w(TAG, "placeCall refused: ${e.message}")
            null
        }
    }

    /**
     * Hangs up anything still live that this app dialled for a campaign. A run that
     * fails during setup would otherwise leave a call ringing with nobody watching it.
     */
    fun hangUpExpected() {
        val stray = ids.entries.filter { (_, id) ->
            val s = calls.value.firstOrNull { it.id == id }
            s != null && s.state != CallState.DISCONNECTED && isCampaignNumber(s.number)
        }
        stray.forEach { (call, id) ->
            DialerLog.w(TAG, "Hanging up a call left over from the run", "call" to id)
            runCatching { call.disconnect() }
        }
    }

    fun clearExpectedNumbers() = expectedOutgoing.clear()

    override fun hold(callId: String) { byId[callId]?.hold() }
    override fun unhold(callId: String) { byId[callId]?.unhold() }

    override fun conference(callId: String, otherCallId: String): ConferenceResult {
        val a = byId[callId]
        val b = byId[otherCallId]
        val action = ConferenceStrategy.choose(facts(callId, a, b), facts(otherCallId, b, a))
        DialerLog.i(
            TAG, "Merge attempt", "action" to action, "lead_call" to callId, "ai_call" to otherCallId,
            "lead" to describe(a), "ai" to describe(b),
        )
        return try {
            when (action) {
                // conference() is what merges two separate calls; mergeConference() only does
                // something once a conference container already exists.
                ConferenceStrategy.Action.CONFERENCE -> { a!!.conference(b!!); ConferenceResult(action) }
                ConferenceStrategy.Action.MERGE_CONFERENCE -> { a!!.mergeConference(); ConferenceResult(action) }
                ConferenceStrategy.Action.ALREADY_MERGED -> ConferenceResult(action)
                ConferenceStrategy.Action.IMPOSSIBLE -> ConferenceResult(action, "a call is missing or disconnected")
            }
        } catch (e: Exception) {
            DialerLog.e(TAG, "Merge threw", e, "action" to action)
            ConferenceResult(action, e.javaClass.simpleName + ": " + e.message)
        }
    }

    private fun facts(id: String, call: Call?, other: Call?) = ConferenceStrategy.CallFacts(
        id = id,
        exists = call != null,
        state = call?.let { mapState(it.state) } ?: CallState.DISCONNECTED,
        parentId = call?.parent?.let { ids[it] },
        isConferenceable = call?.conferenceableCalls?.contains(other) == true,
        canMergeConference = call?.details?.can(Call.Details.CAPABILITY_MERGE_CONFERENCE) == true,
    )

    /** Capability snapshot — the first thing to check when a carrier refuses to merge. */
    private fun describe(call: Call?): String {
        val d = call?.details ?: return "absent"
        fun cap(flag: Int, name: String) = if (d.can(flag)) name else null
        val caps = listOfNotNull(
            cap(Call.Details.CAPABILITY_MERGE_CONFERENCE, "merge"),
            cap(Call.Details.CAPABILITY_MANAGE_CONFERENCE, "manage"),
            cap(Call.Details.CAPABILITY_HOLD, "hold"),
            cap(Call.Details.CAPABILITY_SUPPORT_HOLD, "supports_hold"),
            cap(Call.Details.CAPABILITY_SEPARATE_FROM_CONFERENCE, "separate"),
            cap(Call.Details.CAPABILITY_SWAP_CONFERENCE, "swap"),
        )
        return "state=" + mapState(call.state) + " caps=[" + caps.joinToString(",") + "]" +
            " conferenceable=" + call.conferenceableCalls.size +
            " children=" + call.children.size +
            " parent=" + (call.parent?.let { ids[it] } ?: "-")
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

    /** Declines a ringing call and has telephony text the caller [message]. */
    fun rejectWithMessage(callId: String, message: String) {
        DialerLog.i(TAG, "Declining with a text", "call" to callId)
        byId[callId]?.reject(true, message)
    }

    override fun setMuted(muted: Boolean) { service?.setMuted(muted) }

    /** Loudspeaker on or off for the current call (personal calls; the run never uses it). */
    fun setSpeaker(on: Boolean) {
        service?.setAudioRoute(if (on) android.telecom.CallAudioState.ROUTE_SPEAKER else android.telecom.CallAudioState.ROUTE_WIRED_OR_EARPIECE)
    }

    /** One keypad press in a live call, for phone menus ("press 1 for…"). */
    fun pressKey(callId: String, key: Char) {
        val call = byId[callId] ?: return
        call.playDtmfTone(key)
        call.stopDtmfTone()
    }

    private companion object {
        const val TAG = "CallRegistry"
        const val DTMF_TONE_MS = 300L
        const val DTMF_GAP_MS = 200L
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

    /**
     * The SIM's own number, when the platform happens to know it. Indian carriers
     * usually leave this blank, so every caller must treat null as normal.
     */
    fun selfNumber(context: Context, id: String?): String? {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.READ_PHONE_NUMBERS) != PackageManager.PERMISSION_GRANTED) {
            return null
        }
        val handle = handle(context, id) ?: return null
        val telecom = context.getSystemService(TelecomManager::class.java)
        runCatching { telecom.getPhoneAccount(handle)?.address?.schemeSpecificPart }
            .getOrNull()?.takeIf { it.isNotBlank() }?.let { return it }
        return runCatching {
            val subs = context.getSystemService(SubscriptionManager::class.java)
            val info = subs?.activeSubscriptionInfoList?.firstOrNull { it.iccId == handle.id }
                ?: subs?.activeSubscriptionInfoList?.firstOrNull()
                ?: return null
            val number = if (Build.VERSION.SDK_INT >= 33) {
                subs.getPhoneNumber(info.subscriptionId)
            } else {
                @Suppress("DEPRECATION") info.number
            }
            number?.takeIf { it.isNotBlank() }
        }.getOrNull()
    }
}
