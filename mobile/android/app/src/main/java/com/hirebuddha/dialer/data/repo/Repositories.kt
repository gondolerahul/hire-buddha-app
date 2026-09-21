package com.hirebuddha.dialer.data.repo

import android.content.ContentResolver
import android.net.Uri
import android.os.Build
import android.provider.OpenableColumns
import com.hirebuddha.dialer.BuildConfig
import com.hirebuddha.dialer.data.api.AgentDto
import com.hirebuddha.dialer.data.api.AnalyticsDto
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.CallsPageDto
import com.hirebuddha.dialer.data.api.CampaignDto
import com.hirebuddha.dialer.data.api.CreateCampaignRequest
import com.hirebuddha.dialer.data.api.CreateCampaignResponse
import com.hirebuddha.dialer.data.api.DeviceDto
import com.hirebuddha.dialer.data.api.DeviceRegisterRequest
import com.hirebuddha.dialer.data.api.HireBuddhaApi
import com.hirebuddha.dialer.data.api.RepDto
import com.hirebuddha.dialer.data.api.TimelineDto
import com.hirebuddha.dialer.data.api.UploadReportDto
import com.hirebuddha.dialer.data.api.VerificationDialingRequest
import com.hirebuddha.dialer.data.api.VoiceSessionDto
import com.hirebuddha.dialer.data.api.apiCall
import com.hirebuddha.dialer.data.api.map
import com.hirebuddha.dialer.data.settings.AppSettings
import javax.inject.Inject
import javax.inject.Singleton
import okhttp3.MediaType
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody
import okio.BufferedSink
import okio.source

@Singleton
class DeviceRepository @Inject constructor(
    private val api: HireBuddhaApi,
    private val settings: AppSettings,
) {
    /** Registers (idempotent on install id); a SIM change re-opens verification server-side. */
    suspend fun register(phoneAccountLabel: String?): ApiResult<DeviceDto> {
        val result = apiCall {
            api.registerDevice(
                DeviceRegisterRequest(
                    installId = settings.installId(),
                    model = "${Build.MANUFACTURER} ${Build.MODEL}",
                    osVersion = Build.VERSION.RELEASE,
                    appVersion = "${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
                    phoneAccountLabel = phoneAccountLabel,
                )
            )
        }
        if (result is ApiResult.Ok) settings.setDeviceId(result.value.deviceId)
        return result
    }

    suspend fun status(deviceId: String) = apiCall { api.device(deviceId) }
    suspend fun reissueVerification(deviceId: String) = apiCall { api.reissueVerification(deviceId) }

    /**
     * Announces that the verification call is being placed right now, so the server
     * can still capture the caller ID if the carrier swallows the keypad tones.
     */
    suspend fun announceDialing(deviceId: String, simNumber: String?) =
        apiCall { api.verificationDialing(deviceId, VerificationDialingRequest(simNumber)) }
}

@Singleton
class CampaignRepository @Inject constructor(private val api: HireBuddhaApi) {

    suspend fun campaigns(): ApiResult<List<CampaignDto>> = apiCall { api.campaigns() }.map { it.campaigns }
    suspend fun campaign(id: String) = apiCall { api.campaign(id) }
    suspend fun agents(): ApiResult<List<AgentDto>> = apiCall { api.agents() }.map { it.agents }
    suspend fun reps(): ApiResult<List<RepDto>> = apiCall { api.reps() }.map { it.reps }

    suspend fun upload(resolver: ContentResolver, uri: Uri): ApiResult<UploadReportDto> {
        val (name, size) = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)
            ?.use { c -> if (c.moveToFirst()) (c.getString(0) ?: "contacts") to c.getLong(1) else null }
            ?: ("contacts" to -1L)
        if (size > MAX_UPLOAD_BYTES) {
            return ApiResult.Err(413, "file_too_large", "File is larger than 10 MB")
        }
        val lower = name.lowercase()
        if (!lower.endsWith(".csv") && !lower.endsWith(".xlsx")) {
            return ApiResult.Err(415, "unsupported_file_type", "Pick a .csv or .xlsx file")
        }
        // Streamed straight from the content provider: the file is never copied into app storage (docs 05 §8).
        val body = object : RequestBody() {
            override fun contentType(): MediaType = "application/octet-stream".toMediaType()
            override fun contentLength(): Long = size
            override fun writeTo(sink: BufferedSink) {
                resolver.openInputStream(uri)?.source()?.use { sink.writeAll(it) }
            }
        }
        return apiCall { api.uploadContacts(MultipartBody.Part.createFormData("file", name, body)) }
    }

    suspend fun create(request: CreateCampaignRequest): ApiResult<CreateCampaignResponse> =
        apiCall { api.createCampaign(request) }

    suspend fun analytics(campaignId: String): ApiResult<AnalyticsDto> = apiCall { api.campaignAnalytics(campaignId) }
    suspend fun summary(from: String?, to: String?, userId: String?): ApiResult<AnalyticsDto> =
        apiCall { api.analyticsSummary(from, to, userId) }

    suspend fun calls(campaignId: String, disposition: String?, status: String?, offset: Int): ApiResult<CallsPageDto> =
        apiCall { api.campaignCalls(campaignId, disposition, status, 50, offset) }

    suspend fun voiceSession(id: String): ApiResult<VoiceSessionDto> = apiCall { api.voiceSession(id) }
    suspend fun timeline(attemptId: String): ApiResult<TimelineDto> = apiCall { api.timeline(attemptId) }

    private companion object {
        const val MAX_UPLOAD_BYTES = 10L * 1024 * 1024
    }
}
