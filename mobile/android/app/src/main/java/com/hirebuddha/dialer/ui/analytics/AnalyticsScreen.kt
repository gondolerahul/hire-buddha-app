package com.hirebuddha.dialer.ui.analytics

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.hirebuddha.dialer.data.api.AnalyticsDto
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.DailyDto
import com.hirebuddha.dialer.data.repo.CampaignRepository
import com.hirebuddha.dialer.ui.common.ErrorState
import com.hirebuddha.dialer.ui.common.FunnelBars
import com.hirebuddha.dialer.ui.common.Loading
import com.hirebuddha.dialer.ui.common.StatTile
import com.hirebuddha.dialer.ui.common.humanize
import com.hirebuddha.dialer.ui.common.pct
import dagger.hilt.android.lifecycle.HiltViewModel
import java.time.LocalDate
import java.time.ZoneId
import javax.inject.Inject
import kotlinx.coroutines.launch

@HiltViewModel
class AnalyticsViewModel @Inject constructor(private val repo: CampaignRepository) : ViewModel() {
    var days by mutableStateOf(7); private set
    var data by mutableStateOf<AnalyticsDto?>(null); private set
    var error by mutableStateOf<String?>(null); private set

    init { load(7) }

    fun load(range: Int) = viewModelScope.launch {
        days = range
        error = null
        val today = LocalDate.now(ZoneId.of("Asia/Kolkata"))
        when (val r = repo.summary(today.minusDays((range - 1).toLong()).toString(), today.toString(), null)) {
            is ApiResult.Ok -> data = r.value
            is ApiResult.Err -> error = r.message
            ApiResult.Empty -> Unit
        }
    }
}

@Composable
fun AnalyticsScreen(isAdmin: Boolean, modifier: Modifier = Modifier, vm: AnalyticsViewModel = hiltViewModel()) {
    Column(modifier.fillMaxSize()) {
        Text(if (isAdmin) "Team analytics" else "My analytics", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(start = 16.dp, top = 20.dp))
        Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(1 to "Today", 7 to "7 days", 30 to "30 days").forEach { (d, label) ->
                FilterChip(selected = vm.days == d, onClick = { vm.load(d) }, label = { Text(label) })
            }
        }
        val a = vm.data
        when {
            vm.error != null && a == null -> ErrorState(vm.error!!, { vm.load(vm.days) })
            a == null -> Loading()
            else -> LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        StatTile("Calls", "${a.funnel.attempts}", Modifier.weight(1f))
                        StatTile("Answered", pct(a.rates.answer), Modifier.weight(1f))
                    }
                }
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        StatTile("Conversations", "${a.funnel.conversation}", Modifier.weight(1f), caption = a.timing.talkMinutes?.let { "$it talk min" })
                        StatTile("Interested", "${a.funnel.interested}", Modifier.weight(1f), caption = "conversion ${pct(a.rates.conversion)}")
                    }
                }
                item {
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(16.dp)) {
                            Text("Funnel", style = MaterialTheme.typography.titleMedium)
                            Spacer(Modifier.height(10.dp))
                            FunnelBars(a.funnel)
                        }
                    }
                }
                if (a.daily.size > 1) item { DailyBars(a.daily) }
                if (a.outcomes.isNotEmpty()) {
                    item {
                        Card(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Text("Outcomes", style = MaterialTheme.typography.titleMedium)
                                a.outcomes.entries.sortedByDescending { it.value }.forEach { (k, v) ->
                                    Row { Text(humanize(k), Modifier.weight(1f)); Text("$v") }
                                }
                            }
                        }
                    }
                }
                if (isAdmin && a.byRep.isNotEmpty()) {
                    item {
                        Card(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                Text("By rep", style = MaterialTheme.typography.titleMedium)
                                a.byRep.forEach { r ->
                                    Column {
                                        Text(r.name, style = MaterialTheme.typography.bodyLarge)
                                        Text("${r.attempts} calls · ${pct(r.answerRate)} answered · ${r.interested} interested · ${r.talkMinutes} min",
                                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/** Calls per day (one series, one hue); interested count shown as the label. */
@Composable
private fun DailyBars(daily: List<DailyDto>) {
    val max = daily.maxOf { it.attempted }.coerceAtLeast(1)
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text("Calls per day", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(12.dp))
            Row(Modifier.fillMaxWidth().height(120.dp), horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.Bottom) {
                daily.takeLast(30).forEach { d ->
                    Box(Modifier.weight(1f).fillMaxHeight(), contentAlignment = Alignment.BottomCenter) {
                        Box(
                            Modifier.fillMaxWidth().fillMaxHeight(d.attempted.toFloat() / max)
                                .clip(RoundedCornerShape(topStart = 3.dp, topEnd = 3.dp))
                                .background(MaterialTheme.colorScheme.primary)
                        )
                    }
                }
            }
            Row(Modifier.fillMaxWidth()) {
                Text(daily.first().date.takeLast(5), style = MaterialTheme.typography.labelSmall, modifier = Modifier.weight(1f))
                Text(daily.last().date.takeLast(5), style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}
