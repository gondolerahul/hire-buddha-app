package com.hirebuddha.dialer.ui.run

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.run.RunController
import com.hirebuddha.dialer.run.RunStatus
import com.hirebuddha.dialer.run.RunUiState
import com.hirebuddha.dialer.run.Step
import com.hirebuddha.dialer.run.TranscriptTurn
import com.hirebuddha.dialer.run.UserCommand
import com.hirebuddha.dialer.ui.common.Avatar
import com.hirebuddha.dialer.ui.common.BrandDots
import com.hirebuddha.dialer.ui.common.CardBody
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.Eyebrow
import com.hirebuddha.dialer.ui.common.GlassSurface
import com.hirebuddha.dialer.ui.common.GoldCard
import com.hirebuddha.dialer.ui.common.goldGlow
import com.hirebuddha.dialer.ui.common.HbButton
import com.hirebuddha.dialer.ui.common.HbButtonSize
import com.hirebuddha.dialer.ui.common.HbButtonStyle
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.common.HbIconButton
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.MonoText
import com.hirebuddha.dialer.ui.common.PositivePill
import com.hirebuddha.dialer.ui.common.StepRow
import com.hirebuddha.dialer.ui.common.StepState
import com.hirebuddha.dialer.ui.common.formatDuration
import com.hirebuddha.dialer.ui.common.humanize
import com.hirebuddha.dialer.ui.common.initialsOf
import com.hirebuddha.dialer.ui.common.maskPhone
import com.hirebuddha.dialer.ui.theme.BrandType
import com.hirebuddha.dialer.ui.theme.HbTheme
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.delay

@HiltViewModel
class RunViewModel @Inject constructor(val controller: RunController) : ViewModel()

/**
 * The run destination (docs 11 §III, screens 14–20).
 *
 * One screen with five faces, because a rep reads this standing up, often mid-sentence:
 * connecting, ringing, in conversation, paused, done. Whatever the state, the controls
 * that apply to it are in the bottom third and nothing else is.
 */
@Composable
fun RunScreen(onBack: () -> Unit, vm: RunViewModel = hiltViewModel()) {
    val s by vm.controller.state.collectAsStateWithLifecycle()
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            now = System.currentTimeMillis()
            delay(500)
        }
    }

    Box(Modifier.fillMaxSize()) {
        when (s.status) {
            RunStatus.COMPLETED -> RunCompleteScreen(s, now, onBack, vm.controller)
            RunStatus.PAUSED, RunStatus.STOPPED, RunStatus.ERROR -> RunPausedScreen(s, onBack, vm.controller)
            else -> RunCockpit(s, now, onBack, vm.controller)
        }

        // Overlays. The wrap-up only appears once the call is genuinely over.
        if (s.awaitingMergeDecision) UnidentifiedSheet(s, now, vm.controller)
        s.wrapUp?.let { if (!s.awaitingMergeDecision) WrapUpSheet(it, s, now, vm.controller) }
    }
}

// ═══════════════════════════════════════════════════════════════════ COCKPIT

@Composable
private fun RunCockpit(s: RunUiState, now: Long, onBack: () -> Unit, controller: RunController) {
    var menuOpen by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        RunTopBar(s, onBack) { menuOpen = true }
        when (s.step) {
            Step.IN_CONVERSATION -> ConversationPane(s, now, controller)
            Step.CALLING_LEAD, Step.MERGING -> RingingPane(s, now, controller)
            Step.FETCHING_LEAD, Step.WAITING_NEXT, Step.IDLE -> BetweenPane(s, controller)
            else -> ConnectingPane(s, now, controller)
        }
    }
    if (menuOpen) RunMenuSheet(s, controller) { menuOpen = false }
}

