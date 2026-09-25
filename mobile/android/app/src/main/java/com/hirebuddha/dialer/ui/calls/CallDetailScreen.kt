package com.hirebuddha.dialer.ui.calls

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.media.MediaPlayer
import android.os.Build
import android.provider.CalendarContract
import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import com.hirebuddha.dialer.ui.common.BrandDots
import com.hirebuddha.dialer.ui.common.HbIcon
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import kotlinx.coroutines.delay
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.TimelineEntryDto
import com.hirebuddha.dialer.data.api.TranscriptTurnDto
import com.hirebuddha.dialer.data.api.VoiceSessionDto
import com.hirebuddha.dialer.data.repo.CampaignRepository
import com.hirebuddha.dialer.ui.common.CardBody
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.DispositionPill
import com.hirebuddha.dialer.ui.common.EmptyState
import com.hirebuddha.dialer.ui.common.Eyebrow
import com.hirebuddha.dialer.ui.common.GoldCard
import com.hirebuddha.dialer.ui.common.Hairline
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbTopBar
import com.hirebuddha.dialer.ui.common.Loading
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.MonoText
import com.hirebuddha.dialer.ui.common.StepRow
import com.hirebuddha.dialer.ui.common.StepState
import com.hirebuddha.dialer.ui.common.formatMinutes
import com.hirebuddha.dialer.ui.common.humanize
import com.hirebuddha.dialer.ui.theme.HbTheme
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.launch

@HiltViewModel
class CallDetailViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val repo: CampaignRepository,
) : ViewModel() {
    var session by mutableStateOf<VoiceSessionDto?>(null); private set
    var timeline by mutableStateOf<List<TimelineEntryDto>>(emptyList()); private set
    var loading by mutableStateOf(true); private set
    var error by mutableStateOf<String?>(null); private set

    enum class Recording { Idle, Loading, Ready, Failed }
    var recording by mutableStateOf(Recording.Idle); private set
    var recordingFile by mutableStateOf<File?>(null); private set

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

    /** Downloaded on the first tap of Play, not on open: most people only read the summary. */
    fun fetchRecording() = viewModelScope.launch {
        val s = session ?: return@launch
        val path = s.recordingUrl ?: return@launch
        if (recording == Recording.Loading || recording == Recording.Ready) return@launch
        recording = Recording.Loading
        val file = File(File(context.cacheDir, "recordings"), "${s.id}.audio")
        recording = if (repo.downloadRecording(path, file)) {
            recordingFile = file
            Recording.Ready
        } else {
            file.delete()
            Recording.Failed
        }
    }

    /** A recording is a real person's voice: it lives on the phone only while it is on screen. */
    override fun onCleared() {
        recordingFile?.delete()
        super.onCleared()
    }
}

/**
 * Screen 21. Summary first, because it is the only part anyone reads. The AI and
 * recording disclosure stays in the transcript — it is a compliance artefact, not chrome.
 */
