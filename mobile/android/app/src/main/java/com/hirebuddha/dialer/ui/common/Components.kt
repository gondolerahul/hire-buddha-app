package com.hirebuddha.dialer.ui.common

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.hirebuddha.dialer.data.api.FunnelDto
import kotlin.math.roundToInt

@Composable
fun Loading(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
}

@Composable
fun ErrorState(message: String, onRetry: (() -> Unit)? = null, modifier: Modifier = Modifier) {
    Column(
        modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(message, textAlign = TextAlign.Center, style = MaterialTheme.typography.bodyLarge)
        if (onRetry != null) {
            Spacer(Modifier.height(16.dp))
            Button(onClick = onRetry) { Text("Try again") }
        }
    }
}

@Composable
fun StatTile(label: String, value: String, modifier: Modifier = Modifier, caption: String? = null) {
    Card(modifier, colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(Modifier.padding(horizontal = 14.dp, vertical = 12.dp)) {
            Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(4.dp))
            Text(value, style = MaterialTheme.typography.headlineSmall)
            caption?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
    }
}

fun pct(rate: Double?): String = rate?.let { "${(it * 100).roundToInt()}%" } ?: "—"

/** Horizontal funnel: one sequential hue, bar length = share of the first stage. */
@Composable
fun FunnelBars(funnel: FunnelDto, modifier: Modifier = Modifier) {
    val stages = listOfNotNull(
        funnel.leads?.let { "Leads" to it },
        "Attempted" to funnel.attempted,
        "Lead answered" to funnel.leadAnswered,
        "Merged with AI" to funnel.merged,
        "Conversation ≥30s" to funnel.conversation,
        "Interested" to funnel.interested,
    )
    val max = stages.maxOfOrNull { it.second }?.coerceAtLeast(1) ?: 1
    val base = MaterialTheme.colorScheme.primary
    Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        stages.forEachIndexed { i, (label, value) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(label, Modifier.width(128.dp), style = MaterialTheme.typography.bodySmall)
                Box(
                    Modifier.weight(1f).height(18.dp).clip(RoundedCornerShape(4.dp))
                        .background(MaterialTheme.colorScheme.surfaceVariant)
                ) {
                    Box(
                        Modifier.fillMaxWidth(value.toFloat() / max).height(18.dp)
                            .background(base.copy(alpha = 1f - i * 0.12f))
                    )
                }
                Text("$value", Modifier.width(48.dp).padding(start = 8.dp), style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

@Composable
fun Pill(text: String, color: Color) {
    Text(
        text,
        Modifier.clip(RoundedCornerShape(50)).background(color.copy(alpha = 0.12f)).padding(horizontal = 8.dp, vertical = 2.dp),
        color = color,
        style = MaterialTheme.typography.labelSmall,
    )
}

fun humanize(code: String?): String = code?.replace('_', ' ')?.replaceFirstChar { it.uppercase() } ?: "—"
