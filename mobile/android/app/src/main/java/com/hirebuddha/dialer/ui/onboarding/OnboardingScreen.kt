package com.hirebuddha.dialer.ui.onboarding

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.core.DialerLog
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.MeDto
import com.hirebuddha.dialer.data.logs.LogRepository
import com.hirebuddha.dialer.data.push.PushClient
import com.hirebuddha.dialer.data.repo.DeviceRepository
import com.hirebuddha.dialer.data.settings.AppSettings
import com.hirebuddha.dialer.telecom.CallRegistry
import com.hirebuddha.dialer.telecom.CallState
import com.hirebuddha.dialer.telecom.DialerRole
import com.hirebuddha.dialer.telecom.SimAccounts
import com.hirebuddha.dialer.ui.common.BrandDots
import com.hirebuddha.dialer.ui.common.CardBody
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.Eyebrow
import com.hirebuddha.dialer.ui.common.GoldCard
import com.hirebuddha.dialer.ui.common.GoldPill
import com.hirebuddha.dialer.ui.common.Hairline
import com.hirebuddha.dialer.ui.common.HbButton
import com.hirebuddha.dialer.ui.common.HbButtonSize
import com.hirebuddha.dialer.ui.common.HbButtonStyle
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.common.HbRing
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.MonoText
import com.hirebuddha.dialer.ui.common.PositivePill
import com.hirebuddha.dialer.ui.common.StepRow
import com.hirebuddha.dialer.ui.common.StepState
import com.hirebuddha.dialer.ui.common.goldGlow
import com.hirebuddha.dialer.ui.common.maskPhone
import com.hirebuddha.dialer.ui.theme.BrandType
import com.hirebuddha.dialer.ui.theme.HbTheme
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

private val REQUIRED_PERMISSIONS = buildList {
    add(Manifest.permission.CALL_PHONE)
    add(Manifest.permission.READ_PHONE_STATE)
    add(Manifest.permission.READ_PHONE_NUMBERS)
    if (Build.VERSION.SDK_INT >= 33) add(Manifest.permission.POST_NOTIFICATIONS)
}

fun hasPermissions(context: Context) = REQUIRED_PERMISSIONS.all {
    ContextCompat.checkSelfPermission(context, it) == PackageManager.PERMISSION_GRANTED
}

/**
 * How far the verification call has got. The old screen reported all of this through one
 * mutable string, which is why a failure on a new carrier was impossible to debug from a
 * support call (docs 11 §2.2 F6).
 */
sealed interface VerifyPhase {
    data object Idle : VerifyPhase
    data object Registering : VerifyPhase
    data object Calling : VerifyPhase
    data class SendingCode(val round: Int, val of: Int) : VerifyPhase
    data object Confirming : VerifyPhase
    data object Verified : VerifyPhase
    data class Failed(val message: String) : VerifyPhase
}

