package com.hirebuddha.dialer.telecom

import android.os.Build
import android.os.Bundle
import android.telecom.Call
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
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
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.ui.common.Avatar
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.Eyebrow
import com.hirebuddha.dialer.ui.common.GoldPill
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.common.HbIconButton
import com.hirebuddha.dialer.ui.common.MarkWatermark
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.MonoText
import com.hirebuddha.dialer.ui.common.goldGlow
import com.hirebuddha.dialer.ui.common.initialsOf
import com.hirebuddha.dialer.ui.theme.BrandType
import com.hirebuddha.dialer.ui.theme.HbTheme
import com.hirebuddha.dialer.ui.theme.HireBuddhaTheme
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import kotlinx.coroutines.launch

/**
 * Screen 24 — the dial pad every default phone app must ship (`ACTION_DIAL`, `tel:` links).
 *
 * Deliberately plain, but not unfinished: tabular mono digits and the same gold call
 * button as everywhere else. This is what a rep sees when they tap a number in any app.
 */
@AndroidEntryPoint
class DialerActivity : ComponentActivity() {
    @Inject lateinit var registry: CallRegistry

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        val initial = intent?.data?.schemeSpecificPart.orEmpty()
        setContent {
            HireBuddhaTheme {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    DialPad(initial) { number ->
                        val scope = kotlinx.coroutines.MainScope()
                        scope.launch { registry.placeCall(number) }
                        finish()
                    }
                }
            }
        }
    }
}

private val KEYS = listOf(
    "1" to "", "2" to "ABC", "3" to "DEF",
    "4" to "GHI", "5" to "JKL", "6" to "MNO",
    "7" to "PQRS", "8" to "TUV", "9" to "WXYZ",
    "*" to "", "0" to "+", "#" to "",
)

@Composable
private fun DialPad(initial: String, onCall: (String) -> Unit) {
    val c = HbTheme.colors
    var number by remember { mutableStateOf(initial) }
    Column(
        Modifier.fillMaxSize().statusBarsPadding().padding(horizontal = HbTheme.dims.gutter)
            .navigationBarsPadding(),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Row(Modifier.fillMaxWidth().height(56.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Phone", Modifier.weight(1f), style = MaterialTheme.typography.titleLarge, color = c.fg)
        }
        Spacer(Modifier.weight(1f))
        Text(
            number.ifEmpty { " " },
            style = BrandType.mono.copy(fontSize = 31.sp, letterSpacing = 0.04.em()),
            color = c.fg,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(6.dp))
        CardCaption(if (number.isEmpty()) "Enter a number" else "Calling from your verified SIM")
        Spacer(Modifier.height(22.dp))
        KEYS.chunked(3).forEach { row ->
            Row(Modifier.fillMaxWidth().padding(bottom = 10.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                row.forEach { (digit, letters) ->
                    Column(
                        Modifier.weight(1f).height(66.dp)
                            .clip(RoundedCornerShape(HbTheme.dims.rLg))
                            .background(c.surface2)
                            .border(1.dp, c.border, RoundedCornerShape(HbTheme.dims.rLg))
                            .clickable { number += digit },
                        verticalArrangement = Arrangement.Center,
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text(
                            digit,
                            style = MaterialTheme.typography.headlineSmall.copy(fontSize = 25.sp),
                            color = c.fg,
                        )
                        if (letters.isNotEmpty()) MicroText(letters)
                    }
                }
            }
        }
        Spacer(Modifier.height(10.dp))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Spacer(Modifier.width(56.dp))
            Box(
                Modifier.weight(1f),
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    Modifier.size(72.dp).clip(CircleShape).background(c.accent)
                        .clickable(enabled = number.isNotBlank()) { onCall(number) },
                    contentAlignment = Alignment.Center,
                ) { HbIcon(R.drawable.ic_phone, size = 26.dp, tint = c.onAccent) }
            }
            HbIconButton(
                R.drawable.ic_x, { number = number.dropLast(1) },
                Modifier.size(56.dp), size = 56.dp, iconSize = 22.dp,
                contentDescription = "Delete",
            )
        }
        Spacer(Modifier.height(18.dp))
    }
}

private fun Double.em() = androidx.compose.ui.unit.TextUnit(this.toFloat(), androidx.compose.ui.unit.TextUnitType.Em)

