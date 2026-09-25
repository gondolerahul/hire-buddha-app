package com.hirebuddha.dialer.ui.campaigns

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.hirebuddha.dialer.R
import androidx.compose.ui.draw.alpha
import com.hirebuddha.dialer.core.stringMap
import com.hirebuddha.dialer.data.api.AgentDto
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.CreateCampaignRequest
import com.hirebuddha.dialer.data.api.MeDto
import com.hirebuddha.dialer.data.api.RepDto
import com.hirebuddha.dialer.data.api.UploadReportDto
import com.hirebuddha.dialer.data.repo.CampaignRepository
import com.hirebuddha.dialer.ui.common.Avatar
import com.hirebuddha.dialer.ui.common.BrandDots
import com.hirebuddha.dialer.ui.common.CardBody
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.Eyebrow
import com.hirebuddha.dialer.ui.common.GlassSurface
import com.hirebuddha.dialer.ui.common.GoldPill
import com.hirebuddha.dialer.ui.common.Hairline
import com.hirebuddha.dialer.ui.common.HbButton
import com.hirebuddha.dialer.ui.common.HbButtonSize
import com.hirebuddha.dialer.ui.common.HbButtonStyle
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.common.HbProgress
import com.hirebuddha.dialer.ui.common.HbTextField
import com.hirebuddha.dialer.ui.common.HbTopBar
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.MonoText
import com.hirebuddha.dialer.ui.common.Numeral
import com.hirebuddha.dialer.ui.common.Pill
import com.hirebuddha.dialer.ui.common.PositivePill
import com.hirebuddha.dialer.ui.theme.BrandType
import com.hirebuddha.dialer.ui.theme.HbTheme
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.launch

@HiltViewModel
class CreateCampaignViewModel @Inject constructor(private val repo: CampaignRepository) : ViewModel() {
    var step by mutableStateOf(1); private set
    var report by mutableStateOf<UploadReportDto?>(null); private set
    var fileName by mutableStateOf<String?>(null); private set
    var fileSize by mutableStateOf<Long?>(null); private set
    var uploading by mutableStateOf(false); private set
    var agents by mutableStateOf<List<AgentDto>>(emptyList()); private set
    /** Uploads checked earlier and not yet used — a rep who backed out can pick up again. */
    var recent by mutableStateOf<List<UploadReportDto>>(emptyList()); private set
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
        recent = repo.recentUploads()
    }

    /** Skips the upload: the server still holds this report and its contacts for a day. */
    fun reuse(upload: UploadReportDto) {
        report = upload
        fileName = upload.filename
        fileSize = null
        if (name.isBlank()) name = upload.filename?.substringBeforeLast('.').orEmpty()
        error = null
        step = 2
    }

    fun back() { if (step > 1) step-- }
    fun toConfigure() { step = 3 }

    fun upload(context: Context, uri: Uri, fileName: String?, size: Long? = null) = viewModelScope.launch {
        uploading = true
        error = null
        this@CreateCampaignViewModel.fileName = fileName
        fileSize = size
        when (val r = repo.upload(context.contentResolver, uri)) {
            is ApiResult.Ok -> {
                report = r.value
                if (name.isBlank()) name = fileName?.substringBeforeLast('.').orEmpty()
                step = 2
            }
            is ApiResult.Err -> error = r.message
            ApiResult.Empty -> error = "Upload failed."
        }
        uploading = false
    }

    fun create(isAdmin: Boolean, onCreated: (String) -> Unit) = viewModelScope.launch {
        val upload = report ?: return@launch
        val agent = agentId ?: run { error = "Choose an agent."; return@launch }
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

/**
 * Screens 10–12. Three explicit steps replace one long form that silently grew as you
 * filled it in, so a rep always knows how much is left.
 */
@Composable
fun CreateCampaignScreen(
    me: MeDto,
    onBack: () -> Unit,
    onCreated: (String) -> Unit,
    vm: CreateCampaignViewModel = hiltViewModel(),
) {
    val context = LocalContext.current
    remember { vm.init(me.isAdmin); true }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) {
            val (name, size) = context.contentResolver
                .query(
                    uri,
                    arrayOf(android.provider.OpenableColumns.DISPLAY_NAME, android.provider.OpenableColumns.SIZE),
                    null, null, null,
                )
                ?.use { if (it.moveToFirst()) it.getString(0) to (if (it.isNull(1)) null else it.getLong(1)) else null }
                ?: (null to null)
            vm.upload(context, uri, name, size)
        }
    }

    val pick = {
        picker.launch(
            arrayOf(
                "text/csv", "text/comma-separated-values", "text/plain",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/octet-stream",
            )
        )
    }

    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            HbTopBar(
                title = "New campaign",
                navigationIcon = if (vm.step == 1) R.drawable.ic_x else R.drawable.ic_back,
                onNavigate = { if (vm.step == 1) onBack() else vm.back() },
            )
            StepHeader(vm.step)
            when (vm.step) {
                1 -> UploadStep(vm, onPick = pick)
                2 -> ReportStep(vm)
                else -> ConfigureStep(vm, me)
            }
        }
        if (vm.step == 2 || vm.step == 3) {
            StickyAction(vm, me, onCreated, onReupload = { vm.back(); pick() }, modifier = Modifier.align(Alignment.BottomCenter))
        }
    }
}

