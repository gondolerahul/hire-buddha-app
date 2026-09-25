package com.hirebuddha.dialer.ui.run

import androidx.compose.foundation.background
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.run.RunController
import com.hirebuddha.dialer.run.RunStatus
import com.hirebuddha.dialer.run.RunUiState
import com.hirebuddha.dialer.ui.common.CardBody
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.Eyebrow
import com.hirebuddha.dialer.ui.common.GoldCard
import com.hirebuddha.dialer.ui.common.HbButton
import com.hirebuddha.dialer.ui.common.HbButtonSize
import com.hirebuddha.dialer.ui.common.HbButtonStyle
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.common.MarkWatermark
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.MonoText
import com.hirebuddha.dialer.ui.common.Numeral
import com.hirebuddha.dialer.ui.common.StatTile
import com.hirebuddha.dialer.ui.common.goldGlow
import com.hirebuddha.dialer.ui.theme.BrandType
import com.hirebuddha.dialer.ui.theme.HbTheme
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.CampaignDto
import com.hirebuddha.dialer.data.api.PreflightDto
import com.hirebuddha.dialer.data.repo.CampaignRepository
import com.hirebuddha.dialer.data.settings.AppSettings
import com.hirebuddha.dialer.ui.common.BrandDots
import com.hirebuddha.dialer.ui.common.FunnelStages
import dagger.hilt.android.lifecycle.HiltViewModel
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import javax.inject.Inject
import kotlinx.coroutines.launch

/**
 * Screen 19. Pause is a destination, not a greyed-out run screen: it answers the two
 * questions a paused rep actually has — how am I doing, and what just happened.
 */
@Composable
fun RunPausedScreen(s: RunUiState, onBack: () -> Unit, controller: RunController) {
    val c = HbTheme.colors
    val scope = rememberCoroutineScope()
    val errored = s.status == RunStatus.ERROR
    Column(
        Modifier.fillMaxSize().statusBarsPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = HbTheme.dims.gutter)
            .navigationBarsPadding(),
    ) {
        Row(Modifier.fillMaxWidth().height(56.dp), verticalAlignment = Alignment.CenterVertically) {
            com.hirebuddha.dialer.ui.common.HbIconButton(
                R.drawable.ic_chev_d, onBack, contentDescription = "Back",
                modifier = Modifier.offset(x = (-12).dp),
            )
            Column(Modifier.weight(1f)) {
                Text(
                    s.campaignName ?: "Campaign run",
                    style = MaterialTheme.typography.titleMedium, color = c.fg, maxLines = 1,
                )
                MonoText("paused after lead ${s.callsMade}")
            }
        }

        HbCard(Modifier.fillMaxWidth(), padding = 20.dp, border = c.borderGold) {
            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                Box(
                    Modifier.size(56.dp).clip(CircleShape)
                        .background(if (errored) c.negativeQuiet else c.accentQuiet),
                    contentAlignment = Alignment.Center,
                ) {
                    HbIcon(
                        if (errored) R.drawable.ic_alert else R.drawable.ic_pause,
                        size = 24.dp,
                        tint = if (errored) c.negative else c.accent,
                    )
                }
                Spacer(Modifier.height(16.dp))
                Text(
                    if (errored) "Run stopped" else "Run paused",
                    style = MaterialTheme.typography.headlineSmall, color = c.fg,
                )
                Spacer(Modifier.height(6.dp))
                CardCaption(
                    s.message ?: "Nobody is being called. Your place in the list is held.",
                    Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(18.dp))
                val remaining = s.lead?.remaining
                HbButton(
                    text = if (remaining != null) "Resume — $remaining leads left" else "Resume calling",
                    onClick = { scope.launch { controller.resume() } },
                    modifier = Modifier.fillMaxWidth(),
                    style = HbButtonStyle.Hero,
                    size = HbButtonSize.Large,
                    icon = R.drawable.ic_play,
                )
                HbButton(
                    // Ends on the summary rather than leaving: "what did I get done" is the
                    // question a rep ending a run has, and it used to go unanswered.
                    "End this run", { scope.launch { controller.end() } },
                    Modifier.fillMaxWidth(), HbButtonStyle.Ghost, HbButtonSize.Small,
                )
            }
        }

        Spacer(Modifier.height(24.dp))
        Eyebrow("This session", color = c.fgSubtle)
        Spacer(Modifier.height(10.dp))
        SessionTiles(s)
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun SessionTiles(s: RunUiState) {
    Column {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            StatTile("Calls placed", "${s.callsMade}", Modifier.weight(1f))
            StatTile(
                "Connected", "${s.connected}", Modifier.weight(1f),
                valueColor = HbTheme.colors.positive,
            )
        }
        Spacer(Modifier.height(10.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            StatTile(
                "Answer rate",
                if (s.callsMade > 0) "${(s.leadAnswered * 100) / s.callsMade}%" else "—",
                Modifier.weight(1f),
            )
            StatTile("Talk time", "${s.talkSeconds / 60}m", Modifier.weight(1f))
        }
    }
}