/**
 * Screen 25 — the full-screen incoming-call UI a default dialer is obliged to ship.
 *
 * It earns its keep by doing what the stock dialer cannot: recognising the caller as a
 * lead in a live campaign, and saying that answering will pause the run — behaviour the
 * orchestrator already implements but never announced.
 */
@AndroidEntryPoint
class InCallActivity : ComponentActivity() {
    @Inject lateinit var registry: CallRegistry

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent {
            HireBuddhaTheme {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    val calls by registry.calls.collectAsStateWithLifecycle()
                    val call = calls.firstOrNull { it.state == CallState.RINGING }
                        ?: calls.firstOrNull { it.state != CallState.DISCONNECTED }
                    LaunchedEffect(call == null) { if (call == null) finish() }
                    if (call != null) CallPanel(call, registry)
                }
            }
        }
    }
}

@Composable
private fun CallPanel(call: CallSnapshot, registry: CallRegistry) {
    val c = HbTheme.colors
    var muted by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val ringing = call.state == CallState.RINGING
    val isLead = registry.isCampaignNumber(call.number)

    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().goldGlow(radiusDp = 260.dp, center = Offset(170f, -80f), alpha = 0.55f))
        MarkWatermark(Modifier.align(Alignment.BottomEnd), height = 600.dp, alpha = 0.05f)
        Column(
            Modifier.fillMaxSize().statusBarsPadding().padding(horizontal = HbTheme.dims.gutter)
                .navigationBarsPadding(),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.height(56.dp))
            Eyebrow(
                when (call.state) {
                    CallState.RINGING -> "Incoming call"
                    CallState.DIALING, CallState.NEW -> "Calling"
                    CallState.HOLDING -> "On hold"
                    else -> "In call"
                }
            )
            Spacer(Modifier.height(24.dp))
            Avatar(
                initialsOf(call.number, "?"),
                size = 96.dp,
                shape = CircleShape,
            )
            Spacer(Modifier.height(20.dp))
            Text(
                call.number ?: "Unknown number",
                style = MaterialTheme.typography.headlineSmall,
                color = c.fg,
                textAlign = TextAlign.Center,
            )
            if (isLead) {
                Spacer(Modifier.height(14.dp))
                GoldPill("Lead in a live campaign", dot = true)
            }

            Spacer(Modifier.weight(1f))

            if (ringing && isLead) {
                // The orchestrator pauses after the current attempt when a real call
                // arrives; saying so beforehand removes the surprise.
                HbCard(Modifier.fillMaxWidth(), padding = 13.dp, border = Color.Transparent) {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        HbIcon(R.drawable.ic_info, size = 16.dp, tint = c.gold300)
                        MicroText("Your run will pause after this call", Modifier.weight(1f), c.fgMuted)
                    }
                }
                Spacer(Modifier.height(20.dp))
            }

            Row(
                Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 24.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Bottom,
            ) {
                if (ringing) {
                    CallAction("Decline", R.drawable.ic_phone_end, c.negative, Color(0xFF20100B)) {
                        val target = registry.call(call.id)
                        if (Build.VERSION.SDK_INT >= 30) target?.reject(Call.REJECT_REASON_DECLINED)
                        else @Suppress("DEPRECATION") target?.reject(false, null)
                    }
                    CallAction("Answer", R.drawable.ic_phone, c.positive, Color(0xFF0F2015)) {
                        registry.call(call.id)?.answer(android.telecom.VideoProfile.STATE_AUDIO_ONLY)
                    }
                } else {
                    CallAction(
                        if (muted) "Unmute" else "Mute",
                        if (muted) R.drawable.ic_mic_off else R.drawable.ic_mic,
                        c.surface3, c.fg,
                    ) { muted = !muted; registry.setMuted(muted) }
                    CallAction("End", R.drawable.ic_phone_end, c.negative, Color(0xFF20100B)) {
                        scope.launch { registry.disconnect(call.id) }
                    }
                }
            }
        }
    }
}

@Composable
private fun CallAction(
    label: String,
    icon: Int,
    background: Color,
    tint: Color,
    onClick: () -> Unit,
) = Column(horizontalAlignment = Alignment.CenterHorizontally) {
    Box(
        Modifier.size(68.dp).clip(CircleShape).background(background).clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { HbIcon(icon, size = 25.dp, tint = tint) }
    Spacer(Modifier.height(10.dp))
    MicroText(label)
}
