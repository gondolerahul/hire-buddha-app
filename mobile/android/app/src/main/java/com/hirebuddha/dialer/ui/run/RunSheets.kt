package com.hirebuddha.dialer.ui.run

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
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
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.run.RunController
import com.hirebuddha.dialer.run.RunUiState
import com.hirebuddha.dialer.run.UserCommand
import com.hirebuddha.dialer.run.Step
import com.hirebuddha.dialer.run.WrapUp
import com.hirebuddha.dialer.ui.common.CardBody
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.Eyebrow
import com.hirebuddha.dialer.ui.common.Hairline
import com.hirebuddha.dialer.ui.common.HbButton
import com.hirebuddha.dialer.ui.common.HbButtonSize
import com.hirebuddha.dialer.ui.common.HbButtonStyle
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.common.HbRing
import com.hirebuddha.dialer.ui.common.HbTextField
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.MonoText
import com.hirebuddha.dialer.ui.common.PositivePill
import com.hirebuddha.dialer.ui.common.formatMinutes
import com.hirebuddha.dialer.ui.common.maskPhone
import com.hirebuddha.dialer.ui.theme.BrandType
import com.hirebuddha.dialer.ui.theme.HbTheme
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZoneId
import kotlin.math.ceil
import kotlinx.coroutines.launch

/*
 * Bottom sheets for the run: the identification fallback (screen 17) and the wrap-up
 * (screen 18). Both are hand-built rather than ModalBottomSheet so the scrim, the
 * countdown and the dismiss rules stay under our control — a sheet that can be
 * swiped away by accident mid-call is worse than no sheet.
 */

@Composable
private fun RunSheet(content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
    val c = HbTheme.colors
    Box(Modifier.fillMaxSize()) {
        // Scrim: not dismissible. Both sheets are decisions, not detours.
        Box(Modifier.fillMaxSize().background(Color(0xA8000000)))
        Column(
            Modifier.align(Alignment.BottomCenter).fillMaxWidth()
                .clip(RoundedCornerShape(topStart = HbTheme.dims.r2Xl, topEnd = HbTheme.dims.r2Xl))
                .background(c.surface)
                .border(
                    1.dp, c.borderStrong,
                    RoundedCornerShape(topStart = HbTheme.dims.r2Xl, topEnd = HbTheme.dims.r2Xl),
                )
                .padding(horizontal = HbTheme.dims.gutter)
                .navigationBarsPadding()
                .padding(top = 10.dp, bottom = 16.dp),
        ) {
            Box(
                Modifier.align(Alignment.CenterHorizontally)
                    .size(width = 38.dp, height = 4.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(c.borderStrong)
            )
            Spacer(Modifier.height(18.dp))
            content()
        }
    }
}

/**
 * Screen 17. The old version was a stock alert with an invisible 15-second timer that
 * silently chose "skip". Here both identification paths are shown, the consequence is in
 * the rep's language, and the countdown and its default are on screen.
 */
@Composable
fun UnidentifiedSheet(s: RunUiState, now: Long, controller: RunController) {
    val c = HbTheme.colors
    val leadName = s.lead?.name ?: "this lead"
    val secondsLeft = s.nextLeadAt?.let { ceil((it - now) / 1000.0).toInt().coerceAtLeast(0) }
    RunSheet {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(
                Modifier.size(40.dp).clip(RoundedCornerShape(14.dp)).background(c.accentQuiet),
                contentAlignment = Alignment.Center,
            ) { HbIcon(R.drawable.ic_alert, size = 20.dp, tint = c.accent) }
            Text(
                "${agentName(s)} can't place this lead",
                style = MaterialTheme.typography.headlineSmall.copy(
                    fontSize = androidx.compose.ui.unit.TextUnit(19f, androidx.compose.ui.unit.TextUnitType.Sp)
                ),
                color = c.fg,
                modifier = Modifier.weight(1f),
            )
        }
        Spacer(Modifier.height(14.dp))
        CardBody(
            "Your carrier didn't pass the keypad code through. If you connect them now, " +
                "${agentName(s, capital = false)} will still take the call but won't know $leadName's name or details.",
        )
        Spacer(Modifier.height(14.dp))
        Column(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(HbTheme.dims.rMd))
                .background(c.surface2).padding(13.dp),
        ) {
            IdentRow("Caller ID match", s.identification?.contains("cli") == true)
            Spacer(Modifier.height(9.dp))
            Hairline()
            Spacer(Modifier.height(9.dp))
            IdentRow("Keypad code", s.identification?.contains("dtmf") == true)
        }
        Spacer(Modifier.height(16.dp))
        HbButton(
            "Connect them anyway", { controller.decideMerge(true) },
            Modifier.fillMaxWidth(), HbButtonStyle.Primary, HbButtonSize.Large,
        )
        Spacer(Modifier.height(10.dp))
        HbButton(
            "Put ${s.lead?.name?.substringBefore(' ') ?: "them"} back in the queue",
            { controller.decideMerge(false) },
            Modifier.fillMaxWidth(), HbButtonStyle.Secondary,
        )
        if (secondsLeft != null) {
            Spacer(Modifier.height(14.dp))
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                HbIcon(R.drawable.ic_clock, size = 13.dp, tint = c.fgSubtle)
                Spacer(Modifier.size(6.dp))
                MicroText("Deciding for you in ${secondsLeft}s — we'll put them back")
            }
        }
    }
}

