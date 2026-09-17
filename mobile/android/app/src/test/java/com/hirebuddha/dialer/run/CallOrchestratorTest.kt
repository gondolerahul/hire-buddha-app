package com.hirebuddha.dialer.run

import com.hirebuddha.dialer.data.push.PushEvents
import com.hirebuddha.dialer.data.push.PushMessage
import com.hirebuddha.dialer.telecom.CallControl
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

    override fun conference(callId: String, otherCallId: String): Boolean {
        if (!mergeWorks) return true  // telecom accepts, but the conference never becomes active
        val conf = "conf${++n}"
        state.update { list ->
            list.map { if (it.id == callId || it.id == otherCallId) it.copy(parentId = conf, state = CallState.ACTIVE) else it } +
                CallSnapshot(conf, null, CallState.ACTIVE, outgoing = false, isConference = true, childIds = listOf(callId, otherCallId))
        }
        scope.launch {
            aiEndsAfterMergeMs?.let { delay(it); push.emit("attempt.ai_ended", "reason" to "conversation_complete") }
        }
        scope.launch {
            leadHangsUpAfterMergeMs?.let { delay(it); set(callId) { s -> s.copy(state = CallState.DISCONNECTED) } }
        }
        return true
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
                "lead_answered", "merged", "rep_muted", "completed"),
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

        h.orchestrator.reset("run1", "camp1", "Sept")  // resume
        assertEquals(RunStatus.COMPLETED, h.orchestrator.run("run1", "dev1", config))
        assertEquals(0, h.backend.leads.size)
        assertEquals(1, h.orchestrator.state.value.callsMade)
    }
}