@HiltViewModel
class OnboardingViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val devices: DeviceRepository,
    private val settings: AppSettings,
    private val registry: CallRegistry,
    private val push: PushClient,
    private val logs: LogRepository,
) : ViewModel() {
    var permissionsOk by mutableStateOf(hasPermissions(context)); private set
    var roleHeld by mutableStateOf(DialerRole.isHeld(context)); private set
    var sims by mutableStateOf(SimAccounts.list(context)); private set
    var selectedSim by mutableStateOf<String?>(null); private set
    var phase by mutableStateOf<VerifyPhase>(VerifyPhase.Idle); private set
    var verifiedCli by mutableStateOf<String?>(null); private set
    var did by mutableStateOf<String?>(null); private set
    var startedAt by mutableStateOf(0L); private set

    val verifying get() = phase !is VerifyPhase.Idle && phase !is VerifyPhase.Verified && phase !is VerifyPhase.Failed

    init {
        viewModelScope.launch { selectedSim = settings.current().phoneAccountId }
    }

    fun recheck() {
        permissionsOk = hasPermissions(context)
        roleHeld = DialerRole.isHeld(context)
        sims = SimAccounts.list(context)
        if (selectedSim == null && sims.size == 1) chooseSim(sims.first())
    }

    fun chooseSim(sim: SimAccounts.Sim) = viewModelScope.launch {
        settings.setPhoneAccount(sim.id, sim.label)
        selectedSim = sim.id
    }

    fun dismissFailure() { phase = VerifyPhase.Idle }

    /**
     * ADR-001 §1: call the agent DID once and key in the code; the backend records the
     * caller ID exactly as the provider presents it. Unchanged behaviour — every step
     * now reports itself so the rep (and support) can see where it got to.
     */
    fun verify(onDone: () -> Unit) = viewModelScope.launch {
        startedAt = System.currentTimeMillis()
        phase = VerifyPhase.Registering
        DialerLog.i(TAG, "Verification started", "role_held" to roleHeld, "sim" to (selectedSim != null))
        val device = when (val r = devices.register(sims.firstOrNull { it.id == selectedSim }?.label)) {
            is ApiResult.Ok -> r.value
            is ApiResult.Err -> return@launch fail("Register", r.message, r.code)
            ApiResult.Empty -> return@launch fail("Register", "Registration failed.")
        }
        if (device.status == "verified") {
            DialerLog.i(TAG, "Phone already verified")
            verifiedCli = device.verifiedCli
            phase = VerifyPhase.Verified
            logs.flushSoon()
            return@launch
        }
        val v = device.verification ?: return@launch fail("Verification", "No verification issued.")
        did = v.did
        push.start()
        phase = VerifyPhase.Calling

        // Tell the server we are dialling: if the carrier swallows the keypad tones it
        // can still verify us from the caller ID of this very call.
        val simNumber = SimAccounts.selfNumber(context, selectedSim)
        val announced = devices.announceDialing(device.deviceId, simNumber) is ApiResult.Ok
        DialerLog.i(
            TAG, "Placing verification call", "did" to DialerLog.maskNumber(v.did),
            "sim_number_known" to (simNumber != null), "announced" to announced,
        )

        val callId = registry.placeCall(v.did)
        if (callId == null) {
            return@launch fail("Call", "Couldn't place the call. Make sure this app is your default phone app.")
        }
        val connected = withTimeoutOrNull(20_000) {
            registry.calls.filter { list ->
                list.firstOrNull { it.id == callId }?.state in setOf(CallState.ACTIVE, CallState.DISCONNECTED)
            }.first()
        }?.firstOrNull { it.id == callId }?.state == CallState.ACTIVE
        DialerLog.i(TAG, "Verification call connected", "connected" to connected)
        if (!connected) {
            registry.disconnect(callId)
            registry.clearExpectedNumbers()
            return@launch fail("Call", "The verification call didn't connect. Try again.")
        }

        // One burst of tones is easy for a carrier to drop, so repeat the code while the
        // call lasts, checking for confirmation between rounds.
        var confirmed = false
        for (round in 1..DTMF_ROUNDS) {
            delay(if (round == 1) 1_500L else 800L)  // let the media stream settle
            val state = registry.calls.value.firstOrNull { it.id == callId }?.state
            if (state != CallState.ACTIVE) {
                DialerLog.w(TAG, "Verification call ended before the code went through", "state" to state, "round" to round)
                break
            }
            phase = VerifyPhase.SendingCode(round, DTMF_ROUNDS)
            DialerLog.i(TAG, "Playing verification code", "round" to round)
            registry.playDtmf(callId, v.dtmfSequence)
            confirmed = awaitVerified(device.deviceId, ROUND_WAIT_MS)
            if (confirmed) break
        }
        registry.disconnect(callId)
        registry.clearExpectedNumbers()
        if (!confirmed) {
            // The server gives up on the tones after ~20 s and verifies from the caller
            // ID instead; that lands just after the call drops.
            phase = VerifyPhase.Confirming
            confirmed = awaitVerified(device.deviceId, TAIL_WAIT_MS)
        }
        DialerLog.i(TAG, "Verification finished", "verified" to confirmed)
        logs.flush()
        if (confirmed) {
            verifiedCli = (devices.status(device.deviceId) as? ApiResult.Ok)?.value?.verifiedCli
            phase = VerifyPhase.Verified
        } else {
            phase = VerifyPhase.Failed(
                "We couldn't verify this phone. Check that the agent's number is reachable, then try again."
            )
        }
    }

    /** Polls the device status while also listening for the server's push. */
    private suspend fun awaitVerified(deviceId: String, timeoutMs: Long): Boolean =
        withTimeoutOrNull(timeoutMs) {
            val viaPush = launch { push.messages.first { it.type == "device.verified" } }
            var ok = false
            try {
                while (!ok) {
                    ok = viaPush.isCompleted ||
                        (devices.status(deviceId) as? ApiResult.Ok)?.value?.status == "verified"
                    if (!ok) delay(2_000)
                }
            } finally {
                viaPush.cancel()
            }
            ok
        } ?: false

    private fun fail(step: String, message: String, code: String? = null) {
        DialerLog.w(TAG, "Verification failed", "step" to step, "reason" to message, "code" to code)
        phase = VerifyPhase.Failed(message)
        logs.flushSoon()
    }

    private companion object {
        const val TAG = "Verify"
        const val DTMF_ROUNDS = 3
        const val ROUND_WAIT_MS = 6_000L
        const val TAIL_WAIT_MS = 20_000L
    }
}

