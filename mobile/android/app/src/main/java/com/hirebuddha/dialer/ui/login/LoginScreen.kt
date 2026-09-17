package com.hirebuddha.dialer.ui.login

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.auth.SessionRepository
import com.hirebuddha.dialer.data.settings.AppSettings
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

@Composable
fun LoginScreen(onLoggedIn: () -> Unit, vm: LoginViewModel = hiltViewModel()) {
    var showServer by remember { mutableStateOf(false) }
    Column(
        Modifier.fillMaxSize().padding(horizontal = 28.dp).imePadding(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("HireBuddha Dialer", style = MaterialTheme.typography.headlineSmall)
        Text(
            "Sign in with your HireBuddha account",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(28.dp))
        OutlinedTextField(
            value = vm.email, onValueChange = { vm.email = it }, label = { Text("Email") },
            singleLine = true, modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
        )
        Spacer(Modifier.height(12.dp))
        OutlinedTextField(
            value = vm.password, onValueChange = { vm.password = it }, label = { Text("Password") },
            singleLine = true, modifier = Modifier.fillMaxWidth(),
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
        )
        vm.error?.let {
            Spacer(Modifier.height(10.dp))
            Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
        }
        Spacer(Modifier.height(20.dp))
        Button(onClick = { vm.submit(onLoggedIn) }, enabled = !vm.busy, modifier = Modifier.fillMaxWidth().height(48.dp)) {
            if (vm.busy) CircularProgressIndicator(Modifier.height(20.dp), strokeWidth = 2.dp) else Text("Sign in")
        }
        TextButton(onClick = { showServer = !showServer }) { Text(if (showServer) "Hide server settings" else "Server settings") }
        if (showServer) ServerSettings(vm.settings)
    }
}

@Composable
fun ServerSettings(settings: AppSettings) {
    val scope = rememberCoroutineScope()
    var api by remember { mutableStateOf("") }
    var ws by remember { mutableStateOf("") }
    var loaded by remember { mutableStateOf(false) }
    var saved by remember { mutableStateOf(false) }
    if (!loaded) {
        androidx.compose.runtime.LaunchedEffect(Unit) {
            val p = settings.current()
            api = p.apiBaseUrl
            ws = p.pushWsUrl
            loaded = true
        }
    }
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(api, { api = it; saved = false }, label = { Text("API server") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(ws, { ws = it; saved = false }, label = { Text("Push socket") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        TextButton(onClick = { scope.launch { settings.setServer(api, ws); saved = true } }) {
            Text(if (saved) "Saved" else "Save server")
        }
    }
}
