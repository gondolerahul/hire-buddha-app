package com.hirebuddha.dialer.ui.common

import androidx.annotation.DrawableRes
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.data.api.FunnelDto
import com.hirebuddha.dialer.ui.theme.BrandType
import com.hirebuddha.dialer.ui.theme.HbTheme
import com.hirebuddha.dialer.ui.theme.StatusColors
import kotlin.math.roundToInt

/*
 * Screen-level composites built from the primitives in Brand.kt.
 */

// ═════════════════════════════════════════════════════════════════ APP BAR

/** Two-line app bar: title plus the one fact that identifies what you are looking at. */
@Composable
fun HbTopBar(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    @DrawableRes navigationIcon: Int? = null,
    onNavigate: (() -> Unit)? = null,
    actions: @Composable RowScope.() -> Unit = {},
) = Row(
    modifier.fillMaxWidth().height(56.dp).padding(horizontal = 8.dp),
    verticalAlignment = Alignment.CenterVertically,
) {
    if (navigationIcon != null && onNavigate != null) {
        HbIconButton(navigationIcon, onNavigate, contentDescription = "Back")
    } else {
        Spacer(Modifier.width(12.dp))
    }
    Column(Modifier.weight(1f)) {
        Text(
            title,
            style = MaterialTheme.typography.titleLarge,
            color = HbTheme.colors.fg,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        subtitle?.let { MonoText(it, color = HbTheme.colors.fgSubtle) }
    }
    actions()
}

// ══════════════════════════════════════════════════════════════════ STATES

/** The dotted-B motif is the app's only spinner. */
@Composable
fun Loading(modifier: Modifier = Modifier, label: String? = null) = Column(
    modifier.fillMaxSize(),
    verticalArrangement = Arrangement.Center,
    horizontalAlignment = Alignment.CenterHorizontally,
) {
    BrandDots(dotSize = 7.dp)
    label?.let { Spacer(Modifier.height(16.dp)); CardCaption(it) }
}

/**
 * Nothing here yet — a normal, calm state. Kept separate from [ErrorState]: the old
 * app rendered "No campaigns assigned to you" through the error path, which is
 * indistinguishable from a network failure.
 */
@Composable
fun EmptyState(
    title: String,
    message: String,
    modifier: Modifier = Modifier,
    @DrawableRes icon: Int = R.drawable.ic_list,
    action: @Composable (() -> Unit)? = null,
) = Column(
    modifier.fillMaxSize().padding(horizontal = 32.dp),
    verticalArrangement = Arrangement.Center,
    horizontalAlignment = Alignment.CenterHorizontally,
) {
    Box(
        Modifier.size(58.dp).clip(RoundedCornerShape(18.dp)).background(HbTheme.colors.surface2),
        contentAlignment = Alignment.Center,
    ) { HbIcon(icon, size = 24.dp, tint = HbTheme.colors.fgSubtle) }
    Spacer(Modifier.height(18.dp))
    Text(title, style = MaterialTheme.typography.headlineSmall, color = HbTheme.colors.fg, textAlign = TextAlign.Center)
    Spacer(Modifier.height(8.dp))
    CardBody(message, Modifier.fillMaxWidth(), HbTheme.colors.fgMuted)
    action?.let { Spacer(Modifier.height(20.dp)); it() }
}

/** Something went wrong. Always offers the retry, because most causes are transient. */
@Composable
fun ErrorState(message: String, onRetry: (() -> Unit)? = null, modifier: Modifier = Modifier) = Column(
    modifier.fillMaxSize().padding(horizontal = 32.dp),
    verticalArrangement = Arrangement.Center,
    horizontalAlignment = Alignment.CenterHorizontally,
) {
    Box(
        Modifier.size(58.dp).clip(RoundedCornerShape(18.dp)).background(HbTheme.colors.negativeQuiet),
        contentAlignment = Alignment.Center,
    ) { HbIcon(R.drawable.ic_alert, size = 24.dp, tint = HbTheme.colors.negative) }
    Spacer(Modifier.height(18.dp))
    Text(
        message,
        style = MaterialTheme.typography.bodyLarge,
        color = HbTheme.colors.fgMuted,
        textAlign = TextAlign.Center,
    )
    if (onRetry != null) {
        Spacer(Modifier.height(20.dp))
        HbButton("Try again", onRetry, style = HbButtonStyle.Secondary, icon = R.drawable.ic_refresh)
    }
}

// ═══════════════════════════════════════════════════════════════════ TILES

@Composable
fun StatTile(
    label: String,
    value: String,
    modifier: Modifier = Modifier,
    caption: String? = null,
    valueColor: Color = HbTheme.colors.fg,
) = HbCard(modifier, padding = 14.dp) {
    Eyebrow(label, color = HbTheme.colors.fgSubtle)
    Spacer(Modifier.height(6.dp))
    Numeral(value, style = BrandType.numeralSmall, color = valueColor)
    caption?.let { Spacer(Modifier.height(4.dp)); MicroText(it) }
}

fun pct(rate: Double?): String = rate?.let { "${(it * 100).roundToInt()}%" } ?: "—"

// ══════════════════════════════════════════════════════════════════ FUNNEL

/**
 * One hue for volume, sage for the one stage that counts as success. The desktop
 * system's rule — never colour two things differently unless they mean different
 * things — matters more on a small screen, not less.
 */
@Composable
fun FunnelBars(funnel: FunnelDto, modifier: Modifier = Modifier) = FunnelStages(
    listOfNotNull(
        funnel.leads?.let { "Leads" to it },
        "Attempted" to maxOf(funnel.attempted, funnel.attempts),
        "Answered" to funnel.leadAnswered,
        "Merged" to funnel.merged,
        "Talked 30s+" to funnel.conversation,
        "Interested" to funnel.interested,
    ),
    modifier,
)

/** The funnel bars for any list of stages, widest first; the last stage is the success. */
@Composable
fun FunnelStages(stages: List<Pair<String, Int>>, modifier: Modifier = Modifier) {
    val c = HbTheme.colors
    val max = stages.maxOfOrNull { it.second }?.coerceAtLeast(1) ?: 1
    Column(modifier, verticalArrangement = Arrangement.spacedBy(9.dp)) {
        stages.forEachIndexed { i, (label, value) ->
            val isLast = i == stages.lastIndex
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    label,
                    Modifier.width(92.dp),
                    style = MaterialTheme.typography.labelMedium,
                    color = c.fgMuted,
                    maxLines = 1,
                )
                Box(
                    Modifier.weight(1f).height(20.dp)
                        .clip(RoundedCornerShape(5.dp))
                        .background(Color(0x0DFFF0DC))
                ) {
                    Box(
                        Modifier.fillMaxWidth(value.toFloat() / max).fillMaxHeight()
                            .clip(RoundedCornerShape(5.dp))
                            .background(if (isLast) c.positive else c.accent)
                    )
                }
                MonoText(
                    "$value",
                    Modifier.width(38.dp).padding(start = 8.dp),
                    color = if (isLast) c.positive else c.fg,
                    style = BrandType.monoBody,
                )
            }
        }
    }
}