@Composable
private fun RunTopBar(s: RunUiState, onBack: () -> Unit, onMenu: () -> Unit) {
    val c = HbTheme.colors
    Row(
        Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        HbIconButton(R.drawable.ic_chev_d, onBack, contentDescription = "Minimise the run")
        Column(Modifier.weight(1f)) {
            Text(
                s.lead?.name ?: s.campaignName ?: "Campaign run",
                style = MaterialTheme.typography.titleMedium,
                color = c.fg,
                maxLines = 1,
            )
            val position = s.lead?.let { "lead ${s.callsMade + 1} of ${s.callsMade + 1 + it.remaining}" }
            MonoText(position ?: humanize(s.status.name.lowercase()), color = c.fgSubtle)
        }
        if (s.step == Step.IN_CONVERSATION) {
            PositivePill("Merged")
            Spacer(Modifier.size(4.dp))
        }
        // Always present, including mid-conversation: Stop used to be unreachable once a
        // call was live, which left a running campaign with no way out of it.
        HbIconButton(R.drawable.ic_more, onMenu, contentDescription = "Run options")
    }
}

/** Screen 14. The lead's phone has not rung yet — say so, or the wait looks like a fault. */
@Composable
private fun ConnectingPane(s: RunUiState, now: Long, controller: RunController) {
    val c = HbTheme.colors
    Column(
        Modifier.fillMaxSize().padding(horizontal = HbTheme.dims.gutter).navigationBarsPadding(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(24.dp))
        Box(contentAlignment = Alignment.Center) {
            Box(Modifier.size(300.dp).goldGlow(radiusDp = 150.dp))
            PulseRings()
            Box(
                Modifier.size(96.dp).clip(CircleShape).background(c.accentQuiet).border(1.dp, c.borderGold, RoundedCornerShape(percent = 50)),
                contentAlignment = Alignment.Center,
            ) { HbIcon(R.drawable.ic_ai, size = 40.dp, tint = c.accent) }
        }
        Spacer(Modifier.height(32.dp))
        Eyebrow("Connecting your Buddha")
        Spacer(Modifier.height(8.dp))
        Text(
            "The agent is joining",
            style = MaterialTheme.typography.headlineSmall,
            color = c.fg,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(8.dp))
        CardBody(
            "The lead's phone will not ring until the agent is ready and briefed.",
            Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(16.dp))
        BrandDots()

        Spacer(Modifier.height(24.dp))
        HbCard(Modifier.fillMaxWidth()) { RunSteps(s, now) }

        Spacer(Modifier.weight(1f))
        s.lead?.let { lead ->
            HbCard(Modifier.fillMaxWidth(), padding = 13.dp, border = Color.Transparent) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    HbIcon(R.drawable.ic_user, size = 16.dp, tint = c.fgSubtle)
                    Column(Modifier.weight(1f)) {
                        CardCaption("Up next · ${lead.name ?: "Lead"}", color = c.fgMuted)
                        MonoText(maskPhone(lead.phone))
                    }
                }
            }
        }
        Spacer(Modifier.height(12.dp))
        SkipAndStop(controller)
        Spacer(Modifier.height(16.dp))
    }
}

/** Screen 15. Identification finally gets a visible receipt, in words. */
@Composable
private fun RingingPane(s: RunUiState, now: Long, controller: RunController) {
    val c = HbTheme.colors
    val lead = s.lead
    Column(
        Modifier.fillMaxSize().padding(horizontal = HbTheme.dims.gutter)
            .verticalScroll(rememberScrollState()).navigationBarsPadding(),
    ) {
        IdentificationReceipt(s.identification)
        Spacer(Modifier.height(28.dp))
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            Box(contentAlignment = Alignment.Center) {
                PulseRings(color = Color(0x1AFFF0DC))
                Avatar(
                    initialsOf(lead?.name, "?"),
                    size = 84.dp,
                    shape = RoundedCornerShape(percent = 50),
                )
            }
            Spacer(Modifier.height(20.dp))
            Text(
                lead?.name ?: maskPhone(lead?.phone),
                style = MaterialTheme.typography.headlineSmall,
                color = c.fg,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(6.dp))
            MonoText(maskPhone(lead?.phone), color = c.fgMuted, style = BrandType.monoBody)
            Spacer(Modifier.height(14.dp))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                BrandDots(count = 3, dotSize = 5.dp)
                MonoText(
                    if (s.step == Step.MERGING) "Bringing everyone together" else "Ringing",
                    color = c.gold300,
                    style = BrandType.monoBody,
                )
            }
        }

        if (!lead?.fields.isNullOrEmpty()) {
            Spacer(Modifier.height(24.dp))
            LeadContextCard(lead.fields)
        }
        Spacer(Modifier.height(20.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            HbButton(
                "Skip", { controller.command(UserCommand.SKIP) },
                Modifier.weight(1f), HbButtonStyle.Secondary, icon = R.drawable.ic_skip,
            )
            HbButton(
                "Cancel call", { controller.command(UserCommand.HANG_UP) },
                Modifier.weight(1f), HbButtonStyle.Danger, icon = R.drawable.ic_phone_end,
            )
        }
        Spacer(Modifier.height(16.dp))
    }
}

