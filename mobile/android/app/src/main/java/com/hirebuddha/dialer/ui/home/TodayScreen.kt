package com.hirebuddha.dialer.ui.home

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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
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
import com.hirebuddha.dialer.data.api.CallbackDto
import com.hirebuddha.dialer.data.api.CampaignDto
import com.hirebuddha.dialer.data.api.MeDto
import com.hirebuddha.dialer.data.api.PreflightDto
import com.hirebuddha.dialer.data.repo.CampaignRepository
import com.hirebuddha.dialer.data.settings.AppSettings
import com.hirebuddha.dialer.run.RunController
import com.hirebuddha.dialer.run.RunStatus
import com.hirebuddha.dialer.run.RunUiState
import com.hirebuddha.dialer.ui.common.Avatar
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.Eyebrow
import com.hirebuddha.dialer.ui.common.GoldCard
import com.hirebuddha.dialer.ui.common.GoldPill
import com.hirebuddha.dialer.ui.common.HbButton
import com.hirebuddha.dialer.ui.common.HbButtonSize
import com.hirebuddha.dialer.ui.common.HbButtonStyle
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.common.HbProgress
import com.hirebuddha.dialer.ui.common.HbRing
import com.hirebuddha.dialer.ui.common.Hairline
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.MonoText
import com.hirebuddha.dialer.ui.common.Numeral
import com.hirebuddha.dialer.ui.common.PositivePill
import com.hirebuddha.dialer.ui.common.SectionLabel
import com.hirebuddha.dialer.ui.common.initialsOf
import com.hirebuddha.dialer.ui.theme.BrandType
import com.hirebuddha.dialer.ui.theme.HbTheme
import dagger.hilt.android.lifecycle.HiltViewModel
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import javax.inject.Inject
import kotlin.math.roundToInt
import kotlinx.coroutines.launch

private val IST: ZoneId = ZoneId.of("Asia/Kolkata")

@HiltViewModel
class TodayViewModel @Inject constructor(
    @dagger.hilt.android.qualifiers.ApplicationContext private val context: android.content.Context,
    private val repo: CampaignRepository,
    private val settings: AppSettings,
    val run: RunController,
) : ViewModel() {
    var today by mutableStateOf<AnalyticsDto?>(null); private set
    var preflight by mutableStateOf<PreflightDto?>(null); private set
    var campaigns by mutableStateOf<List<CampaignDto>>(emptyList()); private set
    var callbacks by mutableStateOf<List<CallbackDto>>(emptyList()); private set
    var loading by mutableStateOf(true); private set
    /** A run the server still holds open that this process is not driving. */
    var orphanRun by mutableStateOf<ActiveRunDto?>(null); private set
    var stopping by mutableStateOf(false); private set

    init { load() }

    fun load() = viewModelScope.launch {
        val date = LocalDate.now(IST).toString()
        (repo.summary(date, date, null) as? ApiResult.Ok)?.let { today = it.value }
        preflight = repo.preflight(deviceId = settings.current().deviceId)
        (repo.campaigns() as? ApiResult.Ok)?.let { campaigns = it.value }
        callbacks = repo.callbacks(withinHours = 24)
        com.hirebuddha.dialer.data.notify.AppNotifications.scheduleCallbackReminders(context, callbacks)
        refreshOrphan()
        loading = false
    }

    private suspend fun refreshOrphan() {
        orphanRun = repo.activeRuns().firstOrNull { it.runId != run.state.value.runId }
    }

    fun stopOrphan(runId: String) = viewModelScope.launch {
        stopping = true
        run.stopRun(runId)
        stopping = false
        load()
    }
}

/**
 * Screen 07 — the Today tab, and the answer to "what now?".
 *
 * The app used to open straight onto a campaign list, which answers "which campaign?"
 * — a question a rep with one assigned list does not have. Cap, calling window, today's
 * numbers and the one paused run are what actually matters at 9:41 in the morning.
 */
