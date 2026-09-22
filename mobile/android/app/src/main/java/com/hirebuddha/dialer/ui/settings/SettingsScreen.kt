package com.hirebuddha.dialer.ui.settings

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings as AndroidSettings
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.hirebuddha.dialer.BuildConfig
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.data.api.AppVersionDto
import com.hirebuddha.dialer.data.api.MeDto
import com.hirebuddha.dialer.data.logs.LogRepository
import com.hirebuddha.dialer.data.settings.AppSettings
import com.hirebuddha.dialer.data.settings.DialerPrefs
import com.hirebuddha.dialer.telecom.DialerRole
import com.hirebuddha.dialer.ui.common.Avatar
import com.hirebuddha.dialer.ui.common.BuddhaLabLockup
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.Eyebrow
import com.hirebuddha.dialer.ui.common.Hairline
import com.hirebuddha.dialer.ui.common.HbButton
import com.hirebuddha.dialer.ui.common.HbButtonSize
import com.hirebuddha.dialer.ui.common.HbButtonStyle
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.common.HbTopBar
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.MonoText
import com.hirebuddha.dialer.ui.common.Pill
import com.hirebuddha.dialer.ui.common.PositivePill
import com.hirebuddha.dialer.ui.common.SectionLabel
import com.hirebuddha.dialer.ui.common.initialsOf
import com.hirebuddha.dialer.ui.login.ServerSettings
import com.hirebuddha.dialer.ui.theme.HbTheme
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.launch

@HiltViewModel
class SettingsViewModel @Inject constructor(
    val settings: AppSettings,
    private val logs: LogRepository,
) : ViewModel() {
    /** Ships whatever the outbox is holding right now; the periodic sweep is every 30 min. */
    fun sendDiagnostics() = viewModelScope.launch { logs.flush() }
}