/**
 * Screen 16. The live transcript is the reason to keep the phone in your hand: it is how
 * the rep knows when to unmute. Controls sit in a glass dock ranked by how often they
 * are used, with End call sized to be deliberate.
 */
@Composable
private fun ConversationPane(s: RunUiState, now: Long, controller: RunController) {
    val c = HbTheme.colors
    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            Column(Modifier.padding(horizontal = HbTheme.dims.gutter)) {
                GoldCard(Modifier.fillMaxWidth(), padding = 14.dp) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        MergedAvatars(s)
                        Column(Modifier.weight(1f)) {
                            Text(
                                if (s.aiInCall) "The agent is talking" else "You're on the call",
                                style = MaterialTheme.typography.titleSmall,
                                color = c.fg,
                            )
                            MicroText(
                                if (s.muted) "You are muted — the lead cannot hear you"
                                else "You are unmuted — the lead can hear you",
                                color = if (s.muted) c.fgFaint else c.gold300,
                            )
                        }
                        Column(horizontalAlignment = Alignment.End) {
                            Text(
                                s.conversationStartedAt?.let { formatDuration(now - it) } ?: "0:00",
                                style = BrandType.monoBody.copy(fontSize = androidx.compose.ui.unit.TextUnit(19f, androidx.compose.ui.unit.TextUnitType.Sp)),
                                color = c.accent,
                            )
                            MicroText("talk time")
                        }
                    }
                }
            }
            Spacer(Modifier.height(14.dp))
            TranscriptPane(s.transcript, Modifier.weight(1f))
        }
        InCallDock(s, controller, Modifier.align(Alignment.BottomCenter))
    }
}

@Composable
private fun TranscriptPane(turns: List<TranscriptTurn>, modifier: Modifier = Modifier) {
    val c = HbTheme.colors
    val listState = rememberLazyListState()
    LaunchedEffect(turns.size) {
        if (turns.isNotEmpty()) listState.animateScrollToItem(turns.lastIndex)
    }
    Column(modifier.fillMaxWidth().padding(horizontal = HbTheme.dims.gutter)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Eyebrow("Live transcript", Modifier.weight(1f), color = c.fgSubtle)
            if (turns.isNotEmpty()) {
                Box(Modifier.size(6.dp).clip(CircleShape).background(c.positive))
                Spacer(Modifier.size(6.dp))
                MicroText("following")
            }
        }
        Spacer(Modifier.height(10.dp))
        if (turns.isEmpty()) {
            Column(
                Modifier.fillMaxWidth().weight(1f),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                BrandDots(count = 3, dotSize = 5.dp, color = c.fgDisabled)
                Spacer(Modifier.height(10.dp))
                MicroText("Waiting for the first words")
            }
        } else {
            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = 190.dp),
            ) {
                items(turns) { turn -> TranscriptBubble(turn) }
            }
        }
    }
}

@Composable
private fun TranscriptBubble(turn: TranscriptTurn) {
    val c = HbTheme.colors
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = if (turn.isAgent) Arrangement.Start else Arrangement.End,
    ) {
        Column(
            Modifier
                .fillMaxWidth(0.82f)
                .clip(RoundedCornerShape(15.dp, 15.dp, if (turn.isAgent) 15.dp else 5.dp, if (turn.isAgent) 5.dp else 15.dp))
                .background(if (turn.isAgent) c.surface2 else c.accentQuiet)
                .border(
                    1.dp,
                    if (turn.isAgent) c.border else c.borderGold,
                    RoundedCornerShape(15.dp, 15.dp, if (turn.isAgent) 15.dp else 5.dp, if (turn.isAgent) 5.dp else 15.dp),
                )
                .padding(horizontal = 13.dp, vertical = 9.dp),
        ) {
            Eyebrow(
                if (turn.isAgent) "Agent" else "Lead",
                color = if (turn.isAgent) c.fgSubtle else c.gold300.copy(alpha = 0.75f),
            )
            Spacer(Modifier.height(4.dp))
            Text(
                turn.text,
                style = MaterialTheme.typography.bodyMedium,
                color = if (turn.isAgent) c.fg else c.gold300,
            )
        }
    }
}

