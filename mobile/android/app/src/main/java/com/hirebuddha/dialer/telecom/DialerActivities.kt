package com.hirebuddha.dialer.telecom

import android.os.Bundle
import android.telecom.Call
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Backspace
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.CallEnd
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.hirebuddha.dialer.ui.theme.HireBuddhaTheme
import com.hirebuddha.dialer.ui.theme.StatusColors
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import kotlinx.coroutines.launch

/** Minimal dial pad required of the default phone app (handles ACTION_DIAL / tel: links). */
@AndroidEntryPoint
class DialerActivity : ComponentActivity() {
    @Inject lateinit var registry: CallRegistry

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val initial = intent?.data?.schemeSpecificPart.orEmpty()
        setContent {
            HireBuddhaTheme {
                Surface(Modifier.fillMaxSize()) {
                    DialPad(initial) { number ->
                        val scope = kotlinx.coroutines.MainScope()
                        scope.launch { registry.placeCall(number) }
                        finish()
                    }
                }
            }
        }
    }
}

@Composable
private fun DialPad(initial: String, onCall: (String) -> Unit) {
    var number by remember { mutableStateOf(initial) }
    val keys = listOf("1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#")
    Column(Modifier.fillMaxSize().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Bottom) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(number.ifEmpty { " " }, fontSize = 34.sp, modifier = Modifier.weight(1f))
            IconButton(onClick = { number = number.dropLast(1) }) { Icon(Icons.AutoMirrored.Filled.Backspace, "Delete") }
        }
        Spacer(Modifier.height(24.dp))
        keys.chunked(3).forEach { row ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                row.forEach { k -> TextButton(onClick = { number += k }, modifier = Modifier.size(84.dp)) { Text(k, fontSize = 28.sp) } }
            }
        }
        Spacer(Modifier.height(16.dp))
        FilledIconButton(
            onClick = { if (number.isNotBlank()) onCall(number) },
            modifier = Modifier.size(72.dp),
            colors = IconButtonDefaults.filledIconButtonColors(containerColor = StatusColors.positive),
        ) { Icon(Icons.Filled.Call, "Call") }
    }
}

/** Incoming and ongoing UI for calls that are not part of a campaign run. */
@AndroidEntryPoint
class InCallActivity : ComponentActivity() {
    @Inject lateinit var registry: CallRegistry

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            HireBuddhaTheme {
                Surface(Modifier.fillMaxSize()) {
                    val calls by registry.calls.collectAsStateWithLifecycle()
                    val call = calls.firstOrNull { it.state == CallState.RINGING }
                        ?: calls.firstOrNull { it.state != CallState.DISCONNECTED }
                    LaunchedEffect(call == null) { if (call == null) finish() }
                    if (call != null) CallPanel(call, registry)
                }
            }
        }
    }
}

@Composable
private fun CallPanel(call: CallSnapshot, registry: CallRegistry) {
    var muted by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    Column(Modifier.fillMaxSize().padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.SpaceBetween) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Spacer(Modifier.height(48.dp))
            Text(call.number ?: "Unknown", style = MaterialTheme.typography.headlineSmall)
            Text(
                when (call.state) {
                    CallState.RINGING -> "Incoming call"
                    CallState.DIALING, CallState.NEW -> "Calling…"
                    CallState.HOLDING -> "On hold"
                    else -> "In call"
                },
                style = MaterialTheme.typography.bodyLarge,
            )
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
            if (call.state == CallState.RINGING) {
                Button(
                    onClick = { registry.call(call.id)?.answer(android.telecom.VideoProfile.STATE_AUDIO_ONLY) },
                    colors = ButtonDefaults.buttonColors(containerColor = StatusColors.positive),
                ) { Icon(Icons.Filled.Call, null); Text("  Answer") }
                Button(
                    onClick = {
                        val ringing = registry.call(call.id)
                        if (android.os.Build.VERSION.SDK_INT >= 30) ringing?.reject(Call.REJECT_REASON_DECLINED)
                        else @Suppress("DEPRECATION") ringing?.reject(false, null)
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = StatusColors.negative),
                ) { Icon(Icons.Filled.CallEnd, null); Text("  Decline") }
            } else {
                FilledIconButton(onClick = { muted = !muted; registry.setMuted(muted) }, modifier = Modifier.size(64.dp)) {
                    Icon(if (muted) Icons.Filled.MicOff else Icons.Filled.Mic, "Mute")
                }
                FilledIconButton(
                    onClick = { scope.launch { registry.disconnect(call.id) } },
                    modifier = Modifier.size(64.dp),
                    colors = IconButtonDefaults.filledIconButtonColors(containerColor = StatusColors.negative),
                ) { Icon(Icons.Filled.CallEnd, "End call") }
            }
        }
    }
}
