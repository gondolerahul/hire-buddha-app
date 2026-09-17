package com.hirebuddha.dialer.ui.campaigns

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.outlined.UploadFile
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuAnchorType
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.hirebuddha.dialer.core.stringMap
import com.hirebuddha.dialer.data.api.AgentDto
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.CreateCampaignRequest
import com.hirebuddha.dialer.data.api.MeDto
import com.hirebuddha.dialer.data.api.RepDto
import com.hirebuddha.dialer.data.api.UploadReportDto
import com.hirebuddha.dialer.data.repo.CampaignRepository
import com.hirebuddha.dialer.ui.common.StatTile
import com.hirebuddha.dialer.ui.common.humanize
import com.hirebuddha.dialer.ui.theme.StatusColors
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.launch

@HiltViewModel
class CreateCampaignViewModel @Inject constructor(private val repo: CampaignRepository) : ViewModel() {
    var report by mutableStateOf<UploadReportDto?>(null); private set
    var uploading by mutableStateOf(false); private set
    var agents by mutableStateOf<List<AgentDto>>(emptyList()); private set
    var reps by mutableStateOf<List<RepDto>>(emptyList()); private set
    var name by mutableStateOf("")
    var agentId by mutableStateOf<String?>(null)
    var assignees by mutableStateOf(setOf<String>())
    var creating by mutableStateOf(false); private set
    var error by mutableStateOf<String?>(null); private set

    fun init(isAdmin: Boolean) = viewModelScope.launch {
        when (val r = repo.agents()) {
            is ApiResult.Ok -> { agents = r.value; if (r.value.size == 1) agentId = r.value.first().agentId }
            is ApiResult.Err -> error = r.message
            ApiResult.Empty -> Unit
        }
        if (isAdmin) (repo.reps() as? ApiResult.Ok)?.let { reps = it.value }
    }

    fun upload(context: Context, uri: Uri, fileName: String?) = viewModelScope.launch {
        uploading = true
        error = null
        when (val r = repo.upload(context.contentResolver, uri)) {
            is ApiResult.Ok -> {
                report = r.value
                if (name.isBlank()) name = fileName?.substringBeforeLast('.').orEmpty()
            }
            is ApiResult.Err -> error = r.message
            ApiResult.Empty -> error = "Upload failed."
        }
        uploading = false
    }

