package com.hirebuddha.dialer.ui.login

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.hirebuddha.dialer.BuildConfig
import com.hirebuddha.dialer.R
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.auth.SessionRepository
import com.hirebuddha.dialer.data.settings.AppSettings
import com.hirebuddha.dialer.ui.common.BrandDots
import com.hirebuddha.dialer.ui.common.BrandMark
import com.hirebuddha.dialer.ui.common.CardBody
import com.hirebuddha.dialer.ui.common.HbButton
import com.hirebuddha.dialer.ui.common.HbButtonSize
import com.hirebuddha.dialer.ui.common.HbButtonStyle
import com.hirebuddha.dialer.ui.common.HbCard
import com.hirebuddha.dialer.ui.common.HbIcon
import com.hirebuddha.dialer.ui.common.HbIconButton
import com.hirebuddha.dialer.ui.common.HbTextField
import com.hirebuddha.dialer.ui.common.MicroText
import com.hirebuddha.dialer.ui.common.goldGlow
import com.hirebuddha.dialer.ui.theme.HbTheme
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.launch

@HiltViewModel
class LoginViewModel @Inject constructor(
    private val session: SessionRepository,
    val settings: AppSettings,
) : ViewModel() {
    var email by mutableStateOf("")
    var password by mutableStateOf("")
    var busy by mutableStateOf(false)
        private set
    var error by mutableStateOf<String?>(null)
        private set

    init {
        // Reps sign in on a shared handset more often than you would think; prefilling
        // the last address saves the most error-prone typing on the screen.
        viewModelScope.launch { settings.current().lastEmail?.let { if (email.isBlank()) email = it } }
    }

    fun submit(onSuccess: () -> Unit) {
        if (email.isBlank() || password.isBlank()) {
            error = "Enter your email and password."
            return
        }
        busy = true
        error = null
        viewModelScope.launch {
            when (val r = session.login(email, password)) {
                is ApiResult.Ok -> onSuccess()
                is ApiResult.Err -> error = r.message
                ApiResult.Empty -> error = "Login failed."
            }
            busy = false
        }
    }
}

/** Screen 02. Same three fields as before, given air and a brand anchor. */
@Composable
fun LoginScreen(onLoggedIn: () -> Unit, vm: LoginViewModel = hiltViewModel()) {
    val c = HbTheme.colors
    var showServer by remember { mutableStateOf(false) }
    var reveal by remember { mutableStateOf(false) }

    Box(Modifier.fillMaxSize()) {
        Box(Modifier.fillMaxSize().goldGlow(radiusDp = 230.dp, center = Offset(120f, -120f), alpha = 0.85f))
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp).imePadding(),
        ) {
            Spacer(Modifier.height(54.dp))
            BrandMark(height = 121.dp)
            Spacer(Modifier.height(24.dp))
            Text("Sign in", style = MaterialTheme.typography.headlineMedium, color = c.fg)
            Spacer(Modifier.height(8.dp))
            CardBody("Use the same HireBuddha account you use on the web.")

            Spacer(Modifier.height(32.dp))
            HbTextField(
                value = vm.email,
                onValueChange = { vm.email = it },
                label = "Work email",
                placeholder = "you@company.com",
                leadingIcon = R.drawable.ic_mail,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
            )
            Spacer(Modifier.height(14.dp))
            HbTextField(
                value = vm.password,
                onValueChange = { vm.password = it },
                label = "Password",
                leadingIcon = R.drawable.ic_lock,
                visualTransformation = if (reveal) VisualTransformation.None else PasswordVisualTransformation(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                trailing = {
                    HbIconButton(
                        if (reveal) R.drawable.ic_eye else R.drawable.ic_eye,
                        onClick = { reveal = !reveal },
                        size = 40.dp, iconSize = 18.dp,
                        tint = if (reveal) c.accent else c.fgSubtle,
                        contentDescription = if (reveal) "Hide password" else "Show password",
                    )
                },
            )
            vm.error?.let {
                Spacer(Modifier.height(12.dp))
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    HbIcon(R.drawable.ic_alert, size = 16.dp, tint = c.negative)
                    Text(it, style = MaterialTheme.typography.bodyMedium, color = c.negative)
                }
            }

            Spacer(Modifier.height(24.dp))
            HbButton(
                text = if (vm.busy) "Signing in" else "Sign in",
                onClick = { vm.submit(onLoggedIn) },
                modifier = Modifier.fillMaxWidth(),
                size = HbButtonSize.Large,
                enabled = !vm.busy,
                content = if (!vm.busy) null else {
                    { BrandDots(count = 4, dotSize = 6.dp, color = c.onAccent) }
                },
            )
            HbButton(
                text = if (showServer) "Hide server settings" else "Server settings",
                onClick = { showServer = !showServer },
                modifier = Modifier.fillMaxWidth(),
                style = HbButtonStyle.Ghost,
                size = HbButtonSize.Small,
            )
            if (showServer) {
                Spacer(Modifier.height(4.dp))
                ServerSettings(vm.settings)
            }

            Spacer(Modifier.weight(1f))
            Spacer(Modifier.height(40.dp))
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                MicroText("Buddha Cognitive Lab  ·  v${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})")
            }
            Spacer(Modifier.height(22.dp))
        }
    }
}

/**
 * Server override. A real need for a sideloaded build — pilots point at staging — but
 * demoted from a toggle that reflowed the form mid-sign-in to a card behind a link.
 */
@Composable
fun ServerSettings(settings: AppSettings) {
    val scope = rememberCoroutineScope()
    var api by remember { mutableStateOf("") }
    var ws by remember { mutableStateOf("") }
    var loaded by remember { mutableStateOf(false) }
    var saved by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        val p = settings.current()
        api = p.apiBaseUrl
        ws = p.pushWsUrl
        loaded = true
    }
    if (!loaded) return
    HbCard(Modifier.fillMaxWidth()) {
        HbTextField(api, { api = it; saved = false }, label = "API server")
        Spacer(Modifier.height(10.dp))
        HbTextField(ws, { ws = it; saved = false }, label = "Push socket")
        Spacer(Modifier.height(12.dp))
        HbButton(
            text = if (saved) "Saved" else "Save server",
            onClick = { scope.launch { settings.setServer(api, ws); saved = true } },
            modifier = Modifier.fillMaxWidth(),
            style = HbButtonStyle.Secondary,
            size = HbButtonSize.Small,
        )
    }
}
