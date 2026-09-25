package com.hirebuddha.dialer.ui.campaigns

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.data.api.ActiveRunDto
import com.hirebuddha.dialer.data.api.AnalyticsDto
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.CallItemDto
import com.hirebuddha.dialer.data.api.CampaignDto
import com.hirebuddha.dialer.data.api.MeDto
import com.hirebuddha.dialer.data.api.PreflightDto
import com.hirebuddha.dialer.data.repo.CampaignRepository
import com.hirebuddha.dialer.data.settings.AppSettings
import com.hirebuddha.dialer.run.RunController
import com.hirebuddha.dialer.run.RunStatus
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.ChipRow
import com.hirebuddha.dialer.ui.common.DispositionPill
import com.hirebuddha.dialer.data.api.AssigneeDto
import com.hirebuddha.dialer.ui.common.Hairline
import com.hirebuddha.dialer.ui.common.BrandDots
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.heightIn
import com.hirebuddha.dialer.data.api.RepDto
import com.hirebuddha.dialer.data.api.DailyCapDto
import com.hirebuddha.dialer.data.api.RepStatDto
import com.hirebuddha.dialer.ui.common.Avatar
import com.hirebuddha.dialer.ui.common.initialsOf
import com.hirebuddha.dialer.ui.common.EmptyState
import com.hirebuddha.dialer.ui.common.ErrorState
import com.hirebuddha.dialer.ui.common.Eyebrow
import com.hirebuddha.dialer.ui.common.FunnelBars
import com.hirebuddha.dialer.ui.common.GoldCard
import com.hirebuddha.dialer.ui.common.GoldPill
import com.hirebuddha.dialer.ui.common.HbButton
import com.hirebuddha.dialer.ui.common.HbButtonSize
import com.hirebuddha.dialer.ui.common.HbButtonStyle
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbChip
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.common.HbIconButton
import com.hirebuddha.dialer.ui.common.HbProgress
import com.hirebuddha.dialer.ui.common.HbTextField
import com.hirebuddha.dialer.ui.common.HbTopBar
import com.hirebuddha.dialer.ui.common.Loading
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.MonoText
import com.hirebuddha.dialer.ui.common.NegativePill
import com.hirebuddha.dialer.ui.common.Numeral
import com.hirebuddha.dialer.ui.common.Pill
import com.hirebuddha.dialer.ui.common.PositivePill
import com.hirebuddha.dialer.ui.common.SectionLabel
import com.hirebuddha.dialer.ui.common.StatTile
import com.hirebuddha.dialer.ui.common.biggestDropMessage
import com.hirebuddha.dialer.ui.common.humanize
import com.hirebuddha.dialer.ui.common.pct
import com.hirebuddha.dialer.ui.theme.BrandType
import com.hirebuddha.dialer.ui.theme.HbTheme
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.launch

// ══════════════════════════════════════════════════════════════════════ LIST

@HiltViewModel
class CampaignListViewModel @Inject constructor(
    private val repo: CampaignRepository,
    val run: RunController,
) : ViewModel() {
    var campaigns by mutableStateOf<List<CampaignDto>?>(null); private set
    var error by mutableStateOf<String?>(null); private set
    var refreshing by mutableStateOf(false); private set
    var query by mutableStateOf("")
    var searching by mutableStateOf(false)
    var filter by mutableStateOf<String?>(null)

    init { load() }

    fun load() = viewModelScope.launch {
        refreshing = true
        when (val r = repo.campaigns()) {
            is ApiResult.Ok -> { campaigns = r.value; error = null }
            is ApiResult.Err -> error = r.message
            ApiResult.Empty -> campaigns = emptyList()
        }
        refreshing = false
    }

    /** Filtering is client-side: a rep has tens of campaigns, not thousands. */
    fun visible(): List<CampaignDto> = campaigns.orEmpty()
        .filter { filter == null || it.status == filter }
        .filter { query.isBlank() || it.name.contains(query, ignoreCase = true) }
}

