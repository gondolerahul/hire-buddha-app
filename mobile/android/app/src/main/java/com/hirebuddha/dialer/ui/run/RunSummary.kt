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
                    "End this run", { controller.stop(); onBack() },
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
                if (s.callsMade > 0) "${(s.connected * 100) / s.callsMade}%" else "—",
                Modifier.weight(1f),
            )
            StatTile("Talk time", "${s.talkSeconds / 60}m", Modifier.weight(1f))
        }
    }
}

/**
 * Screen 20. The run used to end by popping the back stack. This is the one moment the
 * brand voice earns a line of lift, and the one screen a rep will screenshot.
 */
@Composable
fun RunCompleteScreen(s: RunUiState, now: Long, onBack: () -> Unit, controller: RunController) {
    val c = HbTheme.colors
    val minutes = s.talkSeconds / 60
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
            Eyebrow("Run complete")
            Spacer(Modifier.height(10.dp))
            Text(
                summaryLine(s.callsMade, minutes),
                style = MaterialTheme.typography.headlineMedium,
                color = c.fg,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(10.dp))
            CardBody(
                listOfNotNull(s.campaignName, s.message).joinToString(" · "),
                Modifier.fillMaxWidth(),
            )

            Spacer(Modifier.height(24.dp))
            GoldCard(Modifier.fillMaxWidth()) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    BigFigure("${s.connected}", "connected", Modifier.weight(1f), gradient = true)
                    BigFigure(
                        if (s.callsMade > 0) "${(s.connected * 100) / s.callsMade}%" else "—",
                        "answered", Modifier.weight(1f),
                    )
                }
                Spacer(Modifier.height(18.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    BigFigure("${s.callsMade}", "calls placed", Modifier.weight(1f))
                    BigFigure(
                        if (s.connected > 0) formatAvg(s.talkSeconds / s.connected) else "—",
                        "average conversation", Modifier.weight(1f),
                    )
                }
            }

            Spacer(Modifier.height(20.dp))
            HbButton(
                "Back to campaigns", onBack,
                Modifier.fillMaxWidth(), HbButtonStyle.Hero, HbButtonSize.Large,
            )
            Spacer(Modifier.height(24.dp))
        }
    }
}

/** One honest sentence. No invented figures — everything here is counted, not estimated. */
private fun summaryLine(calls: Int, minutes: Int): String = when {
    calls == 0 -> "No calls this time."
    minutes < 1 -> "$calls calls placed."
    else -> "$calls calls, $minutes minutes\nof your voice saved."
}

private fun formatAvg(seconds: Int): String = "%d:%02d".format(seconds / 60, seconds % 60)

@Composable
private fun BigFigure(value: String, label: String, modifier: Modifier = Modifier, gradient: Boolean = false) =
    Column(modifier) {
        Numeral(value, style = BrandType.numeralLarge, gradient = gradient)
        Spacer(Modifier.height(4.dp))
        MicroText(label)
    }
