package com.hirebuddha.dialer.run

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import com.hirebuddha.dialer.core.asText
import com.hirebuddha.dialer.core.stringMap
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.AttemptCreateRequest
import com.hirebuddha.dialer.data.api.HireBuddhaApi
import com.hirebuddha.dialer.data.api.RunStartRequest
import com.hirebuddha.dialer.data.api.RunUpdateRequest
import com.hirebuddha.dialer.data.api.apiCall
import com.hirebuddha.dialer.data.outbox.EventOutbox
import com.hirebuddha.dialer.data.push.PushClient
import com.hirebuddha.dialer.data.settings.AppSettings
import com.hirebuddha.dialer.telecom.CallRegistry
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/** [DialerBackend] over the REST API; events go through the durable outbox. */
class ApiDialerBackend(
    private val api: HireBuddhaApi,
    private val outbox: EventOutbox,
) : DialerBackend {

    override suspend fun nextLead(runId: String): LeaseResult = when (val r = apiCall { api.nextLead(runId) }) {
        is ApiResult.Ok -> {
            val contact = r.value.contact
            val phone = contact["phone"].asText()
            if (phone == null) LeaseResult.Failed("bad_lead", "A lead has no phone number.", retryable = false)
            else LeaseResult.Leased(
                Lead(
                    campaignCallId = r.value.campaignCallId,
                    phone = phone,
                    name = (contact["name"] ?: contact["Name"]).asText(),
                    fields = contact.stringMap() - "phone",
                    remaining = r.value.remaining,
                )
            )
        }
        ApiResult.Empty -> LeaseResult.NoMoreLeads
        is ApiResult.Err -> LeaseResult.Failed(r.code, r.message, retryable = r.isNetwork || r.httpStatus in listOf(409, 423, 429, 500, 502, 503))
    }

    override suspend fun createAttempt(runId: String, campaignCallId: String, deviceId: String): AttemptResult =
        when (val r = apiCall { api.createAttempt(AttemptCreateRequest(runId, campaignCallId, deviceId)) }) {
            is ApiResult.Ok -> AttemptResult.Created(Attempt(r.value.attemptId, r.value.did, r.value.dtmfSequence))
            is ApiResult.Err -> AttemptResult.Failed(r.code, r.message, retryable = r.isNetwork)
            ApiResult.Empty -> AttemptResult.Failed("empty", "Couldn't start the call.", retryable = true)
        }

    override suspend fun event(attemptId: String, type: String, payload: Map<String, String>, urgent: Boolean): Boolean {
        outbox.record(attemptId, type, payload)
        return if (urgent) {
            withTimeoutOrNull(2_000) { outbox.flush() } ?: false
        } else {
            // Non-urgent events ride along with the next flush; fire one now without waiting.
            flushScope.launch { outbox.flush() }
            true
        }
    }

    override suspend fun attemptStatus(attemptId: String): String? =
        (apiCall { api.attempt(attemptId) } as? ApiResult.Ok)?.value?.status

    private val flushScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
}

/**
 * Process-wide owner of the active campaign run. The UI talks to this; [RunService]
 * hosts the coroutine as a foreground service so the run survives backgrounding.
 */
@Singleton
class RunController @Inject constructor(
    @ApplicationContext private val context: Context,
    private val api: HireBuddhaApi,
    private val registry: CallRegistry,
    private val push: PushClient,
    private val outbox: EventOutbox,
    private val settings: AppSettings,
) {
    private val orchestrator = CallOrchestrator(registry, ApiDialerBackend(api, outbox), push)
    val state: StateFlow<RunUiState> = orchestrator.state
    private var job: Job? = null

    fun isRunActive(): Boolean = job?.isActive == true

    suspend fun start(campaignId: String, campaignName: String): ApiResult<Unit> {
        if (isRunActive()) return ApiResult.Err(-1, "already_running", "A campaign is already running on this phone.")
        val deviceId = settings.current().deviceId
            ?: return ApiResult.Err(-1, "no_device", "Verify this phone first.")
        return when (val r = apiCall { api.startRun(campaignId, RunStartRequest(deviceId)) }) {
            is ApiResult.Ok -> {
                orchestrator.reset(r.value.runId, campaignId, campaignName)
                push.start()
                ContextCompat.startForegroundService(context, Intent(context, RunService::class.java))
                ApiResult.Ok(Unit)
            }
            is ApiResult.Err -> r
            ApiResult.Empty -> ApiResult.Err(-1, "empty", "Couldn't start the run.")
        }
    }

    /** Called by [RunService] once it is in the foreground. */
    fun execute(scope: CoroutineScope, onFinished: () -> Unit) {
        if (isRunActive()) return
        val runId = state.value.runId ?: return onFinished()
        job = scope.launch {
            try {
                val prefs = settings.current()
                val deviceId = prefs.deviceId ?: return@launch
                val config = OrchestratorConfig(
                    gapBetweenLeadsMs = prefs.gapSeconds * 1_000L,
                    leadRingTimeoutMs = prefs.leadRingTimeoutSeconds * 1_000L,
                )
                val final = orchestrator.run(runId, deviceId, config)
                val serverStatus = when (final) {
                    RunStatus.PAUSED -> "paused"
                    RunStatus.STOPPED -> "stopped"
                    else -> null  // completed runs are closed server-side by /next
                }
                serverStatus?.let { apiCall { api.updateRun(runId, RunUpdateRequest(it)) } }
                outbox.flush()
            } finally {
                registry.clearExpectedNumbers()
                onFinished()
            }
        }
    }

    suspend fun resume(): ApiResult<Unit> {
        val s = state.value
        val runId = s.runId ?: return ApiResult.Err(-1, "no_run", "Nothing to resume.")
        return when (val r = apiCall { api.updateRun(runId, RunUpdateRequest("running")) }) {
            is ApiResult.Ok -> {
                orchestrator.reset(runId, s.campaignId.orEmpty(), s.campaignName.orEmpty())
                push.start()
                ContextCompat.startForegroundService(context, Intent(context, RunService::class.java))
                ApiResult.Ok(Unit)
            }
            is ApiResult.Err -> r
            ApiResult.Empty -> ApiResult.Err(-1, "empty", "Couldn't resume.")
        }
    }

    fun pause() = orchestrator.requestPause()

    fun stop() {
        orchestrator.requestStop()
        if (!isRunActive()) {
            state.value.runId?.let { runId ->
                CoroutineScope(Dispatchers.IO).launch { apiCall { api.updateRun(runId, RunUpdateRequest("stopped")) } }
            }
        }
    }

    fun command(command: UserCommand) = orchestrator.send(command)
    fun decideMerge(mergeAnyway: Boolean) = orchestrator.decideMerge(mergeAnyway)

    /** A real incoming call during a run: finish the current lead, then pause. */
    fun onIncomingCallDuringRun() {
        if (isRunActive()) orchestrator.requestPause()
    }
}
