package com.hirebuddha.dialer.data.settings

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.hirebuddha.dialer.BuildConfig
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.settingsStore: DataStore<Preferences> by preferencesDataStore(name = "settings")

data class DialerPrefs(
    val apiBaseUrl: String,
    val pushWsUrl: String,
    val installId: String?,
    val deviceId: String?,
    val phoneAccountId: String?,
    val phoneAccountLabel: String?,
    val gapSeconds: Int,
    val leadRingTimeoutSeconds: Int,
)

/** Non-secret app settings (tokens live in [com.hirebuddha.dialer.data.auth.TokenStore]). */
@Singleton
class AppSettings @Inject constructor(@ApplicationContext private val context: Context) {

    private object Keys {
        val apiBaseUrl = stringPreferencesKey("api_base_url")
        val pushWsUrl = stringPreferencesKey("push_ws_url")
        val installId = stringPreferencesKey("install_id")
        val deviceId = stringPreferencesKey("device_id")
        val phoneAccountId = stringPreferencesKey("phone_account_id")
        val phoneAccountLabel = stringPreferencesKey("phone_account_label")
        val gapSeconds = intPreferencesKey("gap_seconds")
        val leadRingTimeout = intPreferencesKey("lead_ring_timeout_seconds")
    }

    val prefs: Flow<DialerPrefs> = context.settingsStore.data.map { p ->
        DialerPrefs(
            apiBaseUrl = p[Keys.apiBaseUrl] ?: BuildConfig.DEFAULT_API_BASE_URL,
            pushWsUrl = p[Keys.pushWsUrl] ?: BuildConfig.DEFAULT_PUSH_WS_URL,
            installId = p[Keys.installId],
            deviceId = p[Keys.deviceId],
            phoneAccountId = p[Keys.phoneAccountId],
            phoneAccountLabel = p[Keys.phoneAccountLabel],
            gapSeconds = p[Keys.gapSeconds] ?: 5,
            leadRingTimeoutSeconds = p[Keys.leadRingTimeout] ?: 35,
        )
    }

    suspend fun current(): DialerPrefs = prefs.first()

    /** Stable per-install id sent to the backend (regenerated only by reinstalling). */
    suspend fun installId(): String {
        current().installId?.let { return it }
        val id = UUID.randomUUID().toString()
        context.settingsStore.edit { it[Keys.installId] = id }
        return id
    }

    suspend fun setServer(apiBaseUrl: String, pushWsUrl: String) = context.settingsStore.edit {
        it[Keys.apiBaseUrl] = apiBaseUrl.trim().let { u -> if (u.endsWith("/")) u else "$u/" }
        it[Keys.pushWsUrl] = pushWsUrl.trim()
    }

    suspend fun setDeviceId(deviceId: String?) = context.settingsStore.edit {
        if (deviceId == null) it.remove(Keys.deviceId) else it[Keys.deviceId] = deviceId
    }

    suspend fun setPhoneAccount(id: String, label: String) = context.settingsStore.edit {
        it[Keys.phoneAccountId] = id
        it[Keys.phoneAccountLabel] = label
    }

    suspend fun setGapSeconds(seconds: Int) = context.settingsStore.edit { it[Keys.gapSeconds] = seconds.coerceIn(0, 60) }

    suspend fun setLeadRingTimeout(seconds: Int) =
        context.settingsStore.edit { it[Keys.leadRingTimeout] = seconds.coerceIn(15, 60) }
}
