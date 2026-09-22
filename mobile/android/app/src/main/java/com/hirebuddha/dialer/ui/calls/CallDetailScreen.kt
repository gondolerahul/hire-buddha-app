package com.hirebuddha.dialer.ui.calls

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.TimelineEntryDto
import com.hirebuddha.dialer.data.api.TranscriptTurnDto
import com.hirebuddha.dialer.data.api.VoiceSessionDto
import com.hirebuddha.dialer.data.repo.CampaignRepository
import com.hirebuddha.dialer.ui.common.CardBody
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.DispositionPill
import com.hirebuddha.dialer.ui.common.EmptyState
import com.hirebuddha.dialer.ui.common.Eyebrow
import com.hirebuddha.dialer.ui.common.GoldCard
import com.hirebuddha.dialer.ui.common.Hairline
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbTopBar
import com.hirebuddha.dialer.ui.common.Loading
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.MonoText
import com.hirebuddha.dialer.ui.common.StepRow
import com.hirebuddha.dialer.ui.common.StepState
import com.hirebuddha.dialer.ui.common.formatMinutes
import com.hirebuddha.dialer.ui.common.humanize
import com.hirebuddha.dialer.ui.theme.HbTheme
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.launch

@HiltViewModel
class CallDetailViewModel @Inject constructor(private val repo: CampaignRepository) : ViewModel() {
    var session by mutableStateOf<VoiceSessionDto?>(null); private set
    var timeline by mutableStateOf<List<TimelineEntryDto>>(emptyList()); private set
    var loading by mutableStateOf(true); private set
    var error by mutableStateOf<String?>(null); private set

    fun load(sessionId: String?, attemptId: String?) = viewModelScope.launch {
        loading = true
        if (sessionId != null) {
            when (val r = repo.voiceSession(sessionId)) {
                is ApiResult.Ok -> session = r.value
                is ApiResult.Err -> error = r.message
                ApiResult.Empty -> Unit
            }
        }
        if (attemptId != null) (repo.timeline(attemptId) as? ApiResult.Ok)?.let { timeline = it.value.timeline }
        loading = false
    }
}

/**
 * Screen 21. Summary first, because it is the only part anyone reads. The AI and
 * recording disclosure stays in the transcript — it is a compliance artefact, not chrome.
 */