/** Screens 04–06. */
@Composable
fun OnboardingScreen(
    me: MeDto,
    onDone: () -> Unit,
    onLogout: () -> Unit,
    vm: OnboardingViewModel = hiltViewModel(),
) {
    val context = LocalContext.current
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { vm.recheck() }
    val roleLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { vm.recheck() }
    LaunchedEffect(Unit) { vm.recheck() }

    when {
        vm.verifying -> VerifyingScreen(vm)
        vm.phase is VerifyPhase.Verified -> ReadyScreen(vm, onDone)
        else -> SetupScreen(
            me, vm, onLogout,
            onPermissions = { permissionLauncher.launch(REQUIRED_PERMISSIONS.toTypedArray()) },
            onRole = { roleLauncher.launch(DialerRole.requestIntent(context)) },
        )
    }
}

/** Screen 04. Completed steps collapse so only the live one carries weight. */
@Composable
private fun SetupScreen(
    me: MeDto,
    vm: OnboardingViewModel,
    onLogout: () -> Unit,
    onPermissions: () -> Unit,
    onRole: () -> Unit,
) {
    val c = HbTheme.colors
    val step = when {
        !vm.permissionsOk -> 1
        !vm.roleHeld -> 2
        else -> 3
    }
    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().goldGlow(radiusDp = 210.dp, center = androidx.compose.ui.geometry.Offset(1000f, -120f), alpha = 0.55f))
        Column(
            Modifier.fillMaxSize().statusBarsPadding().verticalScroll(rememberScrollState())
                .padding(horizontal = HbTheme.dims.gutter).navigationBarsPadding(),
        ) {
            Row(Modifier.fillMaxWidth().height(56.dp), verticalAlignment = Alignment.CenterVertically) {
                Eyebrow("Step $step of 3", Modifier.weight(1f))
                MonoText("~2 min")
            }
            Text("Set up this phone", style = MaterialTheme.typography.headlineMedium, color = c.fg)
            Spacer(Modifier.height(8.dp))
            CardBody(
                "${me.fullName.substringBefore(' ')} — HireBuddha needs to place two calls from your SIM " +
                    "and join them, so Android asks for a little more than usual.",
            )
            Spacer(Modifier.height(20.dp))

            CollapsedStep(
                n = 1, title = "Calling permissions",
                detail = "Phone, SIM list, notifications",
                done = vm.permissionsOk, active = step == 1,
                actionLabel = "Allow", onAction = onPermissions,
            )
            Spacer(Modifier.height(10.dp))
            CollapsedStep(
                n = 2, title = "Default phone app",
                detail = "So we can hear the lead pick up and merge the calls. Your normal calls still work.",
                done = vm.roleHeld, active = step == 2,
                actionLabel = "Set as default", onAction = onRole, enabled = vm.permissionsOk,
            )
            Spacer(Modifier.height(10.dp))

            if (step == 3) {
                GoldCard(Modifier.fillMaxWidth()) {
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        StepBadge(3, active = true)
                        Column(Modifier.weight(1f)) {
                            Text("Verify your number", style = MaterialTheme.typography.titleMedium, color = c.fg)
                            CardCaption("One 15-second call to your agent, so the system can recognise your caller ID")
                        }
                    }
                    Spacer(Modifier.height(16.dp))
                    Eyebrow("Calling SIM", color = c.fgSubtle)
                    Spacer(Modifier.height(8.dp))
                    if (vm.sims.isEmpty()) {
                        CardCaption("No SIM that can place calls was found.")
                    }
                    vm.sims.forEach { sim ->
                        SimRow(
                            label = sim.label,
                            // Reps with two SIMs have to guess today; showing the number
                            // each choice maps to is the whole fix.
                            number = SimAccounts.selfNumber(LocalContext.current, sim.id)?.let { maskPhone(it) },
                            selected = vm.selectedSim == sim.id,
                            recommended = vm.sims.size > 1 && sim == vm.sims.first(),
                        ) { vm.chooseSim(sim) }
                        Spacer(Modifier.height(8.dp))
                    }
                    Spacer(Modifier.height(8.dp))
                    HbButton(
                        "Place the verification call",
                        { vm.verify {} },
                        Modifier.fillMaxWidth(),
                        HbButtonStyle.Hero,
                        HbButtonSize.Large,
                        icon = R.drawable.ic_phone,
                        enabled = vm.permissionsOk && vm.roleHeld && vm.selectedSim != null,
                    )
                    Spacer(Modifier.height(10.dp))
                    MicroText("Free on your plan. We never read your call log.", Modifier.fillMaxWidth())
                    (vm.phase as? VerifyPhase.Failed)?.let {
                        Spacer(Modifier.height(10.dp))
                        MicroText(it.message, color = c.negative)
                    }
                }
            }

            Spacer(Modifier.height(20.dp))
            HbButton("Log out", onLogout, Modifier.fillMaxWidth(), HbButtonStyle.Ghost, HbButtonSize.Small)
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun CollapsedStep(
    n: Int,
    title: String,
    detail: String,
    done: Boolean,
    active: Boolean,
    actionLabel: String,
    onAction: () -> Unit,
    enabled: Boolean = true,
) {
    val c = HbTheme.colors
    HbCard(Modifier.fillMaxWidth(), padding = 14.dp) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            StepBadge(n, done = done, active = active)
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleMedium, color = c.fg)
                if (!done) CardCaption(detail) else MicroText(detail)
            }
            if (done) PositivePill("Done") else Unit
        }
        if (!done && active) {
            Spacer(Modifier.height(12.dp))
            HbButton(actionLabel, onAction, Modifier.fillMaxWidth(), HbButtonStyle.Primary, enabled = enabled)
        }
    }
}

