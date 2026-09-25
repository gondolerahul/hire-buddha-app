package com.hirebuddha.dialer.ui.analytics

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
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
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.data.api.AnalyticsDto
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.DailyDto
import com.hirebuddha.dialer.data.repo.CampaignRepository
import com.hirebuddha.dialer.ui.common.Avatar
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.ChipRow
import com.hirebuddha.dialer.ui.common.ErrorState
import com.hirebuddha.dialer.ui.common.FunnelBars
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbChip
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.common.HbProgress
import com.hirebuddha.dialer.ui.common.HbTopBar
import com.hirebuddha.dialer.ui.common.Loading
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.MonoText
import com.hirebuddha.dialer.ui.common.PositivePill
import com.hirebuddha.dialer.ui.common.StatTile
import com.hirebuddha.dialer.ui.common.biggestDropMessage
import com.hirebuddha.dialer.ui.common.humanize
import com.hirebuddha.dialer.ui.common.initialsOf
import com.hirebuddha.dialer.ui.common.pct
import com.hirebuddha.dialer.ui.theme.HbTheme
import dagger.hilt.android.lifecycle.HiltViewModel
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DateRangePicker
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.SelectableDates
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDateRangePickerState
import androidx.compose.runtime.remember
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import java.time.LocalDate
import java.time.ZoneId
import javax.inject.Inject
import kotlin.math.roundToInt
import kotlinx.coroutines.launch

@HiltViewModel
class AnalyticsViewModel @Inject constructor(private val repo: CampaignRepository) : ViewModel() {
    /** 1, 7 or 30 for the preset chips; null for a custom range. */
    var days by mutableStateOf<Int?>(7); private set
    var from by mutableStateOf(today().minusDays(6)); private set
    var to by mutableStateOf(today()); private set
    var data by mutableStateOf<AnalyticsDto?>(null); private set
    /** The same number of days immediately before, for "+18% vs the previous 7 days". */
    var previous by mutableStateOf<AnalyticsDto?>(null); private set
    var error by mutableStateOf<String?>(null); private set

    init { load(7) }

    fun load(range: Int) = loadRange(today().minusDays((range - 1).toLong()), today(), range)

    fun loadRange(start: LocalDate, end: LocalDate, preset: Int? = null) = viewModelScope.launch {
        days = preset
        from = start
        to = end
        error = null
        val length = ChronoUnit.DAYS.between(start, end) + 1
        when (val r = repo.summary(start.toString(), end.toString(), null)) {
            is ApiResult.Ok -> data = r.value
            is ApiResult.Err -> error = r.message
            ApiResult.Empty -> Unit
        }
        previous = (repo.summary(start.minusDays(length).toString(), start.minusDays(1).toString(), null) as? ApiResult.Ok)?.value
    }

    fun retry() = loadRange(from, to, days)

    private fun today() = LocalDate.now(ZoneId.of("Asia/Kolkata"))
}

/** "+18% vs the previous 7 days"; nothing when there is no earlier period to beat. */
internal fun changeCaption(now: Int, before: Int?, days: Long): String? {
    if (before == null || before <= 0) return null
    val change = ((now - before) * 100.0 / before).roundToInt()
    val sign = if (change > 0) "+" else ""
    val period = when (days) {
        1L -> "yesterday"
        7L -> "last week"
        else -> "the previous $days days"
    }
    return "$sign$change% vs $period"
}

/**
 * Screen 22. Same API as before with one addition that changes how it is used: a plain
 * sentence naming the biggest drop-off. A funnel tells a rep what happened; a sentence
 * tells them what to do about it.
 */
