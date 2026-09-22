package com.hirebuddha.dialer

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.hirebuddha.dialer.ui.AppState
import com.hirebuddha.dialer.ui.AppViewModel
import com.hirebuddha.dialer.ui.MainNavigation
import com.hirebuddha.dialer.ui.common.Avatar
import com.hirebuddha.dialer.ui.common.BuddhaLabLockup
import com.hirebuddha.dialer.ui.common.CardBody
import com.hirebuddha.dialer.ui.common.CardCaption
import com.hirebuddha.dialer.ui.common.Eyebrow
import com.hirebuddha.dialer.ui.common.HbButton
import com.hirebuddha.dialer.ui.common.HbButtonSize
import com.hirebuddha.dialer.ui.common.HbButtonStyle
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.common.humanize
import com.hirebuddha.dialer.ui.common.initialsOf
import com.hirebuddha.dialer.ui.login.LoginScreen
import com.hirebuddha.dialer.ui.onboarding.OnboardingScreen
import com.hirebuddha.dialer.ui.splash.SplashScreen
import com.hirebuddha.dialer.ui.theme.HbTheme
import com.hirebuddha.dialer.ui.theme.HireBuddhaTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    private val appViewModel: AppViewModel by viewModels()
    private val openRun = mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        // Hold the system splash (the mark on the brand canvas) until the session check
        // has a verdict, so the handoff to SplashScreen is seamless rather than a flash.
        val splash = installSplashScreen()
        splash.setKeepOnScreenCondition { appViewModel.state.value is AppState.Loading }
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        openRun.value = intent?.getBooleanExtra(EXTRA_OPEN_RUN, false) == true
        setContent {
            HireBuddhaTheme {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    val state by appViewModel.state.collectAsStateWithLifecycle()
                    when (val s = state) {
                        AppState.Loading -> SplashScreen()
                        AppState.LoggedOut -> LoginScreen(onLoggedIn = appViewModel::onLoggedIn)
                        is AppState.Blocked -> BlockedScreen(s.message, s.email, s.role, appViewModel::logout, appViewModel::refresh)
                        is AppState.UpdateRequired -> UpdateRequiredScreen(s.info.latestVersionName, s.info.downloadUrl)
                        is AppState.NeedsOnboarding -> OnboardingScreen(
                            me = s.me,
                            onDone = appViewModel::onOnboarded,
                            onLogout = appViewModel::logout,
                        )
                        is AppState.Ready -> MainNavigation(
                            me = s.me,
                            update = s.update,
                            openRun = openRun.value,
                            onRunOpened = { openRun.value = false },
                            onLogout = appViewModel::logout,
                            onDeviceNeedsSetup = appViewModel::refresh,
                        )
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        if (intent.getBooleanExtra(EXTRA_OPEN_RUN, false)) openRun.value = true
    }

    override fun onResume() {
        super.onResume()
        // The rep can revoke the dialer role from system settings at any time; docs 05 §3
        // requires us to notice. Re-resolving the app state sends them back to setup.
        appViewModel.recheckDeviceReadiness()
    }

    companion object {
        const val EXTRA_OPEN_RUN = "open_run"
    }
}

/**
 * The role gate (FR-A2, screen 03). Naming the role and showing whose account it is
 * turns a dead end into a decision — the previous version was one centred sentence.
 */
@Composable
private fun BlockedScreen(
    message: String,
    email: String?,
    role: String?,
    onLogout: () -> Unit,
    onRetry: () -> Unit,
) {
    val c = HbTheme.colors
    val context = LocalContext.current
    Column(
        Modifier.fillMaxSize().padding(horizontal = 24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            Modifier.size(64.dp).clip(RoundedCornerShape(20.dp))
                .background(c.surface2),
            contentAlignment = Alignment.Center,
        ) { HbIcon(R.drawable.ic_device, size = 28.dp, tint = c.fgSubtle) }
        Spacer(Modifier.height(24.dp))
        Text(
            "This app is for reps",
            style = MaterialTheme.typography.headlineSmall,
            color = c.fg,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(10.dp))
        CardBody(message, Modifier.fillMaxWidth().padding(horizontal = 8.dp))
        if (email != null) {
            Spacer(Modifier.height(24.dp))
            HbCard(Modifier.fillMaxWidth(), padding = 14.dp) {
                androidx.compose.foundation.layout.Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Avatar(initialsOf(email.substringBefore('@')), gold = true)
                    Column(Modifier.weight(1f)) {
                        Text(email, style = MaterialTheme.typography.titleMedium, color = c.fg)
                        role?.let { CardCaption(humanize(it)) }
                    }
                }
            }
        }
        Spacer(Modifier.height(20.dp))
        HbButton(
            "Open the web console",
            onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(WEB_CONSOLE_URL))) },
            modifier = Modifier.fillMaxWidth(),
            style = HbButtonStyle.Secondary,
            icon = R.drawable.ic_external,
        )
        Spacer(Modifier.height(6.dp))
        HbButton("Try again", onRetry, Modifier.fillMaxWidth(), HbButtonStyle.Ghost, HbButtonSize.Small)
        HbButton("Sign in as someone else", onLogout, Modifier.fillMaxWidth(), HbButtonStyle.Ghost, HbButtonSize.Small)
    }
}

/**
 * A hard version gate. Private distribution means there is no store to push through,
 * so this is the only lever when a release breaks the wire contract.
 */
@Composable
private fun UpdateRequiredScreen(version: String, url: String?) {
    val c = HbTheme.colors
    val context = LocalContext.current
    Column(
        Modifier.fillMaxSize().padding(horizontal = 24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            Modifier.size(64.dp).clip(RoundedCornerShape(20.dp)).background(c.accentQuiet),
            contentAlignment = Alignment.Center,
        ) { HbIcon(R.drawable.ic_download, size = 28.dp, tint = c.accent) }
        Spacer(Modifier.height(24.dp))
        Eyebrow("Update required")
        Spacer(Modifier.height(10.dp))
        Text(
            "Version $version is ready",
            style = MaterialTheme.typography.headlineSmall,
            color = c.fg,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(8.dp))
        CardBody("This version can no longer place calls. Install the update to keep working.")
        if (url != null) {
            Spacer(Modifier.height(24.dp))
            HbButton(
                "Download update",
                onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) },
                modifier = Modifier.fillMaxWidth(),
                size = HbButtonSize.Large,
                icon = R.drawable.ic_download,
            )
        }
        Spacer(Modifier.height(40.dp))
        BuddhaLabLockup(width = 116.dp, alpha = 0.5f)
    }
}

private const val WEB_CONSOLE_URL = "https://app.hirebuddha.com/"
