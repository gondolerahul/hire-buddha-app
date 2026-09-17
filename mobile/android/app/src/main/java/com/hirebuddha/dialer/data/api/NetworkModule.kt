package com.hirebuddha.dialer.data.api

import com.hirebuddha.dialer.BuildConfig
import com.hirebuddha.dialer.core.AppJson
import com.hirebuddha.dialer.data.auth.SessionEvents
import com.hirebuddha.dialer.data.auth.TokenStore
import com.hirebuddha.dialer.data.settings.AppSettings
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import java.util.concurrent.TimeUnit
import javax.inject.Singleton
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import okhttp3.Authenticator
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

/** Retrofit is built once against a placeholder host; this rewrites every request to the configured server. */
class ServerUrlInterceptor(private val settings: AppSettings) : Interceptor {
    @Volatile private var cached: Pair<String, HttpUrl>? = null

    private fun base(): HttpUrl {
        val raw = runBlocking { settings.current().apiBaseUrl }
        cached?.let { if (it.first == raw) return it.second }
        return raw.toHttpUrl().also { cached = raw to it }
    }

    override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
        val req = chain.request()
        if (req.url.host != PLACEHOLDER_HOST) return chain.proceed(req)
        val base = base()
        val url = req.url.newBuilder()
            .scheme(base.scheme).host(base.host).port(base.port)
            .encodedPath(base.encodedPath.trimEnd('/') + req.url.encodedPath)
            .build()
        return chain.proceed(req.newBuilder().url(url).build())
    }

    companion object {
        const val PLACEHOLDER_HOST = "hirebuddha.invalid"
    }
}

class AuthInterceptor(private val tokens: TokenStore) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): okhttp3.Response {
        val req = chain.request()
        val token = tokens.accessToken
        if (token.isNullOrEmpty() || req.url.encodedPath.endsWith("/auth/login")) return chain.proceed(req)
        return chain.proceed(req.newBuilder().header("Authorization", "Bearer $token").build())
    }
}

/** On 401: rotate the refresh token once (serialized) and retry; otherwise end the session. */
class TokenAuthenticator(
    private val tokens: TokenStore,
    private val refreshClient: OkHttpClient,
    private val sessionEvents: SessionEvents,
) : Authenticator {
    private val lock = Any()

    override fun authenticate(route: okhttp3.Route?, response: okhttp3.Response): Request? {
        if (response.request.url.encodedPath.contains("/auth/")) return null
        if (responseCount(response) >= 2) return null
        synchronized(lock) {
            val sent = response.request.header("Authorization")?.removePrefix("Bearer ")
            val current = tokens.accessToken
            if (current != null && current != sent) {
                return response.request.newBuilder().header("Authorization", "Bearer $current").build()
            }
            val refresh = tokens.refreshToken ?: return logout()
            val url = response.request.url.newBuilder().encodedPath(
                response.request.url.encodedPath.substringBefore("/api/v1/") + "/api/v1/auth/refresh"
            ).query(null).build()
            val body = AppJson.encodeToString(RefreshRequest.serializer(), RefreshRequest(refresh))
                .toRequestBody("application/json".toMediaType())
            val refreshed = runCatching {
                refreshClient.newCall(Request.Builder().url(url).post(body).build()).execute().use { r ->
                    if (!r.isSuccessful) null
                    else AppJson.decodeFromString(TokenResponse.serializer(), r.body.string())
                }
            }.getOrNull() ?: return logout()
            tokens.save(refreshed.accessToken, refreshed.refreshToken)
            return response.request.newBuilder().header("Authorization", "Bearer ${refreshed.accessToken}").build()
        }
    }

    private fun logout(): Request? {
        tokens.clear()
        sessionEvents.expired.value = true
        return null
    }

    private fun responseCount(response: okhttp3.Response): Int {
        var r: okhttp3.Response? = response
        var n = 0
        while (r != null) { n++; r = r.priorResponse }
        return n
    }
}

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides @Singleton
    fun sessionEvents() = SessionEvents(MutableStateFlow(false))

    @Provides @Singleton
    fun okHttp(settings: AppSettings, tokens: TokenStore, sessionEvents: SessionEvents): OkHttpClient {
        val urlInterceptor = ServerUrlInterceptor(settings)
        val base = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(120, TimeUnit.SECONDS)
            .addInterceptor(urlInterceptor)
            .build()
        return base.newBuilder()
            .addInterceptor(AuthInterceptor(tokens))
            .authenticator(TokenAuthenticator(tokens, base, sessionEvents))
            .apply {
                if (BuildConfig.DEBUG) {
                    // BASIC only: headers and bodies contain tokens and lead PII.
                    addInterceptor(HttpLoggingInterceptor().setLevel(HttpLoggingInterceptor.Level.BASIC))
                }
            }
            .build()
    }

    @Provides @Singleton
    fun api(client: OkHttpClient): HireBuddhaApi = Retrofit.Builder()
        .baseUrl("https://${ServerUrlInterceptor.PLACEHOLDER_HOST}/api/v1/")
        .client(client)
        .addConverterFactory(AppJson.asConverterFactory("application/json".toMediaType()))
        .build()
        .create(HireBuddhaApi::class.java)
}
