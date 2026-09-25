package com.hirebuddha.dialer.data.api

import okhttp3.MultipartBody
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query

/** Paths are relative to `<server>/api/v1/`. */
interface HireBuddhaApi {

    @POST("auth/login") suspend fun login(@Body body: LoginRequest): Response<TokenResponse>
    @GET("mobile/me") suspend fun me(): Response<MeDto>
    @GET("mobile/app-version") suspend fun appVersion(@Query("version_code") versionCode: Int): Response<AppVersionDto>

    @POST("mobile/devices") suspend fun registerDevice(@Body body: DeviceRegisterRequest): Response<DeviceDto>
    @GET("mobile/devices/{id}") suspend fun device(@Path("id") id: String): Response<DeviceDto>
    @POST("mobile/devices/{id}/verification") suspend fun reissueVerification(@Path("id") id: String): Response<DeviceDto>
    @POST("mobile/devices/{id}/verification/dialing")
    suspend fun verificationDialing(@Path("id") id: String, @Body body: VerificationDialingRequest): Response<VerificationDialingDto>

    @GET("mobile/campaigns") suspend fun campaigns(): Response<CampaignsResponse>
    @GET("mobile/campaigns/{id}") suspend fun campaign(@Path("id") id: String): Response<CampaignDto>
    @GET("mobile/agents") suspend fun agents(): Response<AgentsResponse>
    @GET("mobile/reps") suspend fun reps(): Response<RepsResponse>
    @GET("mobile/leads/lookup") suspend fun lookupLead(@Query("phone") phone: String): Response<LeadLookupResponse>
    @PUT("mobile/campaigns/{id}/assignees")
    suspend fun setAssignees(@Path("id") campaignId: String, @Body body: AssigneesUpdateRequest): Response<AssigneesResponse>

    @Multipart
    @POST("campaigns/upload-contacts")
    suspend fun uploadContacts(@Part file: MultipartBody.Part): Response<UploadReportDto>

    @POST("campaigns") suspend fun createCampaign(@Body body: CreateCampaignRequest): Response<CreateCampaignResponse>

    @POST("mobile/campaigns/{id}/runs") suspend fun startRun(@Path("id") campaignId: String, @Body body: RunStartRequest): Response<RunDto>
    @PATCH("mobile/runs/{id}") suspend fun updateRun(@Path("id") runId: String, @Body body: RunUpdateRequest): Response<RunDto>
    @POST("mobile/runs/{id}/next") suspend fun nextLead(@Path("id") runId: String): Response<LeaseDto>

    @POST("mobile/call-attempts") suspend fun createAttempt(@Body body: AttemptCreateRequest): Response<AttemptDto>
    @GET("mobile/call-attempts/{id}") suspend fun attempt(@Path("id") attemptId: String): Response<AttemptDto>
    @POST("mobile/call-attempts/{id}/events") suspend fun postEvents(@Path("id") attemptId: String, @Body body: EventBatch): Response<EventAck>
    @POST("mobile/logs") suspend fun postLogs(@Body body: LogBatch): Response<LogAck>
    @GET("mobile/call-attempts/{id}/timeline") suspend fun timeline(@Path("id") attemptId: String): Response<TimelineDto>

    @GET("campaigns/{id}/mobile-analytics") suspend fun campaignAnalytics(@Path("id") campaignId: String): Response<AnalyticsDto>
    @GET("campaigns/{id}/calls") suspend fun campaignCalls(
        @Path("id") campaignId: String,
        @Query("disposition") disposition: String? = null,
        @Query("status") status: String? = null,
        /** Also list leads nobody has called yet. Older servers ignore it (and show a rep only their own calls). */
        @Query("include_pending") includePending: Boolean? = null,
        @Query("limit") limit: Int = 50,
        @Query("offset") offset: Int = 0,
    ): Response<CallsPageDto>
    @GET("mobile/analytics/summary") suspend fun analyticsSummary(
        @Query("from") from: String? = null,
        @Query("to") to: String? = null,
        @Query("user_id") userId: String? = null,
    ): Response<AnalyticsDto>

    @GET("streaming/voice-sessions/{id}") suspend fun voiceSession(@Path("id") sessionId: String): Response<VoiceSessionDto>

    // Added in app 1.1 / backend mobile_dialer_002. A server that predates them answers
    // 404, which the repository treats as "feature unavailable" rather than an error —
    // the APK is sideloaded, so app and server versions drift by design.
    @GET("mobile/preflight") suspend fun preflight(
        @Query("campaign_id") campaignId: String? = null,
        @Query("device_id") deviceId: String? = null,
    ): Response<PreflightDto>

    @PATCH("mobile/campaign-calls/{id}/disposition")
    suspend fun setDisposition(@Path("id") campaignCallId: String, @Body body: RepDispositionRequest): Response<RepDispositionResponse>

    /** Runs still open for this user — the way back to a run the app has forgotten. */
    @GET("mobile/runs/active") suspend fun activeRuns(): Response<ActiveRunsResponse>

    @GET("mobile/callbacks") suspend fun callbacks(
        @Query("within_hours") withinHours: Int = 24,
        @Query("limit") limit: Int = 50,
    ): Response<CallbacksResponse>
}
