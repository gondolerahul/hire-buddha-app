package com.hirebuddha.dialer.run

import com.hirebuddha.dialer.data.push.PushEvents
import com.hirebuddha.dialer.data.push.PushMessage
import com.hirebuddha.dialer.telecom.CallControl
import com.hirebuddha.dialer.telecom.ConferenceResult
import com.hirebuddha.dialer.telecom.ConferenceStrategy
import com.hirebuddha.dialer.telecom.CallSnapshot
import com.hirebuddha.dialer.telecom.CallState
import com.hirebuddha.dialer.telecom.LeadFailureCause
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

private const val DID = "+918065251146"
private const val LEAD_PHONE = "+919812345678"

sealed interface LeadBehavior {
    data class Answer(val afterMs: Long) : LeadBehavior
    data class Reject(val afterMs: Long, val cause: LeadFailureCause) : LeadBehavior
    data object RingForever : LeadBehavior
}

class FakeCalls(private val scope: CoroutineScope, private val push: FakePush) : CallControl {
    private val state = MutableStateFlow<List<CallSnapshot>>(emptyList())
    override val calls = state
    var aiAnswers = true
    var lead: LeadBehavior = LeadBehavior.Answer(3_000)
    var mergeWorks = true
    /** Some stacks (VoLTE/IMS) drop the two legs and leave only the conference call. */
    var mergeReplacesLegs = false
    /** Merge requests that telecom silently ignores before it finally works. */
    var mergeAttemptsBeforeSuccess = 0
    var conferenceCalls = 0
    /** Which push the "gateway" sends after the DTMF token arrives. */
    var readyPush: String? = "attempt.ai_ready"
    var aiEndsAfterMergeMs: Long? = 20_000
    var leadHangsUpAfterMergeMs: Long? = null

    val dtmf = mutableListOf<Pair<String, String>>()
    val mutes = mutableListOf<Boolean>()
    val disconnected = mutableListOf<String>()
    private var n = 0

    private fun set(id: String, f: (CallSnapshot) -> CallSnapshot) =
        state.update { list -> list.map { if (it.id == id) f(it) else it } }

    override suspend fun placeCall(number: String): String {
        val id = "c${++n}"
        state.update { it + CallSnapshot(id, number, CallState.DIALING, outgoing = true) }
        scope.launch {
            if (number == DID) {
                delay(2_000)
                if (aiAnswers) set(id) { it.copy(state = CallState.ACTIVE) }
            } else when (val b = lead) {
                is LeadBehavior.Answer -> { delay(b.afterMs); set(id) { it.copy(state = CallState.ACTIVE) } }
                is LeadBehavior.Reject -> { delay(b.afterMs); set(id) { it.copy(state = CallState.DISCONNECTED, disconnectCause = b.cause) } }
                LeadBehavior.RingForever -> Unit
            }
        }
        return id
    }

    override fun hold(callId: String) = set(callId) { it.copy(state = CallState.HOLDING) }
    override fun unhold(callId: String) = set(callId) { it.copy(state = CallState.ACTIVE) }

    override fun conference(callId: String, otherCallId: String): ConferenceResult {
        conferenceCalls++
        val action = ConferenceStrategy.choose(
            factsFor(callId, otherCallId), factsFor(otherCallId, callId),
        )
        if (action == ConferenceStrategy.Action.IMPOSSIBLE) return ConferenceResult(action, "gone")
        // telecom accepts the request but nothing happens
        if (!mergeWorks || conferenceCalls <= mergeAttemptsBeforeSuccess) return ConferenceResult(action)
        val conf = "conf${++n}"
        state.update { list ->
            val legs = list.map {
                when {
                    it.id != callId && it.id != otherCallId -> it
                    mergeReplacesLegs -> it.copy(state = CallState.DISCONNECTED)
                    else -> it.copy(parentId = conf, state = CallState.ACTIVE)
                }
            }
            legs + CallSnapshot(
                conf, null, CallState.ACTIVE, outgoing = false, isConference = true,
                childIds = if (mergeReplacesLegs) emptyList() else listOf(callId, otherCallId),
            )
        }
        scope.launch {
            aiEndsAfterMergeMs?.let { delay(it); push.emit("attempt.ai_ended", "reason" to "conversation_complete") }
        }
        scope.launch {
            leadHangsUpAfterMergeMs?.let {
                delay(it)
                // The lead leaving ends the conference too.
                set(callId) { s -> s.copy(state = CallState.DISCONNECTED) }
                set(conf) { s -> s.copy(state = CallState.DISCONNECTED) }
            }
        }
        return ConferenceResult(action)
    }