@Composable
private fun StepHeader(step: Int) {
    val labels = listOf("the list", "what we found", "who calls")
    Column(Modifier.padding(horizontal = HbTheme.dims.gutter)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            repeat(3) { i ->
                HbProgress(if (i < step) 1f else 0f, Modifier.weight(1f), height = 3.dp)
            }
        }
        Spacer(Modifier.height(10.dp))
        Eyebrow("Step $step of 3 — ${labels[step - 1]}")
        Spacer(Modifier.height(16.dp))
    }
}

/** Screen 10. */
@Composable
private fun UploadStep(vm: CreateCampaignViewModel, onPick: () -> Unit) {
    val c = HbTheme.colors
    val context = LocalContext.current
    var sampleSaved by remember { mutableStateOf(false) }

    LazyColumn(
        contentPadding = PaddingValues(HbTheme.dims.gutter, 0.dp, HbTheme.dims.gutter, 40.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Text("Bring your leads", style = MaterialTheme.typography.headlineMedium, color = c.fg)
            Spacer(Modifier.height(8.dp))
            CardBody("A spreadsheet with one row per person. We check it before anything is created.")
        }
        item {
            Column(
                Modifier.fillMaxWidth()
                    .clip(RoundedCornerShape(HbTheme.dims.rLg))
                    .border(1.dp, c.borderStrong, RoundedCornerShape(HbTheme.dims.rLg))
                    .clickable(enabled = !vm.uploading, onClick = onPick)
                    .padding(vertical = 28.dp, horizontal = 20.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Box(
                    Modifier.size(52.dp).clip(RoundedCornerShape(17.dp)).background(c.accentQuiet),
                    contentAlignment = Alignment.Center,
                ) { HbIcon(R.drawable.ic_upload, size = 24.dp, tint = c.accent) }
                Spacer(Modifier.height(14.dp))
                Text(
                    if (vm.uploading) "Checking your file" else "Choose a .xlsx or .csv",
                    style = MaterialTheme.typography.titleMedium,
                    color = c.fg,
                )
                Spacer(Modifier.height(6.dp))
                if (vm.uploading) BrandDots() else CardCaption("From your phone, Drive or WhatsApp")
            }
        }
        item {
            // The column rules belong above the picker, not under it in grey 12sp.
            HbCard(Modifier.fillMaxWidth(), padding = 14.dp) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    HbIcon(R.drawable.ic_info, size = 17.dp, tint = c.gold300)
                    Text("What the file needs", style = MaterialTheme.typography.titleSmall, color = c.fg)
                }
                Spacer(Modifier.height(12.dp))
                Hairline()
                Spacer(Modifier.height(12.dp))
                RequirementRow(
                    "Required", true,
                    "A phone column — named phone, mobile, contact or number",
                )
                Spacer(Modifier.height(10.dp))
                RequirementRow(
                    "Optional", false,
                    "Any other column becomes something your agent can say — name, city, budget, the flat they enquired about",
                )
                Spacer(Modifier.height(14.dp))
                HbButton(
                    if (sampleSaved) "Saved to Downloads" else "Download a sample sheet",
                    { if (writeSampleCsv(context)) sampleSaved = true },
                    Modifier.fillMaxWidth(),
                    HbButtonStyle.Secondary,
                    HbButtonSize.Small,
                    icon = R.drawable.ic_download,
                )
            }
        }
        if (vm.recent.isNotEmpty()) {
            item {
                Spacer(Modifier.height(4.dp))
                Eyebrow("Recent", color = c.fgSubtle)
                Spacer(Modifier.height(8.dp))
                HbCard(Modifier.fillMaxWidth(), padding = 4.dp) {
                    vm.recent.forEachIndexed { i, upload ->
                        if (i > 0) Hairline()
                        Row(
                            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            HbIcon(R.drawable.ic_file, size = 18.dp, tint = c.fgSubtle)
                            Column(Modifier.weight(1f)) {
                                Text(
                                    upload.filename ?: "Contacts",
                                    style = MaterialTheme.typography.titleSmall, color = c.fg,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                                )
                                MicroText(
                                    listOfNotNull(
                                        com.hirebuddha.dialer.ui.common.shortDate(upload.createdAt)?.let { "Uploaded $it" },
                                        "${upload.validRows} valid rows",
                                    ).joinToString(" · "),
                                )
                            }
                            HbButton("Reuse", { vm.reuse(upload) }, style = HbButtonStyle.Secondary, size = HbButtonSize.Small)
                        }
                    }
                }
            }
        }
        vm.error?.let { item { MicroText(it, color = c.negative) } }
    }
}