@Composable
fun TodayScreen(
    me: MeDto,
    onOpenCampaign: (String) -> Unit,
    onOpenRun: () -> Unit,
    onSeeAll: () -> Unit,
    modifier: Modifier = Modifier,
    vm: TodayViewModel = hiltViewModel(),
) {
    val c = HbTheme.colors
    val runState by vm.run.state.collectAsStateWithLifecycle()

    LazyColumn(
        modifier.fillMaxSize(),
        contentPadding = PaddingValues(HbTheme.dims.gutter, 0.dp, HbTheme.dims.gutter, 150.dp),
    ) {
        item(key = "greeting") { Greeting(me) }
        item(key = "cap") {
            DayCard(vm.preflight, vm.today)
            Spacer(Modifier.height(24.dp))
        }

        if (runState.status == RunStatus.RUNNING || runState.status == RunStatus.PAUSED) {
            item(key = "resume") {
                SectionLabel("Pick up where you left off")
                Spacer(Modifier.height(10.dp))
                ResumeCard(runState, onOpenRun)
                Spacer(Modifier.height(24.dp))
            }
        }

        // A campaign stuck at "running" with nothing happening is the single most
        // confusing state in the app; offer the way out where it is first noticed.
        vm.orphanRun?.let { orphan ->
            item(key = "orphan") {
                OrphanRunBanner(orphan, vm.stopping) { vm.stopOrphan(orphan.runId) }
                Spacer(Modifier.height(24.dp))
            }
        }

        if (vm.callbacks.isNotEmpty()) {
            item(key = "callbacks") {
                CallbacksCard(vm.callbacks, onOpenCampaign)
                Spacer(Modifier.height(24.dp))
            }
        }

        val assigned = vm.campaigns.filter { it.status != "completed" }.take(3)
        if (assigned.isNotEmpty()) {
            item(key = "assigned-label") {
                SectionLabel("Assigned to you") {
                    Text(
                        "See all",
                        style = MaterialTheme.typography.labelMedium,
                        color = c.accent,
                        modifier = Modifier.clickable(onClick = onSeeAll),
                    )
                }
                Spacer(Modifier.height(10.dp))
            }
            items(assigned, key = { it.id }) { campaign ->
                CampaignMiniRow(campaign) { onOpenCampaign(campaign.id) }
                Spacer(Modifier.height(10.dp))
            }
        }
    }
}