    private fun factsFor(id: String, otherId: String): ConferenceStrategy.CallFacts {
        val snapshot = state.value.firstOrNull { it.id == id }
        return ConferenceStrategy.CallFacts(
            id = id,
            exists = snapshot != null,
            state = snapshot?.state ?: CallState.DISCONNECTED,
            parentId = snapshot?.parentId,
            isConferenceable = state.value.any { it.id == otherId },
        )
    }

    override suspend fun playDtmf(callId: String, sequence: String) {
        dtmf += callId to sequence
        delay(sequence.length * 250L)
        if (sequence.startsWith("*")) readyPush?.let { type ->
            scope.launch { delay(3_000); push.emit(type, "identification" to "cli+dtmf") }
        }
    }

    override fun disconnect(callId: String) {
        disconnected += callId
        set(callId) { it.copy(state = CallState.DISCONNECTED) }
        val children = state.value.firstOrNull { it.id == callId }?.childIds.orEmpty()
        children.forEach { child -> set(child) { it.copy(state = CallState.DISCONNECTED) } }
    }

    override fun setMuted(muted: Boolean) { mutes += muted }
}

class FakePush : PushEvents {
    private val flow = MutableSharedFlow<PushMessage>(extraBufferCapacity = 16)
    override val messages: SharedFlow<PushMessage> = flow
    fun emit(type: String, vararg fields: Pair<String, String>) {
        val obj = buildJsonObject {
            put("type", JsonPrimitive(type))
            put("attempt_id", JsonPrimitive("a1"))
            fields.forEach { (k, v) -> put(k, JsonPrimitive(v)) }
        }
        flow.tryEmit(PushMessage(type, obj))
    }
}

class FakeBackend : DialerBackend {
    val events = mutableListOf<Pair<String, Map<String, String>>>()
    val leads = ArrayDeque<Lead>()
    var ackUrgent = true
    var status: String? = null

    override suspend fun nextLead(runId: String): LeaseResult =
        leads.removeFirstOrNull()?.let { LeaseResult.Leased(it) } ?: LeaseResult.NoMoreLeads

    override suspend fun createAttempt(runId: String, campaignCallId: String, deviceId: String) =
        AttemptResult.Created(Attempt("a1", DID, "*4821#"))

    override suspend fun event(attemptId: String, type: String, payload: Map<String, String>, urgent: Boolean): Boolean {
        events += type to payload
        return if (urgent) ackUrgent else true
    }

    override suspend fun attemptStatus(attemptId: String) = status
    fun types() = events.map { it.first }
}

private fun lead(name: String = "Asha") = Lead("cc1", LEAD_PHONE, name, mapOf("city" to "Pune"), remaining = 3)

private class Harness(scope: TestScope) {
    val push = FakePush()
    val calls = FakeCalls(scope.backgroundScope, push)
    val backend = FakeBackend()
    val orchestrator = CallOrchestrator(calls, backend, push, clock = { scope.testScheduler.currentTime })
}

class CallOrchestratorTest {

    private val config = OrchestratorConfig(gapBetweenLeadsMs = 0)

