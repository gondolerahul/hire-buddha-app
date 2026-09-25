package com.hirebuddha.dialer.telecom

import kotlinx.coroutines.flow.StateFlow

enum class CallState { NEW, DIALING, RINGING, ACTIVE, HOLDING, DISCONNECTED, OTHER }

/** Immutable view of a telecom call, safe to hold in UI state and unit tests. */
data class CallSnapshot(
    val id: String,
    val number: String?,
    val state: CallState,
    val outgoing: Boolean,
    val isConference: Boolean = false,
    val parentId: String? = null,
    val childIds: List<String> = emptyList(),
    val canMerge: Boolean = false,
    val disconnectCause: LeadFailureCause? = null,
    /** The carrier can decline this call with a text (the "Message" button). */
    val canRespondViaText: Boolean = false,
)

/** Maps Android DisconnectCause to the backend's lead_failed causes (docs 06 §2.5). */
enum class LeadFailureCause(val wire: String) {
    BUSY("busy"), NO_ANSWER("no_answer"), REJECTED("rejected"), UNREACHABLE("unreachable"),
    INVALID("invalid"), FAILED("failed");
}

/** Outcome of one merge attempt, logged and retried by the orchestrator. */
data class ConferenceResult(
    val action: ConferenceStrategy.Action,
    val error: String? = null,
) {
    val attempted get() = action == ConferenceStrategy.Action.CONFERENCE || action == ConferenceStrategy.Action.MERGE_CONFERENCE
}

/** Everything the orchestrator needs from Android telecom — faked in unit tests. */
interface CallControl {
    val calls: StateFlow<List<CallSnapshot>>

    /** Places a carrier call on the verified SIM; returns the new call's id once telecom reports it. */
    suspend fun placeCall(number: String): String?
    fun hold(callId: String)
    fun unhold(callId: String)
    /** Asks telecom to merge two calls; the orchestrator confirms the result from call state. */
    fun conference(callId: String, otherCallId: String): ConferenceResult
    suspend fun playDtmf(callId: String, sequence: String)
    fun disconnect(callId: String)
    fun setMuted(muted: Boolean)
}
