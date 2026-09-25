package com.hirebuddha.dialer.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.data.api.AppVersionDto
import com.hirebuddha.dialer.data.api.MeDto
import com.hirebuddha.dialer.ui.analytics.AnalyticsScreen
import com.hirebuddha.dialer.ui.calls.CallDetailScreen
import com.hirebuddha.dialer.ui.campaigns.CampaignDetailScreen
import com.hirebuddha.dialer.ui.campaigns.CampaignListScreen
import com.hirebuddha.dialer.ui.campaigns.CreateCampaignScreen
import com.hirebuddha.dialer.ui.common.GlassSurface
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.home.TodayScreen
import com.hirebuddha.dialer.ui.run.RunScreen
import com.hirebuddha.dialer.ui.settings.SettingsScreen
import com.hirebuddha.dialer.ui.theme.HbTheme

object Routes {
    const val HOME = "home"
    const val CREATE = "create"
    const val RUN = "run"
    const val CAMPAIGN = "campaign/{id}?filter={filter}"
    const val CALL = "call?session={session}&attempt={attempt}&title={title}"
    fun campaign(id: String, filter: String? = null) = "campaign/$id" + (filter?.let { "?filter=$it" } ?: "")
    fun call(sessionId: String?, attemptId: String?, title: String?) =
        "call?session=${sessionId.orEmpty()}&attempt=${attemptId.orEmpty()}&title=${Uri.encode(title.orEmpty())}"
}

@Composable
fun MainNavigation(
    me: MeDto,
    update: AppVersionDto?,
    openRun: Boolean,
    onRunOpened: () -> Unit,
    onLogout: () -> Unit,
    onDeviceNeedsSetup: () -> Unit,
) {
    val nav = rememberNavController()
    LaunchedEffect(openRun) {
        if (openRun) {
            nav.navigate(Routes.RUN) { launchSingleTop = true }
            onRunOpened()
        }
    }
    NavHost(nav, startDestination = Routes.HOME) {
        composable(Routes.HOME) {
            HomeTabs(
                me = me,
                update = update,
                onOpenCampaign = { nav.navigate(Routes.campaign(it)) },
                onCreate = { nav.navigate(Routes.CREATE) },
                onOpenRun = { nav.navigate(Routes.RUN) { launchSingleTop = true } },
                onLogout = onLogout,
                onDeviceNeedsSetup = onDeviceNeedsSetup,
            )
        }
        composable(Routes.CREATE) {
            CreateCampaignScreen(
                me = me,
                onBack = { nav.popBackStack() },
                onCreated = { id -> nav.popBackStack(); nav.navigate(Routes.campaign(id)) },
            )
        }
        composable(
            Routes.CAMPAIGN,
            arguments = listOf(
                navArgument("id") { type = NavType.StringType },
                navArgument("filter") { type = NavType.StringType; nullable = true; defaultValue = null },
            ),
        ) { entry ->
            CampaignDetailScreen(
                campaignId = entry.arguments?.getString("id").orEmpty(),
                initialFilter = entry.arguments?.getString("filter"),
                isAdmin = me.isAdmin,
                meId = me.userId,
                onBack = { nav.popBackStack() },
                onOpenRun = { nav.navigate(Routes.RUN) { launchSingleTop = true } },
                onOpenCall = { session, attempt, title -> nav.navigate(Routes.call(session, attempt, title)) },
            )
        }
        // The run is a destination, not a tab: it is reachable from Today, the campaign
        // list, campaign detail and the notification, and always opens the same live run.
        composable(Routes.RUN) {
            RunScreen(
                onBack = { nav.popBackStack() },
                // The finished run is not somewhere to come back to, so it leaves the stack.
                onOpenCampaign = { id, filter ->
                    nav.navigate(Routes.campaign(id, filter)) { popUpTo(Routes.RUN) { inclusive = true } }
                },
            )
        }
        composable(
            Routes.CALL,
            arguments = listOf(
                navArgument("session") { type = NavType.StringType; defaultValue = "" },
                navArgument("attempt") { type = NavType.StringType; defaultValue = "" },
                navArgument("title") { type = NavType.StringType; defaultValue = "" },
            ),
        ) { entry ->
            CallDetailScreen(
                sessionId = entry.arguments?.getString("session")?.ifBlank { null },
                attemptId = entry.arguments?.getString("attempt")?.ifBlank { null },
                title = entry.arguments?.getString("title")?.ifBlank { null } ?: "Call",
                onBack = { nav.popBackStack() },
            )
        }
    }
}