    @Test
    fun `happy path runs AI-first, mutes the rep and ends when the AI says goodbye`() = runTest {
        val h = Harness(this)
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config)

        assertEquals(LeadOutcome.Completed("conversation_complete"), outcome)
        assertEquals(
            listOf("ai_dialing", "ai_answered", "dtmf_sent", "ai_ready_received", "ai_held", "lead_dialing",
                "lead_answered", "merge_requested", "merged", "rep_muted", "completed"),
            h.backend.types(),
        )
        assertEquals("c1" to "*4821#", h.calls.dtmf.first())  // token goes on the AI leg, before the lead exists
        assertEquals(listOf(true, false), h.calls.mutes)       // D4: muted on merge, restored at the end
        assertEquals("cli+dtmf", h.orchestrator.state.value.identification)
    }

    @Test
    fun `busy lead is reported with its cause and the AI leg is dropped`() = runTest {
        val h = Harness(this)
        h.calls.lead = LeadBehavior.Reject(2_000, LeadFailureCause.BUSY)
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config)

        assertEquals(LeadOutcome.LeadFailed(LeadFailureCause.BUSY), outcome)
        assertEquals("lead_failed" to mapOf("cause" to "busy"), h.backend.events.last())
        assertTrue("c1" in h.calls.disconnected)
    }

    @Test
    fun `unanswered lead times out as no_answer and both legs are hung up`() = runTest {
        val h = Harness(this)
        h.calls.lead = LeadBehavior.RingForever
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config.copy(leadRingTimeoutMs = 30_000))

        assertEquals(LeadOutcome.LeadFailed(LeadFailureCause.NO_ANSWER), outcome)
        assertTrue(h.calls.disconnected.containsAll(listOf("c1", "c2")))
    }

    @Test
    fun `AI number not answering pauses the run as a setup failure`() = runTest {
        val h = Harness(this)
        h.calls.aiAnswers = false
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config)

        assertTrue(outcome is LeadOutcome.SetupFailed)
        assertEquals("ai_failed" to mapOf("reason" to "ai_not_answered"), h.backend.events.last())
        assertFalse(h.backend.types().contains("lead_dialing"))
    }

    @Test
    fun `failed merge hangs up both legs and reports merge_failed`() = runTest {
        val h = Harness(this)
        h.calls.mergeWorks = false
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config)

        assertEquals("merge_failed", (outcome as LeadOutcome.SetupFailed).code)
        assertTrue(h.backend.types().contains("merge_failed"))
        assertTrue(h.calls.disconnected.containsAll(listOf("c1", "c2")))
    }

    @Test
    fun `unidentified AI without a rep decision returns the lead instead of calling it`() = runTest {
        val h = Harness(this)
        h.calls.readyPush = "attempt.unidentified"
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config)

        assertEquals(LeadOutcome.Skipped, outcome)
        assertEquals("ai_failed" to mapOf("reason" to "unidentified_skipped"), h.backend.events.last())
        assertFalse(h.backend.types().contains("lead_dialing"))
    }

    @Test
    fun `rep can merge anyway when the AI could not identify the lead`() = runTest {
        val h = Harness(this)
        h.calls.readyPush = "attempt.unidentified"
        backgroundScope.launch {
            h.orchestrator.state.collect { if (it.awaitingMergeDecision) h.orchestrator.decideMerge(true) }
        }
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config)

        assertEquals(LeadOutcome.Completed("conversation_complete"), outcome)
        assertTrue(h.backend.types().contains("merged"))
    }

    @Test
    fun `no push and no ready status times out waiting for the AI`() = runTest {
        val h = Harness(this)
        h.calls.readyPush = null
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config)
        assertEquals("ai_ready_timeout", (outcome as LeadOutcome.SetupFailed).code)
    }

    @Test
    fun `missed push is recovered by polling the attempt status`() = runTest {
        val h = Harness(this)
        h.calls.readyPush = null
        h.backend.status = "ai_ready"
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config)
        assertEquals(LeadOutcome.Completed("conversation_complete"), outcome)
    }

    @Test
    fun `unacknowledged merged event falls back to a DTMF hash on the AI leg`() = runTest {
        val h = Harness(this)
        h.backend.ackUrgent = false
        h.orchestrator.runLead("run1", "dev1", lead(), config)
        assertTrue(h.calls.dtmf.contains("c1" to "#"))
    }

    @Test
    fun `rep unmutes then the lead hangs up`() = runTest {
        val h = Harness(this)
        h.calls.aiEndsAfterMergeMs = null
        h.calls.leadHangsUpAfterMergeMs = 10_000
        backgroundScope.launch {
            h.orchestrator.state.collect { if (it.step == Step.IN_CONVERSATION && it.muted) h.orchestrator.send(UserCommand.TOGGLE_MUTE) }
        }
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config)

        assertEquals(LeadOutcome.Completed("lead"), outcome)
        assertTrue(h.backend.types().containsAll(listOf("rep_unmuted", "lead_disconnected")))
        assertTrue(h.calls.mutes.contains(false))
    }

    @Test
    fun `merge is confirmed when the stack replaces both legs with a conference call`() = runTest {
        // Regression: VoLTE stacks remove the two calls and leave only the conference.
        // The first build read that as a merge failure and hung up on the lead.
        val h = Harness(this)
        h.calls.mergeReplacesLegs = true
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config)

        assertEquals(LeadOutcome.Completed("conversation_complete"), outcome)
        assertTrue(h.backend.types().contains("merged"))
        assertFalse(h.backend.types().contains("merge_failed"))
    }

    @Test
    fun `merge request is retried when telecom ignores the first attempt`() = runTest {
        val h = Harness(this)
        h.calls.mergeAttemptsBeforeSuccess = 2
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config.copy(mergeTimeoutMs = 15_000))

        assertEquals(LeadOutcome.Completed("conversation_complete"), outcome)
        assertTrue("expected more than one merge request", h.calls.conferenceCalls >= 3)
        assertTrue(h.backend.types().contains("merged"))
    }

    @Test
    fun `conversation survives the legs disappearing into the conference`() = runTest {
        val h = Harness(this)
        h.calls.mergeReplacesLegs = true
        h.calls.aiEndsAfterMergeMs = 30_000
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config)

        // Without the conference-aware check this ended instantly as "lead hung up".
        assertEquals(LeadOutcome.Completed("conversation_complete"), outcome)
        assertFalse(h.backend.types().contains("lead_disconnected"))
    }

    @Test
    fun `run completes when no leads are left and pauses when asked`() = runTest {
        val h = Harness(this)
        h.backend.leads += lead("One")
        h.backend.leads += lead("Two")
        h.orchestrator.reset("run1", "camp1", "Sept")
        val pauser = backgroundScope.launch {
            h.orchestrator.state.collect { if (it.step == Step.IN_CONVERSATION) h.orchestrator.requestPause() }
        }
        // Pause takes effect after the current lead finishes, not mid-call.
        assertEquals(RunStatus.PAUSED, h.orchestrator.run("run1", "dev1", config))
        assertEquals(1, h.backend.leads.size)
        pauser.cancel()

        h.orchestrator.resume("run1")
        assertEquals(RunStatus.COMPLETED, h.orchestrator.run("run1", "dev1", config))
        assertEquals(0, h.backend.leads.size)
        // The summary covers the whole run, not just the stretch since the pause.
        assertEquals(2, h.orchestrator.state.value.callsMade)
        assertEquals(2, h.orchestrator.state.value.connected)
    }
}