/** Screen 08. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CampaignListScreen(
    me: MeDto,
    onOpen: (String) -> Unit,
    onOpenRun: () -> Unit,
    modifier: Modifier = Modifier,
    vm: CampaignListViewModel = hiltViewModel(),
) {
    val c = HbTheme.colors
    val runState by vm.run.state.collectAsStateWithLifecycle()
    val all = vm.campaigns

    Column(modifier.fillMaxSize()) {
        HbTopBar(
            title = "Campaigns",
            actions = {
                HbIconButton(
                    if (vm.searching) R.drawable.ic_x else R.drawable.ic_search,
                    { vm.searching = !vm.searching; if (!vm.searching) vm.query = "" },
                    tint = if (vm.searching) c.accent else c.fgMuted,
                    contentDescription = "Search campaigns",
                )
            },
        )
        if (vm.searching) {
            HbTextField(
                vm.query, { vm.query = it },
                Modifier.padding(horizontal = HbTheme.dims.gutter),
                placeholder = "Search by name",
                leadingIcon = R.drawable.ic_search,
            )
            Spacer(Modifier.height(12.dp))
        }

        if (all != null && all.isNotEmpty()) {
            ChipRow(Modifier.padding(horizontal = HbTheme.dims.gutter)) {
                val counts = all.groupingBy { it.status }.eachCount()
                HbChip("All ${all.size}", vm.filter == null, onClick = { vm.filter = null })
                listOf("running", "pending", "completed").forEach { status ->
                    counts[status]?.let { n ->
                        HbChip("${humanize(status)} $n", vm.filter == status, onClick = { vm.filter = status })
                    }
                }
            }
            Spacer(Modifier.height(14.dp))
        }

        when {
            all == null && vm.error != null -> ErrorState(vm.error!!, vm::load)
            all == null -> Loading()
            all.isEmpty() -> EmptyState(
                title = if (me.isAdmin) "No campaigns yet" else "Nothing assigned yet",
                message = if (me.isAdmin) "Upload a lead list and your first Buddha can start calling."
                else "When an admin assigns you a campaign it will show up here.",
                icon = R.drawable.ic_list,
            )
            else -> PullToRefreshBox(
                isRefreshing = vm.refreshing,
                onRefresh = { vm.load() },
                modifier = Modifier.fillMaxSize(),
            ) {
                LazyColumn(
                    contentPadding = PaddingValues(HbTheme.dims.gutter, 0.dp, HbTheme.dims.gutter, 150.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    val live = runState.status == RunStatus.RUNNING || runState.status == RunStatus.PAUSED
                    if (live) item(key = "live") { LiveRunCard(runState, onOpenRun) }
                    val visible = vm.visible()
                    if (visible.isEmpty()) {
                        item(key = "none") {
                            Column(Modifier.fillMaxWidth().padding(top = 40.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                CardCaption("Nothing matches that.")
                            }
                        }
                    }
                    items(visible, key = { it.id }) { campaign ->
                        CampaignCard(campaign) { onOpen(campaign.id) }
                    }
                }
            }
        }
    }
}

/** The one live thing on the screen, and the only gold surface on it. */
@Composable
private fun LiveRunCard(runState: com.hirebuddha.dialer.run.RunUiState, onOpen: () -> Unit) {
    val c = HbTheme.colors
    val paused = runState.status == RunStatus.PAUSED
    GoldCard(Modifier.fillMaxWidth(), padding = 16.dp, onClick = onOpen) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            GoldPill(if (paused) "Paused" else "Live now", dot = true)
            Spacer(Modifier.weight(1f))
            runState.lead?.let { MonoText("lead ${runState.callsMade + 1} of ${runState.callsMade + 1 + it.remaining}") }
        }
        Spacer(Modifier.height(12.dp))
        Text(
            runState.campaignName ?: "Campaign",
            style = MaterialTheme.typography.titleLarge,
            color = c.fg,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Spacer(Modifier.height(4.dp))
        CardCaption(
            if (paused) "Paused — your place is held" else runState.lastOutcome ?: "Working through the list",
        )
        Spacer(Modifier.height(14.dp))
        HbButton(
            if (paused) "Resume run" else "Open live run",
            onOpen,
            Modifier.fillMaxWidth(),
            HbButtonStyle.Primary,
            HbButtonSize.Small,
            icon = R.drawable.ic_phone,
        )
    }
}

@Composable
private fun CampaignCard(campaign: CampaignDto, onClick: () -> Unit) {
    val c = HbTheme.colors
    val blocked = campaign.did == null && campaign.status != "completed"
    HbCard(Modifier.fillMaxWidth(), onClick = onClick) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                campaign.name,
                Modifier.weight(1f),
                style = MaterialTheme.typography.titleLarge,
                color = c.fg,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.size(8.dp))
            when {
                blocked -> NegativePill("Needs attention")
                campaign.status == "completed" -> PositivePill("Done")
                campaign.status == "running" -> GoldPill("Running", dot = true)
                else -> Pill(humanize(campaign.status))
            }
        }
        Spacer(Modifier.height(4.dp))
        // Which Buddha is calling, and on what number: the first thing a rep checks.
        CardCaption(
            listOfNotNull(
                campaign.agentName ?: "AI agent",
                campaign.did,
            ).joinToString(" · "),
        )
        if (blocked) {
            Spacer(Modifier.height(6.dp))
            MicroText("The agent has no phone number assigned", color = c.negative)
        }
        Spacer(Modifier.height(14.dp))
        val progress = if (campaign.totalContacts > 0) campaign.done.toFloat() / campaign.totalContacts else 0f
        HbProgress(
            progress,
            brush = if (campaign.status == "completed") androidx.compose.ui.graphics.SolidColor(c.positive) else null,
        )
        Spacer(Modifier.height(8.dp))
        Row(Modifier.fillMaxWidth()) {
            MonoText("${campaign.done} of ${campaign.totalContacts} called", Modifier.weight(1f))
            MonoText("${campaign.interested} interested", color = if (campaign.interested > 0) c.positive else c.fgSubtle)
        }
    }
}

