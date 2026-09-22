package com.hirebuddha.dialer.ui.campaigns

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.PowerManager
import android.provider.Settings
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.data.api.PreflightDto
import com.hirebuddha.dialer.telecom.DialerRole
import com.hirebuddha.dialer.ui.common.BrandDots
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.Eyebrow
import com.hirebuddha.dialer.ui.common.Hairline
import com.hirebuddha.dialer.ui.common.HbButton
import com.hirebuddha.dialer.ui.common.HbButtonSize
import com.hirebuddha.dialer.ui.common.HbButtonStyle
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.MonoText
import com.hirebuddha.dialer.ui.theme.HbTheme

/**
 * Screen 13 — the pre-flight check, and the single highest-value addition in this pass.
 *
 * Every condition here already existed: calling hours and the daily cap are enforced by
 * the lease endpoint, credits by `create_attempt`, the dialer role by Android itself.
 * The app simply had no way to read them before a run, so a rep met each one as a failed
 * call somewhere in the middle of an afternoon.
 *
 * A *warning* (battery saver, no headset) never blocks: the rep knows things we don't.
 * A *blocker* does, because it is a condition the server enforces on every single lease —
 * outside calling hours, cap reached, no credits, no DID. Starting into one of those does
 * not fail loudly, it starts a run that pauses on its first lead, which is exactly how
 * "the call is not initiating" looked in the field.
 */
@Composable
fun PreflightSheet(
    preflight: PreflightDto?,
    starting: Boolean,
    error: String?,
    onStart: () -> Unit,
    onDismiss: () -> Unit,
) {
    val c = HbTheme.colors
    val context = LocalContext.current
    val checks = remember(preflight) { buildChecks(context, preflight) }
    val blockers = checks.count { it.level == Level.Blocked }

    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().background(Color(0xA8000000)).clickable(onClick = onDismiss))
        Column(
            Modifier.align(Alignment.BottomCenter).fillMaxWidth()
                .clip(RoundedCornerShape(topStart = HbTheme.dims.r2Xl, topEnd = HbTheme.dims.r2Xl))
                .background(c.surface)
                .border(
                    1.dp, c.borderStrong,
                    RoundedCornerShape(topStart = HbTheme.dims.r2Xl, topEnd = HbTheme.dims.r2Xl),
                )
                .padding(horizontal = HbTheme.dims.gutter)
                .navigationBarsPadding()
                .padding(top = 10.dp, bottom = 16.dp),
        ) {
            Box(
                Modifier.align(Alignment.CenterHorizontally)
                    .size(width = 38.dp, height = 4.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(c.borderStrong)
            )
            Spacer(Modifier.height(18.dp))
            Eyebrow("Before we start")
            Spacer(Modifier.height(8.dp))
            val firstBlocker = checks.firstOrNull { it.level == Level.Blocked }
            Text(
                when {
                    blockers == 0 -> "Your phone is ready"
                    blockers == 1 -> "One thing to sort out first"
                    else -> "$blockers things to sort out first"
                },
                style = MaterialTheme.typography.headlineSmall,
                color = c.fg,
            )
            Spacer(Modifier.height(6.dp))
            CardCaption(
                when {
                    preflight == null -> "Checking what this phone can do. Some checks need a newer server."
                    firstBlocker != null ->
                        "${firstBlocker.title} — the server refuses every call until this is fixed, " +
                            "so the run would start and immediately pause."
                    else -> "${checks.size} checks, so a run never stops halfway for a reason we could have caught."
                },
            )

            Spacer(Modifier.height(16.dp))
            if (preflight == null && checks.isEmpty()) {
                Row(Modifier.fillMaxWidth().padding(vertical = 20.dp), horizontalArrangement = Arrangement.Center) {
                    BrandDots()
                }
            } else {
                HbCard(Modifier.fillMaxWidth()) {
                    checks.forEachIndexed { i, check ->
                        if (i > 0) Hairline()
                        CheckRow(check, context)
                    }
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                MicroText(it, color = c.negative)
            }

            Spacer(Modifier.height(16.dp))
            HbButton(
                text = if (starting) "Starting" else if (blockers > 0) "Can't start yet" else "Start the run",
                onClick = onStart,
                modifier = Modifier.fillMaxWidth(),
                style = if (blockers == 0) HbButtonStyle.Hero else HbButtonStyle.Secondary,
                size = HbButtonSize.Large,
                icon = if (starting || blockers > 0) null else R.drawable.ic_phone,
                // Deliberately not startable: every lease would be refused.
                enabled = !starting && blockers == 0,
                content = if (!starting) null else {
                    { BrandDots(count = 4, dotSize = 6.dp, color = c.onAccent) }
                },
            )
            HbButton(
                if (blockers > 0) "Close" else "Not now",
                onDismiss, Modifier.fillMaxWidth(), HbButtonStyle.Ghost, HbButtonSize.Small,
            )
        }
    }
}

