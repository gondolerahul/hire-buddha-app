package com.hirebuddha.dialer.data.logs

import android.content.Context
import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.hirebuddha.dialer.BuildConfig
import com.hirebuddha.dialer.core.AppJson
import com.hirebuddha.dialer.core.DialerLog
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.HireBuddhaApi
import com.hirebuddha.dialer.data.api.LogBatch
import com.hirebuddha.dialer.data.api.LogEntryDto
import com.hirebuddha.dialer.data.api.apiCall
import com.hirebuddha.dialer.data.settings.AppSettings
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject

@Entity(tableName = "log_entries", indices = [Index(value = ["sent"])])
data class LogRow(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val seq: Long,
    val level: String,
    val tag: String,
    val message: String,
    val fieldsJson: String,
    val deviceTs: String,
    val runId: String?,
    val attemptId: String?,
    val sent: Boolean = false,
)

@Dao
interface LogDao {
    @Insert suspend fun insert(row: LogRow)

    @Query("SELECT * FROM log_entries WHERE sent = 0 ORDER BY id LIMIT :limit")
    suspend fun unsent(limit: Int = 200): List<LogRow>

    @Query("UPDATE log_entries SET sent = 1 WHERE id IN (:ids)")
    suspend fun markSent(ids: List<Long>)

    @Query("SELECT COUNT(*) FROM log_entries WHERE sent = 0")
    suspend fun unsentCount(): Int

    /** Keep the local copy small; the server holds the permanent record. */
    @Query("DELETE FROM log_entries WHERE sent = 1 AND id < (SELECT COALESCE(MAX(id), 0) - 2000 FROM log_entries)")
    suspend fun prune()

    @Query("DELETE FROM log_entries WHERE id < (SELECT COALESCE(MAX(id), 0) - 20000 FROM log_entries)")
    suspend fun trimHard()
}

/**
 * Persists [DialerLog] entries and ships them to the server. Writes are fire-and-forget so
 * logging never blocks a call; uploads are batched, retried by WorkManager, and flushed
 * immediately on errors and at the end of each call attempt.
 */
@Singleton
class LogRepository @Inject constructor(
    private val dao: LogDao,
    private val api: HireBuddhaApi,
    private val settings: AppSettings,
    @ApplicationContext private val context: Context,
) : DialerLog.Sink {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val uploadLock = Mutex()

    override fun write(entry: DialerLog.Entry) {
        scope.launch {
            runCatching {
                dao.insert(
                    LogRow(
                        seq = entry.seq,
                        level = entry.level.name,
                        tag = entry.tag,
                        message = entry.message.take(2000),
                        fieldsJson = JsonObject(entry.fields.mapValues { JsonPrimitive(it.value.take(2000)) }).toString(),
                        deviceTs = entry.deviceTs,
                        runId = entry.runId,
                        attemptId = entry.attemptId,
                    )
                )
                if (entry.level == DialerLog.Level.ERROR) flush()
            }
        }
    }

    fun flushSoon() { scope.launch { flush() } }

    /** Returns true when nothing is left to send. */
    suspend fun flush(): Boolean = uploadLock.withLock {
        val deviceId = settings.current().deviceId
        var sentAll = true
        while (true) {
            val rows = runCatching { dao.unsent() }.getOrDefault(emptyList())
            if (rows.isEmpty()) break
            val batch = LogBatch(
                device_id = deviceId,
                app_version = "${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
                entries = rows.map {
                    LogEntryDto(
                        seq = it.seq,
                        level = it.level,
                        tag = it.tag,
                        message = it.message,
                        fields = runCatching { AppJson.parseToJsonElement(it.fieldsJson).jsonObject }.getOrDefault(JsonObject(emptyMap())),
                        device_ts = it.deviceTs,
                        run_id = it.runId,
                        attempt_id = it.attemptId,
                    )
                },
            )
            when (apiCall { api.postLogs(batch) }) {
                is ApiResult.Ok, ApiResult.Empty -> runCatching { dao.markSent(rows.map { it.id }) }
                is ApiResult.Err -> { sentAll = false; break }
            }
            if (rows.size < 200) break
        }
        runCatching { dao.prune(); dao.trimHard() }
        if (!sentAll) scheduleRetry()
        sentAll && runCatching { dao.unsentCount() }.getOrDefault(1) == 0
    }

    private fun scheduleRetry() {
        WorkManager.getInstance(context).enqueueUniqueWork(
            "log_upload",
            ExistingWorkPolicy.KEEP,
            OneTimeWorkRequestBuilder<LogUploadWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build(),
        )
    }

    /** Ships anything left over even if the app never comes back to the foreground. */
    fun schedulePeriodicUpload() {
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            "log_upload_periodic",
            ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<LogUploadWorker>(30, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build(),
        )
    }
}

@EntryPoint
@InstallIn(SingletonComponent::class)
interface LogEntryPoint {
    fun logs(): LogRepository
}

class LogUploadWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val repo = EntryPointAccessors.fromApplication(applicationContext, LogEntryPoint::class.java).logs()
        return if (repo.flush()) Result.success() else Result.retry()
    }
}