@Composable
private fun StepBadge(n: Int, done: Boolean = false, active: Boolean = false) {
    val c = HbTheme.colors
    Box(
        Modifier.size(26.dp).clip(CircleShape)
            .background(if (done) c.positive else if (active) c.accentQuiet else Color.Transparent)
            .border(if (done) 0.dp else 1.75.dp, if (active) c.accent else c.borderStrong, CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        if (done) HbIcon(R.drawable.ic_check, size = 14.dp, tint = Color(0xFF0F2015))
        else MonoText("$n", color = if (active) c.accent else c.fgFaint)
    }
}

@Composable
private fun SimRow(
    label: String,
    number: String?,
    selected: Boolean,
    recommended: Boolean,
    onSelect: () -> Unit,
) {
    val c = HbTheme.colors
    Row(
        Modifier.fillMaxWidth()
            .clip(RoundedCornerShape(HbTheme.dims.rMd))
            .background(c.surface2)
            .border(1.dp, if (selected) c.borderGold else c.border, RoundedCornerShape(HbTheme.dims.rMd))
            .clickable(onClick = onSelect)
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Box(
            Modifier.size(20.dp).clip(CircleShape)
                .border(1.75.dp, if (selected) c.accent else c.borderStrong, CircleShape),
            contentAlignment = Alignment.Center,
        ) { if (selected) Box(Modifier.size(10.dp).clip(CircleShape).background(c.accent)) }
        Column(Modifier.weight(1f)) {
            Text(
                label,
                style = MaterialTheme.typography.titleSmall,
                color = if (selected) c.fg else c.fgMuted,
            )
            number?.let { MonoText(it) }
        }
        if (recommended) GoldPill("Recommended")
    }
}

/** Screen 05 — the riskiest 40 seconds in the product, finally legible. */
@Composable
private fun VerifyingScreen(vm: OnboardingViewModel) {
    val c = HbTheme.colors
    var elapsed by androidx.compose.runtime.remember { mutableStateOf(0) }
    LaunchedEffect(vm.startedAt) {
        while (true) {
            elapsed = ((System.currentTimeMillis() - vm.startedAt) / 1000).toInt()
            delay(500)
        }
    }
    val phase = vm.phase

    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().goldGlow(radiusDp = 260.dp, center = androidx.compose.ui.geometry.Offset(170f, 700f)))
        Column(
            Modifier.fillMaxSize().statusBarsPadding().padding(horizontal = HbTheme.dims.gutter)
                .navigationBarsPadding(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            HbRing(
                fraction = (elapsed / 45f).coerceIn(0f, 1f),
                diameter = 132.dp,
                stroke = 3.dp,
            ) {
                HbIcon(R.drawable.ic_phone, size = 30.dp, tint = c.accent)
                Spacer(Modifier.height(6.dp))
                MonoText("%d:%02d".format(elapsed / 60, elapsed % 60), color = c.gold300, style = BrandType.monoBody)
            }
            Spacer(Modifier.height(28.dp))
            Text(
                when (phase) {
                    is VerifyPhase.SendingCode -> "Listening for your tones"
                    VerifyPhase.Confirming -> "Confirming with the server"
                    else -> "Calling your agent"
                },
                style = MaterialTheme.typography.headlineSmall,
                color = c.fg,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(8.dp))
            CardBody(
                when (phase) {
                    is VerifyPhase.SendingCode ->
                        "Stay on the call. We're playing a short keypad code so the agent can match this phone to you."
                    VerifyPhase.Confirming ->
                        "The tones didn't get through. We're checking whether your caller ID was enough."
                    else -> "This takes about fifteen seconds."
                },
                Modifier.fillMaxWidth(),
            )

            Spacer(Modifier.height(24.dp))
            HbCard(Modifier.fillMaxWidth()) {
                val reached = phaseRank(phase)
                VerifyStep("Phone registered", 0, reached, isLast = false)
                VerifyStep(
                    vm.did?.let { "Connected to $it" } ?: "Connected to your agent",
                    1, reached, isLast = false,
                )
                VerifyStep(
                    "Sending the keypad code", 2, reached, isLast = false,
                    detail = (phase as? VerifyPhase.SendingCode)?.let { "Round ${it.round} of ${it.of}" },
                )
                VerifyStep("Caller ID confirmed", 3, reached, isLast = true)
            }
        }
    }
}

