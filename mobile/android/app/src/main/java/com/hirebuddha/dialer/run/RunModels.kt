package com.hirebuddha.dialer.run

import com.hirebuddha.dialer.telecom.LeadFailureCause

data class Lead(val campaignCallId: String, val phone: String, val name: String?, val fields: Map<String, String>, val remaining: Int)

data class Attempt(val attemptId: String, val did: String, val dtmfSequence: String)

sealed interface LeaseResult {
    data class Leased(val lead: Lead) : LeaseResult
    data object NoMoreLeads : LeaseResult
    data class Failed(val code: String, val message: String, val retryable: Boolean) : LeaseResult
}

sealed interface AttemptResult {
    data class Created(val attempt: Attempt) : AttemptResult
    data class Failed(val code: String, val message: String, val retryable: Boolean) : AttemptResult
}

/** Backend operations the orchestrator needs (implemented over Retrofit + the event outbox). */
interface DialerBackend {
    suspend fun nextLead(runId: String): LeaseResult
    suspend fun createAttempt(runId: String, campaignCallId: String, deviceId: String): AttemptResult
    /** Persists and sends an event; returns true once the server acknowledged it. */
    suspend fun event(attemptId: String, type: String, payload: Map<String, String> = emptyMap(), urgent: Boolean = false): Boolean
    suspend fun attemptStatus(attemptId: String): String?
}

/** Live steps shown on the run screen (docs 05 §5). */
enum class Step { IDLE, FETCHING_LEAD, CONNECTING_AI, SENDING_CODE, WAITING_AI, CALLING_LEAD, MERGING, IN_CONVERSATION, WRAPPING_UP, WAITING_NEXT }

enum class RunStatus { IDLE, STARTING, RUNNING, PAUSED, STOPPED, COMPLETED, ERROR }

sealed interface LeadOutcome {
    data class Completed(val endedBy: String) : LeadOutcome
    data class LeadFailed(val cause: LeadFailureCause) : LeadOutcome
    data object Skipped : LeadOutcome
    /** Something about the phone/AI setup failed; the run pauses so the rep can check. */
    data class SetupFailed(val code: String, val message: String) : LeadOutcome
}

enum class UserCommand { TOGGLE_MUTE, TAKE_OVER, HANG_UP, SKIP }

data class RunUiState(
    val status: RunStatus = RunStatus.IDLE,
    val runId: String? = null,
    val campaignId: String? = null,
    val campaignName: String? = null,
    val step: Step = Step.IDLE,
    val lead: Lead? = null,
    val identification: String? = null,
    val muted: Boolean = false,
    val aiInCall: Boolean = false,
    val conversationStartedAt: Long? = null,
    val nextLeadAt: Long? = null,
    val lastOutcome: String? = null,
    val message: String? = null,
    val awaitingMergeDecision: Boolean = false,
    val callsMade: Int = 0,
)

data class OrchestratorConfig(
    val aiAnswerTimeoutMs: Long = 15_000,
    val aiReadyTimeoutMs: Long = 25_000,
    val holdTimeoutMs: Long = 3_000,
    val leadRingTimeoutMs: Long = 35_000,
    val mergeTimeoutMs: Long = 6_000,
    val mergeDecisionTimeoutMs: Long = 15_000,
    val gapBetweenLeadsMs: Long = 5_000,
    val eventAckWaitMs: Long = 2_000,
)