/** Where the funnel leaks, said in a sentence. A funnel shows what happened; this says what to do. */
fun biggestDropMessage(funnel: FunnelDto): String? {
    val answered = funnel.leadAnswered
    val talked = funnel.conversation
    if (answered <= 0) return null
    val lost = answered - talked
    if (lost <= 0 || lost < answered / 4) return null
    return "Biggest drop: $lost people answered but hung up inside 30 seconds."
}

// ═════════════════════════════════════════════════════════════════ STEPPER

enum class StepState { Done, Current, Upcoming }

/**
 * Vertical stepper. Labels read as sentences about people, not orchestrator states —
 * "Telling her who she is calling", not WAITING_AI.
 */
@Composable
fun StepRow(
    state: StepState,
    label: String,
    modifier: Modifier = Modifier,
    detail: String? = null,
    isLast: Boolean = false,
) {
    val c = HbTheme.colors
    Row(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            val node = RoundedCornerShape(percent = 50)
            Box(
                Modifier.size(23.dp)
                    .clip(node)
                    .background(
                        when (state) {
                            StepState.Done -> c.positive
                            StepState.Current -> c.accentQuiet
                            StepState.Upcoming -> Color.Transparent
                        }
                    )
                    .then(
                        when (state) {
                            StepState.Upcoming -> Modifier.border(1.75.dp, c.borderStrong, node)
                            StepState.Current -> Modifier.border(1.75.dp, c.accent, node)
                            StepState.Done -> Modifier
                        }
                    ),
                contentAlignment = Alignment.Center,
            ) {
                when (state) {
                    StepState.Done -> HbIcon(R.drawable.ic_check, size = 13.dp, tint = Color(0xFF0F2015))
                    StepState.Current -> BrandDots(count = 1, dotSize = 7.dp)
                    StepState.Upcoming -> Unit
                }
            }
            if (!isLast) {
                Box(
                    Modifier.width(1.5.dp).height(26.dp)
                        .background(if (state == StepState.Done) c.positive.copy(alpha = 0.4f) else c.border)
                )
            }
        }
        Column(Modifier.weight(1f).padding(bottom = if (isLast) 0.dp else 4.dp)) {
            Text(
                label,
                style = MaterialTheme.typography.bodyLarge.copy(
                    fontWeight = if (state == StepState.Current) androidx.compose.ui.text.font.FontWeight.SemiBold
                    else androidx.compose.ui.text.font.FontWeight.Normal
                ),
                color = when (state) {
                    StepState.Done -> c.fgMuted
                    StepState.Current -> c.fg
                    StepState.Upcoming -> c.fgFaint
                },
            )
            detail?.let {
                Spacer(Modifier.height(3.dp))
                MonoText(it, color = if (state == StepState.Current) c.gold300 else c.fgSubtle)
            }
        }
    }
}