// ════════════════════════════════════════════════════════════════════ DETAIL

@HiltViewModel
class CampaignDetailViewModel @Inject constructor(
    private val repo: CampaignRepository,
    private val settings: AppSettings,
    val run: RunController,
) : ViewModel() {
    var campaign by mutableStateOf<CampaignDto?>(null); private set
    var analytics by mutableStateOf<AnalyticsDto?>(null); private set
    var calls by mutableStateOf<List<CallItemDto>>(emptyList()); private set
    /** Rows matching the current filter server-side; more than [calls] means another page. */
    var callsTotal by mutableIntStateOf(0); private set
    var loadingMore by mutableStateOf(false); private set
    var filter by mutableStateOf<String?>(null); private set
    var error by mutableStateOf<String?>(null); private set
    var starting by mutableStateOf(false); private set
    var startError by mutableStateOf<String?>(null); private set
    var preflight by mutableStateOf<PreflightDto?>(null); private set
    var showPreflight by mutableStateOf(false)

    /** A run the server still holds open — for this campaign or any other. */
    var openRun by mutableStateOf<ActiveRunDto?>(null); private set
    /** Set when starting was refused because another run owns the device. */
    var blockedBy by mutableStateOf<ActiveRunDto?>(null)
    var stopping by mutableStateOf(false); private set

    /** Admin only: everyone who could be put on this list, loaded when Manage opens. */
    var companyReps by mutableStateOf<List<RepDto>?>(null); private set
    var showManage by mutableStateOf(false)
    var savingAssignees by mutableStateOf(false); private set
    var assigneesError by mutableStateOf<String?>(null); private set

    fun openManage() = viewModelScope.launch {
        showManage = true
        assigneesError = null
        if (companyReps == null) {
            when (val r = repo.reps()) {
                is ApiResult.Ok -> companyReps = r.value
                is ApiResult.Err -> assigneesError = r.message
                ApiResult.Empty -> companyReps = emptyList()
            }
        }
    }

    fun saveAssignees(userIds: Set<String>) = viewModelScope.launch {
        val current = campaign ?: return@launch
        savingAssignees = true
        assigneesError = null
        when (val r = repo.setAssignees(current.id, userIds.toList())) {
            is ApiResult.Ok -> { campaign = current.copy(assignees = r.value); showManage = false }
            is ApiResult.Err -> assigneesError = r.message
            ApiResult.Empty -> showManage = false
        }
        savingAssignees = false
    }

    private var initialFilterApplied = false

    fun load(id: String, initialFilter: String? = null) = viewModelScope.launch {
        // Arriving from "Review the interested" on the run summary: open on that filter once,
        // then leave the chips to the rep.
        if (!initialFilterApplied) {
            initialFilterApplied = true
            initialFilter?.let { filter = it }
        }
        when (val r = repo.campaign(id)) {
            is ApiResult.Ok -> campaign = r.value
            is ApiResult.Err -> { error = r.message; return@launch }
            ApiResult.Empty -> Unit
        }
        (repo.analytics(id) as? ApiResult.Ok)?.let { analytics = it.value }
        refreshOpenRun()
        loadCalls(id)
        // Read up front, not only when Start is tapped: the remaining cap belongs next to
        // the button, where the rep decides whether today is the day for this list.
        preflight = repo.preflight(campaignId = id, deviceId = settings.current().deviceId)
    }

    /**
     * The live run lives in memory, so a crash or a reinstall leaves one the app cannot
     * reach — and every campaign then refuses to start with `device_busy`. Asking the
     * server is the only way to find it again.
     */
    fun refreshOpenRun() = viewModelScope.launch {
        openRun = repo.activeRuns().firstOrNull()
    }

    fun stopOpenRun(runId: String) = viewModelScope.launch {
        stopping = true
        when (val r = run.stopRun(runId)) {
            is ApiResult.Err -> startError = r.message
            else -> { startError = null; blockedBy = null }
        }
        stopping = false
        openRun = repo.activeRuns().firstOrNull()
        campaign?.id?.let { load(it) }
    }

    fun stopAndStart(blockingRunId: String, onStarted: () -> Unit) = viewModelScope.launch {
        val campaign = campaign ?: return@launch
        stopping = true
        startError = null
        when (val r = run.stopAndStart(blockingRunId, campaign.id, campaign.name)) {
            is ApiResult.Ok -> { blockedBy = null; showPreflight = false; onStarted() }
            is ApiResult.Err -> startError = r.message
            ApiResult.Empty -> Unit
        }
        stopping = false
        openRun = repo.activeRuns().firstOrNull()
    }

    fun setFilter(id: String, value: String?) { filter = value; loadCalls(id) }

    private fun loadCalls(id: String) = viewModelScope.launch {
        (fetchCalls(id, offset = 0) as? ApiResult.Ok)?.let {
            calls = it.value.items
            callsTotal = it.value.total
        }
    }

    fun loadMore(id: String) = viewModelScope.launch {
        if (loadingMore) return@launch
        loadingMore = true
        (fetchCalls(id, offset = calls.size) as? ApiResult.Ok)?.let { page ->
            val seen = calls.mapTo(HashSet()) { it.campaignCallId }
            calls = calls + page.value.items.filter { it.campaignCallId !in seen }
            callsTotal = page.value.total
        }
        loadingMore = false
    }

    private suspend fun fetchCalls(id: String, offset: Int) = when (filter) {
        "interested", "not_interested", "callback" -> repo.calls(id, filter, null, offset)
        "failed" -> repo.calls(id, null, "failed", offset)
        // The leads nobody has reached yet are most of a fresh list; a rep sees them too.
        "pending" -> repo.calls(id, null, "pending", offset, includePending = true)
        else -> repo.calls(id, null, null, offset, includePending = true)
    }

    /** Pre-flight first (screen 13): every blocker here used to surface as a failed call. */
    fun openPreflight() = viewModelScope.launch {
        val id = campaign?.id ?: return@launch
        showPreflight = true
        preflight = repo.preflight(campaignId = id, deviceId = settings.current().deviceId)
    }

    fun start(onStarted: () -> Unit) = viewModelScope.launch {
        val campaign = campaign ?: return@launch
        starting = true
        startError = null
        when (val r = run.start(campaign.id, campaign.name)) {
            is ApiResult.Ok -> { showPreflight = false; onStarted() }
            is ApiResult.Err -> {
                startError = r.message
                // The server names the run in the way; offer to clear it rather than
                // leaving the rep with "stop it first" and nothing to stop it with.
                val blockingId = r.field("blocking_run_id")
                blockedBy = if (r.code == "device_busy" && blockingId != null) {
                    ActiveRunDto(
                        runId = blockingId,
                        campaignId = r.field("blocking_campaign_id").orEmpty(),
                        campaignName = r.field("blocking_campaign_name"),
                        status = r.field("blocking_run_status") ?: "running",
                    )
                } else {
                    openRun?.takeIf { r.code == "device_busy" }
                }
            }
            ApiResult.Empty -> Unit
        }
        starting = false
    }
}