private enum class Level { Ok, Warn, Blocked }

private data class Check(
    val title: String,
    val detail: String?,
    val level: Level,
    val trailing: String? = null,
    val fix: ((Context) -> Unit)? = null,
)

/**
 * Local checks come first because they are the ones the rep can act on right now;
 * server-side limits follow. A missing pre-flight endpoint degrades to local-only.
 */
private fun buildChecks(context: Context, p: PreflightDto?): List<Check> {
    val checks = mutableListOf<Check>()

    checks += if (DialerRole.isHeld(context)) {
        Check("Default phone app", null, Level.Ok, trailing = "Active")
    } else {
        Check(
            "Default phone app", "Needed to hear the lead answer and merge the calls",
            Level.Blocked, trailing = "Fix",
            fix = { ctx -> ctx.startActivity(DialerRole.requestIntent(ctx)) },
        )
    }

    // Android kills a backgrounded foreground service on several OEM skins unless the
    // app is exempt. This is the commonest cause of a run dying mid-afternoon.
    val power = context.getSystemService(PowerManager::class.java)
    val exempt = runCatching { power?.isIgnoringBatteryOptimizations(context.packageName) == true }.getOrDefault(true)
    if (!exempt) {
        checks += Check(
            "Battery saver is on", "Android may stop the run while the screen is off",
            Level.Warn, trailing = "Fix",
            fix = { ctx ->
                runCatching {
                    ctx.startActivity(
                        Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                            .setData(Uri.parse("package:${ctx.packageName}"))
                    )
                }
            },
        )
    }

    if (p == null) return checks

    checks += if (p.device.verified) {
        Check("Calling SIM", p.device.phoneAccountLabel, Level.Ok, trailing = p.device.verifiedCli?.takeLast(6))
    } else {
        Check("This phone is not verified", "Verify your number in Settings", Level.Blocked)
    }

    val window = p.callingWindow
    checks += if (!window.enforced) {
        Check("Calling window", "No restriction set", Level.Ok)
    } else if (window.open) {
        Check("Calling window open", null, Level.Ok, trailing = "until ${window.end}")
    } else {
        Check(
            "Outside calling hours",
            "Calls are allowed ${window.start}–${window.end} IST. Come back at ${window.start}.",
            Level.Blocked, trailing = "opens ${window.start}",
        )
    }

    val cap = p.dailyCap
    if (cap.limit != null) {
        val remaining = cap.remaining ?: 0
        checks += when {
            remaining <= 0 -> Check("Daily cap reached", "${cap.used} of ${cap.limit} calls today", Level.Blocked)
            remaining <= 20 -> Check("Daily cap", "${cap.used} of ${cap.limit} used", Level.Warn, trailing = "$remaining left")
            else -> Check("Daily cap", null, Level.Ok, trailing = "$remaining left")
        }
    }

    checks += if (p.credits.ok) {
        Check("Agent has credits", null, Level.Ok, trailing = "Ready")
    } else {
        Check("Not enough credits", p.credits.message, Level.Blocked)
    }

    p.campaign?.let { campaign ->
        checks += when {
            campaign.did == null -> Check("The agent has no phone number", "Ask your admin to assign one", Level.Blocked)
            campaign.pending <= 0 -> Check("No leads left", null, Level.Blocked)
            else -> Check("${campaign.agentName ?: "Agent"} is reachable", null, Level.Ok, trailing = campaign.did)
        }
    }

    return checks
}

@Composable
private fun CheckRow(check: Check, context: Context) {
    val c = HbTheme.colors
    val tint = when (check.level) {
        Level.Ok -> c.positive
        Level.Warn -> c.accent
        Level.Blocked -> c.negative
    }
    Row(
        Modifier.fillMaxWidth()
            .then(if (check.fix != null) Modifier.clickable { check.fix.invoke(context) } else Modifier)
            .padding(vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(
            Modifier.size(23.dp).clip(CircleShape)
                .background(if (check.level == Level.Ok) tint else Color.Transparent)
                .border(if (check.level == Level.Ok) 0.dp else 1.75.dp, tint, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            HbIcon(
                when (check.level) {
                    Level.Ok -> R.drawable.ic_check
                    else -> R.drawable.ic_alert
                },
                size = 13.dp,
                tint = if (check.level == Level.Ok) Color(0xFF0F2015) else tint,
            )
        }
        Column(Modifier.weight(1f)) {
            Text(check.title, style = MaterialTheme.typography.titleSmall, color = c.fg)
            check.detail?.let { MicroText(it, color = if (check.level == Level.Ok) c.fgFaint else tint) }
        }
        check.trailing?.let {
            MonoText(it, color = if (check.fix != null) c.accent else c.fgSubtle)
        }
    }
}
