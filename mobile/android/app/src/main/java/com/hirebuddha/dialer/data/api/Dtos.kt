package com.hirebuddha.dialer.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

// Wire contract: docs/mobile-dialer-app/06-backend-changes-and-api.md and 07-analytics.md

@Serializable data class LoginRequest(val email: String, val password: String)
@Serializable data class RefreshRequest(@SerialName("refresh_token") val refreshToken: String)
@Serializable data class TokenResponse(
    @SerialName("access_token") val accessToken: String,
    @SerialName("refresh_token") val refreshToken: String? = null,
)

@Serializable data class MeDto(
    @SerialName("user_id") val userId: String,
    val email: String,
    @SerialName("full_name") val fullName: String,
    val role: String,
    @SerialName("is_admin") val isAdmin: Boolean,
    @SerialName("company_name") val companyName: String? = null,
)

@Serializable data class AppVersionDto(
    @SerialName("latest_version_code") val latestVersionCode: Int,
    @SerialName("latest_version_name") val latestVersionName: String,
    @SerialName("download_url") val downloadUrl: String? = null,
    @SerialName("update_available") val updateAvailable: Boolean = false,
    @SerialName("update_required") val updateRequired: Boolean = false,
)

// ── Devices ──────────────────────────────────────────────────────────────

@Serializable data class DeviceRegisterRequest(
    @SerialName("install_id") val installId: String,
    val model: String?,
    @SerialName("os_version") val osVersion: String?,
    @SerialName("app_version") val appVersion: String?,
    @SerialName("phone_account_label") val phoneAccountLabel: String?,
    @SerialName("fcm_token") val fcmToken: String? = null,
)

@Serializable data class VerificationDto(
    val did: String,
    val code: String,
    @SerialName("dtmf_sequence") val dtmfSequence: String,
    @SerialName("expires_at") val expiresAt: String,
)

@Serializable data class DeviceDto(
    @SerialName("device_id") val deviceId: String,
    val status: String,
    @SerialName("verified_cli") val verifiedCli: String? = null,
    @SerialName("cli_available") val cliAvailable: Boolean = false,
    val verification: VerificationDto? = null,
)

// ── Campaigns ────────────────────────────────────────────────────────────

@Serializable data class AssigneeDto(@SerialName("user_id") val userId: String, val name: String)

@Serializable data class CampaignDto(
    val id: String,
    val name: String,
    val description: String? = null,
    val status: String,
    @SerialName("agent_name") val agentName: String? = null,
    val did: String? = null,
    @SerialName("total_contacts") val totalContacts: Int = 0,
    val pending: Int = 0,
    val completed: Int = 0,
    val failed: Int = 0,
    val skipped: Int = 0,
    val interested: Int = 0,
    val done: Int = 0,
    val assignees: List<AssigneeDto> = emptyList(),
    @SerialName("created_at") val createdAt: String? = null,
)

@Serializable data class CampaignsResponse(val campaigns: List<CampaignDto>)
@Serializable data class AgentDto(@SerialName("agent_id") val agentId: String, val name: String, val did: String?, val provider: String?)
@Serializable data class AgentsResponse(val agents: List<AgentDto>)
@Serializable data class RepDto(@SerialName("user_id") val userId: String, val name: String, val email: String, val role: String)
@Serializable data class RepsResponse(val reps: List<RepDto>)

@Serializable data class RowErrorDto(val row: Int, val field: String, val value: String, val reason: String)

@Serializable data class UploadReportDto(
    @SerialName("upload_id") val uploadId: String,
    @SerialName("file_type") val fileType: String,
    @SerialName("total_rows") val totalRows: Int,
    @SerialName("valid_rows") val validRows: Int,
    @SerialName("invalid_rows") val invalidRows: Int,
    @SerialName("duplicate_rows") val duplicateRows: Int,
    val columns: List<String>,
    @SerialName("phone_column") val phoneColumn: String? = null,
    val errors: List<RowErrorDto> = emptyList(),
    val preview: List<JsonObject> = emptyList(),
)

@Serializable data class CreateCampaignRequest(
    @SerialName("agent_id") val agentId: String,
    val name: String,
    @SerialName("contact_upload_id") val contactUploadId: String,
    @SerialName("execution_mode") val executionMode: String = "mobile_conference",
    @SerialName("assignee_user_ids") val assigneeUserIds: List<String>? = null,
)

@Serializable data class CreateCampaignResponse(val id: String, val name: String, val status: String)

// ── Runs & attempts ──────────────────────────────────────────────────────

