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
import androidx.compose.runtime.produceState
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
import androidx.lifecycle.lifecycleScope
import androidx.compose.ui.platform.LocalContext
import com.hirebuddha.dialer.data.settings.AppSettings
import com.hirebuddha.dialer.data.api.LeadLookupDto
import com.hirebuddha.dialer.data.repo.CampaignRepository
import com.hirebuddha.dialer.run.RunController
import com.hirebuddha.dialer.run.RunStatus
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
import androidx.core.content.ContextCompat
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers

/**
 * Screen 24 — the dial pad every default phone app must ship (`ACTION_DIAL`, `tel:` links).
 *
 * Deliberately plain, but not unfinished: tabular mono digits and the same gold call
 * button as everywhere else. This is what a rep sees when they tap a number in any app.
 */
@AndroidEntryPoint
class DialerActivity : ComponentActivity() {
    @Inject lateinit var registry: CallRegistry
    @Inject lateinit var settings: AppSettings
    @Inject lateinit var runController: RunController

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        val initial = intent?.data?.schemeSpecificPart.orEmpty()
        setContent {
            HireBuddhaTheme {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    val simLabel by produceState<String?>(null) { value = settings.current().phoneAccountLabel }
                    val run by runController.state.collectAsStateWithLifecycle()
                    PhoneScreen(
                        initial = initial,
                        callingFrom = callingFrom(simLabel),
                        // A personal call during a run would collide with the lead legs.
                        runLive = run.status == RunStatus.RUNNING,
                        onClose = ::finish,
                    ) { number ->
                        lifecycleScope.launch {
                            registry.placePersonalCall(number)
                            finish()
                        }
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

/**
 * "Jio · SIM 1", the carrier and slot the call will go out on — the question a rep with
 * two SIMs has before dialling. The network name is what the phone is registered on now.
 */
@Composable
private fun callingFrom(simLabel: String?): String? {
    val context = LocalContext.current
    val network = remember {
        runCatching {
            context.getSystemService(android.telephony.TelephonyManager::class.java)
                ?.networkOperatorName?.takeIf { it.isNotBlank() }
        }.getOrNull()
    }
    return listOfNotNull(network, simLabel?.takeIf { it != network }).joinToString(" · ").ifBlank { null }
}

@Composable
internal fun DialPad(
    number: String,
    onNumber: (String) -> Unit,
    callingFrom: String?,
    enabled: Boolean,
    onCall: (String) -> Unit,
    modifier: Modifier = Modifier,
    suggestions: @Composable () -> Unit = {},
) {
    val c = HbTheme.colors
    Column(modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
        suggestions()
        Spacer(Modifier.weight(1f))
        Text(
            number.ifEmpty { " " },
            style = BrandType.mono.copy(fontSize = 31.sp, letterSpacing = 0.04.em()),
            color = c.fg,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(6.dp))
        CardCaption(
            when {
                number.isEmpty() -> "Enter a number"
                callingFrom != null -> "Calling from $callingFrom"
                else -> "Calling from your verified SIM"
            }
        )
        Spacer(Modifier.height(22.dp))
        KEYS.chunked(3).forEach { row ->
            Row(Modifier.fillMaxWidth().padding(bottom = 10.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                row.forEach { (digit, letters) ->
                    Column(
                        Modifier.weight(1f).height(66.dp)
                            .clip(RoundedCornerShape(HbTheme.dims.rLg))
                            .background(c.surface2)
                            .border(1.dp, c.border, RoundedCornerShape(HbTheme.dims.rLg))
                            .clickable { onNumber(number + digit) },
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
                    Modifier.size(72.dp).clip(CircleShape)
                        .background(if (enabled) c.accent else c.surface3)
                        .clickable(enabled = enabled && number.isNotBlank()) { onCall(number) },
                    contentAlignment = Alignment.Center,
                ) { HbIcon(R.drawable.ic_phone, size = 26.dp, tint = c.onAccent) }
            }
            HbIconButton(
                R.drawable.ic_x, { onNumber(number.dropLast(1)) },
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
 * lead from the rep's campaigns, and saying up front that answering pauses a live run.
 */
@AndroidEntryPoint
class InCallActivity : ComponentActivity() {
    @Inject lateinit var registry: CallRegistry
    @Inject lateinit var campaigns: CampaignRepository
    @Inject lateinit var runController: RunController

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent {
            HireBuddhaTheme {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    val calls by registry.calls.collectAsStateWithLifecycle()
                    val run by runController.state.collectAsStateWithLifecycle()
                    val call = calls.firstOrNull { it.state == CallState.RINGING }
                        ?: calls.firstOrNull { it.state != CallState.DISCONNECTED }
                    LaunchedEffect(call == null) { if (call == null) finish() }
                    // Looked up once per number; the screen shows the number until it lands.
                    val lead by produceState<LeadLookupDto?>(null, call?.number) {
                        value = call?.number?.let { campaigns.lookupLead(it) }
                    }
                    // A personal call to or from someone saved on the phone shows their name.
                    val saved by produceState<String?>(null, call?.number) {
                        value = call?.number?.let { n ->
                            withContext(Dispatchers.IO) { contactNameFor(this@InCallActivity, n) }
                        }
                    }
                    if (call != null) {
                        CallPanel(call, lead, saved, runLive = run.status == RunStatus.RUNNING, registry = registry)
                    }
                }
            }
        }
    }
}

@Composable
private fun CallPanel(
    call: CallSnapshot,
    lead: LeadLookupDto?,
    savedName: String?,
    runLive: Boolean,
    registry: CallRegistry,
) {
    val c = HbTheme.colors
    var muted by remember { mutableStateOf(false) }
    var speaker by remember { mutableStateOf(false) }
    var keypad by remember { mutableStateOf(false) }
    var replying by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val ringing = call.state == CallState.RINGING
    val name = lead?.contactName?.takeIf { it.isNotBlank() } ?: savedName

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
                initialsOf(name ?: call.number, "?"),
                size = 96.dp,
                shape = CircleShape,
                gold = lead != null,
            )
            Spacer(Modifier.height(20.dp))
            Text(
                name ?: call.number ?: "Unknown number",
                style = MaterialTheme.typography.headlineSmall.copy(fontSize = 25.sp),
                color = c.fg,
                textAlign = TextAlign.Center,
            )
            if (name != null && call.number != null) {
                Spacer(Modifier.height(6.dp))
                MonoText(call.number, color = c.fgMuted, style = BrandType.monoBody)
            }
            if (lead != null) {
                Spacer(Modifier.height(14.dp))
                GoldPill("Lead · ${lead.campaignName ?: "one of your campaigns"}", dot = lead.campaignStatus == "running")
            }

            Spacer(Modifier.weight(1f))

            if (ringing && runLive) {
                // The run pauses only if the rep picks up — say so while there is still a
                // choice to make, rather than after the calling has stopped.
                HbCard(Modifier.fillMaxWidth(), padding = 13.dp, border = Color.Transparent) {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        HbIcon(R.drawable.ic_info, size = 16.dp, tint = c.gold300)
                        MicroText(
                            "Answering pauses your run once the current lead is done. Declining keeps it going.",
                            Modifier.weight(1f), c.fgMuted,
                        )
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
                    // Only when the carrier can send it; otherwise the button would lie.
                    if (call.canRespondViaText) {
                        CallAction("Message", R.drawable.ic_message, c.surface3, c.fg) { replying = true }
                    }
                    CallAction("Answer", R.drawable.ic_phone, c.positive, Color(0xFF0F2015)) {
                        registry.call(call.id)?.answer(android.telecom.VideoProfile.STATE_AUDIO_ONLY)
                    }
                } else {
                    CallAction(
                        if (muted) "Unmute" else "Mute",
                        if (muted) R.drawable.ic_mic_off else R.drawable.ic_mic,
                        if (muted) c.accentQuiet else c.surface3, c.fg,
                    ) { muted = !muted; registry.setMuted(muted) }
                    CallAction("Keypad", R.drawable.ic_keypad, if (keypad) c.accentQuiet else c.surface3, c.fg) {
                        keypad = !keypad
                    }
                    CallAction("Speaker", R.drawable.ic_speaker, if (speaker) c.accentQuiet else c.surface3, c.fg) {
                        speaker = !speaker; registry.setSpeaker(speaker)
                    }
                    CallAction("End", R.drawable.ic_phone_end, c.negative, Color(0xFF20100B)) {
                        scope.launch { registry.disconnect(call.id) }
                    }
                }
            }
        }

        if (keypad && !ringing) {
            InCallKeypad(
                onKey = { registry.pressKey(call.id, it) },
                onClose = { keypad = false },
                modifier = Modifier.align(Alignment.BottomCenter),
            )
        }

        if (replying && ringing) {
            QuickReplySheet(
                firstName = name?.substringBefore(' '),
                onSend = { text -> replying = false; registry.rejectWithMessage(call.id, text) },
                onDismiss = { replying = false },
            )
        }
    }
}

/** Decline-with-a-text. Short, and polite enough to send to a lead as well as a friend. */
@Composable
private fun QuickReplySheet(firstName: String?, onSend: (String) -> Unit, onDismiss: () -> Unit) {
    val c = HbTheme.colors
    val replies = listOfNotNull(
        firstName?.let { "Hi $it, I can't talk right now. I'll call you back shortly." },
        "Can't talk right now. I'll call you back shortly.",
        "I'm on another call. I'll call you back in a few minutes.",
        "Please text me and I'll get back to you.",
    )
    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().background(Color(0xA8000000)).clickable(onClick = onDismiss))
        Column(
            Modifier.align(Alignment.BottomCenter).fillMaxWidth()
                .clip(RoundedCornerShape(topStart = HbTheme.dims.r2Xl, topEnd = HbTheme.dims.r2Xl))
                .background(c.surface)
                .border(1.dp, c.borderStrong, RoundedCornerShape(topStart = HbTheme.dims.r2Xl, topEnd = HbTheme.dims.r2Xl))
                .padding(horizontal = HbTheme.dims.gutter)
                .navigationBarsPadding()
                .padding(top = 18.dp, bottom = 16.dp),
        ) {
            Eyebrow("Decline with a message")
            Spacer(Modifier.height(12.dp))
            replies.forEach { reply ->
                Text(
                    reply,
                    Modifier.fillMaxWidth()
                        .clip(RoundedCornerShape(HbTheme.dims.rMd))
                        .clickable { onSend(reply) }
                        .background(c.surface2)
                        .padding(horizontal = 14.dp, vertical = 13.dp),
                    style = MaterialTheme.typography.bodyMedium,
                    color = c.fg,
                )
                Spacer(Modifier.height(8.dp))
            }
            CardCaption("Sent as a text from your SIM; the call is declined.")
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

/** Keys for phone menus in a live call. Each press is sent as a tone at once. */
@Composable
private fun InCallKeypad(onKey: (Char) -> Unit, onClose: () -> Unit, modifier: Modifier = Modifier) {
    val c = HbTheme.colors
    var typed by remember { mutableStateOf("") }
    Column(
        modifier.fillMaxWidth()
            .clip(RoundedCornerShape(topStart = HbTheme.dims.r2Xl, topEnd = HbTheme.dims.r2Xl))
            .background(c.surface)
            .navigationBarsPadding()
            .padding(horizontal = HbTheme.dims.gutter, vertical = 14.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            MonoText(typed.ifEmpty { " " }, Modifier.weight(1f), color = c.fg, style = BrandType.monoBody)
            HbIconButton(R.drawable.ic_x, onClose, contentDescription = "Hide keypad")
        }
        Spacer(Modifier.height(8.dp))
        KEYS.chunked(3).forEach { row ->
            Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                row.forEach { (digit, _) ->
                    Box(
                        Modifier.weight(1f).height(54.dp)
                            .clip(RoundedCornerShape(HbTheme.dims.rMd))
                            .background(c.surface2)
                            .clickable { typed += digit; onKey(digit.first()) },
                        contentAlignment = Alignment.Center,
                    ) { Text(digit, style = MaterialTheme.typography.headlineSmall, color = c.fg) }
                }
            }
        }
    }
}

/** The saved name for [number], or null. Needs READ_CONTACTS; without it, just the number. */
internal fun contactNameFor(context: android.content.Context, number: String): String? = runCatching {
    if (ContextCompat.checkSelfPermission(context, android.Manifest.permission.READ_CONTACTS) !=
        android.content.pm.PackageManager.PERMISSION_GRANTED
    ) return@runCatching null
    val uri = android.net.Uri.withAppendedPath(
        android.provider.ContactsContract.PhoneLookup.CONTENT_FILTER_URI, android.net.Uri.encode(number),
    )
    context.contentResolver.query(uri, arrayOf(android.provider.ContactsContract.PhoneLookup.DISPLAY_NAME), null, null, null)
        ?.use { if (it.moveToFirst()) it.getString(0) else null }
}.getOrNull()
