package com.hirebuddha.dialer.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.hirebuddha.dialer.BuildConfig
import com.hirebuddha.dialer.data.api.MeDto
import com.hirebuddha.dialer.data.settings.AppSettings
import com.hirebuddha.dialer.data.settings.DialerPrefs
import com.hirebuddha.dialer.ui.login.ServerSettings
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.launch

@HiltViewModel
class SettingsViewModel @Inject constructor(val settings: AppSettings) : ViewModel()

@Composable
fun SettingsScreen(me: MeDto, onLogout: () -> Unit, onReverify: () -> Unit, modifier: Modifier = Modifier, vm: SettingsViewModel = hiltViewModel()) {
    val prefs by vm.settings.prefs.collectAsStateWithLifecycle(initialValue = null as DialerPrefs?)
    val scope = rememberCoroutineScope()
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Settings", style = MaterialTheme.typography.headlineSmall)
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(me.fullName, style = MaterialTheme.typography.titleMedium)
                Text("${me.email} · ${if (me.isAdmin) "Tenant admin" else "Rep"}", style = MaterialTheme.typography.bodySmall)
                me.companyName?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
            }
        }
        prefs?.let { p ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Calling", style = MaterialTheme.typography.titleMedium)
                    Text("SIM: ${p.phoneAccountLabel ?: "not chosen"}", style = MaterialTheme.typography.bodyMedium)
                    OutlinedButton(onClick = onReverify) { Text("Change SIM / verify again") }
                    Text("Pause between leads: ${p.gapSeconds}s", style = MaterialTheme.typography.bodyMedium)
                    Slider(value = p.gapSeconds.toFloat(), onValueChange = { v -> scope.launch { vm.settings.setGapSeconds(v.toInt()) } }, valueRange = 0f..30f, steps = 29)
                    Text("Ring the lead for: ${p.leadRingTimeoutSeconds}s", style = MaterialTheme.typography.bodyMedium)
                    Slider(value = p.leadRingTimeoutSeconds.toFloat(), onValueChange = { v -> scope.launch { vm.settings.setLeadRingTimeout(v.toInt()) } }, valueRange = 15f..60f, steps = 44)
                    Text("You're muted automatically when the lead joins; tap Unmute on the call screen to speak.",
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        Card(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp)) {
                Text("Server", style = MaterialTheme.typography.titleMedium)
                ServerSettings(vm.settings)
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Version ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})", Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
            OutlinedButton(onClick = onLogout) { Text("Log out") }
        }
    }
}
