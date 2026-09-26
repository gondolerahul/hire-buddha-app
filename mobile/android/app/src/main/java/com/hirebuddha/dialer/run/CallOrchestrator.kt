package com.hirebuddha.dialer.run

import com.hirebuddha.dialer.core.DialerLog
import com.hirebuddha.dialer.data.push.PushEvents
import com.hirebuddha.dialer.data.push.PushMessage
import com.hirebuddha.dialer.telecom.CallControl
import com.hirebuddha.dialer.telecom.ConferenceStrategy
import com.hirebuddha.dialer.telecom.CallSnapshot
import com.hirebuddha.dialer.telecom.CallState
import com.hirebuddha.dialer.telecom.PhoneNumbers
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
    /** The rep is done with the gap between leads: go now. */
    private val continueNow = Channel<Unit>(Channel.CONFLATED)

    @Volatile private var pauseRequested = false
    @Volatile private var stopRequested = false
    /**
     * Skip applies to every phase, not just the conversation. FR-E7 requires it and the
     * rep needs it most while an unreachable lead is still ringing — which is exactly
     * where the old UI offered no control at all.
     */
    @Volatile private var skipRequested = false
    @Volatile private var transcriptOn = true

    fun send(command: UserCommand) {
        if (command == UserCommand.SKIP) skipRequested = true
        commands.trySend(command)
    }
    fun decideMerge(mergeAnyway: Boolean) { mergeDecisions.trySend(mergeAnyway) }
    fun requestPause() { pauseRequested = true }
    fun requestStop() { stopRequested = true }

    /** Freeze the countdown to the next lead while the rep fills in the wrap-up. */
    fun holdGap() { _state.update { it.copy(gapHeld = true) } }

    /** Dismiss the wrap-up and move on immediately. */
    fun continueRun() {
        _state.update { it.copy(gapHeld = false, wrapUp = null) }
        continueNow.trySend(Unit)
    }

    /** Forget the current run entirely — used after stopping one out of band. */
    fun clear() {
        pauseRequested = false
        stopRequested = false
        skipRequested = false
        DialerLog.setRun(null)
        _state.value = RunUiState()
    }

    fun reset(runId: String, campaignId: String, campaignName: String, agentName: String? = null) {
        DialerLog.setRun(runId)
        DialerLog.i(TAG, "Run started", "run" to runId, "campaign" to campaignId)
        pauseRequested = false
        stopRequested = false
        skipRequested = false
        _state.value = RunUiState(
            status = RunStatus.RUNNING, runId = runId, campaignId = campaignId,
            campaignName = campaignName, agentName = agentName, startedAt = clock(),
        )
    }

    /** Pick a paused run back up. Unlike [reset], the session tallies carry on. */
    fun resume(runId: String) {
        DialerLog.setRun(runId)
        DialerLog.i(TAG, "Run resumed", "run" to runId)
        pauseRequested = false
        stopRequested = false
        skipRequested = false
        _state.update {
            it.copy(
                status = RunStatus.RUNNING, runId = runId, step = Step.IDLE, message = null,
                nextLeadAt = null, wrapUp = null, gapHeld = false, endedAt = null,
            )
        }
    }

    /** The rep's own read of a finished call, once the server has accepted it. */
    fun recordDisposition(disposition: String) = _state.update {
        when (disposition) {
            "interested" -> it.copy(interested = it.interested + 1)
            "callback" -> it.copy(callbacks = it.callbacks + 1)
            else -> it
        }
    }

    /** A run that was not executing (paused) has been ended server-side. */
    fun markStopped() = _state.update {
        it.copy(status = RunStatus.STOPPED, step = Step.IDLE, nextLeadAt = null, endedAt = it.endedAt ?: clock())
    }

    /** Runs until the leads are exhausted, a pause/stop is requested, or setup fails. */
    suspend fun run(runId: String, deviceId: String, config: OrchestratorConfig): RunStatus {
        transcriptOn = config.showTranscript
        _state.update { it.copy(askedAfterCalls = config.askAfterEveryCall, showTranscript = config.showTranscript) }
        while (true) {
            if (stopRequested) return finish(RunStatus.STOPPED)
            if (pauseRequested) return finish(RunStatus.PAUSED)

            setStep(Step.FETCHING_LEAD)
            val lead = when (val lease = backend.nextLead(runId)) {
                is LeaseResult.Leased -> lease.lead
                LeaseResult.NoMoreLeads -> return finish(RunStatus.COMPLETED, "All leads have been called.")
                is LeaseResult.Failed -> return finish(if (lease.retryable) RunStatus.PAUSED else RunStatus.ERROR, lease.message)
            }
            // Lead PII never outlives its lease (NFR-6): the previous lead's transcript
            // and wrap-up go before the next one is shown.
            _state.update {
                it.copy(lead = lead, identification = null, message = null, leadRingingSince = null,
                        transcript = emptyList(), wrapUp = null, gapHeld = false)
            }
            val startedAt = clock()

            val outcome = runLead(runId, deviceId, lead, config)
            val talked = ((clock() - startedAt) / 1000).toInt()
            _state.update {
                val conversation = it.conversationStartedAt
                val conversationSeconds =
                    if (conversation != null) ((clock() - conversation) / 1000).toInt() else 0
                it.copy(
                    lastOutcome = describe(outcome), callsMade = it.callsMade + 1, aiInCall = false,
                    conversationStartedAt = null, muted = false, awaitingMergeDecision = false,
                    connected = it.connected + if (outcome is LeadOutcome.Completed) 1 else 0,
                    talked30 = it.talked30 + if (conversationSeconds >= 30) 1 else 0,
                    talkSeconds = it.talkSeconds + conversationSeconds,
                    // Only a call the lead actually joined is worth asking the rep about.
                    wrapUp = (outcome as? LeadOutcome.Completed)
                        ?.takeIf { config.askAfterEveryCall }
                        ?.let { done ->
                        WrapUp(
                            campaignCallId = lead.campaignCallId,
                            leadName = lead.name,
                            phone = lead.phone,
                            talkSeconds = conversationSeconds,
                            endedBy = done.endedBy,
                        )
                    },
                )
            }
            if (outcome is LeadOutcome.SetupFailed) return finish(RunStatus.PAUSED, outcome.message)
            if (stopRequested) return finish(RunStatus.STOPPED)
            if (pauseRequested) return finish(RunStatus.PAUSED)

            awaitGap(config)
        }
    }

    /**
     * The pause between leads. Normally [OrchestratorConfig.gapBetweenLeadsMs], but the
     * wrap-up sheet can hold it open indefinitely — the rep is mid-thought about the call
     * they just had, and hurrying that is how dispositions end up wrong.
     */
    private suspend fun awaitGap(config: OrchestratorConfig) {
        val wrapUp = _state.value.wrapUp
        if (config.gapBetweenLeadsMs <= 0 && wrapUp == null) return
        setStep(Step.WAITING_NEXT)
        // A rep who sets the gap to zero still gets a fair chance to answer the wrap-up:
        // otherwise the sheet would appear and vanish in the same frame.
        val window = if (wrapUp != null) maxOf(config.gapBetweenLeadsMs, WRAP_UP_MIN_MS) else config.gapBetweenLeadsMs
        val deadline = clock() + window
        _state.update { it.copy(nextLeadAt = deadline) }
        while (true) {
            if (stopRequested || pauseRequested) break
            val held = _state.value.gapHeld
            val remaining = deadline - clock()
            if (!held && remaining <= 0) break
            val goNow = select<Boolean> {
                continueNow.onReceive { true }
                onTimeout(if (held) 500 else remaining.coerceIn(50, 250)) { false }
            }
            if (goNow) break
        }
        _state.update { it.copy(nextLeadAt = null, gapHeld = false, wrapUp = null) }
    }

    private fun finish(status: RunStatus, message: String? = null): RunStatus {
        DialerLog.i(TAG, "Run finished", "status" to status, "message" to message)
        _state.update {
            it.copy(status = status, step = Step.IDLE, message = message ?: it.message, nextLeadAt = null, endedAt = clock())
        }
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
        while (continueNow.tryReceive().isSuccess) Unit
        skipRequested = false

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
        when (orSkip { awaitState(aiCall, config.aiAnswerTimeoutMs) { it.state == CallState.ACTIVE } }) {
            is Awaited.Reached -> Unit
            null -> {
                calls.disconnect(aiCall)
                return skipped(aid, "connecting_ai")
            }
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
            AiReady.Skipped -> {
                calls.disconnect(aiCall)
                return skipped(aid, "waiting_for_ai")
            }
            AiReady.Unidentified -> {
                _state.update { it.copy(awaitingMergeDecision = true, message = "The AI couldn't confirm which lead this is.") }
                // The countdown and its default are shown to the rep (screen 17); the old
                // dialog ran this same 15 s timer invisibly.
                _state.update { it.copy(nextLeadAt = clock() + config.mergeDecisionTimeoutMs) }
                val mergeAnyway = select<Boolean> {
                    mergeDecisions.onReceive { it }
                    onTimeout(config.mergeDecisionTimeoutMs) { false }
                }
                _state.update { it.copy(nextLeadAt = null) }
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
        _state.update { it.copy(leadRingingSince = clock()) }
        val answered = awaitLeadAnswer(leadCall, aiCall, config.leadRingTimeoutMs, pushes)
        when (answered) {
            is Awaited.Reached -> Unit
            Awaited.Skipped -> {
                calls.disconnect(leadCall)
                calls.disconnect(aiCall)
                return skipped(aid, "ringing_lead")
            }
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
        // The gateway starts the greeting now, so it plays the instant the merge lands.
        backend.signal(aid, "lead_answered")
        backend.event(aid, "lead_answered")
        _state.update { it.copy(leadAnswered = it.leadAnswered + 1) }

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
        // Every second here is dead air for the lead. The socket is already open; an
        // HTTP POST after a few idle seconds pays for a new connection (1-2 s on mobile).
        backend.signal(aid, "merged")
        val acked = backend.event(aid, "merged", urgent = true)
        if (!acked) {
            // No data connection: tell the gateway over the call itself (the lead hears one short beep).
            calls.playDtmf(aiCall, "#")
        }
        backend.event(aid, "rep_muted")

        // 5. conversation
        return converse(aid, leadCall, aiCall, conferenceId, pushes, attempt.did)
    }

    /**
     * Asks telecom to merge, then waits for any of the shapes a merged call can take.
     * Retries because the conferenceable state can land a beat after the lead answers,
     * and some stacks drop the first request while the call is still stabilising.
     */
    private suspend fun mergeWithRetries(aid: String, leadCall: String, aiCall: String, config: OrchestratorConfig): String? {
        val deadline = clock() + config.mergeTimeoutMs
        val before = calls.calls.value.map { it.id }.toSet()
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
            val confirmed = awaitMerged(leadCall, aiCall, MERGE_RETRY_MS)
            if (confirmed != null) return confirmed
            if (calls.calls.value.any { it.id !in before }) {
                // New legs appeared: the network is building the conference. Asking
                // again now could knock it over, so wait it out instead.
                DialerLog.i(TAG, "Merge underway; waiting for it", "attempt" to attempt)
                return awaitMerged(leadCall, aiCall, (deadline - clock()).coerceAtLeast(0))
            }
            DialerLog.w(TAG, "Merge not confirmed yet; retrying", "attempt" to attempt, "action" to result.action)
        }
        return null
    }

    private enum class AiReady { Identified, Unidentified, Ended, Dropped, TimedOut, Skipped }

    private suspend fun waitForAiReady(aid: String, aiCall: String, config: OrchestratorConfig, pushes: Channel<PushMessage>): AiReady {
        val deadline = clock() + config.aiReadyTimeoutMs
        while (true) {
            if (skipRequested) return AiReady.Skipped
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
        did: String,
    ): LeadOutcome {
        var aiPresent = true
        /** Set while the agent says its hand-over line; the fallback deadline if the push never comes. */
        var handoverDeadline: Long? = null

        /**
         * The agent has handed over: take it out of the call and give the rep the lead.
         * The gateway ends its side, but the provider's hang-up API cannot be relied on,
         * so the phone drops the agent's leg too — the leg itself where it is visible,
         * or the matching participant where the stack hides legs inside the conference.
         */
        fun completeHandover(reason: String) {
            if (!aiPresent) return
            aiPresent = false
            handoverDeadline = null
            val aiLegs = calls.calls.value.filter {
                it.state != CallState.DISCONNECTED && !it.isConference &&
                    (it.id == aiCall || (it.number != null && PhoneNumbers.sameNumber(it.number, did)))
            }
            aiLegs.forEach { calls.disconnect(it.id) }
            calls.setMuted(false)
            DialerLog.i(TAG, "Rep took over", "reason" to reason, "ai_legs_dropped" to aiLegs.size)
            _state.update {
                it.copy(
                    muted = false, aiInCall = false, handingOver = false, noLeadAudio = false,
                    message = "You're talking to the lead now.",
                )
            }
        }
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
                pushes.onReceive { msg ->
                    when (msg.type) {
                        "attempt.ai_ended" -> ConversationEvent.AiEnded(msg.str("reason"))
                        "attempt.no_lead_audio" -> ConversationEvent.NoLeadAudio
                        "attempt.transcript" -> { appendTranscript(msg); ConversationEvent.Ignored }
                        else -> ConversationEvent.Ignored
                    }
                }
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
                    UserCommand.TAKE_OVER -> if (aiPresent && handoverDeadline == null) {
                        // The agent tells the lead it is transferring them, then leaves. The
                        // rep stays muted until then so the two never talk over each other.
                        handoverDeadline = clock() + HANDOVER_TIMEOUT_MS
                        _state.update { it.copy(handingOver = true, message = null) }
                        val sent = backend.event(aid, "rep_takeover", urgent = true)
                        DialerLog.i(TAG, "Take over requested", "acked" to sent)
                        // Offline, the agent never hears about it: take the call at once.
                        if (!sent) completeHandover("offline")
                    }
                    UserCommand.HANG_UP, UserCommand.SKIP -> {
                        hangUpAll(conferenceId, leadCall, aiCall)
                        backend.event(aid, "rep_hangup")
                        return LeadOutcome.Completed("rep")
                    }
                }
                is ConversationEvent.AiEnded -> if (event.reason == "rep_takeover" || handoverDeadline != null) {
                    // The hand-over, not a goodbye: the lead stays on with the rep. Hanging up
                    // the conference here is what used to drop the lead on Take over.
                    completeHandover("ai_left")
                } else if (!aiPresent) {
                    Unit  // already handed over; a late push must not end the rep's call
                } else {
                    // The agent said goodbye (or detected voicemail): end the whole conference.
                    DialerLog.i(TAG, "AI ended the call", "reason" to event.reason)
                    hangUpAll(conferenceId, leadCall, aiCall)
                    backend.event(aid, "completed", mapOf("reason" to (event.reason ?: "ai_ended")))
                    return LeadOutcome.Completed(event.reason ?: "ai")
                }
                ConversationEvent.NoLeadAudio -> if (aiPresent) {
                    DialerLog.w(TAG, "Gateway hears no lead audio after the merge")
                    _state.update { it.copy(noLeadAudio = true) }
                }
                ConversationEvent.Tick -> handoverDeadline?.let { if (clock() > it) completeHandover("timeout") }
                ConversationEvent.Ignored -> Unit
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
        data object NoLeadAudio : ConversationEvent
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
        data object Skipped : Awaited
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
            val skip = async { while (!skipRequested) delay(120); Unit }
            val result = select<Awaited> {
                answer.onAwait { it }
                aiLost.onAwait { Awaited.OtherLegLost }
                skip.onAwait { Awaited.Skipped }
            }
            answer.cancel()
            aiLost.cancel()
            skip.cancel()
            result
        }

    /** Returns the conference id once telecom reports the two legs merged, else null. */
    private suspend fun awaitMerged(leadCall: String, aiCall: String, timeoutMs: Long): String? =
        withTimeoutOrNull(timeoutMs) {
            calls.calls.first { list -> ConferenceStrategy.mergedConferenceId(list, leadCall, aiCall) != null }
            ConferenceStrategy.mergedConferenceId(calls.calls.value, leadCall, aiCall)
        }

    /**
     * Keeps the last [MAX_TRANSCRIPT_TURNS] turns of the live conversation (screen 16).
     * Memory only, dropped with the lease — nothing here is ever written to disk.
     */
    private fun appendTranscript(msg: PushMessage) {
        if (!transcriptOn) return
        val text = msg.str("text")?.takeIf { it.isNotBlank() } ?: return
        val turn = TranscriptTurn(msg.str("speaker") ?: "agent", text, clock())
        _state.update {
            it.copy(transcript = (it.transcript + turn).takeLast(MAX_TRANSCRIPT_TURNS))
        }
    }

    /** Races any wait against the rep pressing Skip; null means they did. */
    private suspend fun <T : Any> orSkip(block: suspend () -> T): T? = coroutineScope {
        if (skipRequested) return@coroutineScope null
        val work = async { block() }
        val skip = async { while (!skipRequested) delay(120); Unit }
        val result = select<T?> {
            work.onAwait { it }
            skip.onAwait { null }
        }
        work.cancel()
        skip.cancel()
        result
    }

    /**
     * The rep moved on. `skipped` returns the lead to pending server-side rather than
     * burning it, so an unreachable number is retried later in the run.
     */
    private suspend fun skipped(aid: String, phase: String): LeadOutcome {
        DialerLog.i(TAG, "Lead skipped by rep", "phase" to phase)
        backend.event(aid, "skipped", mapOf("phase" to phase))
        skipRequested = false
        return LeadOutcome.Skipped
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
        /**
         * How long to wait for telecom to confirm one merge request before asking again.
         * Samsung + Jio ignores a request made the instant the lead answers and takes the
         * next one; this used to be 2 s, all of it silence for a lead who just said hello.
         * Not shorter: the conference legs of a request that did take appear up to ~0.85 s
         * later, and a retry inside that window would land on a merge in progress.
         */
        const val MERGE_RETRY_MS = 1_000L
        /** Enough for the rep to follow the thread; the full transcript lives server-side. */
        const val MAX_TRANSCRIPT_TURNS = 40
        /** Minimum time the wrap-up sheet stays up, even when the gap is set to zero. */
        const val WRAP_UP_MIN_MS = 5_000L
        /** Longest the rep waits on the agent's hand-over line before taking the call anyway. */
        const val HANDOVER_TIMEOUT_MS = 15_000L
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