private fun phaseRank(phase: VerifyPhase): Int = when (phase) {
    VerifyPhase.Idle, VerifyPhase.Registering -> 0
    VerifyPhase.Calling -> 1
    is VerifyPhase.SendingCode -> 2
    VerifyPhase.Confirming -> 3
    VerifyPhase.Verified -> 4
    is VerifyPhase.Failed -> 3
}

@Composable
private fun VerifyStep(label: String, rank: Int, reached: Int, isLast: Boolean, detail: String? = null) =
    StepRow(
        state = when {
            reached > rank -> StepState.Done
            reached == rank -> StepState.Current
            else -> StepState.Upcoming
        },
        label = label,
        detail = detail,
        isLast = isLast,
    )

/** Screen 06 — the one place to introduce the two limits that will otherwise surprise. */
@Composable
private fun ReadyScreen(vm: OnboardingViewModel, onDone: () -> Unit) {
    val c = HbTheme.colors
    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().goldGlow(radiusDp = 280.dp, center = androidx.compose.ui.geometry.Offset(170f, 500f), alpha = 0.75f))
        com.hirebuddha.dialer.ui.common.MarkWatermark(
            Modifier.align(Alignment.Center), height = 700.dp, alpha = 0.06f,
        )
        Column(
            Modifier.fillMaxSize().statusBarsPadding().padding(horizontal = HbTheme.dims.gutter)
                .navigationBarsPadding(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                Modifier.size(72.dp).clip(CircleShape).background(c.positiveQuiet)
                    .border(1.dp, c.positive.copy(alpha = 0.42f), CircleShape),
                contentAlignment = Alignment.Center,
            ) { HbIcon(R.drawable.ic_check, size = 34.dp, tint = c.positive) }
            Spacer(Modifier.height(24.dp))
            Text("This phone is ready", style = MaterialTheme.typography.headlineSmall, color = c.fg)
            Spacer(Modifier.height(8.dp))
            CardBody(
                "Your agent will recognise calls from this number from now on.",
                Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(24.dp))
            HbCard(Modifier.fillMaxWidth()) {
                Fact("Verified number", vm.verifiedCli?.let { maskPhone(it) } ?: "recorded")
                Hairline()
                Fact("Calling SIM", vm.sims.firstOrNull { it.id == vm.selectedSim }?.label ?: "chosen")
            }
            Spacer(Modifier.height(20.dp))
            HbButton(
                "Start working", onDone, Modifier.fillMaxWidth(),
                HbButtonStyle.Primary, HbButtonSize.Large,
            )
        }
    }
}

@Composable
private fun Fact(label: String, value: String) = Row(
    Modifier.fillMaxWidth().padding(vertical = 10.dp),
    verticalAlignment = Alignment.CenterVertically,
) {
    CardCaption(label, Modifier.weight(1f))
    MonoText(value, color = HbTheme.colors.fg, style = BrandType.monoBody)
}
