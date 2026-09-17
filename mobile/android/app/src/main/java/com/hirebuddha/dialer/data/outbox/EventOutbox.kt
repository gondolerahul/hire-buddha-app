package com.hirebuddha.dialer.data.outbox

import android.content.Context
import android.os.SystemClock
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.Transaction
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.hirebuddha.dialer.core.AppJson
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.EventBatch
import com.hirebuddha.dialer.data.api.EventDto
import com.hirebuddha.dialer.data.api.HireBuddhaApi
import com.hirebuddha.dialer.data.api.apiCall
import dagger.Module
import dagger.Provides
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import java.time.Instant
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject

@Entity(tableName = "outbox_events", indices = [Index(value = ["attemptId", "seq"], unique = true)])
data class OutboxEvent(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val attemptId: String,
    val seq: Int,
    val type: String,
    val deviceTs: String,
    val elapsedMs: Long,
    val payloadJson: String,
    val sent: Boolean = false,
)

@Dao
interface OutboxDao {
    @Query("SELECT COALESCE(MAX(seq), 0) FROM outbox_events WHERE attemptId = :attemptId")
    suspend fun maxSeq(attemptId: String): Int

    @Insert suspend fun insert(event: OutboxEvent): Long

    @Query("SELECT * FROM outbox_events WHERE sent = 0 ORDER BY attemptId, seq LIMIT 200")
    suspend fun unsent(): List<OutboxEvent>

    @Query("UPDATE outbox_events SET sent = 1 WHERE attemptId = :attemptId AND seq IN (:seqs)")
    suspend fun markSent(attemptId: String, seqs: List<Int>)

    @Query("DELETE FROM outbox_events WHERE sent = 1 AND id < (SELECT COALESCE(MAX(id), 0) - 500 FROM outbox_events)")
    suspend fun prune()

    @Query("SELECT COUNT(*) FROM outbox_events WHERE sent = 0")
    suspend fun unsentCount(): Int

    @Transaction
    suspend fun append(attemptId: String, type: String, deviceTs: String, elapsedMs: Long, payloadJson: String): Int {
        val seq = maxSeq(attemptId) + 1
        insert(OutboxEvent(attemptId = attemptId, seq = seq, type = type, deviceTs = deviceTs, elapsedMs = elapsedMs, payloadJson = payloadJson))
        return seq
    }
}

@Database(entities = [OutboxEvent::class], version = 1, exportSchema = true)
abstract class DialerDatabase : RoomDatabase() {
    abstract fun outbox(): OutboxDao
}

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {
    @Provides @Singleton
    fun database(@ApplicationContext context: Context): DialerDatabase =
        Room.databaseBuilder(context, DialerDatabase::class.java, "dialer.db").build()

    @Provides fun outboxDao(db: DialerDatabase): OutboxDao = db.outbox()
}

/**
 * At-least-once delivery of call events (docs 05 §7). Events are persisted first, then
 * posted in per-attempt batches; the server dedupes on (attempt_id, seq).
 */
@Singleton
class EventOutbox @Inject constructor(
    private val dao: OutboxDao,
    private val api: HireBuddhaApi,
    @ApplicationContext private val context: Context,
) {
    private val flushLock = Mutex()

    suspend fun record(attemptId: String, type: String, payload: Map<String, String> = emptyMap()): Int {
        val json = JsonObject(payload.mapValues { JsonPrimitive(it.value) }).toString()
        return dao.append(attemptId, type, Instant.now().toString(), SystemClock.elapsedRealtime(), json)
    }

    /** Returns true when nothing is left unsent. */
    suspend fun flush(): Boolean = flushLock.withLock {
        val pending = dao.unsent()
        if (pending.isEmpty()) return true
        var allOk = true
        for ((attemptId, events) in pending.groupBy { it.attemptId }) {
            val batch = EventBatch(events.map {
                EventDto(it.seq, it.type, it.deviceTs, it.elapsedMs, AppJson.parseToJsonElement(it.payloadJson).jsonObject)
            })
            when (val r = apiCall { api.postEvents(attemptId, batch) }) {
                is ApiResult.Ok -> dao.markSent(attemptId, r.value.accepted + r.value.duplicates)
                is ApiResult.Err -> {
                    // 404/422 are permanent (attempt gone / bad event): drop them rather than retry forever.
                    if (r.httpStatus in listOf(404, 422)) dao.markSent(attemptId, events.map { it.seq }) else allOk = false
                }
                ApiResult.Empty -> allOk = false
            }
        }
        dao.prune()
        if (!allOk) scheduleRetry()
        allOk && dao.unsentCount() == 0
    }

    private fun scheduleRetry() {
        val work = OneTimeWorkRequestBuilder<OutboxFlushWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork("outbox_flush", ExistingWorkPolicy.KEEP, work)
    }
}

@EntryPoint
@InstallIn(SingletonComponent::class)
interface OutboxEntryPoint {
    fun outbox(): EventOutbox
}

class OutboxFlushWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val outbox = EntryPointAccessors.fromApplication(applicationContext, OutboxEntryPoint::class.java).outbox()
        return if (outbox.flush()) Result.success() else Result.retry()
    }
}
