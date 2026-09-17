package com.hirebuddha.dialer.ui.calls

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.TimelineEntryDto
import com.hirebuddha.dialer.data.api.VoiceSessionDto
import com.hirebuddha.dialer.data.repo.CampaignRepository
import com.hirebuddha.dialer.ui.common.Loading
import com.hirebuddha.dialer.ui.common.humanize
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.launch

@HiltViewModel
class CallDetailViewModel @Inject constructor(private val repo: CampaignRepository) : ViewModel() {
    var session by mutableStateOf<VoiceSessionDto?>(null); private set
    var timeline by mutableStateOf<List<TimelineEntryDto>>(emptyList()); private set
    var loading by mutableStateOf(true); private set
    var error by mutableStateOf<String?>(null); private set

    fun load(sessionId: String?, attemptId: String?) = viewModelScope.launch {
        loading = true
        if (sessionId != null) {
            when (val r = repo.voiceSession(sessionId)) {
                is ApiResult.Ok -> session = r.value
                is ApiResult.Err -> error = r.message
                ApiResult.Empty -> Unit
            }
        }
        if (attemptId != null) (repo.timeline(attemptId) as? ApiResult.Ok)?.let { timeline = it.value.timeline }
        loading = false
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CallDetailScreen(sessionId: String?, attemptId: String?, title: String, onBack: () -> Unit, vm: CallDetailViewModel = hiltViewModel()) {
    LaunchedEffect(sessionId, attemptId) { vm.load(sessionId, attemptId) }
    Scaffold(topBar = {
        TopAppBar(title = { Text(title) }, navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } })
    }) { padding ->
        if (vm.loading) {
            Loading(Modifier.padding(padding))
            return@Scaffold
        }
        LazyColumn(Modifier.padding(padding), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            vm.error?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
            vm.session?.let { s ->
                item {
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text("AI summary", style = MaterialTheme.typography.titleMedium)
                            Text(s.callSummary ?: "Summary not available yet.", style = MaterialTheme.typography.bodyMedium)
                            s.durationSeconds?.let { Text("AI leg duration: ${it / 60}m ${it % 60}s", style = MaterialTheme.typography.bodySmall) }
                            s.nextAction?.let { Text("Next action: $it", style = MaterialTheme.typography.bodySmall) }
                        }
                    }
                }
                if (s.transcript.isNotEmpty()) {
                    item { Text("Transcript", style = MaterialTheme.typography.titleMedium) }
                    items(s.transcript) { turn -> Bubble(turn.speaker, turn.content) }
                }
            }
            if (vm.timeline.isNotEmpty()) {
                item { Text("Call timeline", style = MaterialTheme.typography.titleMedium) }
                items(vm.timeline) { e ->
                    Row {
                        Text(e.at.substringAfter('T').take(8), Modifier.widthIn(min = 72.dp), style = MaterialTheme.typography.bodySmall)
                        Text(humanize(e.type), style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
            if (vm.session == null && vm.timeline.isEmpty() && vm.error == null) {
                item { Text("No recording or transcript for this call — the lead didn't connect to the AI.") }
            }
        }
    }
}

@Composable
private fun Bubble(speaker: String, text: String) {
    val agent = speaker == "agent"
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (agent) Arrangement.Start else Arrangement.End) {
        Column(
            Modifier.widthIn(max = 300.dp).clip(RoundedCornerShape(12.dp))
                .background(if (agent) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.primaryContainer)
                .padding(10.dp),
            horizontalAlignment = if (agent) Alignment.Start else Alignment.End,
        ) {
            Text(if (agent) "AI agent" else "Lead", style = MaterialTheme.typography.labelSmall)
            Text(text, style = MaterialTheme.typography.bodyMedium)
        }
    }
}
