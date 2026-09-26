package com.hirebuddha.dialer.data.push

import android.util.Log
import com.hirebuddha.dialer.core.AppJson
import com.hirebuddha.dialer.core.asText
import com.hirebuddha.dialer.data.auth.TokenStore
import com.hirebuddha.dialer.data.settings.AppSettings
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.math.min
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/** Server push (docs 06 §5). Type strings: device.verified, attempt.ai_ready, attempt.unidentified, attempt.ai_ended, run.paused. */
data class PushMessage(val type: String, val raw: JsonObject) {
    fun str(key: String): String? = raw[key].asText()
    val attemptId get() = str("attempt_id")
}

interface PushEvents {
    val messages: SharedFlow<PushMessage>
}

@Singleton
class PushClient @Inject constructor(
    client: OkHttpClient,
    private val tokens: TokenStore,
    private val settings: AppSettings,
) : PushEvents {
    private val http = client.newBuilder().pingInterval(0, java.util.concurrent.TimeUnit.SECONDS).build()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val _messages = MutableSharedFlow<PushMessage>(extraBufferCapacity = 64, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    override val messages: SharedFlow<PushMessage> = _messages.asSharedFlow()
    private val _connected = MutableStateFlow(false)
    val connected: StateFlow<Boolean> = _connected.asStateFlow()

    private var loop: Job? = null
    @Volatile private var socket: WebSocket? = null

    /** Keeps a socket open (with backoff) until [stop]. Safe to call repeatedly. */
    fun start() {
        if (loop?.isActive == true) return
        loop = scope.launch {
            var backoffMs = 1_000L
            while (true) {
                val closedCleanly = connectOnce()
                _connected.value = false
                if (tokens.refreshToken == null) break
                delay(if (closedCleanly) 1_000 else backoffMs)
                backoffMs = min(backoffMs * 2, 30_000)
            }
        }
    }

    fun stop() {
        loop?.cancel()
        loop = null
        socket?.close(1000, "bye")
        socket = null
        _connected.value = false
    }

    /**
     * Sends a call signal to the gateway over the open socket (lead_answered, merged).
     * False when the socket is not authenticated; the caller's HTTP event is the fallback.
     */
    fun signal(attemptId: String, signal: String): Boolean {
        val ws = socket ?: return false
        if (!_connected.value) return false
        val msg = buildJsonObject {
            put("type", "signal")
            put("signal", signal)
            put("attempt_id", attemptId)
        }
        return ws.send(msg.toString())
    }

    private suspend fun connectOnce(): Boolean {
        val prefs = settings.current()
        return openSocket(prefs.pushWsUrl, prefs.deviceId)
    }

    private suspend fun openSocket(url: String, deviceId: String?): Boolean = suspendCancellableCoroutine { cont ->
        val request = Request.Builder().url(url).build()
        val ws = http.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                val hello = buildJsonObject {
                    put("type", "auth")
                    put("access_token", tokens.accessToken.orEmpty())
                    deviceId?.let { put("device_id", it) }
                }
                webSocket.send(hello.toString())
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val obj = runCatching { AppJson.parseToJsonElement(text).jsonObject }.getOrNull() ?: return
                when (val type = obj["type"].asText()) {
                    "auth.ok" -> _connected.value = true
                    "ping" -> webSocket.send("""{"type":"pong"}""")
                    null -> Unit
                    else -> _messages.tryEmit(PushMessage(type, obj))
                }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(code, reason)
                if (code == 4001) {
                    // Access token expired: the next REST call refreshes it before we reconnect.
                    Log.i(TAG, "push auth rejected")
                }
                if (cont.isActive) cont.resumeWith(Result.success(code == 1000))
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.w(TAG, "push socket failure: ${t.javaClass.simpleName}")
                if (cont.isActive) cont.resumeWith(Result.success(false))
            }
        })
        socket = ws
        cont.invokeOnCancellation { ws.cancel() }
    }

    private companion object {
        const val TAG = "PushClient"
    }
}