@Composable
fun CallDetailScreen(
    sessionId: String?,
    attemptId: String?,
    title: String,
    onBack: () -> Unit,
    vm: CallDetailViewModel = hiltViewModel(),
) {
    val c = HbTheme.colors
    LaunchedEffect(sessionId, attemptId) { vm.load(sessionId, attemptId) }

    Column(Modifier.fillMaxSize()) {
        HbTopBar(
            title = title,
            subtitle = vm.session?.durationSeconds?.let { formatMinutes(it) },
            navigationIcon = R.drawable.ic_back,
            onNavigate = onBack,
        )
        when {
            vm.loading -> Loading()
            vm.session == null && vm.timeline.isEmpty() && vm.error == null -> EmptyState(
                title = "Nothing recorded",
                message = "The lead never connected to the agent, so there is no transcript for this call.",
                icon = R.drawable.ic_phone_end,
            )
            else -> LazyColumn(
                contentPadding = PaddingValues(HbTheme.dims.gutter, 0.dp, HbTheme.dims.gutter, 40.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                vm.error?.let { item(key = "err") { MicroText(it, color = c.negative) } }

                vm.session?.let { session ->
                    item(key = "summary") {
                        GoldCard(Modifier.fillMaxWidth()) {
                            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                Eyebrow("Agent summary", Modifier.weight(1f))
                                DispositionPill(session.status)
                            }
                            Spacer(Modifier.height(10.dp))
                            Text(
                                session.callSummary ?: "Summary not available yet.",
                                style = MaterialTheme.typography.bodyMedium,
                                color = c.fg,
                            )
                            session.nextAction?.let {
                                Spacer(Modifier.height(14.dp))
                                Hairline()
                                Spacer(Modifier.height(12.dp))
                                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                    com.hirebuddha.dialer.ui.common.HbIcon(
                                        R.drawable.ic_calendar, size = 16.dp, tint = c.accent,
                                    )
                                    CardBody(it, Modifier.weight(1f), c.fg)
                                }
                            }
                        }
                    }

                    if (session.transcript.isNotEmpty()) {
                        item(key = "transcript-header") {
                            Text(
                                "Transcript",
                                Modifier.padding(top = 8.dp),
                                style = MaterialTheme.typography.titleMedium,
                                color = c.fg,
                            )
                        }
                        items(session.transcript) { turn -> Bubble(turn) }
                    }
                }

                if (vm.timeline.isNotEmpty()) {
                    item(key = "timeline") {
                        HbCard(Modifier.fillMaxWidth()) {
                            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    "What happened",
                                    Modifier.weight(1f),
                                    style = MaterialTheme.typography.titleMedium,
                                    color = c.fg,
                                )
                                MicroText("device time")
                            }
                            Spacer(Modifier.height(14.dp))
                            vm.timeline.forEachIndexed { i, entry ->
                                StepRow(
                                    state = StepState.Done,
                                    label = eventLabel(entry.type),
                                    detail = entry.at.substringAfter('T').take(8),
                                    isLast = i == vm.timeline.lastIndex,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

/**
 * Orchestrator event names, said in English. A rep and a support engineer should be able
 * to read the same screen — the raw type stays in `mobile_call_events` for debugging.
 */
private fun eventLabel(type: String): String = when (type) {
    "lease_acquired" -> "Lead reserved"
    "attempt_created" -> "Call attempt opened"
    "ai_dialing" -> "Calling the agent"
    "ai_answered" -> "Agent answered"
    "dtmf_sent" -> "Keypad code sent"
    "ai_ready_received" -> "Agent briefed and ready"
    "ai_held" -> "Agent put on hold"
    "lead_dialing" -> "Dialling the lead"
    "lead_ringing" -> "Lead's phone ringing"
    "lead_answered" -> "Lead answered"
    "merged" -> "Calls merged"
    "merge_failed" -> "Merge failed"
    "rep_muted" -> "You were muted"
    "rep_unmuted" -> "You unmuted"
    "rep_takeover" -> "You took over"
    "lead_disconnected" -> "Lead hung up"
    "ai_disconnected" -> "Agent left"
    "rep_hangup" -> "You ended the call"
    "completed" -> "Call completed"
    "skipped" -> "You skipped this lead"
    "lead_failed" -> "Lead didn't connect"
    "ai_failed" -> "Agent didn't connect"
    else -> humanize(type)
}

@Composable
private fun Bubble(turn: TranscriptTurnDto) {
    val c = HbTheme.colors
    val agent = turn.speaker == "agent"
    val shape = RoundedCornerShape(
        topStart = 15.dp, topEnd = 15.dp,
        bottomStart = if (agent) 5.dp else 15.dp,
        bottomEnd = if (agent) 15.dp else 5.dp,
    )
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = if (agent) Arrangement.Start else Arrangement.End,
    ) {
        Column(
            Modifier.fillMaxWidth(0.85f)
                .clip(shape)
                .background(if (agent) c.surface2 else c.accentQuiet)
                .border(1.dp, if (agent) c.border else c.borderGold, shape)
                .padding(horizontal = 13.dp, vertical = 10.dp),
        ) {
            Eyebrow(if (agent) "Agent" else "Lead", color = if (agent) c.fgSubtle else c.gold300.copy(alpha = 0.75f))
            Spacer(Modifier.height(5.dp))
            Text(
                turn.content,
                style = MaterialTheme.typography.bodyMedium,
                color = if (agent) c.fg else c.gold300,
            )
        }
    }
}
