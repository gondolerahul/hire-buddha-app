package com.hirebuddha.dialer.core

import android.util.Log
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.atomic.AtomicLong

/**
 * App-wide structured log. Every entry goes to Logcat and to a sink that persists it and
 * ships it to the server (see `data/logs`), so a rep's phone can be debugged remotely —
 * there is no adb access on a rep's device.
 *
 * Phone numbers are masked before they are stored: logs are kept server-side indefinitely
 * and lead numbers are personal data (docs 08 §1.2).
 */
object DialerLog {

    enum class Level { DEBUG, INFO, WARN, ERROR }

    data class Entry(
        val seq: Long,
        val level: Level,
        val tag: String,
        val message: String,
        val fields: Map<String, String>,
        val deviceTs: String,
        val runId: String?,
        val attemptId: String?,
    )

    fun interface Sink {
        fun write(entry: Entry)
    }

    private val seq = AtomicLong()
    private val pending = ConcurrentLinkedQueue<Entry>()
    @Volatile private var sink: Sink? = null
    @Volatile private var runId: String? = null
    @Volatile private var attemptId: String? = null

    /** Installed once the DI graph is ready; entries logged before that are replayed. */
    fun install(sink: Sink) {
        this.sink = sink
        while (true) {
            val entry = pending.poll() ?: break
            runCatching { sink.write(entry) }
        }
    }

    fun setRun(runId: String?) { this.runId = runId }
    fun setAttempt(attemptId: String?) { this.attemptId = attemptId }

    fun d(tag: String, message: String, vararg fields: Pair<String, Any?>) = log(Level.DEBUG, tag, message, fields)
    fun i(tag: String, message: String, vararg fields: Pair<String, Any?>) = log(Level.INFO, tag, message, fields)
    fun w(tag: String, message: String, vararg fields: Pair<String, Any?>) = log(Level.WARN, tag, message, fields)
    fun e(tag: String, message: String, vararg fields: Pair<String, Any?>) = log(Level.ERROR, tag, message, fields)

    fun e(tag: String, message: String, error: Throwable, vararg fields: Pair<String, Any?>) {
        val withError = fields.toMutableList().apply {
            add("error" to error.javaClass.simpleName)
            add("error_message" to (error.message ?: ""))
            add("stack" to error.stackTraceToString().take(2000))
        }
        log(Level.ERROR, tag, message, withError.toTypedArray())
    }

    private fun log(level: Level, tag: String, message: String, fields: Array<out Pair<String, Any?>>) {
        val entry = Entry(
            seq = seq.incrementAndGet(),
            level = level,
            tag = tag,
            message = message,
            fields = fields.mapNotNull { (k, v) -> v?.let { k to it.toString() } }.toMap(),
            deviceTs = java.time.Instant.now().toString(),
            runId = runId,
            attemptId = attemptId,
        )
        val rendered = if (entry.fields.isEmpty()) message
        else "$message ${entry.fields.entries.joinToString(" ") { "${it.key}=${it.value}" }}"
        when (level) {
            Level.DEBUG -> Log.d(tag, rendered)
            Level.INFO -> Log.i(tag, rendered)
            Level.WARN -> Log.w(tag, rendered)
            Level.ERROR -> Log.e(tag, rendered)
        }
        val target = sink
        if (target == null) {
            pending.offer(entry)
            while (pending.size > 200) pending.poll()
        } else {
            runCatching { target.write(entry) }
        }
    }

    /** '+919812345678' -> '+91••••5678'. Never log a full lead number. */
    fun maskNumber(number: String?): String {
        if (number.isNullOrBlank()) return ""
        val digits = number.filter(Char::isDigit)
        if (digits.length <= 4) return "••••"
        val prefix = if (number.startsWith("+")) number.take(3) else ""
        return "$prefix••••${digits.takeLast(4)}"
    }
}