/**
 * What the summary needs from the server: how many leads are still waiting, and whether
 * another run could start right now. Everything about the run itself is counted on the
 * phone — the analytics API has no notion of a single run.
 */
@HiltViewModel
class RunSummaryViewModel @Inject constructor(
    private val repo: CampaignRepository,
    private val settings: AppSettings,
) : ViewModel() {
    var campaign by mutableStateOf<CampaignDto?>(null); private set
    var preflight by mutableStateOf<PreflightDto?>(null); private set
    var starting by mutableStateOf(false); private set
    var error by mutableStateOf<String?>(null); private set

    fun load(campaignId: String) = viewModelScope.launch {
        (repo.campaign(campaignId) as? ApiResult.Ok)?.let { campaign = it.value }
        preflight = repo.preflight(campaignId = campaignId, deviceId = settings.current().deviceId)
    }

    /** Starts a fresh run on the same list; the run screen follows the state on its own. */
    fun keepCalling(controller: RunController) = viewModelScope.launch {
        val c = campaign ?: return@launch
        starting = true
        error = null
        controller.awaitIdle()
        (controller.start(c.id, c.name) as? ApiResult.Err)?.let { error = it.message }
        starting = false
    }
}

/**
 * Screen 20. The run used to end by popping the back stack. This is the one moment the
 * brand voice earns a line of lift, and the one screen a rep will screenshot — so every
 * figure on it is counted, not estimated.
 *
 * Shown for a run that ran out of leads and for one the rep ended: both are finished,
 * and "what did I get done, what's next" is the same question either way.
 */
