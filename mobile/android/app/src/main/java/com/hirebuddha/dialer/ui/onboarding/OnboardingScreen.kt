package com.hirebuddha.dialer.ui.onboarding

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.outlined.Circle
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.MeDto
import com.hirebuddha.dialer.data.push.PushClient
import com.hirebuddha.dialer.data.repo.DeviceRepository
import com.hirebuddha.dialer.data.settings.AppSettings
import com.hirebuddha.dialer.telecom.CallRegistry
import com.hirebuddha.dialer.telecom.CallState
import com.hirebuddha.dialer.telecom.DialerRole
import com.hirebuddha.dialer.telecom.SimAccounts
import com.hirebuddha.dialer.ui.theme.StatusColors
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

@HiltViewModel
class OnboardingViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val devices: DeviceRepository,
    private val settings: AppSettings,
    private val registry: CallRegistry,
    private val push: PushClient,
) : ViewModel() {
    var permissionsOk by mutableStateOf(hasPermissions(context)); private set
    var roleHeld by mutableStateOf(DialerRole.isHeld(context)); private set
    var sims by mutableStateOf(SimAccounts.list(context)); private set
    var selectedSim by mutableStateOf<String?>(null); private set
    var verifying by mutableStateOf(false); private set
    var verified by mutableStateOf(false); private set
    var status by mutableStateOf<String?>(null); private set

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

    /**
     * ADR-001 §1: call the agent DID once and key in the code; the backend records the
     * caller ID exactly as the provider presents it.
     */
    fun verify(onDone: () -> Unit) = viewModelScope.launch {
        verifying = true
        status = "Registering this phone…"
        val label = sims.firstOrNull { it.id == selectedSim }?.label
        val device = when (val r = devices.register(label)) {
            is ApiResult.Ok -> r.value
            is ApiResult.Err -> { status = r.message; verifying = false; return@launch }
            ApiResult.Empty -> { status = "Registration failed."; verifying = false; return@launch }
        }
        if (device.status == "verified") {
            verified = true; verifying = false; onDone(); return@launch
        }
        val v = device.verification ?: run { status = "No verification issued."; verifying = false; return@launch }
        push.start()
        status = "Calling HireBuddha to verify your number…"
        val callId = registry.placeCall(v.did)
        if (callId == null) {
            status = "Couldn't place the call. Make sure this app is your default phone app."
            verifying = false
            return@launch
        }
        val active = withTimeoutOrNull(20_000) {
            registry.calls.filter { list -> list.firstOrNull { it.id == callId }?.state in setOf(CallState.ACTIVE, CallState.DISCONNECTED) }.first()
        }?.firstOrNull { it.id == callId }?.state == CallState.ACTIVE
        if (!active) {
            registry.disconnect(callId)
            status = "The verification call didn't connect. Try again."
            verifying = false
            return@launch
        }
        delay(1_500)  // let the media stream start before keying the code
        status = "Sending verification code…"
        registry.playDtmf(callId, v.dtmfSequence)
        val confirmed = withTimeoutOrNull(25_000) {
            val viaPush = launch { push.messages.first { it.type == "device.verified" } }
            while (true) {
                if (viaPush.isCompleted) break
                if ((devices.status(device.deviceId) as? ApiResult.Ok)?.value?.status == "verified") break
                delay(2_000)
            }
            viaPush.cancel()
            true
        } ?: false
        registry.disconnect(callId)
        registry.clearExpectedNumbers()
        verifying = false
        if (confirmed) {
            verified = true
            status = "Phone verified."
            onDone()
        } else {
            status = "We couldn't confirm the code. Check the agent's number and try again."
        }
    }
}

@Composable
fun OnboardingScreen(me: MeDto, onDone: () -> Unit, onLogout: () -> Unit, vm: OnboardingViewModel = hiltViewModel()) {
    val context = LocalContext.current
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { vm.recheck() }
    val roleLauncher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { vm.recheck() }
    LaunchedEffect(Unit) { vm.recheck() }

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 32.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Set up this phone", style = MaterialTheme.typography.headlineSmall)
        Text(
            "Hi ${me.fullName.substringBefore(' ')}. Three quick steps so HireBuddha can call leads from your SIM and bring in the AI agent.",
            style = MaterialTheme.typography.bodyMedium,
        )

        StepCard(1, "Allow calling permissions", vm.permissionsOk) {
            Button(onClick = { permissionLauncher.launch(REQUIRED_PERMISSIONS.toTypedArray()) }) { Text("Allow") }
        }
        StepCard(2, "Make HireBuddha your phone app", vm.roleHeld,
            detail = "Needed to detect when a lead answers, merge the calls and mute you. Normal calls still work.") {
            Button(onClick = { roleLauncher.launch(DialerRole.requestIntent(context)) }, enabled = vm.permissionsOk) { Text("Set as default") }
        }
        StepCard(3, "Choose SIM and verify your number", vm.verified,
            detail = "We place one short call to your company's AI number to record your caller ID.") {
            Column {
                if (vm.sims.isEmpty() && vm.permissionsOk) Text("No SIM that can place calls was found.")
                vm.sims.forEach { sim ->
                    Row(
                        Modifier.fillMaxWidth().selectable(selected = vm.selectedSim == sim.id, onClick = { vm.chooseSim(sim) }),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        RadioButton(selected = vm.selectedSim == sim.id, onClick = { vm.chooseSim(sim) })
                        Text(sim.label)
                    }
                }
                Spacer(Modifier.height(8.dp))
                Button(
                    onClick = { vm.verify(onDone) },
                    enabled = vm.permissionsOk && vm.roleHeld && vm.selectedSim != null && !vm.verifying,
                ) { Text(if (vm.verifying) "Verifying…" else "Verify my number") }
                vm.status?.let { Text(it, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 6.dp)) }
            }
        }
        TextButton(onClick = onLogout) { Text("Log out") }
    }
}

@Composable
private fun StepCard(n: Int, title: String, done: Boolean, detail: String? = null, action: @Composable () -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    if (done) Icons.Filled.CheckCircle else Icons.Outlined.Circle, contentDescription = null,
                    tint = if (done) StatusColors.positive else MaterialTheme.colorScheme.outline,
                )
                Text("  $n. $title", style = MaterialTheme.typography.titleMedium)
            }
            detail?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            if (!done) action()
        }
    }
}
