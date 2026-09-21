package com.hirebuddha.dialer.run

import com.hirebuddha.dialer.core.DialerLog
import com.hirebuddha.dialer.data.push.PushEvents
import com.hirebuddha.dialer.data.push.PushMessage
import com.hirebuddha.dialer.telecom.CallControl
import com.hirebuddha.dialer.telecom.ConferenceStrategy
import com.hirebuddha.dialer.telecom.CallSnapshot
import com.hirebuddha.dialer.telecom.CallState
import com.hirebuddha.dialer.telecom.LeadFailureCause
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.selects.onTimeout
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Drives one campaign run, lead by lead, in the AI-first order decided in ADR-001 §7:
 *
 *   create attempt → dial agent DID → AI leg active → send *token# → wait for ai_ready push
 *   → hold AI leg → dial lead → lead answers → merge → auto-mute rep (D4) → conversation
 *
 * Every step records an event for the backend. Telecom, backend and push are interfaces so
 * the whole flow runs in unit tests with virtual time.
 */
class CallOrchestrator(
    private val calls: CallControl,
    private val backend: DialerBackend,
    private val push: PushEvents,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private val _state = MutableStateFlow(RunUiState())
    val state: StateFlow<RunUiState> = _state.asStateFlow()

    private val commands = Channel<UserCommand>(Channel.UNLIMITED)
    private val mergeDecisions = Channel<Boolean>(Channel.CONFLATED)

    @Volatile private var pauseRequested = false
    @Volatile private var stopRequested = false

    fun send(command: UserCommand) { commands.trySend(command) }
    fun decideMerge(mergeAnyway: Boolean) { mergeDecisions.trySend(mergeAnyway) }
    fun requestPause() { pauseRequested = true }
    fun requestStop() { stopRequested = true }

    fun reset(runId: String, campaignId: String, campaignName: String) {
        DialerLog.setRun(runId)
        DialerLog.i(TAG, "Run started", "run" to runId, "campaign" to campaignId)
        pauseRequested = false
        stopRequested = false
        _state.value = RunUiState(status = RunStatus.RUNNING, runId = runId, campaignId = campaignId, campaignName = campaignName)
    }

    /** Runs until the leads are exhausted, a pause/stop is requested, or setup fails. */
    suspend fun run(runId: String, deviceId: String, config: OrchestratorConfig): RunStatus {
        while (true) {
            if (stopRequested) return finish(RunStatus.STOPPED)
            if (pauseRequested) return finish(RunStatus.PAUSED)

            setStep(Step.FETCHING_LEAD)
            val lead = when (val lease = backend.nextLead(runId)) {
                is LeaseResult.Leased -> lease.lead
                LeaseResult.NoMoreLeads -> return finish(RunStatus.COMPLETED, "All leads have been called.")
                is LeaseResult.Failed -> return finish(if (lease.retryable) RunStatus.PAUSED else RunStatus.ERROR, lease.message)
            }
            _state.update { it.copy(lead = lead, identification = null, message = null) }

            val outcome = runLead(runId, deviceId, lead, config)
            _state.update {
                it.copy(
                    lastOutcome = describe(outcome), callsMade = it.callsMade + 1, aiInCall = false,
                    conversationStartedAt = null, muted = false, awaitingMergeDecision = false,
                )
            }
            if (outcome is LeadOutcome.SetupFailed) return finish(RunStatus.PAUSED, outcome.message)
            if (stopRequested) return finish(RunStatus.STOPPED)
            if (pauseRequested) return finish(RunStatus.PAUSED)

            if (config.gapBetweenLeadsMs > 0) {
                setStep(Step.WAITING_NEXT)
                _state.update { it.copy(nextLeadAt = clock() + config.gapBetweenLeadsMs) }
                delay(config.gapBetweenLeadsMs)
                _state.update { it.copy(nextLeadAt = null) }
            }
        }
    }

    private fun finish(status: RunStatus, message: String? = null): RunStatus {
        DialerLog.i(TAG, "Run finished", "status" to status, "message" to message)
        _state.update { it.copy(status = status, step = Step.IDLE, message = message ?: it.message, nextLeadAt = null) }
        return status
    }

    private fun setStep(step: Step) {
        DialerLog.i(TAG, "Step", "step" to step)
        _state.update { it.copy(step = step) }
    }

    internal suspend fun runLead(runId: String, deviceId: String, lead: Lead, config: OrchestratorConfig): LeadOutcome = coroutineScope {
        // Drain stale UI commands from the previous lead.
        while (commands.tryReceive().isSuccess) Unit
        while (mergeDecisions.tryReceive().isSuccess) Unit

        val attempt = when (val r = backend.createAttempt(runId, lead.campaignCallId, deviceId)) {
            is AttemptResult.Created -> r.attempt
            is AttemptResult.Failed -> {
                DialerLog.e(TAG, "Could not start the call attempt", "code" to r.code, "message" to r.message)
                return@coroutineScope LeadOutcome.SetupFailed(r.code, r.message)
            }
        }
        val aid = attempt.attemptId
        DialerLog.setAttempt(aid)
        DialerLog.i(
            TAG, "Calling lead", "attempt" to aid, "campaign_call" to lead.campaignCallId,
            "lead" to DialerLog.maskNumber(lead.phone), "did" to DialerLog.maskNumber(attempt.did),
        )

        // Subscribe to pushes for this attempt before anything can produce one.
        val pushes = Channel<PushMessage>(Channel.UNLIMITED)
        val pushJob: Job = launch(start = CoroutineStart.UNDISPATCHED) {
            push.messages.collect { if (it.attemptId == null || it.attemptId == aid) pushes.send(it) }
        }
        try {
            flow(aid, attempt, lead, config, pushes)
        } finally {
            pushJob.cancel()
            calls.setMuted(false)
            DialerLog.setAttempt(null)
        }
    }

    private suspend fun flow(
        aid: String, attempt: Attempt, lead: Lead, config: OrchestratorConfig, pushes: Channel<PushMessage>,
    ): LeadOutcome {
        // 1. AI leg
        setStep(Step.CONNECTING_AI)
        backend.event(aid, "ai_dialing")
        val aiCall = calls.placeCall(attempt.did)
        if (aiCall == null) {
            DialerLog.e(TAG, "Could not place the AI call", "did" to DialerLog.maskNumber(attempt.did))
            return setupFailed(aid, "ai_failed", "call_not_placed", "Couldn't place the call to the AI agent. Is this app your default phone app?")
        }
        when (awaitState(aiCall, config.aiAnswerTimeoutMs) { it.state == CallState.ACTIVE }) {
            is Awaited.Reached -> Unit
            else -> {
                calls.disconnect(aiCall)
                return setupFailed(aid, "ai_failed", "ai_not_answered", "The AI agent's number didn't answer. Check the agent's phone number.")
            }
        }
        backend.event(aid, "ai_answered")
        _state.update { it.copy(aiInCall = true) }

        // 2. identify the lead
        setStep(Step.SENDING_CODE)
        calls.playDtmf(aiCall, attempt.dtmfSequence)
        backend.event(aid, "dtmf_sent")

        setStep(Step.WAITING_AI)
        val ready = waitForAiReady(aid, aiCall, config, pushes)
        when (ready) {
            AiReady.Identified -> Unit
            AiReady.Unidentified -> {
                _state.update { it.copy(awaitingMergeDecision = true, message = "The AI couldn't confirm which lead this is.") }
                val mergeAnyway = select<Boolean> {
                    mergeDecisions.onReceive { it }
                    onTimeout(config.mergeDecisionTimeoutMs) { false }
                }
                _state.update { it.copy(awaitingMergeDecision = false, message = null) }
                if (!mergeAnyway) {
                    // ai_failed returns the lead to pending, so it is retried later rather than lost.
                    calls.disconnect(aiCall)
                    backend.event(aid, "ai_failed", mapOf("reason" to "unidentified_skipped"))
                    return LeadOutcome.Skipped
                }
            }
            AiReady.Ended, AiReady.Dropped -> {
                calls.disconnect(aiCall)
                return setupFailed(aid, "ai_failed", "ai_not_ready", "The AI agent didn't get ready. Check your connection and try again.")
            }
            AiReady.TimedOut -> {
                calls.disconnect(aiCall)
                return setupFailed(aid, "ai_failed", "ai_ready_timeout", "The AI agent took too long to get ready.")
            }
        }
        backend.event(aid, "ai_ready_received")

        // 3. hold the AI and dial the lead
        calls.hold(aiCall)
        awaitState(aiCall, config.holdTimeoutMs) { it.state == CallState.HOLDING }  // placing the next call also holds it
        backend.event(aid, "ai_held")

        setStep(Step.CALLING_LEAD)
        backend.event(aid, "lead_dialing")
        val leadCall = calls.placeCall(lead.phone)
        if (leadCall == null) {
            DialerLog.e(TAG, "Could not place the lead call", "lead" to DialerLog.maskNumber(lead.phone))
            calls.disconnect(aiCall)
            return leadFailed(aid, LeadFailureCause.FAILED)
        }
        val answered = awaitLeadAnswer(leadCall, aiCall, config.leadRingTimeoutMs, pushes)
        when (answered) {
            is Awaited.Reached -> Unit
            is Awaited.Failed -> {
                calls.disconnect(aiCall)
                return leadFailed(aid, answered.cause ?: LeadFailureCause.NO_ANSWER)
            }
            Awaited.TimedOut -> {
                calls.disconnect(leadCall)
                calls.disconnect(aiCall)
                return leadFailed(aid, LeadFailureCause.NO_ANSWER)
            }
            Awaited.OtherLegLost -> {
                calls.disconnect(leadCall)
                return setupFailed(aid, "ai_failed", "ai_dropped_while_ringing", "The AI call dropped while the lead was ringing.")
            }
        }
        backend.event(aid, "lead_answered")

        // 4. merge
        setStep(Step.MERGING)
        val conferenceId = mergeWithRetries(aid, leadCall, aiCall, config)
        if (conferenceId == null) {
            val detail = calls.calls.value.joinToString(" | ") {
                "${it.id}:${it.state}${if (it.isConference) ":conf" else ""}${it.parentId?.let { p -> ":parent=$p" } ?: ""}"
            }
            DialerLog.e(TAG, "Merge failed", "lead_call" to leadCall, "ai_call" to aiCall, "calls" to detail)
            backend.event(aid, "merge_failed", mapOf("reason" to "conference_not_active", "calls" to detail.take(400)))
            calls.disconnect(leadCall)
            calls.disconnect(aiCall)
            return LeadOutcome.SetupFailed("merge_failed", "Your network didn't merge the calls. Turn off Wi-Fi calling and try again.")
        }
        DialerLog.i(TAG, "Merged", "conference" to conferenceId, "lead_call" to leadCall, "ai_call" to aiCall)
        calls.setMuted(true)  // D4: rep is muted by default
        _state.update { it.copy(muted = true, conversationStartedAt = clock(), step = Step.IN_CONVERSATION) }
        val acked = backend.event(aid, "merged", urgent = true)
        if (!acked) {
            // No data connection: tell the gateway over the call itself (the lead hears one short beep).
            calls.playDtmf(aiCall, "#")
        }
        backend.event(aid, "rep_muted")

        // 5. conversation
        return converse(aid, leadCall, aiCall, conferenceId, pushes)
    }

    /**
     * Asks telecom to merge, then waits for any of the shapes a merged call can take.
     * Retries because the conferenceable state can land a beat after the lead answers,
     * and some stacks drop the first request while the call is still stabilising.
     */
    private suspend fun mergeWithRetries(aid: String, leadCall: String, aiCall: String, config: OrchestratorConfig): String? {
        val deadline = clock() + config.mergeTimeoutMs
        var attempt = 0
        while (clock() < deadline) {
            attempt++
            val result = calls.conference(leadCall, aiCall)
            if (attempt == 1 || result.error != null) {
                backend.event(aid, "merge_requested", mapOf("action" to result.action.name, "attempt" to attempt.toString()))
            }
            if (result.action == ConferenceStrategy.Action.IMPOSSIBLE) {
                DialerLog.w(TAG, "Merge impossible", "attempt" to attempt, "error" to result.error)
                return null
            }
            val confirmed = awaitMerged(leadCall, aiCall, MERGE_CONFIRM_MS)
            if (confirmed != null) return confirmed
            DialerLog.w(TAG, "Merge not confirmed yet; retrying", "attempt" to attempt, "action" to result.action)
        }
        return null
    }

    private enum class AiReady { Identified, Unidentified, Ended, Dropped, TimedOut }

    private suspend fun waitForAiReady(aid: String, aiCall: String, config: OrchestratorConfig, pushes: Channel<PushMessage>): AiReady {
        val deadline = clock() + config.aiReadyTimeoutMs
        while (true) {
            val remaining = deadline - clock()
            if (remaining <= 0) break
            val result: AiReady? = select<AiReady?> {
                pushes.onReceive { msg ->
                    when (msg.type) {
                        "attempt.ai_ready" -> {
                            _state.update { it.copy(identification = msg.str("identification")) }
                            AiReady.Identified
                        }
                        "attempt.unidentified" -> AiReady.Unidentified
                        "attempt.ai_ended" -> AiReady.Ended
                        else -> null
                    }
                }
                onTimeout(minOf(remaining, 1_000)) {
                    if (isGone(aiCall)) AiReady.Dropped else null
                }
            }
            if (result != null) return result
        }
        // Push may have been missed (socket down): ask the backend directly.
        return when (backend.attemptStatus(aid)) {
            "ai_ready" -> AiReady.Identified
            "unidentified_ready" -> AiReady.Unidentified
            else -> AiReady.TimedOut
        }
    }

    private suspend fun converse(
        aid: String, leadCall: String, aiCall: String, conferenceId: String, pushes: Channel<PushMessage>,
    ): LeadOutcome {
        var aiPresent = true
        fun legVisible(id: String): Boolean = calls.calls.value.any { it.id == id && it.state != CallState.DISCONNECTED }
        fun conferenceLive(): Boolean = calls.calls.value.any { it.id == conferenceId && it.state != CallState.DISCONNECTED }

        // Two stacks, two shapes: either both legs stay visible as children of the
        // conference, or they are replaced by it. That decides what "the call ended" means.
        val legsHidden = !legVisible(leadCall)
        DialerLog.i(TAG, "Conversation started", "conference" to conferenceId, "legs_hidden" to legsHidden)
        fun conversationLive(): Boolean = if (legsHidden) conferenceLive() else legVisible(leadCall)
        while (true) {
            val event: ConversationEvent = select<ConversationEvent> {
                commands.onReceive { ConversationEvent.Command(it) }
                pushes.onReceive { msg -> if (msg.type == "attempt.ai_ended") ConversationEvent.AiEnded(msg.str("reason")) else ConversationEvent.Ignored }
                onTimeout(500) { ConversationEvent.Tick }
            }
            when (event) {
                is ConversationEvent.Command -> when (event.command) {
                    UserCommand.TOGGLE_MUTE -> {
                        val muted = !_state.value.muted
                        calls.setMuted(muted)
                        _state.update { it.copy(muted = muted) }
                        backend.event(aid, if (muted) "rep_muted" else "rep_unmuted")
                    }
                    UserCommand.TAKE_OVER -> if (aiPresent) {
                        backend.event(aid, "rep_takeover")
                        calls.disconnect(aiCall)
                        calls.setMuted(false)
                        aiPresent = false
                        _state.update { it.copy(muted = false, aiInCall = false, message = "You're now talking to the lead.") }
                    }
                    UserCommand.HANG_UP, UserCommand.SKIP -> {
                        hangUpAll(conferenceId, leadCall, aiCall)
                        backend.event(aid, "rep_hangup")
                        return LeadOutcome.Completed("rep")
                    }
                }
                is ConversationEvent.AiEnded -> {
                    // The agent said goodbye (or detected voicemail): end the whole conference.
                    DialerLog.i(TAG, "AI ended the call", "reason" to event.reason)
                    hangUpAll(conferenceId, leadCall, aiCall)
                    backend.event(aid, "completed", mapOf("reason" to (event.reason ?: "ai_ended")))
                    return LeadOutcome.Completed(event.reason ?: "ai")
                }
                ConversationEvent.Tick, ConversationEvent.Ignored -> Unit
            }
            if (!conversationLive()) {
                // Everything is down: the lead (or the network) ended the conference.
                DialerLog.i(TAG, "Conversation ended", "conference" to conferenceId)
                if (aiPresent) calls.disconnect(aiCall)
                backend.event(aid, "lead_disconnected")
                return LeadOutcome.Completed("lead")
            }
            // Only meaningful while the legs are still separately visible; when the stack
            // hides them inside the conference, the gateway's ai_ended push is the signal.
            if (aiPresent && !legsHidden && !legVisible(aiCall) && legVisible(leadCall)) {
                aiPresent = false
                calls.setMuted(false)
                backend.event(aid, "ai_disconnected")
                DialerLog.i(TAG, "AI leg dropped; rep unmuted")
                _state.update { it.copy(muted = false, aiInCall = false, message = "The AI left the call. You're unmuted.") }
            }
        }
    }

    private sealed interface ConversationEvent {
        data class Command(val command: UserCommand) : ConversationEvent
        data class AiEnded(val reason: String?) : ConversationEvent
        data object Tick : ConversationEvent
        data object Ignored : ConversationEvent
    }

    private fun hangUpAll(vararg ids: String) {
        val snapshots = calls.calls.value
        // Disconnect the conference first: on stacks that hide the legs it is the only
        // handle that still works, and it takes the children down with it.
        ids.forEach { id -> snapshots.firstOrNull { it.id == id }?.parentId?.let(calls::disconnect) }
        ids.forEach(calls::disconnect)
    }

    // ── call-state helpers ──────────────────────────────────────────────

    private sealed interface Awaited {
        data class Reached(val snapshot: CallSnapshot) : Awaited
        data class Failed(val cause: LeadFailureCause?) : Awaited
        data object TimedOut : Awaited
        data object OtherLegLost : Awaited
    }

    private fun find(id: String): CallSnapshot? = calls.calls.value.firstOrNull { it.id == id }
    private fun isGone(id: String): Boolean = find(id)?.state?.let { it == CallState.DISCONNECTED } ?: true

    private suspend fun awaitState(id: String, timeoutMs: Long, predicate: (CallSnapshot) -> Boolean): Awaited =
        withTimeoutOrNull(timeoutMs) {
            calls.calls.first { list ->
                val s = list.firstOrNull { it.id == id }
                s == null || s.state == CallState.DISCONNECTED || predicate(s)
            }.firstOrNull { it.id == id }.let { s ->
                when {
                    s == null || s.state == CallState.DISCONNECTED -> Awaited.Failed(s?.disconnectCause)
                    else -> Awaited.Reached(s)
                }
            }
        } ?: Awaited.TimedOut

    private suspend fun awaitLeadAnswer(leadCall: String, aiCall: String, timeoutMs: Long, pushes: Channel<PushMessage>): Awaited =
        coroutineScope {
            val answer = async { awaitState(leadCall, timeoutMs) { it.state == CallState.ACTIVE } }
            val aiLost = async {
                // The AI leg dropping, or the gateway ending it (merge timeout), aborts the ring.
                while (true) {
                    val msg = pushes.tryReceive().getOrNull()
                    if (msg?.type == "attempt.ai_ended" || isGone(aiCall)) return@async true
                    delay(250)
                }
                @Suppress("UNREACHABLE_CODE") false
            }
            val result = select<Awaited> {
                answer.onAwait { it }
                aiLost.onAwait { Awaited.OtherLegLost }
            }
            answer.cancel()
            aiLost.cancel()
            result
        }

    /** Returns the conference id once telecom reports the two legs merged, else null. */
    private suspend fun awaitMerged(leadCall: String, aiCall: String, timeoutMs: Long): String? =
        withTimeoutOrNull(timeoutMs) {
            calls.calls.first { list -> ConferenceStrategy.mergedConferenceId(list, leadCall, aiCall) != null }
            ConferenceStrategy.mergedConferenceId(calls.calls.value, leadCall, aiCall)
        }

    private suspend fun setupFailed(aid: String, eventType: String, reason: String, message: String): LeadOutcome {
        DialerLog.e(TAG, "Setup failed", "event" to eventType, "reason" to reason, "message" to message)
        backend.event(aid, eventType, mapOf("reason" to reason))
        return LeadOutcome.SetupFailed(reason, message)
    }

    private suspend fun leadFailed(aid: String, cause: LeadFailureCause): LeadOutcome {
        DialerLog.i(TAG, "Lead did not connect", "cause" to cause.wire)
        backend.event(aid, "lead_failed", mapOf("cause" to cause.wire))
        return LeadOutcome.LeadFailed(cause)
    }

    private companion object {
        const val TAG = "Orchestrator"
        /** How long to wait for telecom to confirm one merge request before retrying. */
        const val MERGE_CONFIRM_MS = 2_000L
    }

    private fun describe(outcome: LeadOutcome): String = when (outcome) {
        is LeadOutcome.Completed -> "Conversation ended"
        is LeadOutcome.LeadFailed -> when (outcome.cause) {
            LeadFailureCause.BUSY -> "Lead was busy"
            LeadFailureCause.NO_ANSWER -> "No answer"
            LeadFailureCause.REJECTED -> "Lead rejected the call"
            LeadFailureCause.UNREACHABLE -> "Lead unreachable"
            LeadFailureCause.INVALID -> "Invalid number"
            LeadFailureCause.FAILED -> "Call failed"
        }
        LeadOutcome.Skipped -> "Skipped"
        is LeadOutcome.SetupFailed -> outcome.message
    }
}