@Serializable data class RunStartRequest(@SerialName("device_id") val deviceId: String, @SerialName("dial_order") val dialOrder: String = "ai_first")
@Serializable data class RunUpdateRequest(val status: String)
@Serializable data class RunDto(@SerialName("run_id") val runId: String, @SerialName("campaign_id") val campaignId: String, val status: String)

@Serializable data class LeaseDto(
    @SerialName("campaign_call_id") val campaignCallId: String,
    val contact: JsonObject,
    val remaining: Int = 0,
)

@Serializable data class AttemptCreateRequest(
    @SerialName("run_id") val runId: String,
    @SerialName("campaign_call_id") val campaignCallId: String,
    @SerialName("device_id") val deviceId: String,
    val assisted: Boolean = false,
)

@Serializable data class AttemptDto(
    @SerialName("attempt_id") val attemptId: String,
    val did: String,
    @SerialName("dtmf_token") val dtmfToken: String,
    @SerialName("dtmf_sequence") val dtmfSequence: String,
    val status: String,
    @SerialName("identification_method") val identificationMethod: String? = null,
    @SerialName("voice_session_id") val voiceSessionId: String? = null,
    val disposition: String? = null,
    val summary: String? = null,
)

@Serializable data class EventDto(
    val seq: Int,
    val type: String,
    @SerialName("device_ts") val deviceTs: String,
    @SerialName("elapsed_ms") val elapsedMs: Long,
    val payload: JsonObject,
)

@Serializable data class EventBatch(val events: List<EventDto>)
@Serializable data class EventAck(val accepted: List<Int>, val duplicates: List<Int>)

// ── Analytics ────────────────────────────────────────────────────────────

@Serializable data class FunnelDto(
    val leads: Int? = null, val attempted: Int = 0, val attempts: Int = 0,
    @SerialName("ai_ready") val aiReady: Int = 0,
    @SerialName("lead_dialed") val leadDialed: Int = 0,
    @SerialName("lead_answered") val leadAnswered: Int = 0,
    val merged: Int = 0, val conversation: Int = 0, val interested: Int = 0,
)

@Serializable data class RatesDto(
    val answer: Double? = null,
    @SerialName("merge_success") val mergeSuccess: Double? = null,
    val identification: Double? = null,
    val conversion: Double? = null,
)

@Serializable data class TimingDto(
    @SerialName("ai_ready_p50_s") val aiReadyP50: Double? = null,
    @SerialName("avg_conversation_s") val avgConversation: Double? = null,
    @SerialName("talk_minutes") val talkMinutes: Double? = null,
)

@Serializable data class RepStatDto(
    @SerialName("user_id") val userId: String, val name: String, val attempts: Int,
    @SerialName("answer_rate") val answerRate: Double? = null,
    val interested: Int = 0,
    @SerialName("talk_minutes") val talkMinutes: Double = 0.0,
)

@Serializable data class DailyDto(val date: String, val attempted: Int, val merged: Int, val interested: Int)

@Serializable data class AnalyticsDto(
    val funnel: FunnelDto,
    val rates: RatesDto,
    val timing: TimingDto,
    val outcomes: Map<String, Int> = emptyMap(),
    @SerialName("by_rep") val byRep: List<RepStatDto> = emptyList(),
    val daily: List<DailyDto> = emptyList(),
)

@Serializable data class CallItemDto(
    @SerialName("campaign_call_id") val campaignCallId: String,
    @SerialName("contact_name") val contactName: String? = null,
    @SerialName("phone_masked") val phoneMasked: String = "",
    @SerialName("call_status") val callStatus: String,
    val disposition: String? = null,
    @SerialName("rep_name") val repName: String? = null,
    @SerialName("attempt_id") val attemptId: String? = null,
    @SerialName("lead_failure_cause") val leadFailureCause: String? = null,
    @SerialName("conversation_seconds") val conversationSeconds: Int? = null,
    @SerialName("called_at") val calledAt: String? = null,
    @SerialName("voice_session_id") val voiceSessionId: String? = null,
)

@Serializable data class CallsPageDto(val total: Int, val items: List<CallItemDto>)

@Serializable data class TranscriptTurnDto(val speaker: String, val content: String)

@Serializable data class VoiceSessionDto(
    val id: String,
    val status: String,
    @SerialName("started_at") val startedAt: String? = null,
    @SerialName("duration_seconds") val durationSeconds: Int? = null,
    val transcript: List<TranscriptTurnDto> = emptyList(),
    @SerialName("call_summary") val callSummary: String? = null,
    @SerialName("recording_url") val recordingUrl: String? = null,
    @SerialName("next_action") val nextAction: String? = null,
)

@Serializable data class TimelineEntryDto(val at: String, val source: String, val type: String)
@Serializable data class TimelineDto(val timeline: List<TimelineEntryDto>)
