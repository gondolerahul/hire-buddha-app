package com.hirebuddha.dialer.data.auth

import com.hirebuddha.dialer.BuildConfig
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.AppVersionDto
import com.hirebuddha.dialer.data.api.HireBuddhaApi
import com.hirebuddha.dialer.data.api.LoginRequest
import com.hirebuddha.dialer.data.api.MeDto
import com.hirebuddha.dialer.data.api.apiCall
import com.hirebuddha.dialer.data.settings.AppSettings
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Set when the refresh token is rejected; the UI returns to login. */
class SessionEvents(val expired: MutableStateFlow<Boolean>)

@Singleton
class SessionRepository @Inject constructor(
    private val api: HireBuddhaApi,
    private val tokens: TokenStore,
    private val settings: AppSettings,
    val events: SessionEvents,
) {
    private val _me = MutableStateFlow<MeDto?>(null)
    val me: StateFlow<MeDto?> = _me.asStateFlow()

    val isLoggedIn: Boolean get() = tokens.refreshToken != null

    suspend fun login(email: String, password: String): ApiResult<MeDto> {
        return when (val r = apiCall { api.login(LoginRequest(email.trim(), password)) }) {
            is ApiResult.Ok -> {
                tokens.save(r.value.accessToken, r.value.refreshToken)
                settings.setLastEmail(email.trim())
                events.expired.value = false
                loadMe().also { if (it !is ApiResult.Ok) logout() }
            }
            is ApiResult.Err -> if (r.httpStatus == 401) {
                ApiResult.Err(401, "bad_credentials", "Incorrect email or password.")
            } else r
            ApiResult.Empty -> ApiResult.Err(-1, "empty", "Login failed.")
        }
    }

    /** Also enforces the tenant-role gate (the endpoint returns 403 role_not_supported). */
    suspend fun loadMe(): ApiResult<MeDto> = apiCall { api.me() }.also { if (it is ApiResult.Ok) _me.value = it.value }

    suspend fun checkForUpdate(): AppVersionDto? =
        (apiCall { api.appVersion(BuildConfig.VERSION_CODE) } as? ApiResult.Ok)?.value

    suspend fun logout() {
        tokens.clear()
        settings.setDeviceId(null)
        _me.value = null
    }
}