/**
 * Behaviour added in the v2 redesign (docs/mobile-dialer-app/11-ux-and-visual-design.md).
 *
 * `UserCommand.SKIP` existed from the first build but nothing ever sent it, and the
 * orchestrator only honoured it once a conversation was live — precisely the phase where
 * a rep least needs it. These cover the three waits a rep actually sits through.
 *
 * Every test drives the orchestrator from a state observer rather than `advanceTimeBy`,
 * which is the idiom the rest of this file uses: the virtual clock then only advances
 * while the run itself is waiting, so there is no window for a stray coroutine to leak.
 */
class CallOrchestratorV2Test {

    private val config = OrchestratorConfig(gapBetweenLeadsMs = 0)

    /** Presses Skip the first time the run reaches [at]. */
    private fun TestScope.skipAt(h: Harness, at: Step) = backgroundScope.launch {
        h.orchestrator.state.collect { if (it.step == at) h.orchestrator.send(UserCommand.SKIP) }
    }

    @Test
    fun `skip while the agent is connecting never rings the lead`() = runTest {
        val h = Harness(this)
        skipAt(h, Step.CONNECTING_AI)
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config)

        assertEquals(LeadOutcome.Skipped, outcome)
        assertEquals("skipped" to mapOf("phase" to "connecting_ai"), h.backend.events.last())
        // The whole point of AI-first: the lead's phone must never have rung.
        assertFalse(h.backend.types().contains("lead_dialing"))
    }

    @Test
    fun `skip while waiting for the agent to be briefed aborts before the lead is dialled`() = runTest {
        val h = Harness(this)
        h.calls.readyPush = null          // the gateway never says ai_ready
        skipAt(h, Step.WAITING_AI)
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config)

        assertEquals(LeadOutcome.Skipped, outcome)
        assertEquals("skipped" to mapOf("phase" to "waiting_for_ai"), h.backend.events.last())
        assertFalse(h.backend.types().contains("lead_dialing"))
    }

    @Test
    fun `skip while the lead is ringing drops both legs`() = runTest {
        val h = Harness(this)
        h.calls.lead = LeadBehavior.RingForever
        skipAt(h, Step.CALLING_LEAD)
        val outcome = h.orchestrator.runLead("run1", "dev1", lead(), config)

        assertEquals(LeadOutcome.Skipped, outcome)
        assertEquals("skipped" to mapOf("phase" to "ringing_lead"), h.backend.events.last())
        assertTrue(h.calls.disconnected.containsAll(listOf("c1", "c2")))
    }

    @Test
    fun `a connected call is counted and offered for wrap-up`() = runTest {
        val h = Harness(this)
        h.backend.leads += lead("Meenal")
        h.orchestrator.reset("run1", "camp1", "Baner leads")
        // Grab the sheet as it appears: the gap clears it once the run moves on.
        var seen: WrapUp? = null
        backgroundScope.launch { h.orchestrator.state.collect { s -> s.wrapUp?.let { if (seen == null) seen = it } } }
        h.orchestrator.run("run1", "dev1", config)

        assertEquals("cc1", seen?.campaignCallId)
        assertEquals("Meenal", seen?.leadName)
        assertEquals(1, h.orchestrator.state.value.connected)
    }

    @Test
    fun `a lead that never connects is not worth asking the rep about`() = runTest {
        val h = Harness(this)
        h.calls.lead = LeadBehavior.Reject(2_000, LeadFailureCause.BUSY)
        h.backend.leads += lead()
        h.orchestrator.reset("run1", "camp1", "Baner leads")
        var seen: WrapUp? = null
        backgroundScope.launch { h.orchestrator.state.collect { s -> s.wrapUp?.let { if (seen == null) seen = it } } }
        h.orchestrator.run("run1", "dev1", config)

        assertEquals(null, seen)
        assertEquals(0, h.orchestrator.state.value.connected)
    }

    @Test
    fun `run summary funnel counts answered, merged and 30-second conversations`() = runTest {
        val h = Harness(this)
        h.calls.aiEndsAfterMergeMs = 45_000
        h.backend.leads += lead("Long")
        h.orchestrator.reset("run1", "camp1", "Baner leads")
        h.orchestrator.run("run1", "dev1", config)

        h.calls.aiEndsAfterMergeMs = 10_000
        h.backend.leads += lead("Short")
        h.orchestrator.resume("run1")
        h.orchestrator.run("run1", "dev1", config)

        h.calls.lead = LeadBehavior.Reject(2_000, LeadFailureCause.BUSY)
        h.backend.leads += lead("Busy")
        h.orchestrator.resume("run1")
        assertEquals(RunStatus.COMPLETED, h.orchestrator.run("run1", "dev1", config))

        val s = h.orchestrator.state.value
        assertEquals(3, s.callsMade)
        assertEquals(2, s.leadAnswered)
        assertEquals(2, s.connected)
        assertEquals(1, s.talked30)
        assertTrue(s.endedAt != null)
    }

    @Test
    fun `rep dispositions are tallied and a paused run can be marked stopped`() = runTest {
        val h = Harness(this)
        h.orchestrator.reset("run1", "camp1", "Baner leads")
        h.orchestrator.recordDisposition("interested")
        h.orchestrator.recordDisposition("interested")
        h.orchestrator.recordDisposition("callback")
        h.orchestrator.recordDisposition("not_interested")
        h.orchestrator.markStopped()

        val s = h.orchestrator.state.value
        assertEquals(2, s.interested)
        assertEquals(1, s.callbacks)
        assertEquals(RunStatus.STOPPED, s.status)
    }

    @Test
    fun `askAfterEveryCall off means no wrap-up is ever offered`() = runTest {
        val h = Harness(this)
        h.backend.leads += lead()
        h.orchestrator.reset("run1", "camp1", "Baner leads")
        var seen: WrapUp? = null
        backgroundScope.launch { h.orchestrator.state.collect { s -> s.wrapUp?.let { if (seen == null) seen = it } } }
        h.orchestrator.run("run1", "dev1", config.copy(askAfterEveryCall = false))

        assertEquals(null, seen)
        // …so the summary knows it has no interested count to show.
        assertFalse(h.orchestrator.state.value.askedAfterCalls)
    }

    @Test
    fun `transcript turns pushed during the conversation land on the run state`() = runTest {
        val h = Harness(this)
        h.calls.aiEndsAfterMergeMs = null
        h.calls.leadHangsUpAfterMergeMs = 10_000
        // Emit the turns the moment the conference goes live, the way the gateway does.
        backgroundScope.launch {
            h.orchestrator.state.collect {
                if (it.step == Step.IN_CONVERSATION && it.transcript.isEmpty()) {
                    h.push.emit("attempt.transcript", "speaker" to "agent", "text" to "Am I speaking with Asha?")
                    h.push.emit("attempt.transcript", "speaker" to "lead", "text" to "Yes, speaking.")
                }
            }
        }
        h.orchestrator.runLead("run1", "dev1", lead(), config)

        val turns = h.orchestrator.state.value.transcript
        assertEquals(2, turns.size)
        assertTrue(turns[0].isAgent)
        assertFalse(turns[1].isAgent)
        assertEquals("Yes, speaking.", turns[1].text)
    }

    @Test
    fun `a blank transcript push is ignored rather than drawn as an empty bubble`() = runTest {
        val h = Harness(this)
        h.calls.aiEndsAfterMergeMs = null
        h.calls.leadHangsUpAfterMergeMs = 10_000
        var emitted = false
        backgroundScope.launch {
            h.orchestrator.state.collect {
                if (it.step == Step.IN_CONVERSATION && !emitted) {
                    emitted = true
                    h.push.emit("attempt.transcript", "speaker" to "agent", "text" to "   ")
                }
            }
        }
        h.orchestrator.runLead("run1", "dev1", lead(), config)

        assertTrue(emitted)
        assertTrue(h.orchestrator.state.value.transcript.isEmpty())
    }
}