/** Screen 23. Grouped by what a rep would go looking for, not by what the code owns. */
@Composable
fun SettingsScreen(
    me: MeDto,
    update: AppVersionDto?,
    onLogout: () -> Unit,
    onReverify: () -> Unit,
    modifier: Modifier = Modifier,
    vm: SettingsViewModel = hiltViewModel(),
) {
    val c = HbTheme.colors
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val prefs by vm.settings.prefs.collectAsStateWithLifecycle(initialValue = null as DialerPrefs?)
    var showServer by remember { mutableStateOf(false) }
    var diagnosticsSent by remember { mutableStateOf(false) }

    LazyColumn(
        modifier.fillMaxSize(),
        contentPadding = PaddingValues(HbTheme.dims.gutter, 0.dp, HbTheme.dims.gutter, 150.dp),
    ) {
        item(key = "bar") { HbTopBar("Settings") }

        item(key = "profile") {
            HbCard(Modifier.fillMaxWidth()) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Avatar(initialsOf(me.fullName), size = 46.dp, gold = true, shape = RoundedCornerShape(15.dp))
                    Column(Modifier.weight(1f)) {
                        Text(me.fullName, style = MaterialTheme.typography.titleLarge, color = c.fg, maxLines = 1)
                        CardCaption(me.email)
                        Spacer(Modifier.height(6.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Pill(if (me.isAdmin) "Tenant admin" else "Rep")
                            me.companyName?.let { Pill(it) }
                        }
                    }
                }
            }
            Spacer(Modifier.height(24.dp))
        }

        item(key = "phone") {
            SectionLabel("This phone")
            Spacer(Modifier.height(10.dp))
            HbCard(Modifier.fillMaxWidth()) {
                SettingRow(
                    icon = R.drawable.ic_device,
                    title = "Calling SIM",
                    detail = prefs?.phoneAccountLabel ?: "Not chosen",
                    onClick = onReverify,
                ) { PositivePill("Verified") }
                Hairline()
                SettingRow(
                    icon = R.drawable.ic_shield,
                    title = "Default phone app",
                    detail = "Required to merge calls",
                    onClick = { context.startActivity(DialerRole.requestIntent(context)) },
                ) {
                    if (DialerRole.isHeld(context)) PositivePill("Active")
                    else Pill("Not set", color = c.negative, background = c.negativeQuiet)
                }
                Hairline()
                BatteryRow(context)
            }
            Spacer(Modifier.height(24.dp))
        }

        prefs?.let { p ->
            item(key = "calling") {
                SectionLabel("How you call")
                Spacer(Modifier.height(10.dp))
                HbCard(Modifier.fillMaxWidth()) {
                    SliderRow(
                        label = "Pause between leads",
                        value = p.gapSeconds.toFloat(),
                        range = 0f..30f,
                        steps = 29,
                        display = "${p.gapSeconds}s",
                        minLabel = "0", maxLabel = "30s",
                    ) { scope.launch { vm.settings.setGapSeconds(it.toInt()) } }
                    Hairline()
                    Spacer(Modifier.height(14.dp))
                    SliderRow(
                        label = "Ring the lead for",
                        value = p.leadRingTimeoutSeconds.toFloat(),
                        range = 15f..60f,
                        steps = 44,
                        display = "${p.leadRingTimeoutSeconds}s",
                        minLabel = "15", maxLabel = "60s",
                    ) { scope.launch { vm.settings.setLeadRingTimeout(it.toInt()) } }
                    Hairline()
                    ToggleRow(
                        title = "Ask me after every call",
                        detail = "The wrap-up sheet, so your read beats the model's guess",
                        checked = p.askAfterEveryCall,
                    ) { scope.launch { vm.settings.setAskAfterEveryCall(it) } }
                    Hairline()
                    ToggleRow(
                        title = "Show live transcript",
                        detail = "Follow the conversation while the agent talks. Uses a little more data.",
                        checked = p.showTranscript,
                    ) { scope.launch { vm.settings.setShowTranscript(it) } }
                }
                Spacer(Modifier.height(10.dp))
                MicroText("You're muted automatically when the lead joins; tap Unmute on the call screen to speak.")
                Spacer(Modifier.height(24.dp))
            }
        }

        item(key = "app") {
            SectionLabel("App")
            Spacer(Modifier.height(10.dp))
            HbCard(Modifier.fillMaxWidth()) {
                SettingRow(
                    icon = R.drawable.ic_download,
                    title = "Version ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
                    detail = if (update?.updateAvailable == true) "${update.latestVersionName} available" else "Up to date",
                    detailColor = if (update?.updateAvailable == true) c.accent else null,
                ) {
                    if (update?.updateAvailable == true && update.downloadUrl != null) {
                        HbButton(
                            "Update",
                            { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(update.downloadUrl))) },
                            style = HbButtonStyle.Primary, size = HbButtonSize.Small,
                        )
                    }
                }
                Hairline()
                SettingRow(
                    icon = R.drawable.ic_external,
                    title = "Server",
                    detail = prefs?.apiBaseUrl?.removePrefix("https://")?.trimEnd('/') ?: "",
                    onClick = { showServer = !showServer },
                ) { HbIcon(R.drawable.ic_chev_r, size = 17.dp, tint = c.fgDisabled) }
                if (showServer) {
                    Spacer(Modifier.height(12.dp))
                    ServerSettings(vm.settings)
                }
                Hairline()
                // mobile_client_logs already receives everything; this just makes it usable
                // during a pilot without asking a rep to plug the phone into a laptop.
                SettingRow(
                    icon = R.drawable.ic_file,
                    title = "Send diagnostics",
                    detail = if (diagnosticsSent) "Sent — thank you" else "Masked numbers only; helps support",
                    detailColor = if (diagnosticsSent) c.positive else null,
                    onClick = { vm.sendDiagnostics(); diagnosticsSent = true },
                ) { HbIcon(R.drawable.ic_chev_r, size = 17.dp, tint = c.fgDisabled) }
            }
            Spacer(Modifier.height(24.dp))
        }

        item(key = "logout") {
            HbButton(
                "Log out", onLogout, Modifier.fillMaxWidth(), HbButtonStyle.Secondary,
                icon = R.drawable.ic_logout,
            )
            Spacer(Modifier.height(34.dp))
            Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                BuddhaLabLockup(width = 116.dp, alpha = 0.55f)
                Spacer(Modifier.height(10.dp))
                Eyebrow("Towards digital enlightenment", color = c.fgDisabled)
            }
        }
    }
}