@Composable
private fun Greeting(me: MeDto) {
    val c = HbTheme.colors
    val now = LocalTime.now(IST)
    val part = when {
        now.hour < 12 -> "Good morning"
        now.hour < 17 -> "Good afternoon"
        else -> "Good evening"
    }
    Row(Modifier.fillMaxWidth().height(56.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Eyebrow(LocalDate.now(IST).format(DateTimeFormatter.ofPattern("EEEE, d MMM")))
            Spacer(Modifier.height(4.dp))
            Text(
                "$part, ${me.fullName.substringBefore(' ')}",
                style = MaterialTheme.typography.titleLarge,
                color = c.fg,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        // Personal calls: this is the phone's dialer, so the keypad is one tap from home.
        val context = androidx.compose.ui.platform.LocalContext.current
        com.hirebuddha.dialer.ui.common.HbIconButton(
            R.drawable.ic_keypad,
            {
                context.startActivity(
                    android.content.Intent(context, com.hirebuddha.dialer.telecom.DialerActivity::class.java)
                )
            },
            contentDescription = "Phone",
            tint = c.fgMuted,
        )
        Avatar(initialsOf(me.fullName), size = 38.dp)
    }
    Spacer(Modifier.height(4.dp))
}

/**
 * The cap ring is deliberately the largest object on the screen: it is the constraint
 * that ends the rep's day, and it used to be invisible until the server refused a lease.
 */
@Composable
private fun DayCard(preflight: PreflightDto?, today: AnalyticsDto?) {
    val c = HbTheme.colors
    val cap = preflight?.dailyCap
    val limit = cap?.limit
    val used = cap?.used ?: today?.funnel?.attempts ?: 0
    val window = preflight?.callingWindow

    GoldCard(Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            HbRing(
                fraction = if (limit != null && limit > 0) used.toFloat() / limit else 0f,
                diameter = 84.dp,
                stroke = 6.dp,
            ) {
                Numeral("$used", style = BrandType.numeralSmall)
                limit?.let { MicroText("of $it") }
            }
            Column(Modifier.weight(1f)) {
                Eyebrow("Today's calls")
                Spacer(Modifier.height(6.dp))
                Text(
                    when {
                        limit == null -> "No daily limit set"
                        (cap.remaining ?: 0) <= 0 -> "You've hit today's limit"
                        else -> "${cap.remaining} left on your daily cap"
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = c.fg,
                )
                Spacer(Modifier.height(8.dp))
                if (window != null && window.enforced) {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        if (window.open) PositivePill("Window open") else GoldPill("Window closed", dot = true)
                        MonoText(if (window.open) "closes ${window.end}" else "opens ${window.start}")
                    }
                }
            }
        }
        Spacer(Modifier.height(16.dp))
        Hairline()
        Spacer(Modifier.height(14.dp))
        Row(Modifier.fillMaxWidth()) {
            val funnel = today?.funnel
            val answered = funnel?.let { f ->
                if (f.attempts > 0) ((f.leadAnswered * 100.0) / f.attempts).roundToInt() else null
            }
            Figure(answered?.let { "$it%" } ?: "—", "answered", Modifier.weight(1f))
            Figure("${funnel?.interested ?: 0}", "interested", Modifier.weight(1f), c.positive)
            Figure(
                today?.timing?.talkMinutes?.let { "${it.roundToInt()}m" } ?: "—",
                "talk time",
                Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun Figure(value: String, label: String, modifier: Modifier = Modifier, color: Color? = null) =
    Column(modifier) {
        Numeral(value, style = BrandType.numeralSmall, color = color ?: HbTheme.colors.fg)
        Spacer(Modifier.height(3.dp))
        MicroText(label)
    }

@Composable
private fun ResumeCard(runState: RunUiState, onOpen: () -> Unit) {
    val c = HbTheme.colors
    val paused = runState.status == RunStatus.PAUSED
    val remaining = runState.lead?.remaining
    HbCard(Modifier.fillMaxWidth(), border = c.borderGold, onClick = onOpen) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(
                Modifier.size(40.dp).clip(RoundedCornerShape(13.dp)).background(c.accentQuiet),
                contentAlignment = Alignment.Center,
            ) {
                HbIcon(if (paused) R.drawable.ic_pause else R.drawable.ic_phone, size = 19.dp, tint = c.accent)
            }
            Column(Modifier.weight(1f)) {
                Text(
                    runState.campaignName ?: "Campaign",
                    style = MaterialTheme.typography.titleMedium,
                    color = c.fg,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                CardCaption(
                    if (paused) "Paused after lead ${runState.callsMade}" + (runState.endedAt?.let { " · ${ago(it)}" } ?: "")
                    else "Running — tap to open",
                )
            }
        }
        if (remaining != null) {
            val total = runState.callsMade + remaining
            Spacer(Modifier.height(14.dp))
            HbProgress(if (total > 0) runState.callsMade.toFloat() / total else 0f)
            Spacer(Modifier.height(8.dp))
            Row(Modifier.fillMaxWidth()) {
                MonoText("${runState.callsMade} / $total called", Modifier.weight(1f))
                MonoText("$remaining left")
            }
        }
        Spacer(Modifier.height(14.dp))
        HbButton(
            if (paused) "Resume calling" else "Open live run",
            onOpen,
            Modifier.fillMaxWidth(),
            HbButtonStyle.Primary,
            HbButtonSize.Small,
            icon = R.drawable.ic_play,
        )
    }
}

/**
 * Callbacks a rep promised. Before this they had nowhere to go but a rep's memory or a
 * scrap of paper, which is the main reason warm leads went cold.
 */
@Composable
private fun CallbacksCard(callbacks: List<CallbackDto>, onOpenCampaign: (String) -> Unit) {
    val c = HbTheme.colors
    HbCard(Modifier.fillMaxWidth(), border = c.borderGold) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            HbIcon(R.drawable.ic_rotate_l, size = 17.dp, tint = c.gold300)
            val allToday = callbacks.all { it.callbackAt?.let(::isToday) ?: false }
            Text(
                "${callbacks.size} callback${if (callbacks.size == 1) "" else "s"} due" + if (allToday) " today" else "",
                Modifier.weight(1f),
                style = MaterialTheme.typography.titleMedium,
                color = c.fg,
            )
        }
        callbacks.take(3).forEach { callback ->
            Spacer(Modifier.height(12.dp))
            Row(
                Modifier.fillMaxWidth().clickable { onOpenCampaign(callback.campaignId) },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        callback.contactName ?: callback.phoneMasked,
                        style = MaterialTheme.typography.bodyMedium,
                        color = c.fg,
                        maxLines = 1,
                    )
                    MonoText(callback.campaignName ?: callback.phoneMasked)
                }
                callback.callbackAt?.let { GoldPill((if (isToday(it)) "" else "tomorrow ") + shortTime(it)) }
            }
        }
    }
}