@Composable
private fun RequirementRow(label: String, gold: Boolean, text: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        if (gold) GoldPill(label) else Pill(label)
        CardCaption(text, Modifier.weight(1f))
    }
}

/**
 * Writes a sample list to Downloads. MediaStore needs no permission on API 29+, and it
 * removes the commonest support question in the pilot — "what should the file look like?"
 */
private fun writeSampleCsv(context: Context): Boolean = runCatching {
    val values = ContentValues().apply {
        put(MediaStore.Downloads.DISPLAY_NAME, "hirebuddha-sample-leads.csv")
        put(MediaStore.Downloads.MIME_TYPE, "text/csv")
        put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
    }
    val uri = context.contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
        ?: return@runCatching false
    context.contentResolver.openOutputStream(uri)?.use { out ->
        out.write(
            """
            phone,name,locality,config,budget
            +919900000441,Meenal Deshpande,Baner,3 BHK,1.4 Cr
            +918800000037,Arjun Rao,Balewadi,2 BHK,95 L
            """.trimIndent().toByteArray()
        )
    }
    true
}.getOrDefault(false)

/** Screen 11 — FR-C3, ordered by what a rep decides with. */
@Composable
private fun ReportStep(vm: CreateCampaignViewModel) {
    val c = HbTheme.colors
    val report = vm.report ?: return
    var showErrors by remember { mutableStateOf(false) }

    LazyColumn(
        contentPadding = PaddingValues(HbTheme.dims.gutter, 0.dp, HbTheme.dims.gutter, 120.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
                Text(
                    "${report.totalRows} rows read",
                    Modifier.weight(1f),
                    style = MaterialTheme.typography.headlineMedium,
                    color = c.fg,
                )
                if (report.validRows > 0) PositivePill("Ready")
            }
            Spacer(Modifier.height(6.dp))
            MonoText(
                listOfNotNull(
                    vm.fileName ?: report.fileType.uppercase(),
                    vm.fileSize?.let { humanSize(it) },
                    report.phoneColumn?.let { "phone in \u201c$it\u201d" } ?: "no phone column",
                ).joinToString(" · "),
            )
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                CountTile("${report.validRows}", "will be called", Modifier.weight(1f), c.positive)
                CountTile("${report.invalidRows}", "bad numbers", Modifier.weight(1f), c.negative)
                CountTile("${report.duplicateRows}", "duplicates", Modifier.weight(1f), c.fgSubtle)
            }
        }
        item {
            HbCard(Modifier.fillMaxWidth()) {
                // Framing the detected columns this way is the clearest way to explain
                // contact-data injection to someone who has never heard the term.
                Eyebrow("Columns your agent will know", color = c.fgSubtle)
                Spacer(Modifier.height(10.dp))
                // Every column, wrapped: which fields the agent can use is the point of this card.
                FlowRow(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(7.dp),
                    verticalArrangement = Arrangement.spacedBy(7.dp),
                ) {
                    report.columns.forEach { column ->
                        if (column == report.phoneColumn) GoldPill(column) else Pill(column)
                    }
                }
                if (report.preview.isNotEmpty()) {
                    Spacer(Modifier.height(14.dp))
                    Hairline()
                    Spacer(Modifier.height(12.dp))
                    Eyebrow("First rows", color = c.fgSubtle)
                    Spacer(Modifier.height(10.dp))
                    report.preview.take(3).forEach { row ->
                        val fields = row.stringMap()
                        Column(
                            Modifier.fillMaxWidth().padding(bottom = 8.dp)
                                .clip(RoundedCornerShape(HbTheme.dims.rSm))
                                .background(c.surface2).padding(horizontal = 11.dp, vertical = 9.dp),
                        ) {
                            Text(
                                fields["name"] ?: fields["Name"] ?: fields[report.phoneColumn] ?: "—",
                                style = MaterialTheme.typography.titleSmall,
                                color = c.fg,
                                maxLines = 1,
                            )
                            MonoText(
                                fields.entries.filter { it.key != "name" && it.key != "Name" }
                                    .take(4).joinToString(" · ") { it.value },
                            )
                        }
                    }
                }
            }
        }
        if (report.errors.isNotEmpty()) {
            item {
                HbCard(Modifier.fillMaxWidth(), border = c.negative.copy(alpha = 0.28f)) {
                    Row(
                        Modifier.fillMaxWidth().clickable { showErrors = !showErrors },
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        HbIcon(R.drawable.ic_alert, size = 17.dp, tint = c.negative)
                        Text(
                            "${report.errors.size} rows will be skipped",
                            Modifier.weight(1f),
                            style = MaterialTheme.typography.titleSmall,
                            color = c.fg,
                        )
                        HbIcon(
                            if (showErrors) R.drawable.ic_chev_d else R.drawable.ic_chev_r,
                            size = 17.dp, tint = c.fgDisabled,
                        )
                    }
                    Spacer(Modifier.height(12.dp))
                    run {
                        report.errors.take(if (showErrors) 25 else 4).forEach { e ->
                            Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                MonoText("Row ${e.row}", Modifier.size(width = 52.dp, height = 16.dp))
                                MonoText(e.value.ifBlank { "(empty)" }, Modifier.weight(1f), color = c.fgMuted)
                                MicroText(
                                    humanizeReason(e.reason),
                                    color = if (e.reason == "duplicate") c.fgSubtle else c.negative,
                                )
                            }
                        }
                        if (!showErrors && report.errors.size > 4) {
                            Text(
                                "Show all ${report.errors.size}",
                                Modifier.clickable { showErrors = true }.padding(vertical = 4.dp),
                                style = MaterialTheme.typography.labelMedium, color = c.accent,
                            )
                        }
                        if (showErrors && report.errors.size > 25) MicroText("…and ${report.errors.size - 25} more")
                    }
                }
            }
        }
    }
}