@Composable
private fun IdentRow(label: String, ok: Boolean) {
    val c = HbTheme.colors
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        CardCaption(label, Modifier.weight(1f))
        MicroText(if (ok) "received" else "not received", color = if (ok) c.positive else c.negative)
    }
}

/**
 * Screen 18 — the wrap-up. Entirely new: until now the disposition came only from the
 * model's reading of a transcript, and the one human who heard the call was never asked.
 *
 * It lives inside the gap that already exists between leads, so it costs no time; Hold
 * freezes that countdown rather than forcing the rep to pause the whole run.
 */
@Composable
fun WrapUpSheet(wrapUp: WrapUp, s: RunUiState, now: Long, controller: RunController) {
    val c = HbTheme.colors
    val scope = rememberCoroutineScope()
    var note by remember(wrapUp.campaignCallId) { mutableStateOf("") }
    var chosen by remember(wrapUp.campaignCallId) { mutableStateOf<String?>(null) }
    var callbackAt by remember(wrapUp.campaignCallId) { mutableStateOf<Instant?>(null) }
    var submitting by remember(wrapUp.campaignCallId) { mutableStateOf(false) }
    var error by remember(wrapUp.campaignCallId) { mutableStateOf<String?>(null) }

    val secondsLeft = s.nextLeadAt?.let { ceil((it - now) / 1000.0).toInt().coerceAtLeast(0) } ?: 0
    val gapTotal = 5

    fun submit(disposition: String, at: Instant? = null) {
        submitting = true
        error = null
        scope.launch {
            val r = controller.submitDisposition(wrapUp.campaignCallId, disposition, note, at)
            if (r is com.hirebuddha.dialer.data.api.ApiResult.Err) error = r.message
            submitting = false
        }
    }

    RunSheet {
        Row(verticalAlignment = Alignment.CenterVertically) {
            PositivePill(if (wrapUp.endedBy == "rep") "You ended it" else "Ended well")
            Spacer(Modifier.weight(1f))
            MonoText("${formatMinutes(wrapUp.talkSeconds)} talk time")
        }
        Spacer(Modifier.height(10.dp))
        Text(
            "How did ${wrapUp.leadName?.substringBefore(' ') ?: maskPhone(wrapUp.phone)} sound?",
            style = MaterialTheme.typography.headlineSmall,
            color = c.fg,
        )
        Spacer(Modifier.height(6.dp))
        CardCaption("You were on the call — your answer beats the model's guess.")

        Spacer(Modifier.height(16.dp))
        if (chosen == "callback") {
            CallbackPicker(
                onPick = { at -> callbackAt = at; submit("callback", at) },
                onBack = { chosen = null },
            )
        } else {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                DispositionTile(
                    "Interested", R.drawable.ic_star, Modifier.weight(1f),
                    tone = c.positive, enabled = !submitting,
                ) { chosen = "interested"; submit("interested") }
                DispositionTile(
                    "Call back", R.drawable.ic_rotate_l, Modifier.weight(1f),
                    enabled = !submitting,
                ) { chosen = "callback" }
            }
            Spacer(Modifier.height(9.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                DispositionTile(
                    "Not interested", R.drawable.ic_minus, Modifier.weight(1f),
                    enabled = !submitting,
                ) { chosen = "not_interested"; submit("not_interested") }
                DispositionTile(
                    "Do not call", R.drawable.ic_ban, Modifier.weight(1f),
                    tone = c.negative, enabled = !submitting,
                ) { chosen = "do_not_call"; submit("do_not_call") }
            }
            Spacer(Modifier.height(9.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                HbButton(
                    "Wrong number", { chosen = "wrong_number"; submit("wrong_number") },
                    Modifier.weight(1f), HbButtonStyle.Ghost, HbButtonSize.Small, enabled = !submitting,
                )
                HbButton(
                    "Voicemail", { chosen = "voicemail"; submit("voicemail") },
                    Modifier.weight(1f), HbButtonStyle.Ghost, HbButtonSize.Small, enabled = !submitting,
                )
            }

            Spacer(Modifier.height(12.dp))
            HbTextField(
                value = note,
                onValueChange = { note = it.take(500) },
                placeholder = "Add a note for the CRM — optional",
                leadingIcon = R.drawable.ic_edit,
            )
        }

        error?.let {
            Spacer(Modifier.height(10.dp))
            MicroText(it, color = c.negative)
        }

        Spacer(Modifier.height(16.dp))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            HbRing(
                fraction = if (s.gapHeld) 1f else (secondsLeft.toFloat() / gapTotal).coerceIn(0f, 1f),
                diameter = 44.dp,
                stroke = 3.dp,
            ) {
                if (s.gapHeld) {
                    HbIcon(R.drawable.ic_pause, size = 14.dp, tint = c.accent)
                } else {
                    Text("$secondsLeft", style = BrandType.monoBody, color = c.accent)
                }
            }
            Spacer(Modifier.size(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    if (s.gapHeld) "Holding — take your time" else "Next lead shortly",
                    style = MaterialTheme.typography.titleSmall,
                    color = c.fg,
                )
                MicroText(if (s.gapHeld) "Tap Continue when you're done" else "Or answer above")
            }
            if (s.gapHeld) {
                HbButton("Continue", { controller.continueRun() }, style = HbButtonStyle.Secondary, size = HbButtonSize.Small)
            } else {
                HbButton("Hold", { controller.holdGap() }, style = HbButtonStyle.Glass, size = HbButtonSize.Small)
            }
        }
    }
}