@Composable
private fun InCallDock(s: RunUiState, controller: RunController, modifier: Modifier = Modifier) {
    val c = HbTheme.colors
    GlassSurface(
        modifier.fillMaxWidth().padding(horizontal = 12.dp).navigationBarsPadding().padding(bottom = 10.dp),
        gold = true,
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                HbButton(
                    text = if (s.muted) "Unmute to speak" else "Mute me",
                    onClick = { controller.command(UserCommand.TOGGLE_MUTE) },
                    modifier = Modifier.weight(1f).height(54.dp),
                    style = if (s.muted) HbButtonStyle.Hero else HbButtonStyle.Glass,
                    icon = if (s.muted) R.drawable.ic_mic else R.drawable.ic_mic_off,
                )
            }
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                if (s.aiInCall) {
                    HbButton(
                        "Take over", { controller.command(UserCommand.TAKE_OVER) },
                        Modifier.weight(1f), HbButtonStyle.Glass, HbButtonSize.Small,
                        icon = R.drawable.ic_swap,
                    )
                }
                HbButton(
                    "End call", { controller.command(UserCommand.HANG_UP) },
                    Modifier.weight(1f), HbButtonStyle.Danger, HbButtonSize.Small,
                    icon = R.drawable.ic_phone_end,
                )
            }
        }
    }
}

/** Between leads, or fetching the next one. */
@Composable
private fun BetweenPane(s: RunUiState, controller: RunController) {
    val c = HbTheme.colors
    Column(
        Modifier.fillMaxSize().padding(horizontal = HbTheme.dims.gutter).navigationBarsPadding(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        BrandDots(dotSize = 7.dp)
        Spacer(Modifier.height(20.dp))
        Text(
            if (s.step == Step.FETCHING_LEAD) "Finding the next lead" else "Next lead shortly",
            style = MaterialTheme.typography.headlineSmall,
            color = c.fg,
        )
        s.lastOutcome?.let {
            Spacer(Modifier.height(8.dp))
            CardCaption("Last call: $it")
        }
        Spacer(Modifier.height(28.dp))
        SkipAndStop(controller, skipLabel = "Skip the wait")
    }
}

// ══════════════════════════════════════════════════════════════════ PIECES

@Composable
private fun RunSteps(s: RunUiState, now: Long) {
    val steps = listOf(
        Step.FETCHING_LEAD to "Lead reserved for you",
        Step.CONNECTING_AI to "Calling the agent",
        Step.WAITING_AI to "Telling it who it is calling",
        Step.CALLING_LEAD to "Ringing the lead",
        Step.IN_CONVERSATION to "Bringing you all together",
    )
    val order = listOf(
        Step.FETCHING_LEAD, Step.CONNECTING_AI, Step.SENDING_CODE, Step.WAITING_AI,
        Step.CALLING_LEAD, Step.MERGING, Step.IN_CONVERSATION,
    )
    val currentRank = order.indexOf(s.step).let { if (it < 0) 0 else it }
    Column {
        steps.forEachIndexed { i, (step, label) ->
            val rank = order.indexOf(step)
            val state = when {
                rank < currentRank -> StepState.Done
                rank == currentRank || (step == Step.WAITING_AI && s.step == Step.SENDING_CODE) ||
                    (step == Step.IN_CONVERSATION && s.step == Step.MERGING) -> StepState.Current
                else -> StepState.Upcoming
            }
            val detail = when {
                step == Step.WAITING_AI && state == StepState.Done && s.identification != null ->
                    "confirmed by ${identificationLabel(s.identification)}"
                step == Step.IN_CONVERSATION && s.conversationStartedAt != null ->
                    formatDuration(now - s.conversationStartedAt)
                step == Step.CONNECTING_AI && state == StepState.Current -> "usually 5–25 s"
                else -> null
            }
            StepRow(state, label, detail = detail, isLast = i == steps.lastIndex)
        }
    }
}

private fun identificationLabel(method: String?): String = when (method) {
    "cli" -> "caller ID"
    "dtmf" -> "keypad code"
    "cli+dtmf" -> "caller ID and keypad code"
    "reconciled" -> "the server"
    else -> humanize(method)
}

/** The whole point of ADR-001, finally visible at the moment it matters. */
@Composable
private fun IdentificationReceipt(identification: String?) {
    val c = HbTheme.colors
    val ok = identification != null && identification != "unidentified"
    HbCard(
        Modifier.fillMaxWidth(),
        padding = 13.dp,
        border = if (ok) c.positive.copy(alpha = 0.3f) else c.borderGold,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            HbIcon(
                if (ok) R.drawable.ic_check_c else R.drawable.ic_alert,
                size = 17.dp,
                tint = if (ok) c.positive else c.accent,
            )
            Column(Modifier.weight(1f)) {
                Text(
                    if (ok) "The agent is ready, holding" else "The agent is ready but unsure who this is",
                    style = MaterialTheme.typography.titleSmall,
                    color = c.fg,
                )
                MicroText(
                    if (ok) "Recognised by ${identificationLabel(identification)}"
                    else "It will introduce itself without the lead's details",
                )
            }
        }
    }
}