private fun humanizeReason(reason: String): String = when (reason) {
    "duplicate" -> "already in the list"
    "invalid" -> "not a valid number"
    "too_short" -> "too short"
    "missing" -> "no number"
    else -> reason.replace('_', ' ')
}

@Composable
private fun CountTile(value: String, label: String, modifier: Modifier = Modifier, color: Color) =
    HbCard(modifier, padding = 12.dp) {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            Numeral(value, style = BrandType.numeralSmall, color = color)
            Spacer(Modifier.height(4.dp))
            MicroText(label, Modifier.fillMaxWidth())
        }
    }

/** Screen 12 — the agent dropdown becomes a choice you can actually make. */
@Composable
private fun ConfigureStep(vm: CreateCampaignViewModel, me: MeDto) {
    val c = HbTheme.colors
    LazyColumn(
        contentPadding = PaddingValues(HbTheme.dims.gutter, 0.dp, HbTheme.dims.gutter, 120.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Text("Choose the agent", style = MaterialTheme.typography.headlineMedium, color = c.fg)
            Spacer(Modifier.height(8.dp))
            CardBody("Only voice agents with a number assigned can take a conference call.")
        }
        if (vm.agents.isEmpty()) {
            item {
                HbCard(Modifier.fillMaxWidth()) {
                    CardCaption("No agent in your company has a phone number assigned yet. Ask your admin to assign one in the web console.")
                }
            }
        }
        items(vm.agents, key = { it.agentId }) { agent ->
            AgentCard(agent, vm.agentId == agent.agentId) { vm.agentId = agent.agentId }
        }
        item {
            Spacer(Modifier.height(8.dp))
            HbTextField(vm.name, { vm.name = it }, label = "Campaign name", placeholder = "Baner developer leads")
        }
        if (me.isAdmin && vm.reps.isNotEmpty()) {
            item {
                Spacer(Modifier.height(8.dp))
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text("Assign reps", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, color = c.fg)
                    MicroText("${vm.assignees.size} of ${vm.reps.size} selected")
                }
                Spacer(Modifier.height(10.dp))
            }
            item {
                HbCard(Modifier.fillMaxWidth(), padding = 4.dp) {
                    vm.reps.forEachIndexed { i, rep ->
                        if (i > 0) Hairline()
                        RepRow(rep, rep.userId in vm.assignees, isMe = rep.userId == me.userId, enabled = rep.canBeAssigned) {
                            vm.assignees =
                                if (rep.userId in vm.assignees) vm.assignees - rep.userId
                                else vm.assignees + rep.userId
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))
                MicroText("Leads are handed out one at a time, so two reps never call the same person.")
            }
        }
        vm.error?.let { item { MicroText(it, color = c.negative) } }
    }
}