private fun isToday(iso: String): Boolean = runCatching {
    java.time.LocalDateTime.parse(iso.removeSuffix("Z"))
        .atZone(ZoneId.of("UTC")).withZoneSameInstant(ZoneId.systemDefault())
        .toLocalDate() == LocalDate.now()
}.getOrDefault(true)

/** "just now", "8 min ago", "2 h ago". */
private fun ago(epochMs: Long): String {
    val minutes = (System.currentTimeMillis() - epochMs) / 60_000
    return when {
        minutes < 1 -> "just now"
        minutes < 60 -> "$minutes min ago"
        else -> "${minutes / 60} h ago"
    }
}

/** `2026-09-21T16:00:00` → `16:00`. Server times are UTC-naive ISO-8601. */
private fun shortTime(iso: String): String = runCatching {
    java.time.LocalDateTime.parse(iso.removeSuffix("Z"))
        .atZone(ZoneId.of("UTC")).withZoneSameInstant(ZoneId.systemDefault())
        .format(DateTimeFormatter.ofPattern("HH:mm"))
}.getOrDefault(iso.takeLast(8).take(5))

@Composable
private fun CampaignMiniRow(campaign: CampaignDto, onClick: () -> Unit) {
    val c = HbTheme.colors
    val progress = if (campaign.totalContacts > 0) campaign.done.toFloat() / campaign.totalContacts else 0f
    HbCard(Modifier.fillMaxWidth(), padding = 13.dp, onClick = onClick) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            if (campaign.done == 0) {
                Box(
                    Modifier.size(38.dp).clip(CircleShape).border(3.dp, Color(0x17FFF0DC), CircleShape),
                    contentAlignment = Alignment.Center,
                ) { HbIcon(R.drawable.ic_clock, size = 14.dp, tint = c.fgFaint) }
            } else {
                HbRing(
                    progress, diameter = 38.dp, stroke = 3.dp,
                    color = if (campaign.status == "completed") c.positive else c.accent,
                )
            }
            Column(Modifier.weight(1f)) {
                Text(
                    campaign.name,
                    style = MaterialTheme.typography.titleMedium,
                    color = c.fg,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                CardCaption(
                    if (campaign.done == 0) "Not started · ${campaign.totalContacts} leads"
                    else "${campaign.done} / ${campaign.totalContacts} · ${campaign.interested} interested",
                )
            }
            HbIcon(R.drawable.ic_chev_r, size = 18.dp, tint = c.fgDisabled)
        }
    }
}

/**
 * A run the server still considers open that nothing is driving.
 *
 * The live run is held in memory, so a crash, a force-stop or a reinstall strands it:
 * the campaign reads "running", no calls are placed, and every campaign then refuses to
 * start on this phone. Housekeeping clears these after six hours — this is the way to
 * clear one now.
 */
@Composable
private fun OrphanRunBanner(orphan: ActiveRunDto, stopping: Boolean, onStop: () -> Unit) {
    val c = HbTheme.colors
    HbCard(Modifier.fillMaxWidth(), border = c.borderGold) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(
                Modifier.size(40.dp).clip(RoundedCornerShape(13.dp)).background(c.accentQuiet),
                contentAlignment = Alignment.Center,
            ) { HbIcon(R.drawable.ic_alert, size = 19.dp, tint = c.accent) }
            Column(Modifier.weight(1f)) {
                Text(
                    "\u201c${orphan.campaignName ?: "A campaign"}\u201d is marked running",
                    style = MaterialTheme.typography.titleMedium,
                    color = c.fg,
                    maxLines = 2,
                )
                CardCaption("No calls are being placed, and it's holding this phone.")
            }
        }
        Spacer(Modifier.height(14.dp))
        HbButton(
            text = if (stopping) "Stopping" else "Stop that run",
            onClick = onStop,
            modifier = Modifier.fillMaxWidth(),
            style = HbButtonStyle.DangerQuiet,
            size = HbButtonSize.Small,
            icon = R.drawable.ic_stop,
            enabled = !stopping,
        )
    }
}