@Composable
fun CallDetailScreen(
    sessionId: String?,
    attemptId: String?,
    title: String,
    /** The campaign call's outcome — the voice session's own status is only "completed". */
    disposition: String?,
    agentName: String?,
    onBack: () -> Unit,
    vm: CallDetailViewModel = hiltViewModel(),
) {
    val c = HbTheme.colors
    val context = LocalContext.current
    LaunchedEffect(sessionId, attemptId) { vm.load(sessionId, attemptId) }
    val agent = agentName?.substringBefore(' ')?.takeIf { it.isNotBlank() }
    val lead = title.substringBefore(' ').takeIf { it.isNotBlank() && !it.startsWith("+") }

    Column(Modifier.fillMaxSize()) {
        HbTopBar(
            title = title,
            subtitle = listOfNotNull(
                vm.session?.startedAt?.let { formatWhen(it) },
                vm.session?.durationSeconds?.let { formatClock(it) },
            ).joinToString(" · ").ifBlank { null },
            navigationIcon = R.drawable.ic_back,
            onNavigate = onBack,
        )
        when {
            vm.loading -> Loading()
            vm.session == null && vm.timeline.isEmpty() && vm.error == null -> EmptyState(
                title = "Nothing recorded",
                message = "The lead never connected to the agent, so there is no transcript for this call.",
                icon = R.drawable.ic_phone_end,
            )
            else -> LazyColumn(
                contentPadding = PaddingValues(HbTheme.dims.gutter, 0.dp, HbTheme.dims.gutter, 40.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                vm.error?.let { item(key = "err") { MicroText(it, color = c.negative) } }

                vm.session?.let { session ->
                    item(key = "summary") {
                        GoldCard(Modifier.fillMaxWidth()) {
                            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                Eyebrow(agent?.let { "$it's summary" } ?: "Agent summary", Modifier.weight(1f))
                                disposition?.let { DispositionPill(it) }
                            }
                            Spacer(Modifier.height(10.dp))
                            Text(
                                session.callSummary?.let(::plainText) ?: "Summary not available yet.",
                                style = MaterialTheme.typography.bodyMedium,
                                color = c.fg,
                            )
                            session.nextAction?.let(::plainText)?.takeIf { it.isNotBlank() }?.let { action ->
                                Spacer(Modifier.height(14.dp))
                                Hairline()
                                Spacer(Modifier.height(12.dp))
                                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                    HbIcon(R.drawable.ic_calendar, size = 16.dp, tint = c.accent)
                                    CardBody(action, Modifier.weight(1f), c.fg)
                                    Text(
                                        "Add",
                                        Modifier.clickable { addToCalendar(context, action, title, session.callSummary) }
                                            .padding(horizontal = 6.dp, vertical = 4.dp),
                                        style = MaterialTheme.typography.labelMedium,
                                        color = c.accent,
                                    )
                                }
                            }
                        }
                    }

                    if (session.recordingUrl != null && recordingBelongsTo(session)) {
                        item(key = "player") {
                            RecordingPlayer(
                                state = vm.recording,
                                file = vm.recordingFile,
                                durationHint = session.durationSeconds,
                                onFetch = vm::fetchRecording,
                            )
                        }
                    }

                    if (session.transcript.isNotEmpty()) {
                        item(key = "transcript-header") {
                            Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                                Text("Transcript", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium, color = c.fg)
                                val text = remember(session) { transcriptText(session, title, agent, lead) }
                                Text(
                                    "Copy",
                                    Modifier.clickable { copyText(context, text) }.padding(6.dp),
                                    style = MaterialTheme.typography.labelMedium, color = c.accent,
                                )
                                MicroText("·")
                                Text(
                                    "Share",
                                    Modifier.clickable { shareText(context, title, text) }.padding(6.dp),
                                    style = MaterialTheme.typography.labelMedium, color = c.accent,
                                )
                            }
                        }
                        items(session.transcript) { turn ->
                            Bubble(turn, agent, lead, offsetOf(turn.timestamp, session.startedAt))
                        }
                    }
                }

                if (vm.timeline.isNotEmpty()) {
                    item(key = "timeline") {
                        HbCard(Modifier.fillMaxWidth()) {
                            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    "What happened",
                                    Modifier.weight(1f),
                                    style = MaterialTheme.typography.titleMedium,
                                    color = c.fg,
                                )
                                MicroText("device time")
                            }
                            Spacer(Modifier.height(14.dp))
                            vm.timeline.forEachIndexed { i, entry ->
                                StepRow(
                                    state = StepState.Done,
                                    label = eventLabel(entry.type, agent, lead),
                                    detail = entry.at.substringAfter('T').take(8),
                                    isLast = i == vm.timeline.lastIndex,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

/**
 * Play, scrub and speed, over the downloaded file. MediaPlayer is enough here: one short
 * mono file, no playlists — a media library would be most of the APK's growth for nothing.
 */
@Composable
private fun RecordingPlayer(
    state: CallDetailViewModel.Recording,
    file: File?,
    durationHint: Int?,
    onFetch: () -> Unit,
) {
    val c = HbTheme.colors
    var player by remember { mutableStateOf<MediaPlayer?>(null) }
    var playing by remember { mutableStateOf(false) }
    var position by remember { mutableIntStateOf(0) }
    var duration by remember { mutableIntStateOf((durationHint ?: 0) * 1000) }
    var speed by remember { mutableFloatStateOf(1f) }
    var playWhenReady by remember { mutableStateOf(false) }

    DisposableEffect(file) {
        val mp = file?.let { f ->
            runCatching {
                MediaPlayer().apply {
                    setDataSource(f.absolutePath)
                    prepare()
                    setOnCompletionListener { playing = false; position = 0; seekTo(0) }
                }
            }.getOrNull()
        }
        player = mp
        mp?.let { duration = it.duration.coerceAtLeast(0) }
        if (mp != null && playWhenReady) { mp.start(); playing = true; playWhenReady = false }
        onDispose { mp?.release(); player = null; playing = false }
    }
    LaunchedEffect(playing) {
        while (playing) {
            player?.let { position = it.currentPosition }
            delay(250)
        }
    }

    HbCard(Modifier.fillMaxWidth(), padding = 14.dp) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(
                Modifier.size(44.dp).clip(CircleShape).background(c.accent)
                    .clickable(enabled = state != CallDetailViewModel.Recording.Loading) {
                        val mp = player
                        when {
                            mp == null -> { playWhenReady = true; onFetch() }
                            playing -> { mp.pause(); playing = false }
                            else -> { mp.start(); applySpeed(mp, speed); playing = true }
                        }
                    },
                contentAlignment = Alignment.Center,
            ) {
                if (state == CallDetailViewModel.Recording.Loading) BrandDots(count = 3, dotSize = 4.dp, color = c.onAccent)
                else HbIcon(if (playing) R.drawable.ic_pause else R.drawable.ic_play, size = 19.dp, tint = c.onAccent)
            }
            Column(Modifier.weight(1f)) {
                Slider(
                    value = if (duration > 0) position.toFloat() / duration else 0f,
                    onValueChange = { f -> position = (f * duration).toInt(); player?.seekTo(position) },
                    enabled = player != null,
                    colors = SliderDefaults.colors(
                        thumbColor = c.accent, activeTrackColor = c.accent,
                        inactiveTrackColor = c.surface3, disabledInactiveTrackColor = c.surface3,
                    ),
                    modifier = Modifier.height(24.dp),
                )
                Row(Modifier.fillMaxWidth()) {
                    MonoText(formatClock(position / 1000), Modifier.weight(1f))
                    MonoText(if (duration > 0) formatClock(duration / 1000) else "—")
                }
            }
            Text(
                "${if (speed % 1f == 0f) speed.toInt() else speed}×",
                Modifier.clip(RoundedCornerShape(HbTheme.dims.rSm)).background(c.surface2)
                    .clickable {
                        speed = when (speed) { 1f -> 1.5f; 1.5f -> 2f; else -> 1f }
                        player?.let { if (playing) applySpeed(it, speed) }
                    }
                    .padding(horizontal = 9.dp, vertical = 6.dp),
                style = MaterialTheme.typography.labelMedium,
                color = c.fg,
            )
        }
        if (state == CallDetailViewModel.Recording.Failed) {
            Spacer(Modifier.height(6.dp))
            MicroText("Couldn't load the recording. Tap play to try again.", color = c.negative)
        }
    }
}

/**
 * The server may fall back to "the nearest recording in time", which after back-to-back
 * calls can be a different lead's conversation. Its file name carries the session it was
 * made for; one that names another session is not this call's, and is never played.
 */
internal fun recordingBelongsTo(session: VoiceSessionDto): Boolean {
    val named = session.recordingFileName?.let { UUID_IN_NAME.find(it)?.value } ?: return true
    return named.equals(session.id, ignoreCase = true)
}

private val UUID_IN_NAME = Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

/** The model writes markdown ("**", "*   ") that would show up literally; keep the words. */
internal fun plainText(raw: String): String = raw.lines()
    .map { it.trim().trimStart('#').trim().trimStart('*', '-', '•').trim().replace("**", "") }
    .filter { it.isNotBlank() }
    .joinToString(" ")
    .trim()

/** Setting params on a paused player starts it on some OEM builds, so only while playing. */
private fun applySpeed(player: MediaPlayer, speed: Float) {
    runCatching { player.playbackParams = player.playbackParams.setSpeed(speed) }
}

@Composable
private fun Bubble(turn: TranscriptTurnDto, agent: String?, lead: String?, offset: String?) {
    val c = HbTheme.colors
    val isAgent = turn.speaker == "agent"
    val shape = RoundedCornerShape(
        topStart = 15.dp, topEnd = 15.dp,
        bottomStart = if (isAgent) 5.dp else 15.dp,
        bottomEnd = if (isAgent) 15.dp else 5.dp,
    )
    Row(
        Modifier.fillMaxWidth(),
        horizontalArrangement = if (isAgent) Arrangement.Start else Arrangement.End,
    ) {
        Column(
            Modifier.fillMaxWidth(0.85f)
                .clip(shape)
                .background(if (isAgent) c.surface2 else c.accentQuiet)
                .border(1.dp, if (isAgent) c.border else c.borderGold, shape)
                .padding(horizontal = 13.dp, vertical = 10.dp),
        ) {
            Eyebrow(
                listOfNotNull(speakerName(isAgent, agent, lead), offset).joinToString(" · "),
                color = if (isAgent) c.fgSubtle else c.gold300.copy(alpha = 0.75f),
            )
            Spacer(Modifier.height(5.dp))
            Text(
                turn.content,
                style = MaterialTheme.typography.bodyMedium,
                color = if (isAgent) c.fg else c.gold300,
            )
        }
    }
}

private fun speakerName(isAgent: Boolean, agent: String?, lead: String?) =
    if (isAgent) agent ?: "Agent" else lead ?: "Lead"

/** Plain text of the conversation, for Copy and Share: names, offsets, and nothing else. */
private fun transcriptText(session: VoiceSessionDto, title: String, agent: String?, lead: String?): String =
    buildString {
        appendLine(listOfNotNull(title, session.startedAt?.let { formatWhen(it) }).joinToString(" · "))
        session.callSummary?.let { appendLine(); appendLine(plainText(it)) }
        appendLine()
        session.transcript.forEach { turn ->
            val who = speakerName(turn.speaker == "agent", agent, lead)
            val at = offsetOf(turn.timestamp, session.startedAt)
            appendLine(listOfNotNull(who, at).joinToString(" · ") + ": " + turn.content.trim())
        }
    }.trim()

private fun copyText(context: Context, text: String) {
    context.getSystemService(ClipboardManager::class.java)
        ?.setPrimaryClip(ClipData.newPlainText("Call transcript", text))
    // Android 13+ shows its own confirmation; older versions show nothing at all.
    if (Build.VERSION.SDK_INT < 33) Toast.makeText(context, "Transcript copied", Toast.LENGTH_SHORT).show()
}

private fun shareText(context: Context, title: String, text: String) {
    val send = Intent(Intent.ACTION_SEND).setType("text/plain")
        .putExtra(Intent.EXTRA_SUBJECT, "Call with $title")
        .putExtra(Intent.EXTRA_TEXT, text)
    context.startActivity(Intent.createChooser(send, "Share transcript"))
}

/**
 * Opens the calendar with the follow-up filled in. The agent's next action is prose
 * ("Site visit on Saturday morning"), so the rep picks the exact time — a wrong guess
 * at a date is worse than an empty field.
 */
private fun addToCalendar(context: Context, action: String, lead: String, summary: String?) {
    val insert = Intent(Intent.ACTION_INSERT)
        .setData(CalendarContract.Events.CONTENT_URI)
        .putExtra(CalendarContract.Events.TITLE, "$action — $lead")
        .putExtra(CalendarContract.Events.DESCRIPTION, summary.orEmpty())
    runCatching { context.startActivity(insert) }
        .onFailure { Toast.makeText(context, "No calendar app found", Toast.LENGTH_SHORT).show() }
}

/** `2026-09-21T11:20:06` (UTC-naive) → `21 Sep · 11:20` in the phone's zone. */
private fun formatWhen(iso: String): String = runCatching {
    parseUtc(iso).atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("d MMM · HH:mm"))
}.getOrDefault(iso.take(16).replace('T', ' '))

private fun offsetOf(turnAt: String?, startedAt: String?): String? {
    if (turnAt == null || startedAt == null) return null
    return runCatching {
        val seconds = Duration.between(parseUtc(startedAt), parseUtc(turnAt)).seconds
        if (seconds < 0) null else formatClock(seconds.toInt())
    }.getOrNull()
}

private fun parseUtc(iso: String): Instant = runCatching { OffsetDateTime.parse(iso).toInstant() }
    .getOrElse { LocalDateTime.parse(iso.removeSuffix("Z")).toInstant(ZoneOffset.UTC) }

private fun formatClock(seconds: Int): String = "%d:%02d".format(seconds / 60, seconds % 60)

/**
 * Orchestrator event names, said in English. A rep and a support engineer should be able
 * to read the same screen — the raw type stays in `mobile_call_events` for debugging.
 */
private fun eventLabel(type: String, agent: String? = null, lead: String? = null): String = when (type) {
    "ai_answered" -> "${agent ?: "Agent"} answered"
    "ai_ready", "ai_ready_received" -> "${agent ?: "Agent"} briefed and ready"
    "ai_disconnected" -> "${agent ?: "Agent"} left"
    "lead_answered" -> "${lead ?: "Lead"} answered"
    "lead_disconnected" -> "${lead ?: "Lead"} hung up"
    "ended" -> "Call ended"
    "lease_acquired" -> "Lead reserved"
    "attempt_created" -> "Call attempt opened"
    "ai_dialing" -> "Calling the agent"
    "dtmf_sent" -> "Keypad code sent"
    "ai_held" -> "Agent put on hold"
    "lead_dialing" -> "Dialling the lead"
    "lead_ringing" -> "Lead's phone ringing"
    "merged" -> "Calls merged"
    "merge_failed" -> "Merge failed"
    "rep_muted" -> "You were muted"
    "rep_unmuted" -> "You unmuted"
    "rep_takeover" -> "You took over"
    "rep_hangup" -> "You ended the call"
    "completed" -> "Call completed"
    "skipped" -> "You skipped this lead"
    "lead_failed" -> "Lead didn't connect"
    "ai_failed" -> "Agent didn't connect"
    else -> humanize(type)
}