@Composable
fun AnalyticsScreen(isAdmin: Boolean, modifier: Modifier = Modifier, vm: AnalyticsViewModel = hiltViewModel()) {
    val c = HbTheme.colors
    val a = vm.data

    Column(modifier.fillMaxSize()) {
        HbTopBar(if (isAdmin) "Insights" else "My insights")
        var picking by remember { mutableStateOf(false) }
        ChipRow(Modifier.padding(horizontal = HbTheme.dims.gutter)) {
            listOf(1 to "Today", 7 to "7 days", 30 to "30 days").forEach { (d, label) ->
                HbChip(label, vm.days == d, onClick = { vm.load(d) })
            }
            HbChip(
                if (vm.days == null) rangeLabel(vm.from, vm.to) else "Custom",
                vm.days == null,
                onClick = { picking = true },
            )
        }
        if (picking) {
            RangePickerDialog(
                initialFrom = vm.from, initialTo = vm.to,
                onPick = { start, end -> picking = false; vm.loadRange(start, end) },
                onDismiss = { picking = false },
            )
        }
        Spacer(Modifier.height(14.dp))

        when {
            vm.error != null && a == null -> ErrorState(vm.error!!, onRetry = { vm.retry() })
            a == null -> Loading()
            else -> LazyColumn(
                contentPadding = PaddingValues(HbTheme.dims.gutter, 0.dp, HbTheme.dims.gutter, 150.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                item(key = "t1") {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        StatTile(
                            "Calls", "${a.funnel.attempts}", Modifier.weight(1f),
                            caption = changeCaption(
                                a.funnel.attempts, vm.previous?.funnel?.attempts,
                                ChronoUnit.DAYS.between(vm.from, vm.to) + 1,
                            ),
                        )
                        StatTile(
                            "Answered", pct(a.rates.answer), Modifier.weight(1f),
                            caption = "${a.funnel.leadAnswered} picked up",
                        )
                    }
                }
                item(key = "t2") {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        StatTile(
                            "Conversations", "${a.funnel.conversation}", Modifier.weight(1f),
                            caption = a.timing.talkMinutes?.let { "${it.roundToInt()} talk min" },
                        )
                        StatTile(
                            "Interested", "${a.funnel.interested}", Modifier.weight(1f),
                            caption = "conversion ${pct(a.rates.conversion)}",
                            valueColor = if (a.funnel.interested > 0) c.positive else c.fg,
                        )
                    }
                }
                if (a.daily.size > 1) item(key = "daily") { DailyBars(a.daily) }
                item(key = "funnel") {
                    HbCard(Modifier.fillMaxWidth()) {
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            Text("Funnel", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, color = c.fg)
                            MicroText("where leads drop")
                        }
                        Spacer(Modifier.height(14.dp))
                        FunnelBars(a.funnel)
                        biggestDropMessage(a.funnel)?.let {
                            Spacer(Modifier.height(14.dp))
                            Row(
                                Modifier.fillMaxWidth().clip(RoundedCornerShape(HbTheme.dims.rSm))
                                    .background(c.surface2).padding(12.dp),
                                horizontalArrangement = Arrangement.spacedBy(10.dp),
                            ) {
                                HbIcon(R.drawable.ic_info, size = 16.dp, tint = c.gold300)
                                CardCaption(it, Modifier.weight(1f))
                            }
                        }
                    }
                }
                if (a.outcomes.isNotEmpty()) item(key = "outcomes") { Outcomes(a.outcomes) }
                if (isAdmin && a.byRep.isNotEmpty()) item(key = "reps") { ByRep(a) }
            }
        }
    }
}

