package com.hirebuddha.dialer.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.outlined.Campaign
import androidx.compose.material.icons.outlined.Insights
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.hirebuddha.dialer.data.api.AppVersionDto
import com.hirebuddha.dialer.data.api.MeDto
import com.hirebuddha.dialer.ui.analytics.AnalyticsScreen
import com.hirebuddha.dialer.ui.calls.CallDetailScreen
import com.hirebuddha.dialer.ui.campaigns.CampaignDetailScreen
import com.hirebuddha.dialer.ui.campaigns.CampaignListScreen
import com.hirebuddha.dialer.ui.campaigns.CreateCampaignScreen
import com.hirebuddha.dialer.ui.run.RunScreen
import com.hirebuddha.dialer.ui.settings.SettingsScreen

object Routes {
    const val HOME = "home"
    const val CREATE = "create"
    const val RUN = "run"
    const val CAMPAIGN = "campaign/{id}"
    const val CALL = "call?session={session}&attempt={attempt}&title={title}"
    fun campaign(id: String) = "campaign/$id"
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
        composable(Routes.CAMPAIGN, arguments = listOf(navArgument("id") { type = NavType.StringType })) { entry ->
            CampaignDetailScreen(
                campaignId = entry.arguments?.getString("id").orEmpty(),
                isAdmin = me.isAdmin,
                onBack = { nav.popBackStack() },
                onOpenRun = { nav.navigate(Routes.RUN) { launchSingleTop = true } },
                onOpenCall = { session, attempt, title -> nav.navigate(Routes.call(session, attempt, title)) },
            )
        }
        composable(Routes.RUN) { RunScreen(onBack = { nav.popBackStack() }) }
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
    var tab by rememberSaveable { mutableStateOf(0) }
    val context = LocalContext.current
    Scaffold(
        bottomBar = {
            NavigationBar {
                NavigationBarItem(tab == 0, { tab = 0 }, { Icon(Icons.Outlined.Campaign, null) }, label = { Text("Campaigns") })
                NavigationBarItem(tab == 1, { tab = 1 }, { Icon(Icons.Outlined.Insights, null) }, label = { Text("Analytics") })
                NavigationBarItem(tab == 2, { tab = 2 }, { Icon(Icons.Outlined.Settings, null) }, label = { Text("Settings") })
            }
        },
        floatingActionButton = {
            if (tab == 0) ExtendedFloatingActionButton(onClick = onCreate, icon = { Icon(Icons.Filled.Add, null) }, text = { Text("New campaign") })
        },
        snackbarHost = {
            if (update?.updateAvailable == true && update.downloadUrl != null) {
                Snackbar(Modifier.padding(12.dp), action = {
                    Button(onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(update.downloadUrl))) }) { Text("Update") }
                }) { Text("Version ${update.latestVersionName} is available") }
            }
        },
    ) { padding ->
        val modifier = Modifier.padding(padding)
        when (tab) {
            0 -> CampaignListScreen(me = me, onOpen = onOpenCampaign, onOpenRun = onOpenRun, modifier = modifier)
            1 -> AnalyticsScreen(isAdmin = me.isAdmin, modifier = modifier)
            else -> SettingsScreen(me = me, onLogout = onLogout, onReverify = onDeviceNeedsSetup, modifier = modifier)
        }
    }
}