/**
 * Quick callback times rather than a clock face. A rep is standing in a corridor with
 * one hand free; "this evening" is both faster and closer to what the lead actually said.
 */
@Composable
private fun CallbackPicker(onPick: (Instant) -> Unit, onBack: () -> Unit) {
    val zone = remember { ZoneId.systemDefault() }
    val now = remember { java.time.ZonedDateTime.now(zone) }
    val options = remember(now) {
        listOf(
            "In 1 hour" to now.plusHours(1).toInstant(),
            "In 3 hours" to now.plusHours(3).toInstant(),
            "This evening, 18:00" to now.with(LocalTime.of(18, 0))
                .let { if (it.isBefore(now)) it.plusDays(1) else it }.toInstant(),
            "Tomorrow, 10:00" to now.plusDays(1).with(LocalTime.of(10, 0)).toInstant(),
            "Tomorrow, 16:00" to now.plusDays(1).with(LocalTime.of(16, 0)).toInstant(),
            "In 3 days" to now.plusDays(3).with(LocalTime.of(11, 0)).toInstant(),
        )
    }
    Column {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Eyebrow("When should we call back?", Modifier.weight(1f))
            HbButton("Back", onBack, style = HbButtonStyle.Ghost, size = HbButtonSize.Small)
        }
        Spacer(Modifier.height(12.dp))
        options.chunked(2).forEach { pair ->
            Row(Modifier.fillMaxWidth().padding(bottom = 9.dp), horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                pair.forEach { (label, instant) ->
                    HbButton(label, { onPick(instant) }, Modifier.weight(1f), HbButtonStyle.Secondary, HbButtonSize.Small)
                }
                if (pair.size == 1) Spacer(Modifier.weight(1f))
            }
        }
        MicroText("The lead goes back in the queue and comes up again at that time.")
    }
}