/** Screen 09. */
@Composable
fun CampaignDetailScreen(
    campaignId: String,
    isAdmin: Boolean,
    meId: String,
    initialFilter: String? = null,
    onBack: () -> Unit,
    onOpenRun: () -> Unit,
    onOpenCall: (sessionId: String?, attemptId: String?, title: String?) -> Unit,
    vm: CampaignDetailViewModel = hiltViewModel(),
) {
    val c = HbTheme.colors
    LaunchedEffect(campaignId) { vm.load(campaignId, initialFilter) }
    val runState by vm.run.state.collectAsStateWithLifecycle()
    val campaign = vm.campaign

    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            HbTopBar(
                title = campaign?.name ?: "Campaign",
                navigationIcon = R.drawable.ic_back,
                onNavigate = onBack,
            )
            when {
                vm.error != null -> ErrorState(vm.error!!, onRetry = { vm.load(campaignId) })
                campaign == null -> Loading()
                else -> LazyColumn(
                    contentPadding = PaddingValues(HbTheme.dims.gutter, 0.dp, HbTheme.dims.gutter, 40.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    // A run the server still holds but this process is not driving:
                    // after a crash or a reinstall it is otherwise unreachable, and it
                    // blocks every campaign on this device.
                    vm.openRun?.takeIf { it.runId != runState.runId }?.let { orphan ->
                        item(key = "orphan") { OrphanRunCard(orphan, campaign.id, vm) }
                    }
                    item(key = "hero") {
                        val thisRunLive = runState.campaignId == campaign.id &&
                            runState.status in setOf(RunStatus.RUNNING, RunStatus.PAUSED)
                        StartCard(campaign, thisRunLive, vm.preflight?.dailyCap, vm, onOpenRun)
                    }
                    item(key = "tiles") {
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            StatTile("Called", "${campaign.done}/${campaign.totalContacts}", Modifier.weight(1f))
                            StatTile(
                                "Interested", "${campaign.interested}", Modifier.weight(1f),
                                valueColor = if (campaign.interested > 0) c.positive else c.fg,
                            )
                        }
                    }
                    vm.analytics?.let { a ->
                        item(key = "rates") {
                            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                StatTile("Answer rate", pct(a.rates.answer), Modifier.weight(1f))
                                StatTile("Merge success", pct(a.rates.mergeSuccess), Modifier.weight(1f))
                            }
                        }
                        item(key = "funnel") {
                            HbCard(Modifier.fillMaxWidth()) {
                                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                    Text("Funnel", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, color = c.fg)
                                    MicroText("all time")
                                }
                                Spacer(Modifier.height(12.dp))
                                FunnelBars(a.funnel)
                                biggestDropMessage(a.funnel)?.let {
                                    Spacer(Modifier.height(14.dp))
                                    InsightRow(it)
                                }
                            }
                        }
                    }
                    // Who is working this list. Everyone sees the names; call counts come
                    // from analytics, which only tells a rep about their own calls.
                    if (campaign.assignees.isNotEmpty() || !vm.analytics?.byRep.isNullOrEmpty()) {
                        item(key = "reps") {
                            RepsCard(
                                campaign.assignees, vm.analytics?.byRep.orEmpty(), meId,
                                onManage = if (isAdmin) ({ vm.openManage() }) else null,
                            )
                        }
                    }
                    item(key = "leads-header") {
                        Row(Modifier.fillMaxWidth().padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text("Leads", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, color = c.fg)
                            MonoText("${campaign.pending} pending")
                        }
                    }
                    item(key = "leads-filter") {
                        ChipRow {
                            listOf(
                                null to "All", "pending" to "Pending", "interested" to "Interested",
                                "callback" to "Callback", "failed" to "Failed",
                            ).forEach { (value, label) ->
                                HbChip(label, vm.filter == value, onClick = { vm.setFilter(campaignId, value) })
                            }
                        }
                    }
                    items(vm.calls, key = { it.campaignCallId }) { call ->
                        CallRow(call) { onOpenCall(call.voiceSessionId, call.attemptId, call.contactName ?: call.phoneMasked) }
                    }
                    if (vm.calls.size < vm.callsTotal) {
                        item(key = "more") {
                            HbButton(
                                text = if (vm.loadingMore) "Loading" else "Show more — ${vm.callsTotal - vm.calls.size} left",
                                onClick = { vm.loadMore(campaignId) },
                                modifier = Modifier.fillMaxWidth(),
                                style = HbButtonStyle.Ghost,
                                size = HbButtonSize.Small,
                                enabled = !vm.loadingMore,
                            )
                        }
                    }
                    if (vm.calls.isEmpty()) {
                        item(key = "no-calls") {
                            Column(Modifier.fillMaxWidth().padding(vertical = 26.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                                CardCaption(if (vm.filter == "pending") "Nobody is waiting to be called." else "No leads match that filter yet.")
                            }
                        }
                    }
                }
            }
        }
        vm.blockedBy?.let { blocking ->
            SwitchCampaignSheet(
                blocking = blocking,
                target = campaign?.name ?: "this campaign",
                busy = vm.stopping,
                onSwitch = { vm.stopAndStart(blocking.runId, onOpenRun) },
                onDismiss = { vm.blockedBy = null },
            )
        }
        if (vm.showManage && campaign != null) {
            ManageRepsSheet(
                reps = vm.companyReps,
                assigned = campaign.assignees.mapTo(HashSet()) { it.userId },
                saving = vm.savingAssignees,
                error = vm.assigneesError,
                onSave = vm::saveAssignees,
                onDismiss = { vm.showManage = false },
            )
        }
        if (vm.showPreflight && vm.blockedBy == null) {
            PreflightSheet(
                preflight = vm.preflight,
                starting = vm.starting,
                error = vm.startError,
                onStart = { vm.start(onOpenRun) },
                onDismiss = { vm.showPreflight = false },
            )
        }
    }
}