@Composable
private fun BatteryRow(context: Context) {
    val c = HbTheme.colors
    val power = context.getSystemService(PowerManager::class.java)
    val exempt = remember {
        runCatching { power?.isIgnoringBatteryOptimizations(context.packageName) == true }.getOrDefault(true)
    }
    SettingRow(
        icon = R.drawable.ic_zap,
        title = "Battery optimisation",
        detail = if (exempt) "Off — long runs are safe" else "On — may interrupt long runs",
        detailColor = if (exempt) null else c.accent,
        onClick = {
            runCatching {
                context.startActivity(
                    Intent(AndroidSettings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                        .setData(Uri.parse("package:${context.packageName}"))
                )
            }
        },
    ) {
        if (exempt) PositivePill("Exempt") else HbIcon(R.drawable.ic_chev_r, size = 17.dp, tint = c.accent)
    }
}

@Composable
private fun SettingRow(
    icon: Int,
    title: String,
    detail: String?,
    modifier: Modifier = Modifier,
    detailColor: Color? = null,
    onClick: (() -> Unit)? = null,
    trailing: @Composable () -> Unit = {},
) {
    val c = HbTheme.colors
    Row(
        modifier.fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(13.dp),
    ) {
        HbIcon(icon, tint = c.fgSubtle)
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, color = c.fg)
            detail?.takeIf { it.isNotBlank() }?.let { MicroText(it, color = detailColor ?: c.fgFaint) }
        }
        trailing()
    }
}

@Composable
private fun ToggleRow(title: String, detail: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    val c = HbTheme.colors
    Row(
        Modifier.fillMaxWidth().clickable { onChange(!checked) }.padding(vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, color = c.fg)
            MicroText(detail)
        }
        BrandSwitch(checked)
    }
}

/** A switch in brand gold; Material's default is a very loud pill at this size. */
@Composable
private fun BrandSwitch(checked: Boolean) {
    val c = HbTheme.colors
    Box(
        Modifier.size(width = 44.dp, height = 26.dp)
            .clip(RoundedCornerShape(percent = 50))
            .background(if (checked) c.accentQuiet else c.surface3)
            .border(1.dp, if (checked) c.borderGold else c.border, RoundedCornerShape(percent = 50)),
        contentAlignment = if (checked) Alignment.CenterEnd else Alignment.CenterStart,
    ) {
        Box(
            Modifier.padding(horizontal = 3.dp).size(18.dp).clip(CircleShape)
                .background(if (checked) c.accent else c.fgDisabled)
        )
    }
}

@Composable
private fun SliderRow(
    label: String,
    value: Float,
    range: ClosedFloatingPointRange<Float>,
    steps: Int,
    display: String,
    minLabel: String,
    maxLabel: String,
    onChange: (Float) -> Unit,
) {
    val c = HbTheme.colors
    Column(Modifier.fillMaxWidth().padding(vertical = 10.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text(label, Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge, color = c.fg)
            MonoText(display, color = c.accent)
        }
        Slider(
            value = value,
            onValueChange = onChange,
            valueRange = range,
            steps = steps,
            colors = SliderDefaults.colors(
                thumbColor = c.accent,
                activeTrackColor = c.accent,
                inactiveTrackColor = Color(0x17FFF0DC),
                activeTickColor = Color.Transparent,
                inactiveTickColor = Color.Transparent,
            ),
        )
        Row(Modifier.fillMaxWidth()) {
            MonoText(minLabel, Modifier.weight(1f))
            MonoText(maxLabel)
        }
    }
}