/** Calls per day. One hue: the height is the data, colour would only add noise. */
@Composable
private fun DailyBars(daily: List<DailyDto>) {
    val c = HbTheme.colors
    val shown = daily.takeLast(30)
    val max = shown.maxOf { it.attempted }.coerceAtLeast(1)
    HbCard(Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("Calls per day", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, color = c.fg)
            MonoText("${shown.first().date.takeLast(5)} – ${shown.last().date.takeLast(5)}")
        }
        Spacer(Modifier.height(16.dp))
        Row(
            Modifier.fillMaxWidth().height(86.dp),
            horizontalArrangement = Arrangement.spacedBy(3.dp),
            verticalAlignment = Alignment.Bottom,
        ) {
            shown.forEachIndexed { i, day ->
                val isLast = i == shown.lastIndex
                Box(
                    Modifier.weight(1f).fillMaxHeight(),
                    contentAlignment = Alignment.BottomCenter,
                ) {
                    Box(
                        Modifier.fillMaxWidth()
                            .fillMaxHeight((day.attempted.toFloat() / max).coerceAtLeast(0.03f))
                            .clip(RoundedCornerShape(topStart = 3.dp, topEnd = 3.dp))
                            .background(if (isLast) c.accent else c.accent.copy(alpha = 0.32f))
                    )
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        Row(Modifier.fillMaxWidth()) {
            MonoText(shown.first().date.takeLast(5), Modifier.weight(1f))
            MonoText(shown.last().date.takeLast(5))
        }
    }
}

@Composable
private fun Outcomes(outcomes: Map<String, Int>) {
    val c = HbTheme.colors
    val sorted = outcomes.entries.sortedByDescending { it.value }
    val max = sorted.firstOrNull()?.value?.coerceAtLeast(1) ?: 1
    HbCard(Modifier.fillMaxWidth()) {
        Text("Outcomes", style = MaterialTheme.typography.titleMedium, color = c.fg)
        Spacer(Modifier.height(14.dp))
        sorted.forEachIndexed { i, (key, value) ->
            if (i > 0) Spacer(Modifier.height(10.dp))
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                CardCaption(humanize(key), Modifier.width(96.dp))
                Box(Modifier.weight(1f)) {
                    HbProgress(
                        value.toFloat() / max,
                        height = 5.dp,
                        brush = androidx.compose.ui.graphics.SolidColor(
                            when (key) {
                                "interested" -> c.positive
                                "callback" -> c.accent
                                else -> c.fgDisabled
                            }
                        ),
                    )
                }
                Spacer(Modifier.width(10.dp))
                MonoText("$value", Modifier.width(30.dp))
            }
        }
    }
}

@Composable
private fun ByRep(a: AnalyticsDto) {
    val c = HbTheme.colors
    HbCard(Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("By rep", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, color = c.fg)
            MicroText("tenant admin only")
        }
        a.byRep.forEach { rep ->
            Row(
                Modifier.fillMaxWidth().padding(top = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Avatar(initialsOf(rep.name), size = 36.dp)
                Column(Modifier.weight(1f)) {
                    Text(rep.name, style = MaterialTheme.typography.titleSmall, color = c.fg, maxLines = 1)
                    MonoText("${rep.attempts} calls · ${pct(rep.answerRate)} answered · ${rep.talkMinutes.roundToInt()} min")
                }
                PositivePill("${rep.interested}", dot = false)
            }
        }
    }
}

private fun rangeLabel(from: LocalDate, to: LocalDate): String {
    val day = DateTimeFormatter.ofPattern("d MMM")
    return if (from.month == to.month) "${from.dayOfMonth}–${to.format(day)}" else "${from.format(day)} – ${to.format(day)}"
}

/** Material's range picker, limited to days that have happened. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RangePickerDialog(
    initialFrom: LocalDate,
    initialTo: LocalDate,
    onPick: (LocalDate, LocalDate) -> Unit,
    onDismiss: () -> Unit,
) {
    val utc = ZoneOffset.UTC
    val todayMs = LocalDate.now().atStartOfDay(utc).toInstant().toEpochMilli()
    val state = rememberDateRangePickerState(
        initialSelectedStartDateMillis = initialFrom.atStartOfDay(utc).toInstant().toEpochMilli(),
        initialSelectedEndDateMillis = initialTo.atStartOfDay(utc).toInstant().toEpochMilli(),
        selectableDates = object : SelectableDates {
            override fun isSelectableDate(utcTimeMillis: Long) = utcTimeMillis <= todayMs
        },
    )
    fun day(ms: Long) = Instant.ofEpochMilli(ms).atZone(utc).toLocalDate()
    DatePickerDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(
                onClick = {
                    val start = state.selectedStartDateMillis ?: return@TextButton
                    onPick(day(start), day(state.selectedEndDateMillis ?: start))
                },
                enabled = state.selectedStartDateMillis != null,
            ) { Text("Show") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    ) {
        DateRangePicker(state = state, modifier = Modifier.weight(1f), showModeToggle = false)
    }
}