@Composable
private fun StartCard(
    campaign: CampaignDto,
    thisRunLive: Boolean,
    cap: DailyCapDto?,
    vm: CampaignDetailViewModel,
    onOpenRun: () -> Unit,
) {
    val c = HbTheme.colors
    GoldCard(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(
                Modifier.size(42.dp)
                    .clip(RoundedCornerShape(14.dp))
                    .background(c.accentQuiet),
                contentAlignment = Alignment.Center,
            ) { HbIcon(R.drawable.ic_ai, size = 20.dp, tint = c.accent) }
            Column(Modifier.weight(1f)) {
                Text(
                    campaign.agentName ?: "AI agent",
                    style = MaterialTheme.typography.titleMedium,
                    color = c.fg,
                )
                MonoText(listOfNotNull(campaign.did).joinToString(" · ").ifBlank { "no number assigned" })
            }
            if (campaign.did != null) PositivePill("Ready") else NegativePill("No number")
        }
        Spacer(Modifier.height(16.dp))
        when {
            thisRunLive -> HbButton(
                "Open live run", onOpenRun, Modifier.fillMaxWidth(),
                HbButtonStyle.Hero, HbButtonSize.Large, icon = R.drawable.ic_phone,
            )
            campaign.status == "completed" || campaign.pending == 0 -> HbButton(
                "No leads left", {}, Modifier.fillMaxWidth(),
                HbButtonStyle.Secondary, HbButtonSize.Large, enabled = false,
            )
            else -> {
                HbButton(
                    "Start calling — ${campaign.pending} leads",
                    { vm.openPreflight() },
                    Modifier.fillMaxWidth(),
                    HbButtonStyle.Hero,
                    HbButtonSize.Large,
                    icon = R.drawable.ic_phone,
                    enabled = campaign.did != null,
                )
                Spacer(Modifier.height(10.dp))
                Row(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    HbIcon(R.drawable.ic_clock, size = 13.dp, tint = c.fgSubtle)
                    Spacer(Modifier.size(6.dp))
                    // ~2 min per lead including ring time, gap and wrap-up.
                    MicroText(
                        listOfNotNull(
                            "About ${estimateHours(campaign.pending)} at your usual pace",
                            capNote(cap),
                        ).joinToString(" · "),
                    )
                }
            }
        }
        vm.startError?.let {
            Spacer(Modifier.height(8.dp))
            MicroText(it, color = c.negative)
        }
    }
}

