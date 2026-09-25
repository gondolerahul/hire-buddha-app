package com.hirebuddha.dialer.run

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import com.hirebuddha.dialer.core.DialerLog
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
    private val logs: com.hirebuddha.dialer.data.logs.LogRepository,
    private val campaigns: com.hirebuddha.dialer.data.repo.CampaignRepository,
) {
    private val orchestrator = CallOrchestrator(registry, ApiDialerBackend(api, outbox), push)
    val state: StateFlow<RunUiState> = orchestrator.state
    private var job: Job? = null

    fun isRunActive(): Boolean = job?.isActive == true

    suspend fun start(campaignId: String, campaignName: String, agentName: String? = null): ApiResult<Unit> {
        if (isRunActive()) return ApiResult.Err(-1, "already_running", "A campaign is already running on this phone.")
        val deviceId = settings.current().deviceId
            ?: return ApiResult.Err(-1, "no_device", "Verify this phone first.")
        // Without ROLE_DIALER we cannot see call state, merge calls, or even run the
        // phoneCall foreground service — Android kills the app for trying (SecurityException).
        if (!com.hirebuddha.dialer.telecom.DialerRole.isHeld(context)) {
            DialerLog.w(TAG, "Run refused: not the default phone app")
            logs.flushSoon()
            return ApiResult.Err(-1, "not_default_dialer",
                "HireBuddha must be your phone app to place and merge calls. Open Settings in the app to fix this.")
        }
        return when (val r = apiCall { api.startRun(campaignId, RunStartRequest(deviceId)) }) {
            is ApiResult.Ok -> {
                orchestrator.reset(r.value.runId, campaignId, campaignName, agentName)
                logDeviceSnapshot()
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
                    askAfterEveryCall = prefs.askAfterEveryCall,
                    showTranscript = prefs.showTranscript,
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
                registry.hangUpExpected()  // never leave a campaign call ringing after the run
                registry.clearExpectedNumbers()
                logs.flush()  // ship this run's diagnostics without waiting for the periodic sweep
                onFinished()
            }
        }
    }

    suspend fun resume(): ApiResult<Unit> {
        val s = state.value
        val runId = s.runId ?: return ApiResult.Err(-1, "no_run", "Nothing to resume.")
        return when (val r = apiCall { api.updateRun(runId, RunUpdateRequest("running")) }) {
            is ApiResult.Ok -> {
                orchestrator.resume(runId)
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

    /**
     * Ends the current run and leaves it on the summary screen.
     *
     * A live run finishes its current lead and closes itself (see [execute]). A paused one
     * has no loop to do that, so the server is told here and the local state follows —
     * otherwise Today goes on offering to resume a run the server has already stopped.
     */
    suspend fun end(): ApiResult<Unit> {
        if (isRunActive()) {
            orchestrator.requestStop()
            return ApiResult.Ok(Unit)
        }
        val runId = state.value.runId ?: return ApiResult.Ok(Unit)
        return when (val r = apiCall { api.updateRun(runId, RunUpdateRequest("stopped")) }) {
            is ApiResult.Err -> if (r.httpStatus == 409 || r.httpStatus == 404) {
                orchestrator.markStopped(); ApiResult.Ok(Unit)
            } else r
            else -> { orchestrator.markStopped(); ApiResult.Ok(Unit) }
        }
    }

    /** Waits for the run loop to close the run server-side, so a new one isn't refused as `device_busy`. */
    suspend fun awaitIdle() { job?.join() }

    /**
     * Stops a run by id, whether or not this process is the one driving it.
     *
     * The live run lives in memory, so a crash, a force-stop or a reinstall leaves the
     * server holding a run the app can no longer reach — and `start_run` then refuses
     * every campaign on that device with `device_busy`. `GET /mobile/runs/active` finds
     * it again; this is how the rep clears it.
     */
    suspend fun stopRun(runId: String): ApiResult<Unit> {
        if (state.value.runId == runId) orchestrator.requestStop()
        return when (val r = apiCall { api.updateRun(runId, RunUpdateRequest("stopped")) }) {
            is ApiResult.Ok -> {
                if (state.value.runId == runId) orchestrator.clear()
                ApiResult.Ok(Unit)
            }
            // Already stopped server-side is the outcome we wanted.
            is ApiResult.Err -> if (r.httpStatus == 409 || r.httpStatus == 404) ApiResult.Ok(Unit) else r
            ApiResult.Empty -> ApiResult.Ok(Unit)
        }
    }

    /** Stop whatever is holding this device, then start the campaign the rep asked for. */
    suspend fun stopAndStart(
        blockingRunId: String,
        campaignId: String,
        campaignName: String,
        agentName: String? = null,
    ): ApiResult<Unit> {
        val stopped = stopRun(blockingRunId)
        if (stopped is ApiResult.Err) return stopped
        return start(campaignId, campaignName, agentName)
    }

    fun flushLogs() = logs.flushSoon()

    fun command(command: UserCommand) = orchestrator.send(command)
    fun decideMerge(mergeAnyway: Boolean) = orchestrator.decideMerge(mergeAnyway)

    /** The rep is still filling in the wrap-up: stop the countdown to the next lead. */
    fun holdGap() = orchestrator.holdGap()

    /** Dismiss the wrap-up and take the next lead now. */
    fun continueRun() = orchestrator.continueRun()

    /**
     * Records what the rep heard and moves on (docs 11 §3.1, screen 18).
     *
     * The run never waits on the network for this: the call is already over, and a rep
     * standing in a basement should not be held up by it. A failure surfaces as a
     * message and the run continues — the model's own disposition still applies.
     */
    suspend fun submitDisposition(
        campaignCallId: String,
        disposition: String,
        note: String? = null,
        callbackAt: java.time.Instant? = null,
    ): ApiResult<Unit> {
        val result = campaigns.setDisposition(campaignCallId, disposition, note, callbackAt)
        when (result) {
            is ApiResult.Ok -> DialerLog.i(TAG, "Rep disposition recorded", "disposition" to disposition)
            is ApiResult.Err -> DialerLog.w(TAG, "Rep disposition failed", "code" to result.code, "message" to result.message)
            ApiResult.Empty -> Unit
        }
        // Only what the server accepted is counted; a failed write leaves the model's call standing.
        if (result !is ApiResult.Err) orchestrator.recordDisposition(disposition)
        continueRun()
        return when (result) {
            is ApiResult.Err -> result
            else -> ApiResult.Ok(Unit)
        }
    }

    /**
     * Carrier and device facts recorded once per run: whether a phone can merge calls
     * depends on the network (VoLTE / Wi-Fi calling) and the OEM's telecom stack, so this
     * is the first thing to look at when merges fail for one rep but not another.
     */
    private fun logDeviceSnapshot() {
        val fields = mutableListOf<Pair<String, Any?>>(
            "manufacturer" to android.os.Build.MANUFACTURER,
            "model" to android.os.Build.MODEL,
            "android" to android.os.Build.VERSION.RELEASE,
            "sdk" to android.os.Build.VERSION.SDK_INT,
            "default_dialer" to com.hirebuddha.dialer.telecom.DialerRole.isHeld(context),
        )
        runCatching {
            val telephony = context.getSystemService(android.telephony.TelephonyManager::class.java)
            fields += "carrier" to telephony?.networkOperatorName
            fields += "sim_carrier" to telephony?.simOperatorName
            fields += "network_roaming" to telephony?.isNetworkRoaming
            @Suppress("MissingPermission")
            fields += "data_network" to runCatching { telephony?.dataNetworkType }.getOrNull()
        }
        runCatching {
            val sims = com.hirebuddha.dialer.telecom.SimAccounts.list(context)
            fields += "sim_count" to sims.size
            fields += "sim_selected" to kotlinx.coroutines.runBlocking { settings.current().phoneAccountLabel }
        }
        DialerLog.i("Device", "Run environment", *fields.toTypedArray())
    }

    private companion object {
        const val TAG = "RunController"
    }

    /** A real incoming call during a run: finish the current lead, then pause. */
    fun onIncomingCallDuringRun() {
        if (isRunActive()) orchestrator.requestPause()
    }
}