@Composable
fun RunCompleteScreen(
    s: RunUiState,
    onBack: () -> Unit,
    onOpenCampaign: (campaignId: String, filter: String?) -> Unit,
    controller: RunController,
    vm: RunSummaryViewModel = hiltViewModel(),
) {
    val c = HbTheme.colors
    LaunchedEffect(s.campaignId) { s.campaignId?.let { vm.load(it) } }
    val campaign = vm.campaign
    val waiting = campaign?.pending ?: 0
    val blocker = vm.preflight?.let { startBlocker(it) }
    val canKeepCalling = campaign != null && waiting > 0 && blocker == null
    val showReview = s.campaignId != null && (!s.askedAfterCalls || s.interested > 0)

    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().goldGlow(radiusDp = 270.dp, center = androidx.compose.ui.geometry.Offset(150f, 120f)))
        MarkWatermark(
            Modifier.align(Alignment.BottomEnd).offset(x = 90.dp),
            height = 620.dp,
            alpha = 0.05f,
        )
        Column(
            Modifier.fillMaxSize().statusBarsPadding()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = HbTheme.dims.gutter)
                .navigationBarsPadding(),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.height(34.dp))
            Eyebrow(if (s.status == RunStatus.COMPLETED) "Run complete" else "Run ended")
            Spacer(Modifier.height(10.dp))
            Text(
                summaryLine(s.callsMade, s.talkSeconds / 60),
                style = MaterialTheme.typography.headlineMedium,
                color = c.fg,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(10.dp))
            CardBody(
                listOfNotNull(s.campaignName, timeRange(s.startedAt, s.endedAt)).joinToString(" · "),
                Modifier.fillMaxWidth(),
            )

            Spacer(Modifier.height(24.dp))
            GoldCard(Modifier.fillMaxWidth()) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    if (s.askedAfterCalls) {
                        BigFigure("${s.interested}", "interested", Modifier.weight(1f), gradient = true)
                        BigFigure("${s.callbacks}", if (s.callbacks == 1) "callback booked" else "callbacks booked", Modifier.weight(1f))
                    } else {
                        // Without the wrap-up the phone never learns the outcome; the model's
                        // dispositions land on the campaign page a little later.
                        BigFigure("${s.connected}", "conversations", Modifier.weight(1f), gradient = true)
                        BigFigure(formatTalk(s.talkSeconds), "talk time", Modifier.weight(1f))
                    }
                }
                Spacer(Modifier.height(18.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    BigFigure(
                        if (s.callsMade > 0) "${(s.leadAnswered * 100) / s.callsMade}%" else "—",
                        "answered", Modifier.weight(1f),
                    )
                    BigFigure(
                        if (s.connected > 0) formatAvg(s.talkSeconds / s.connected) else "—",
                        "average conversation", Modifier.weight(1f),
                    )
                }
            }

            if (s.callsMade > 0) {
                Spacer(Modifier.height(12.dp))
                HbCard(Modifier.fillMaxWidth()) {
                    Text("Where they went", style = MaterialTheme.typography.titleMedium, color = c.fg)
                    Spacer(Modifier.height(12.dp))
                    FunnelStages(
                        listOfNotNull(
                            "Dialled" to s.callsMade,
                            "Answered" to s.leadAnswered,
                            "Met ${campaign?.agentName?.substringBefore(' ') ?: "agent"}" to s.connected,
                            "Talked 30s+" to s.talked30,
                            ("Interested" to s.interested).takeIf { s.askedAfterCalls },
                        ),
                    )
                }
            }

            if (campaign != null && waiting > 0) {
                Spacer(Modifier.height(12.dp))
                WaitingRow(waiting, blocker ?: vm.preflight?.callingWindow?.takeIf { it.enforced && it.open }
                    ?.let { "the window closes at ${it.end}" })
            }

            Spacer(Modifier.height(20.dp))
            if (canKeepCalling) {
                HbButton(
                    text = if (vm.starting) "Starting" else "Keep calling",
                    onClick = { vm.keepCalling(controller) },
                    modifier = Modifier.fillMaxWidth(),
                    style = HbButtonStyle.Hero,
                    size = HbButtonSize.Large,
                    icon = if (vm.starting) null else R.drawable.ic_phone,
                    enabled = !vm.starting,
                    content = if (!vm.starting) null else {
                        { BrandDots(count = 4, dotSize = 6.dp, color = c.onAccent) }
                    },
                )
                vm.error?.let {
                    Spacer(Modifier.height(8.dp))
                    MicroText(it, color = c.negative)
                }
                Spacer(Modifier.height(10.dp))
            }
            if (showReview) {
                HbButton(
                    if (s.askedAfterCalls) "Review the ${s.interested} interested" else "Review interested leads",
                    { s.campaignId?.let { onOpenCampaign(it, "interested") } },
                    Modifier.fillMaxWidth(),
                    if (canKeepCalling) HbButtonStyle.Secondary else HbButtonStyle.Hero,
                    if (canKeepCalling) HbButtonSize.Medium else HbButtonSize.Large,
                    icon = R.drawable.ic_star,
                )
                Spacer(Modifier.height(6.dp))
            }
            HbButton(
                "Back to campaigns", onBack, Modifier.fillMaxWidth(),
                if (canKeepCalling || showReview) HbButtonStyle.Ghost else HbButtonStyle.Hero,
                if (canKeepCalling || showReview) HbButtonSize.Small else HbButtonSize.Large,
            )
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun WaitingRow(waiting: Int, detail: String?) {
    val c = HbTheme.colors
    Row(
        Modifier.fillMaxWidth()
            .clip(RoundedCornerShape(HbTheme.dims.rSm))
            .background(c.surface2)
            .padding(12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        HbIcon(R.drawable.ic_clock, size = 16.dp, tint = c.gold300)
        CardCaption(
            "$waiting ${if (waiting == 1) "lead" else "leads"} still waiting" + (detail?.let { " — $it" } ?: ""),
            Modifier.weight(1f),
        )
    }
}

/**
 * Why another run could not start right now, in the rep's words — or null if it can.
 * The same server rules the pre-flight sheet enforces: every lease would be refused.
 */
private fun startBlocker(p: PreflightDto): String? = when {
    p.callingWindow.enforced && !p.callingWindow.open -> "calling opens at ${p.callingWindow.start}"
    p.dailyCap.limit != null && (p.dailyCap.remaining ?: 0) <= 0 -> "you've reached today's cap"
    !p.credits.ok -> p.credits.message ?: "the agent is out of credits"
    else -> null
}

/** One honest sentence. No invented figures — everything here is counted, not estimated. */
private fun summaryLine(calls: Int, minutes: Int): String {
    val placed = if (calls == 1) "1 call" else "$calls calls"
    return when {
        calls == 0 -> "No calls this time."
        minutes < 1 -> "$placed placed."
        minutes < 60 -> "$placed, $minutes minutes\nof your voice saved."
        minutes < 120 -> "$placed, an hour\nof your voice saved."
        else -> "$placed, ${minutes / 60} hours\nof your voice saved."
    }
}

private fun timeRange(from: Long?, to: Long?): String? {
    if (from == null) return null
    val fmt = DateTimeFormatter.ofPattern("HH:mm")
    fun at(ms: Long) = Instant.ofEpochMilli(ms).atZone(ZoneId.systemDefault()).format(fmt)
    return if (to == null) "from ${at(from)}" else "${at(from)} to ${at(to)}"
}

private fun formatAvg(seconds: Int): String = "%d:%02d".format(seconds / 60, seconds % 60)

private fun formatTalk(seconds: Int): String = when {
    seconds < 3600 -> "${seconds / 60}m"
    else -> "${seconds / 3600}h ${(seconds % 3600) / 60}m"
}

@Composable
private fun BigFigure(value: String, label: String, modifier: Modifier = Modifier, gradient: Boolean = false) =
    Column(modifier) {
        Numeral(value, style = BrandType.numeralLarge, gradient = gradient)
        Spacer(Modifier.height(4.dp))
        MicroText(label)
    }