@Composable
private fun DispositionTile(
    label: String,
    icon: Int,
    modifier: Modifier = Modifier,
    tone: Color? = null,
    enabled: Boolean = true,
    onClick: () -> Unit,
) {
    val c = HbTheme.colors
    val fg = if (!enabled) c.fgDisabled else tone ?: c.fg
    val shape = RoundedCornerShape(percent = 50)
    Column(
        modifier
            .height(58.dp)
            .clip(shape)
            .background(if (tone != null && enabled) tone.copy(alpha = 0.12f) else Color.Transparent)
            .border(1.dp, if (tone != null && enabled) tone.copy(alpha = 0.4f) else c.borderStrong, shape)
            .clickable(enabled = enabled, onClick = onClick),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        HbIcon(icon, size = 18.dp, tint = fg)
        Spacer(Modifier.height(3.dp))
        Text(label, style = MaterialTheme.typography.titleSmall, color = fg, textAlign = TextAlign.Center)
    }
}

/** Unused today, but callbacks land on a date and the formatter belongs with them. */
internal fun formatCallback(instant: Instant, zone: ZoneId = ZoneId.systemDefault()): String {
    val dt = instant.atZone(zone)
    val today = LocalDate.now(zone)
    val time = "%02d:%02d".format(dt.hour, dt.minute)
    return when (dt.toLocalDate()) {
        today -> "today $time"
        today.plusDays(1) -> "tomorrow $time"
        else -> "${dt.dayOfMonth} ${dt.month.name.take(3).lowercase().replaceFirstChar { it.uppercase() }} $time"
    }
}

/**
 * Run options, reachable from every state including mid-conversation.
 *
 * Stop used to live only on the pre-merge panes, so once a call connected there was no
 * way to end the run at all — "End call" only ends the current lead and the run moves
 * straight on to the next one. Both meanings of stopping are offered explicitly,
 * because during a live call they are very different acts.
 */
@Composable
fun RunMenuSheet(s: RunUiState, controller: RunController, onDismiss: () -> Unit) {
    val c = HbTheme.colors
    val inCall = s.step == Step.IN_CONVERSATION
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
            Eyebrow("Run options")
            Spacer(Modifier.height(4.dp))
            Text(
                s.campaignName ?: "Campaign run",
                style = MaterialTheme.typography.headlineSmall,
                color = c.fg,
            )
            Spacer(Modifier.height(18.dp))

            if (s.step != Step.IDLE) {
                MenuAction(
                    R.drawable.ic_skip, "Skip this lead",
                    "Put them back in the queue and move on",
                ) { controller.command(UserCommand.SKIP); onDismiss() }
                Hairline()
            }
            MenuAction(
                R.drawable.ic_pause,
                if (inCall) "Pause after this call" else "Pause the run",
                "Your place in the list is held",
            ) { controller.pause(); onDismiss() }
            Hairline()
            MenuAction(
                R.drawable.ic_stop,
                if (inCall) "Stop after this call" else "Stop the run",
                if (inCall) "Lets the current conversation finish" else "Ends the run and releases the phone",
                tone = c.negative,
            ) { controller.stop(); onDismiss() }
            if (inCall) {
                Hairline()
                MenuAction(
                    R.drawable.ic_phone_end, "Hang up and stop now",
                    "Ends this call immediately, then the run",
                    tone = c.negative,
                ) {
                    // Order matters: request the stop first so the run loop sees it the
                    // moment the conversation tears down.
                    controller.stop()
                    controller.command(UserCommand.HANG_UP)
                    onDismiss()
                }
            }
            Spacer(Modifier.height(12.dp))
            HbButton("Close", onDismiss, Modifier.fillMaxWidth(), HbButtonStyle.Ghost, HbButtonSize.Small)
        }
    }
}

@Composable
private fun MenuAction(
    icon: Int,
    title: String,
    detail: String,
    tone: Color? = null,
    onClick: () -> Unit,
) {
    val c = HbTheme.colors
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        HbIcon(icon, size = 20.dp, tint = tone ?: c.fgMuted)
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, color = tone ?: c.fg)
            MicroText(detail)
        }
    }
}