/** The daily cap is what actually ends a rep's day, so it sits next to the estimate. */
private fun capNote(cap: DailyCapDto?): String? {
    val limit = cap?.limit ?: return null
    val remaining = cap.remaining ?: (limit - cap.used)
    return if (remaining <= 0) "today's cap is used up" else "cap allows $remaining more today"
}

private fun estimateHours(pending: Int): String {
    val minutes = pending * 2
    return when {
        minutes < 60 -> "$minutes min"
        else -> "${minutes / 60} h"
    }
}

@Composable
private fun InsightRow(text: String) {
    val c = HbTheme.colors
    Row(
        Modifier.fillMaxWidth()
            .clip(RoundedCornerShape(HbTheme.dims.rSm))
            .background(c.surface2)
            .padding(12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        HbIcon(R.drawable.ic_info, size = 16.dp, tint = c.gold300)
        CardCaption(text, Modifier.weight(1f))
    }
}

@Composable
private fun CallRow(call: CallItemDto, onClick: () -> Unit) {
    val c = HbTheme.colors
    val clickable = call.voiceSessionId != null || call.attemptId != null
    Row(
        Modifier.fillMaxWidth()
            .then(if (clickable) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                call.contactName ?: call.phoneMasked,
                style = MaterialTheme.typography.bodyLarge,
                color = c.fg,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            MonoText(
                listOfNotNull(
                    call.phoneMasked.takeIf { call.contactName != null },
                    call.repName,
                    call.conversationSeconds?.let { "${it}s talk" },
                ).joinToString(" · "),
            )
        }
        Spacer(Modifier.size(8.dp))
        when {
            call.disposition == null && call.callStatus == "pending" -> Pill("Pending", color = c.fgSubtle)
            call.disposition == null && call.callStatus == "leased" -> GoldPill("Being called", dot = true)
            else -> DispositionPill(call.disposition ?: call.leadFailureCause ?: call.callStatus)
        }
    }
}


/**
 * A run the server still considers open that this process is not driving.
 *
 * The app keeps the live run in memory, so a crash, a force-stop or a reinstall (which
 * mints a fresh device row) strands it: the campaign shows "running", no calls happen,
 * and `start_run` refuses every campaign on the device. This is the way out.
 */
@Composable
private fun OrphanRunCard(orphan: ActiveRunDto, thisCampaignId: String, vm: CampaignDetailViewModel) {
    val c = HbTheme.colors
    val sameCampaign = orphan.campaignId == thisCampaignId
    HbCard(Modifier.fillMaxWidth(), border = c.borderGold) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(
                Modifier.size(38.dp).clip(RoundedCornerShape(12.dp)).background(c.accentQuiet),
                contentAlignment = Alignment.Center,
            ) { HbIcon(R.drawable.ic_alert, size = 18.dp, tint = c.accent) }
            Column(Modifier.weight(1f)) {
                Text(
                    if (sameCampaign) "This campaign is still marked running"
                    else "Still on \u201c${orphan.campaignName ?: "another campaign"}\u201d",
                    style = MaterialTheme.typography.titleSmall,
                    color = c.fg,
                )
                MicroText(
                    "No calls are being placed. Stop it to free this phone.",
                    color = c.fgMuted,
                )
            }
        }
        Spacer(Modifier.height(14.dp))
        HbButton(
            text = if (vm.stopping) "Stopping" else "Stop that run",
            onClick = { vm.stopOpenRun(orphan.runId) },
            modifier = Modifier.fillMaxWidth(),
            style = HbButtonStyle.DangerQuiet,
            size = HbButtonSize.Small,
            icon = R.drawable.ic_stop,
            enabled = !vm.stopping,
        )
    }
}

