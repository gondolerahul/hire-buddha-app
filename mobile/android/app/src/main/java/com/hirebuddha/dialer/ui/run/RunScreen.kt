package com.hirebuddha.dialer.ui.run

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CallEnd
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material.icons.filled.RecordVoiceOver
import androidx.compose.material.icons.outlined.Circle
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.hirebuddha.dialer.run.RunController
import com.hirebuddha.dialer.run.RunStatus
import com.hirebuddha.dialer.run.RunUiState
import com.hirebuddha.dialer.run.Step
import com.hirebuddha.dialer.run.UserCommand
import com.hirebuddha.dialer.ui.common.humanize
import com.hirebuddha.dialer.ui.theme.StatusColors
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@HiltViewModel
class RunViewModel @Inject constructor(val controller: RunController) : ViewModel()

private val STEPS = listOf(
    Step.CONNECTING_AI to "Connecting AI agent",
    Step.WAITING_AI to "AI ready",
    Step.CALLING_LEAD to "Calling lead",
    Step.MERGING to "Merging calls",
    Step.IN_CONVERSATION to "In conversation",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RunScreen(onBack: () -> Unit, vm: RunViewModel = hiltViewModel()) {
    val s by vm.controller.state.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { now = System.currentTimeMillis(); delay(1_000) } }

    Scaffold(topBar = {
        TopAppBar(
            title = { Text(s.campaignName ?: "Campaign run") },
            navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
        )
    }) { padding ->
        Column(
            Modifier.padding(padding).fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            StatusHeader(s, onPause = vm.controller::pause, onStop = vm.controller::stop, onResume = { scope.launch { vm.controller.resume() } })
            s.lead?.let { lead ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("CURRENT LEAD", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(lead.name ?: maskPhone(lead.phone), style = MaterialTheme.typography.headlineSmall)
                        if (lead.name != null) Text(maskPhone(lead.phone), style = MaterialTheme.typography.bodyMedium)
                        lead.fields.filterKeys { it.lowercase() != "name" }.entries.take(4).forEach { (k, v) ->
                            Text("${humanize(k)}: $v", style = MaterialTheme.typography.bodySmall)
                        }
                        Text("${lead.remaining} leads left after this one", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            if (s.status == RunStatus.RUNNING) StepList(s, now)
            if (s.step == Step.IN_CONVERSATION) InCallControls(s, vm.controller)
            s.message?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = if (s.status == RunStatus.ERROR) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface) }
            s.lastOutcome?.let { Text("Last call: $it · ${s.callsMade} calls this session", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
    }

    if (s.awaitingMergeDecision) {
        AlertDialog(
            onDismissRequest = {},
            title = { Text("Lead not confirmed") },
            text = { Text("The AI couldn't confirm which lead this call is for, so it won't know their name or details. Call the lead anyway?") },
            confirmButton = { TextButton(onClick = { vm.controller.decideMerge(true) }) { Text("Call anyway") } },
            dismissButton = { TextButton(onClick = { vm.controller.decideMerge(false) }) { Text("Skip for now") } },
        )
    }
}

@Composable
private fun StatusHeader(s: RunUiState, onPause: () -> Unit, onStop: () -> Unit, onResume: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(humanize(s.status.name.lowercase()), style = MaterialTheme.typography.titleMedium,
                color = when (s.status) { RunStatus.RUNNING -> StatusColors.positive; RunStatus.ERROR -> StatusColors.negative; else -> StatusColors.warning })
            if (s.nextLeadAt != null) Text("Next lead in a few seconds", style = MaterialTheme.typography.bodySmall)
        }
        when (s.status) {
            RunStatus.RUNNING -> {
                OutlinedButton(onClick = onPause) { Text("Pause") }
                Spacer(Modifier.size(8.dp))
                OutlinedButton(onClick = onStop) { Text("Stop") }
            }
            RunStatus.PAUSED -> {
                Button(onClick = onResume) { Text("Resume") }
                Spacer(Modifier.size(8.dp))
                OutlinedButton(onClick = onStop) { Text("Stop") }
            }
            else -> Unit
        }
    }
    if (s.status == RunStatus.RUNNING && s.step != Step.IN_CONVERSATION && s.step != Step.IDLE) {
        Text("Pause and Stop take effect after the current call.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun StepList(s: RunUiState, now: Long) {
    val currentIndex = STEPS.indexOfFirst { it.first == s.step }.let { idx ->
        when (s.step) {
            Step.SENDING_CODE -> 0
            Step.WAITING_NEXT, Step.WRAPPING_UP -> STEPS.size
            else -> idx
        }
    }
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            STEPS.forEachIndexed { i, (step, label) ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    when {
                        i < currentIndex -> Icon(Icons.Filled.CheckCircle, null, tint = StatusColors.positive)
                        i == currentIndex -> CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
                        else -> Icon(Icons.Outlined.Circle, null, tint = MaterialTheme.colorScheme.outline)
                    }
                    val suffix = when {
                        step == Step.WAITING_AI && i < currentIndex && s.identification != null -> " · identified via ${s.identification}"
                        step == Step.IN_CONVERSATION && s.conversationStartedAt != null -> " · ${formatDuration(now - s.conversationStartedAt)}"
                        else -> ""
                    }
                    Text("  $label$suffix", style = MaterialTheme.typography.bodyLarge)
                }
            }
        }
    }
}

@Composable
private fun InCallControls(s: RunUiState, controller: RunController) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                if (s.muted) "You're muted. The AI is talking to the lead." else "You're unmuted — the lead can hear you.",
                style = MaterialTheme.typography.bodyMedium,
            )
            FilledTonalButton(onClick = { controller.command(UserCommand.TOGGLE_MUTE) }, modifier = Modifier.fillMaxWidth().height(52.dp)) {
                Icon(if (s.muted) Icons.Filled.Mic else Icons.Filled.MicOff, null)
                Text(if (s.muted) "  Unmute to speak" else "  Mute me")
            }
            if (s.aiInCall) {
                OutlinedButton(onClick = { controller.command(UserCommand.TAKE_OVER) }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Filled.RecordVoiceOver, null)
                    Text("  Take over (drop the AI)")
                }
            }
            Button(
                onClick = { controller.command(UserCommand.HANG_UP) },
                colors = ButtonDefaults.buttonColors(containerColor = StatusColors.negative),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Filled.CallEnd, null)
                Text("  End call")
            }
        }
    }
}

private fun formatDuration(ms: Long): String {
    val total = (ms / 1000).coerceAtLeast(0)
    return "%d:%02d".format(total / 60, total % 60)
}

fun maskPhone(phone: String): String =
    if (phone.length <= 4) phone else phone.take(3) + "•".repeat((phone.length - 7).coerceAtLeast(0)) + phone.takeLast(4)