@Composable
private fun AgentCard(agent: AgentDto, selected: Boolean, onSelect: () -> Unit) {
    val c = HbTheme.colors
    val available = agent.did != null
    HbCard(
        Modifier.fillMaxWidth(),
        padding = 14.dp,
        onClick = if (available) onSelect else null,
        border = if (selected) c.borderGold else c.border,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            RadioDot(selected, available)
            Box(
                Modifier.size(38.dp).clip(RoundedCornerShape(12.dp))
                    .background(if (selected) c.accentQuiet else c.surface3),
                contentAlignment = Alignment.Center,
            ) { HbIcon(R.drawable.ic_ai, size = 18.dp, tint = if (selected) c.accent else c.fgSubtle) }
            Column(Modifier.weight(1f)) {
                // What each agent does is what makes this a choice rather than a list of names.
                val (agentName, role) = com.hirebuddha.dialer.ui.common.agentNameAndRole(agent.name)
                Text(
                    agentName ?: agent.name,
                    style = MaterialTheme.typography.titleMedium,
                    color = if (available) c.fg else c.fgSubtle,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                role?.let { CardCaption(it) }
                MonoText(agent.did ?: "No number assigned")
            }
            if (available) PositivePill("Active") else Pill("Unavailable")
        }
    }
}

@Composable
private fun RepRow(rep: RepDto, checked: Boolean, isMe: Boolean, enabled: Boolean, onToggle: () -> Unit) {
    val c = HbTheme.colors
    // Shown but not pickable: assigning work to a phone that cannot run it only moves the
    // failure to the rep, later.
    Row(
        Modifier.fillMaxWidth().clickable(enabled = enabled, onClick = onToggle)
            .alpha(if (enabled) 1f else 0.5f)
            .padding(horizontal = 10.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(
            Modifier.size(20.dp).clip(RoundedCornerShape(6.dp))
                .background(if (checked) c.accent else Color.Transparent)
                .border(1.75.dp, if (checked) c.accent else c.borderStrong, RoundedCornerShape(6.dp)),
            contentAlignment = Alignment.Center,
        ) { if (checked) HbIcon(R.drawable.ic_check, size = 13.dp, tint = c.onAccent) }
        Avatar(com.hirebuddha.dialer.ui.common.initialsOf(rep.name), size = 32.dp)
        Column(Modifier.weight(1f)) {
            Text(rep.name, style = MaterialTheme.typography.bodyLarge, color = c.fg, maxLines = 1)
            MicroText(
                listOfNotNull(
                    "you".takeIf { isMe },
                    com.hirebuddha.dialer.ui.common.humanize(rep.role),
                    when (rep.phoneVerified) { true -> "verified phone"; false -> "phone not verified yet"; null -> null },
                ).joinToString(" · "),
            )
        }
    }
}

@Composable
private fun RadioDot(selected: Boolean, enabled: Boolean) {
    val c = HbTheme.colors
    Box(
        Modifier.size(20.dp)
            .clip(RoundedCornerShape(percent = 50))
            .border(
                1.75.dp,
                if (selected) c.accent else if (enabled) c.borderStrong else c.border,
                RoundedCornerShape(percent = 50),
            ),
        contentAlignment = Alignment.Center,
    ) {
        if (selected) {
            Box(Modifier.size(10.dp).clip(RoundedCornerShape(percent = 50)).background(c.accent))
        }
    }
}

@Composable
private fun StickyAction(
    vm: CreateCampaignViewModel,
    me: MeDto,
    onCreated: (String) -> Unit,
    onReupload: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val c = HbTheme.colors
    GlassSurface(modifier.fillMaxWidth().padding(14.dp).navigationBarsPadding()) {
        Box(Modifier.padding(12.dp)) {
            if (vm.step == 2) Column {
                // Rejected rows are usually fixable in a minute; make that the easy path
                // rather than "back, back, pick the file again".
                if (vm.report?.errors?.isNotEmpty() == true) {
                    HbButton(
                        "Fix the sheet and re-upload", onReupload, Modifier.fillMaxWidth(),
                        HbButtonStyle.Ghost, HbButtonSize.Small, icon = R.drawable.ic_upload,
                    )
                    Spacer(Modifier.height(6.dp))
                }
                HbButton(
                    "Continue with ${vm.report?.validRows ?: 0} leads",
                    { vm.toConfigure() },
                    Modifier.fillMaxWidth(),
                    HbButtonStyle.Primary,
                    icon = R.drawable.ic_fwd,
                    enabled = (vm.report?.validRows ?: 0) > 0,
                )
            } else {
                HbButton(
                    text = if (vm.creating) "Creating" else "Create campaign",
                    onClick = { vm.create(me.isAdmin, onCreated) },
                    modifier = Modifier.fillMaxWidth(),
                    style = HbButtonStyle.Primary,
                    enabled = !vm.creating && vm.agentId != null && vm.name.isNotBlank(),
                    content = if (!vm.creating) null else {
                        { BrandDots(count = 4, dotSize = 6.dp, color = c.onAccent) }
                    },
                )
            }
        }
    }
}

private fun humanSize(bytes: Long): String = when {
    bytes < 1024 -> "$bytes B"
    bytes < 1024 * 1024 -> "${bytes / 1024} KB"
    else -> "%.1f MB".format(bytes / (1024.0 * 1024.0))
}