/** `device_busy`, turned into a choice. */
@Composable
private fun SwitchCampaignSheet(
    blocking: ActiveRunDto,
    target: String,
    busy: Boolean,
    onSwitch: () -> Unit,
    onDismiss: () -> Unit,
) {
    val c = HbTheme.colors
    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().background(Color(0xA8000000)).clickable(onClick = onDismiss))
        Column(
            Modifier.align(Alignment.BottomCenter).fillMaxWidth()
                .clip(RoundedCornerShape(topStart = HbTheme.dims.r2Xl, topEnd = HbTheme.dims.r2Xl))
                .background(c.surface)
                .border(1.dp, c.borderStrong, RoundedCornerShape(topStart = HbTheme.dims.r2Xl, topEnd = HbTheme.dims.r2Xl))
                .padding(horizontal = HbTheme.dims.gutter)
                .navigationBarsPadding()
                .padding(top = 10.dp, bottom = 16.dp),
        ) {
            Box(
                Modifier.align(Alignment.CenterHorizontally).size(width = 38.dp, height = 4.dp)
                    .clip(RoundedCornerShape(2.dp)).background(c.borderStrong)
            )
            Spacer(Modifier.height(18.dp))
            Eyebrow("One campaign at a time")
            Spacer(Modifier.height(8.dp))
            Text(
                "This phone is still on \u201c${blocking.campaignName ?: "another campaign"}\u201d",
                style = MaterialTheme.typography.headlineSmall,
                color = c.fg,
            )
            Spacer(Modifier.height(8.dp))
            CardCaption(
                "A phone can only run one campaign at a time, so leads are never called twice. " +
                    "Stopping it returns any held lead to the queue \u2014 nothing is lost."
            )
            Spacer(Modifier.height(18.dp))
            HbButton(
                text = if (busy) "Switching" else "Stop it and start \u201c$target\u201d",
                onClick = onSwitch,
                modifier = Modifier.fillMaxWidth(),
                style = HbButtonStyle.Primary,
                size = HbButtonSize.Large,
                enabled = !busy,
            )
            HbButton("Keep the current one", onDismiss, Modifier.fillMaxWidth(), HbButtonStyle.Ghost, HbButtonSize.Small)
        }
    }
}

/**
 * The reps on this list (screen 09). Assignment is the list everyone can see; the call
 * counts come from analytics, which is scoped to the viewer for a rep — so a rep sees
 * their own numbers and their colleagues' names, and an admin sees everyone's numbers.
 */
