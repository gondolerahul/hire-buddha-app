package com.hirebuddha.dialer

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.hirebuddha.dialer.ui.AppState
import com.hirebuddha.dialer.ui.AppViewModel
import com.hirebuddha.dialer.ui.MainNavigation
import com.hirebuddha.dialer.ui.common.Loading
import com.hirebuddha.dialer.ui.login.LoginScreen
import com.hirebuddha.dialer.ui.onboarding.OnboardingScreen
import com.hirebuddha.dialer.ui.theme.HireBuddhaTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    private val appViewModel: AppViewModel by viewModels()
    private val openRun = mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        openRun.value = intent?.getBooleanExtra(EXTRA_OPEN_RUN, false) == true
        setContent {
            HireBuddhaTheme {
                Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    val state by appViewModel.state.collectAsStateWithLifecycle()
                    when (val s = state) {
                        AppState.Loading -> Loading()
                        AppState.LoggedOut -> LoginScreen(onLoggedIn = appViewModel::onLoggedIn)
                        is AppState.Blocked -> Blocked(s.message, appViewModel::logout, appViewModel::refresh)
                        is AppState.UpdateRequired -> UpdateRequired(s.info.latestVersionName, s.info.downloadUrl)
                        is AppState.NeedsOnboarding -> OnboardingScreen(me = s.me, onDone = appViewModel::onOnboarded, onLogout = appViewModel::logout)
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

    companion object {
        const val EXTRA_OPEN_RUN = "open_run"
    }
}

@Composable
private fun Blocked(message: String, onLogout: () -> Unit, onRetry: () -> Unit) {
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(message, textAlign = TextAlign.Center, style = MaterialTheme.typography.bodyLarge)
        Spacer(Modifier.height(20.dp))
        Button(onClick = onRetry) { Text("Try again") }
        OutlinedButton(onClick = onLogout) { Text("Log out") }
    }
}

@Composable
private fun UpdateRequired(version: String, url: String?) {
    val context = LocalContext.current
    Column(
        Modifier.fillMaxSize().padding(32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Update required", style = MaterialTheme.typography.headlineSmall)
        Spacer(Modifier.height(8.dp))
        Text("Install version $version to keep calling.", textAlign = TextAlign.Center)
        if (url != null) {
            Spacer(Modifier.height(20.dp))
            Button(onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) }) { Text("Download update") }
        }
    }
}