    fun create(isAdmin: Boolean, onCreated: (String) -> Unit) = viewModelScope.launch {
        val upload = report ?: return@launch
        val agent = agentId ?: run { error = "Choose an AI agent."; return@launch }
        if (name.isBlank()) { error = "Name the campaign."; return@launch }
        creating = true
        error = null
        val request = CreateCampaignRequest(
            agentId = agent, name = name.trim(), contactUploadId = upload.uploadId,
            assigneeUserIds = if (isAdmin && assignees.isNotEmpty()) assignees.toList() else null,
        )
        when (val r = repo.create(request)) {
            is ApiResult.Ok -> onCreated(r.value.id)
            is ApiResult.Err -> error = r.message
            ApiResult.Empty -> error = "Couldn't create the campaign."
        }
        creating = false
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CreateCampaignScreen(me: MeDto, onBack: () -> Unit, onCreated: (String) -> Unit, vm: CreateCampaignViewModel = hiltViewModel()) {
    val context = LocalContext.current
    remember { vm.init(me.isAdmin); true }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            val name = context.contentResolver.query(uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)
                ?.use { if (it.moveToFirst()) it.getString(0) else null }
            vm.upload(context, uri, name)
        }
    }
    Scaffold(topBar = {
        TopAppBar(
            title = { Text("New campaign") },
            navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back") } },
        )
    }) { padding ->
        LazyColumn(Modifier.padding(padding), contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item {
                OutlinedButton(
                    onClick = {
                        picker.launch(arrayOf(
                            "text/csv", "text/comma-separated-values", "text/plain",
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            "application/octet-stream",
                        ))
                    },
                    enabled = !vm.uploading,
                    modifier = Modifier.fillMaxWidth().height(56.dp),
                ) {
                    Icon(Icons.Outlined.UploadFile, null)
                    Text(if (vm.uploading) "  Uploading…" else if (vm.report == null) "  Choose .xlsx or .csv file" else "  Choose a different file")
                }
                Text("Needs a phone column (phone / mobile / contact). Other columns become details the AI can use, like name or city.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp))
            }
            vm.report?.let { r -> reportItems(r) }
            if (vm.report != null) {
                item {
                    OutlinedTextField(vm.name, { vm.name = it }, label = { Text("Campaign name") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                }
                item { AgentPicker(vm.agents, vm.agentId) { vm.agentId = it } }
                if (me.isAdmin && vm.reps.isNotEmpty()) {
                    item { Text("Assign reps (defaults to you)", style = MaterialTheme.typography.titleMedium) }
                    items(vm.reps, key = { it.userId }) { rep ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(rep.userId in vm.assignees, { checked ->
                                vm.assignees = if (checked) vm.assignees + rep.userId else vm.assignees - rep.userId
                            })
                            Column {
                                Text(rep.name)
                                Text(humanize(rep.role), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
                item {
                    Button(
                        onClick = { vm.create(me.isAdmin, onCreated) },
                        enabled = !vm.creating && (vm.report?.validRows ?: 0) > 0,
                        modifier = Modifier.fillMaxWidth().height(52.dp),
                    ) { Text(if (vm.creating) "Creating…" else "Create campaign with ${vm.report?.validRows ?: 0} leads") }
                }
            }
            vm.error?.let { item { Text(it, color = MaterialTheme.colorScheme.error) } }
        }
    }
}

private fun androidx.compose.foundation.lazy.LazyListScope.reportItems(r: UploadReportDto) {
    item {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            StatTile("Valid", "${r.validRows}", Modifier.weight(1f))
            StatTile("Invalid", "${r.invalidRows}", Modifier.weight(1f))
            StatTile("Duplicates", "${r.duplicateRows}", Modifier.weight(1f))
        }
    }
    if (r.errors.isNotEmpty()) {
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text("Rows skipped", style = MaterialTheme.typography.titleMedium)
                    r.errors.take(50).forEach { e ->
                        Text("Row ${e.row}: ${e.value.ifBlank { "(empty)" }} — ${humanize(e.reason)}",
                            style = MaterialTheme.typography.bodySmall, color = if (e.reason == "duplicate") StatusColors.neutral else StatusColors.negative)
                    }
                    if (r.errors.size > 50) Text("…and ${r.errors.size - 50} more", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
    if (r.preview.isNotEmpty()) {
        item {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("Preview", style = MaterialTheme.typography.titleMedium)
                    r.preview.take(5).forEach { row ->
                        val fields = row.stringMap()
                        Text(
                            listOfNotNull(fields["name"] ?: fields["Name"], fields["phone"]).joinToString(" · ") +
                                fields.filterKeys { it !in setOf("phone", "name", "Name") }.entries.take(2).joinToString("") { " · ${it.value}" },
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AgentPicker(agents: List<AgentDto>, selected: String?, onSelect: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    val current = agents.firstOrNull { it.agentId == selected }
    ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }) {
        OutlinedTextField(
            value = current?.let { "${it.name} · ${it.did ?: ""}" } ?: if (agents.isEmpty()) "No voice agent with a phone number" else "Choose AI agent",
            onValueChange = {}, readOnly = true, label = { Text("AI agent") },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
            modifier = Modifier.fillMaxWidth().menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable),
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            agents.forEach { a ->
                DropdownMenuItem(text = { Text("${a.name} · ${a.did ?: ""}") }, onClick = { onSelect(a.agentId); expanded = false })
            }
        }
    }
}