// ═════════════════════════════════════════════════════════════════ CHIP ROW

@Composable
fun ChipRow(modifier: Modifier = Modifier, content: @Composable RowScope.() -> Unit) = Row(
    modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
    horizontalArrangement = Arrangement.spacedBy(8.dp),
    content = content,
)

// ════════════════════════════════════════════════════════════════ FORMATTING

fun humanize(code: String?): String =
    code?.replace('_', ' ')?.replaceFirstChar { it.uppercase() } ?: "—"

/** Matches the server's masking, so the same lead reads the same way everywhere. */
fun maskPhone(phone: String?): String {
    if (phone.isNullOrBlank()) return ""
    if (phone.length <= 7) return phone
    return phone.take(3) + "•".repeat(phone.length - 7) + phone.takeLast(4)
}

fun formatDuration(ms: Long): String {
    val total = (ms / 1000).coerceAtLeast(0)
    return "%d:%02d".format(total / 60, total % 60)
}

fun formatMinutes(seconds: Int?): String = when {
    seconds == null -> "—"
    seconds < 60 -> "${seconds}s"
    else -> "${seconds / 60}m ${seconds % 60}s"
}

fun initialsOf(name: String?, fallback: String = "?"): String {
    val parts = name?.trim()?.split(Regex("\\s+"))?.filter { it.isNotBlank() }.orEmpty()
    return when {
        parts.isEmpty() -> fallback
        parts.size == 1 -> parts[0].take(2)
        else -> "${parts[0].first()}${parts[1].first()}"
    }
}

fun statusColor(status: String?): Color = when (status) {
    "running" -> StatusColors.positive
    "paused" -> StatusColors.warning
    "failed" -> StatusColors.negative
    else -> StatusColors.neutral
}

fun dispositionColor(value: String?): Color = when (value) {
    "interested", "completed" -> StatusColors.positive
    "callback" -> StatusColors.warning
    "not_interested", "voicemail", "wrong_number" -> StatusColors.neutral
    "busy", "no_answer", "pending", "leased", "calling" -> StatusColors.warning
    else -> StatusColors.negative
}

/** Status marker coloured by what it means, so a list scans without reading. */
@Composable
fun DispositionPill(value: String?, modifier: Modifier = Modifier) {
    val c = HbTheme.colors
    val label = humanize(value)
    when (value) {
        "interested", "completed" -> PositivePill(label, modifier)
        "callback" -> GoldPill(label, modifier, dot = true)
        "do_not_call", "failed" -> NegativePill(label, modifier)
        else -> Pill(label, modifier, color = c.fgMuted)
    }
}

/** Column spacing used by every scrolling screen. */
@Composable
fun ScreenColumn(
    modifier: Modifier = Modifier,
    spacing: Dp = 12.dp,
    content: @Composable ColumnScope.() -> Unit,
) = Column(modifier, verticalArrangement = Arrangement.spacedBy(spacing), content = content)

/**
 * Agents are named "Seema - Sales Representative" in the console: a name, then what
 * they do. Cards show both ("Seema · Sales Representative"), the run screens only the name.
 */
fun agentNameAndRole(display: String?): Pair<String?, String?> {
    if (display.isNullOrBlank()) return null to null
    val parts = display.split(" - ", " – ", " — ", limit = 2)
    return parts[0].trim().ifBlank { null } to parts.getOrNull(1)?.trim()?.ifBlank { null }
}

/** `2026-09-14T10:02:11` → `14 Sep`. */
fun shortDate(iso: String?): String? = iso?.let {
    runCatching {
        java.time.LocalDate.parse(it.take(10)).format(java.time.format.DateTimeFormatter.ofPattern("d MMM"))
    }.getOrNull()
}