/** The CSV columns, framed as what the agent knows — which is both true and the rep's cue. */
@Composable
private fun LeadContextCard(fields: Map<String, String>) {
    val shown = fields.filterKeys { it.lowercase() != "name" }
    if (shown.isEmpty()) return
    HbCard(Modifier.fillMaxWidth()) {
        Eyebrow("What the agent knows", color = HbTheme.colors.fgSubtle)
        Spacer(Modifier.height(10.dp))
        shown.entries.forEachIndexed { i, (k, v) ->
            if (i > 0) Spacer(Modifier.height(9.dp))
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
                CardCaption(humanize(k), Modifier.weight(1f))
                Text(
                    v,
                    style = MaterialTheme.typography.bodySmall,
                    color = HbTheme.colors.fg,
                    modifier = Modifier.weight(1.2f),
                    textAlign = TextAlign.End,
                )
            }
        }
    }
}

@Composable
private fun MergedAvatars(s: RunUiState) {
    val c = HbTheme.colors
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier.size(38.dp).clip(CircleShape).background(c.accentQuiet)
                .border(1.dp, c.borderGold, RoundedCornerShape(percent = 50)),
            contentAlignment = Alignment.Center,
        ) { HbIcon(R.drawable.ic_ai, size = 18.dp, tint = c.accent) }
        Avatar(
            initialsOf(s.lead?.name, "L"),
            Modifier.offset(x = (-11).dp),
            size = 38.dp,
            shape = RoundedCornerShape(percent = 50),
        )
    }
}

/**
 * Skip and Stop, present in every pre-merge state. `UserCommand.SKIP` has existed since
 * the first build; until now nothing sent it (docs 11 §2.1 F1).
 */
@Composable
private fun SkipAndStop(controller: RunController, skipLabel: String = "Skip lead") {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        HbButton(
            skipLabel, { controller.command(UserCommand.SKIP) },
            Modifier.weight(1f), HbButtonStyle.Secondary, icon = R.drawable.ic_skip,
        )
        HbButton(
            "Stop run", { controller.stop() },
            Modifier.weight(1f), HbButtonStyle.DangerQuiet,
        )
    }
}

/** Two concentric hairlines: the calm equivalent of a ringing animation. */
@Composable
private fun PulseRings(color: Color = Color(0x38EDAB48)) {
    val circle = RoundedCornerShape(percent = 50)
    Box(Modifier.size(128.dp).border(1.dp, color, circle))
    Box(Modifier.size(160.dp).border(1.dp, color.copy(alpha = color.alpha * 0.45f), circle))
}