@Composable
private fun RepsCard(
    assignees: List<AssigneeDto>,
    stats: List<RepStatDto>,
    meId: String,
    onManage: (() -> Unit)?,
) {
    val c = HbTheme.colors
    val statsById = stats.associateBy { it.userId }
    // Someone who called this list but has since been unassigned still belongs in its history.
    val people = assignees.map { it.userId to it.name } +
        stats.filter { s -> assignees.none { it.userId == s.userId } }.map { it.userId to it.name }
    HbCard(Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("Reps", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, color = c.fg)
            onManage?.let {
                Text(
                    "Manage",
                    Modifier.clickable(onClick = it).padding(vertical = 6.dp, horizontal = 4.dp),
                    style = MaterialTheme.typography.labelMedium,
                    color = c.accent,
                )
            }
        }
        Spacer(Modifier.height(4.dp))
        people.forEach { (userId, name) ->
            val stat = statsById[userId]
            val you = userId == meId
            val assigned = assignees.any { it.userId == userId }
            Row(
                Modifier.fillMaxWidth().padding(vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Avatar(initialsOf(name), size = 34.dp, gold = you)
                Column(Modifier.weight(1f)) {
                    Text(name, style = MaterialTheme.typography.titleSmall, color = c.fg, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    MonoText(
                        listOfNotNull(
                            "you".takeIf { you },
                            stat?.let { "${it.attempts} calls · ${pct(it.answerRate)} answered" }
                                ?: "0 calls".takeIf { you },
                        ).joinToString(" · ").ifBlank { "rep" },
                    )
                }
                when {
                    stat != null && stat.interested > 0 -> PositivePill("${stat.interested}", dot = false)
                    assigned -> Pill("Assigned", color = c.fgSubtle)
                    else -> Pill("Unassigned", color = c.fgFaint)
                }
            }
        }
    }
}

/**
 * Who works this list (admins). Leads are handed out one at a time, so adding a rep
 * mid-campaign just adds another pair of hands; taking one off stops them starting a
 * new run on it, but a run already going finishes on its own.
 */
@Composable
private fun ManageRepsSheet(
    reps: List<RepDto>?,
    assigned: Set<String>,
    saving: Boolean,
    error: String?,
    onSave: (Set<String>) -> Unit,
    onDismiss: () -> Unit,
) {
    val c = HbTheme.colors
    var selected by remember(assigned) { mutableStateOf(assigned) }
    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().background(Color(0xA8000000)).clickable(onClick = onDismiss))
        Column(
            Modifier.align(Alignment.BottomCenter).fillMaxWidth()
                .clip(RoundedCornerShape(topStart = HbTheme.dims.r2Xl, topEnd = HbTheme.dims.r2Xl))
                .background(c.surface)
                .border(1.dp, c.borderStrong, RoundedCornerShape(topStart = HbTheme.dims.r2Xl, topEnd = HbTheme.dims.r2Xl))
                .padding(horizontal = HbTheme.dims.gutter)
                .navigationBarsPadding()
                .padding(top = 10.dp, bottom = 16.dp),
        ) {
            Box(
                Modifier.align(Alignment.CenterHorizontally).size(width = 38.dp, height = 4.dp)
                    .clip(RoundedCornerShape(2.dp)).background(c.borderStrong)
            )
            Spacer(Modifier.height(18.dp))
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("Assign reps", Modifier.weight(1f), style = MaterialTheme.typography.headlineSmall, color = c.fg)
                reps?.let { MicroText("${selected.size} of ${it.size} selected") }
            }
            Spacer(Modifier.height(6.dp))
            CardCaption("Leads are handed out one at a time, so two reps never call the same person.")
            Spacer(Modifier.height(14.dp))
            if (reps == null) {
                Row(Modifier.fillMaxWidth().padding(vertical = 24.dp), horizontalArrangement = Arrangement.Center) {
                    if (error == null) BrandDots()
                }
            } else {
                HbCard(Modifier.fillMaxWidth().heightIn(max = 360.dp), padding = 4.dp) {
                    Column(Modifier.verticalScroll(rememberScrollState())) {
                        reps.forEachIndexed { i, rep ->
                            if (i > 0) Hairline()
                            val checked = rep.userId in selected
                            Row(
                                Modifier.fillMaxWidth()
                                    .clickable { selected = if (checked) selected - rep.userId else selected + rep.userId }
                                    .padding(horizontal = 10.dp, vertical = 10.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(12.dp),
                            ) {
                                Box(
                                    Modifier.size(20.dp).clip(RoundedCornerShape(6.dp))
                                        .background(if (checked) c.accent else Color.Transparent)
                                        .border(1.75.dp, if (checked) c.accent else c.borderStrong, RoundedCornerShape(6.dp)),
                                    contentAlignment = Alignment.Center,
                                ) { if (checked) HbIcon(R.drawable.ic_check, size = 13.dp, tint = c.onAccent) }
                                Avatar(initialsOf(rep.name), size = 32.dp)
                                Column(Modifier.weight(1f)) {
                                    Text(rep.name, style = MaterialTheme.typography.bodyLarge, color = c.fg, maxLines = 1)
                                    MicroText(humanize(rep.role))
                                }
                            }
                        }
                    }
                }
            }
            error?.let {
                Spacer(Modifier.height(10.dp))
                MicroText(it, color = c.negative)
            }
            Spacer(Modifier.height(16.dp))
            HbButton(
                text = when {
                    saving -> "Saving"
                    selected.isEmpty() -> "Pick at least one rep"
                    else -> "Save"
                },
                onClick = { onSave(selected) },
                modifier = Modifier.fillMaxWidth(),
                style = HbButtonStyle.Primary,
                size = HbButtonSize.Large,
                enabled = !saving && reps != null && selected.isNotEmpty() && selected != assigned,
            )
            HbButton("Cancel", onDismiss, Modifier.fillMaxWidth(), HbButtonStyle.Ghost, HbButtonSize.Small)
        }
    }
}