private enum class Tab(val label: String, val icon: Int) {
    Today("Today", R.drawable.ic_home),
    Campaigns("Campaigns", R.drawable.ic_list),
    Insights("Insights", R.drawable.ic_chart),
    Settings("Settings", R.drawable.ic_sliders),
}

@Composable
private fun HomeTabs(
    me: MeDto,
    update: AppVersionDto?,
    onOpenCampaign: (String) -> Unit,
    onCreate: () -> Unit,
    onOpenRun: () -> Unit,
    onLogout: () -> Unit,
    onDeviceNeedsSetup: () -> Unit,
) {
    var tab by rememberSaveable { mutableStateOf(Tab.Today.ordinal) }
    val current = Tab.entries[tab]

    Box(Modifier.fillMaxSize().statusBarsPadding()) {
        when (current) {
            Tab.Today -> TodayScreen(
                me = me,
                onOpenCampaign = onOpenCampaign,
                onOpenRun = onOpenRun,
                onSeeAll = { tab = Tab.Campaigns.ordinal },
            )
            Tab.Campaigns -> CampaignListScreen(me = me, onOpen = onOpenCampaign, onOpenRun = onOpenRun)
            Tab.Insights -> AnalyticsScreen(isAdmin = me.isAdmin)
            Tab.Settings -> SettingsScreen(
                me = me, update = update, onLogout = onLogout, onReverify = onDeviceNeedsSetup,
            )
        }

        if (current == Tab.Campaigns) {
            NewCampaignFab(onCreate, Modifier.align(Alignment.BottomEnd))
        }
        TabBar(current, { tab = it.ordinal }, Modifier.align(Alignment.BottomCenter))
    }
}

/**
 * Floating glass tab bar. One of only four places the liquid-glass material is used —
 * it needs content moving underneath it for the refraction to read at all.
 */
@Composable
private fun TabBar(current: Tab, onSelect: (Tab) -> Unit, modifier: Modifier = Modifier) {
    val c = HbTheme.colors
    GlassSurface(
        modifier.fillMaxWidth().padding(horizontal = 14.dp).navigationBarsPadding().padding(bottom = 8.dp),
    ) {
        Row(
            Modifier.fillMaxWidth().height(64.dp).padding(horizontal = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Tab.entries.forEach { entry ->
                val selected = entry == current
                val alpha by animateFloatAsState(if (selected) 1f else 0f, label = "tab")
                Column(
                    Modifier.weight(1f).height(52.dp)
                        .clip(RoundedCornerShape(HbTheme.dims.rXl))
                        .background(c.accentQuiet.copy(alpha = c.accentQuiet.alpha * alpha))
                        .clickable { onSelect(entry) },
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    HbIcon(entry.icon, size = 21.dp, tint = if (selected) c.accent else c.fgSubtle)
                    Spacer(Modifier.height(3.dp))
                    Text(
                        entry.label,
                        style = MaterialTheme.typography.labelSmall,
                        color = if (selected) c.accent else c.fgSubtle,
                    )
                }
            }
        }
    }
}

@Composable
private fun NewCampaignFab(onClick: () -> Unit, modifier: Modifier = Modifier) {
    val c = HbTheme.colors
    Row(
        modifier
            .navigationBarsPadding()
            .padding(end = 20.dp, bottom = 88.dp)
            .height(52.dp)
            .clip(RoundedCornerShape(percent = 50))
            .background(c.accent)
            .clickable(onClick = onClick)
            .padding(horizontal = 20.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(9.dp),
    ) {
        HbIcon(R.drawable.ic_plus, size = 19.dp, tint = c.onAccent)
        Text("New campaign", style = MaterialTheme.typography.labelLarge, color = c.onAccent)
    }
}

/** Opens the APK download for a sideloaded update. */
@Composable
fun rememberUpdateLauncher(): (String) -> Unit {
    val context = LocalContext.current
    return { url -> context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }
}
