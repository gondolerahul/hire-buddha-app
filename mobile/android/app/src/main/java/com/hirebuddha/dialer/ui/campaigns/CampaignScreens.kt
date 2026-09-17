package com.hirebuddha.dialer.ui.campaigns

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.hirebuddha.dialer.data.api.AnalyticsDto
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.CallItemDto
import com.hirebuddha.dialer.data.api.CampaignDto
import com.hirebuddha.dialer.data.api.MeDto
import com.hirebuddha.dialer.data.repo.CampaignRepository
import com.hirebuddha.dialer.run.RunController
import com.hirebuddha.dialer.run.RunStatus
import com.hirebuddha.dialer.ui.common.ErrorState
import com.hirebuddha.dialer.ui.common.FunnelBars
import com.hirebuddha.dialer.ui.common.Loading
import com.hirebuddha.dialer.ui.common.Pill
import com.hirebuddha.dialer.ui.common.StatTile
import com.hirebuddha.dialer.ui.common.humanize
import com.hirebuddha.dialer.ui.common.pct
import com.hirebuddha.dialer.ui.theme.StatusColors
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.launch

// ── List ─────────────────────────────────────────────────────────────────

@HiltViewModel
class CampaignListViewModel @Inject constructor(
    private val repo: CampaignRepository,
    val run: RunController,
) : ViewModel() {
    var campaigns by mutableStateOf<List<CampaignDto>?>(null); private set
    var error by mutableStateOf<String?>(null); private set
    var refreshing by mutableStateOf(false); private set

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
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CampaignListScreen(me: MeDto, onOpen: (String) -> Unit, onOpenRun: () -> Unit, modifier: Modifier = Modifier, vm: CampaignListViewModel = hiltViewModel()) {
    val runState by vm.run.state.collectAsStateWithLifecycle()
    val list = vm.campaigns
    Column(modifier.fillMaxSize()) {
        Text("Campaigns", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(start = 16.dp, top = 20.dp, bottom = 8.dp))
        if (runState.status == RunStatus.RUNNING || runState.status == RunStatus.PAUSED) {
            Card(Modifier.fillMaxWidth().padding(horizontal = 16.dp).clickable(onClick = onOpenRun)) {
                Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Filled.PlayArrow, null, tint = StatusColors.positive)
                    Spacer(Modifier.width(8.dp))
                    Column(Modifier.weight(1f)) {
                        Text(runState.campaignName ?: "Campaign", style = MaterialTheme.typography.titleMedium)
                        Text(if (runState.status == RunStatus.PAUSED) "Paused — tap to resume" else "Running — tap to open", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
        when {
            list == null && vm.error != null -> ErrorState(vm.error!!, vm::load)
            list == null -> Loading()
            else -> PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = { vm.load() }, modifier = Modifier.fillMaxSize()) {
                if (list.isEmpty()) {
                    ErrorState(if (me.isAdmin) "No mobile campaigns yet. Create one to get started." else "No campaigns are assigned to you yet.")
                } else {
                    LazyColumn(contentPadding = PaddingValues(16.dp, 8.dp, 16.dp, 96.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        items(list, key = { it.id }) { c -> CampaignCard(c) { onOpen(c.id) } }
                    }
                }
            }
        }
    }
}

@Composable
private fun CampaignCard(c: CampaignDto, onClick: () -> Unit) {
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(c.name, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                Pill(humanize(c.status), statusColor(c.status))
            }
            Text(c.agentName ?: "AI agent", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            val progress = if (c.totalContacts > 0) c.done.toFloat() / c.totalContacts else 0f
            LinearProgressIndicator(progress = { progress }, modifier = Modifier.fillMaxWidth())
            Text("${c.done} of ${c.totalContacts} called · ${c.interested} interested", style = MaterialTheme.typography.bodySmall)
        }
    }
}

fun statusColor(status: String) = when (status) {
    "running" -> StatusColors.positive
    "paused" -> StatusColors.warning
    "failed" -> StatusColors.negative
    else -> StatusColors.neutral
}

// ── Detail ───────────────────────────────────────────────────────────────

@HiltViewModel
class CampaignDetailViewModel @Inject constructor(
    private val repo: CampaignRepository,
    val run: RunController,
) : ViewModel() {
    var campaign by mutableStateOf<CampaignDto?>(null); private set
    var analytics by mutableStateOf<AnalyticsDto?>(null); private set
    var calls by mutableStateOf<List<CallItemDto>>(emptyList()); private set
    var filter by mutableStateOf<String?>(null); private set
    var error by mutableStateOf<String?>(null); private set
    var starting by mutableStateOf(false); private set
    var startError by mutableStateOf<String?>(null); private set

    fun load(id: String) = viewModelScope.launch {
        when (val r = repo.campaign(id)) {
            is ApiResult.Ok -> campaign = r.value
            is ApiResult.Err -> { error = r.message; return@launch }
            ApiResult.Empty -> Unit
        }
        (repo.analytics(id) as? ApiResult.Ok)?.let { analytics = it.value }
        loadCalls(id)
    }

    fun setFilter(id: String, value: String?) { filter = value; loadCalls(id) }

    private fun loadCalls(id: String) = viewModelScope.launch {
        val (disposition, status) = when (filter) {
            "interested", "not_interested" -> filter to null
            "failed" -> null to "failed"
            else -> null to null
        }
        (repo.calls(id, disposition, status, 0) as? ApiResult.Ok)?.let { calls = it.value.items }
    }

    fun start(onStarted: () -> Unit) = viewModelScope.launch {
        val c = campaign ?: return@launch
        starting = true
        startError = null
        when (val r = run.start(c.id, c.name)) {
            is ApiResult.Ok -> onStarted()
            is ApiResult.Err -> startError = r.message
            ApiResult.Empty -> Unit
        }
        starting = false
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CampaignDetailScreen(
    campaignId: String,
    isAdmin: Boolean,
    onBack: () -> Unit,
    onOpenRun: () -> Unit,
    onOpenCall: (sessionId: String?, attemptId: String?, title: String?) -> Unit,
    vm: CampaignDetailViewModel = hiltViewModel(),
) {
    LaunchedEffect(campaignId) { vm.load(campaignId) }
    val runState by vm.run.state.collectAsStateWithLifecycle()
    val c = vm.campaign
    Scaffold(topBar = {
        TopAppBar(
            title = { Text(c?.name ?: "Campaign", maxLines = 1, overflow = TextOverflow.Ellipsis) },
            navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
        )
    }) { padding ->
        when {
            vm.error != null -> ErrorState(vm.error!!, { vm.load(campaignId) }, Modifier.padding(padding))
            c == null -> Loading(Modifier.padding(padding))
            else -> LazyColumn(Modifier.padding(padding), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                item {
                    val thisRunActive = runState.campaignId == c.id && runState.status in setOf(RunStatus.RUNNING, RunStatus.PAUSED)
                    if (thisRunActive) {
                        Button(onClick = onOpenRun, modifier = Modifier.fillMaxWidth().height(52.dp)) { Text("Open live run") }
                    } else if (c.status != "completed") {
                        Button(
                            onClick = { vm.start(onOpenRun) },
                            enabled = !vm.starting && c.pending > 0,
                            modifier = Modifier.fillMaxWidth().height(52.dp),
                        ) { Text(if (vm.starting) "Starting…" else if (c.pending > 0) "Start calling (${c.pending} left)" else "No leads left") }
                    }
                    vm.startError?.let { Text(it, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(top = 6.dp)) }
                }
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        StatTile("Called", "${c.done}/${c.totalContacts}", Modifier.weight(1f))
                        StatTile("Interested", "${c.interested}", Modifier.weight(1f))
                    }
                }
                vm.analytics?.let { a ->
                    item {
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            StatTile("Answer rate", pct(a.rates.answer), Modifier.weight(1f))
                            StatTile("Merge success", pct(a.rates.mergeSuccess), Modifier.weight(1f))
                        }
                    }
                    item {
                        Card(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(16.dp)) {
                                Text("Funnel", style = MaterialTheme.typography.titleMedium)
                                Spacer(Modifier.height(10.dp))
                                FunnelBars(a.funnel)
                            }
                        }
                    }
                    if (isAdmin && a.byRep.isNotEmpty()) {
                        item {
                            Card(Modifier.fillMaxWidth()) {
                                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Text("Reps", style = MaterialTheme.typography.titleMedium)
                                    a.byRep.forEach { r ->
                                        Row {
                                            Text(r.name, Modifier.weight(1f))
                                            Text("${r.attempts} calls · ${pct(r.answerRate)} answered · ${r.interested} interested", style = MaterialTheme.typography.bodySmall)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                item {
                    Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(null to "All", "interested" to "Interested", "not_interested" to "Not interested", "failed" to "Failed").forEach { (value, label) ->
                            FilterChip(selected = vm.filter == value, onClick = { vm.setFilter(campaignId, value) }, label = { Text(label) })
                        }
                    }
                }
                items(vm.calls, key = { it.campaignCallId }) { call ->
                    CallRow(call) { onOpenCall(call.voiceSessionId, call.attemptId, call.contactName ?: call.phoneMasked) }
                    HorizontalDivider()
                }
            }
        }
    }
}

@Composable
private fun CallRow(call: CallItemDto, onClick: () -> Unit) {
    val clickable = call.voiceSessionId != null || call.attemptId != null
    Row(
        Modifier.fillMaxWidth().then(if (clickable) Modifier.clickable(onClick = onClick) else Modifier).padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(call.contactName ?: call.phoneMasked, style = MaterialTheme.typography.bodyLarge)
            Text(
                listOfNotNull(call.phoneMasked.takeIf { call.contactName != null }, call.repName, call.conversationSeconds?.let { "${it}s talk" }).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        val label = call.disposition ?: call.leadFailureCause ?: call.callStatus
        Pill(humanize(label), dispositionColor(label))
    }
}

fun dispositionColor(value: String?) = when (value) {
    "interested", "completed" -> StatusColors.positive
    "not_interested", "voicemail" -> StatusColors.neutral
    "busy", "no_answer", "pending", "leased", "calling" -> StatusColors.warning
    else -> StatusColors.negative
}
