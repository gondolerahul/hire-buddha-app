package com.hirebuddha.dialer.ui

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.hirebuddha.dialer.data.api.ApiResult
import com.hirebuddha.dialer.data.api.AppVersionDto
import com.hirebuddha.dialer.data.api.MeDto
import com.hirebuddha.dialer.data.auth.SessionRepository
import com.hirebuddha.dialer.data.repo.DeviceRepository
import com.hirebuddha.dialer.data.settings.AppSettings
import com.hirebuddha.dialer.telecom.DialerRole
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface AppState {
    data object Loading : AppState
    data object LoggedOut : AppState
    data class Blocked(val message: String, val email: String? = null, val role: String? = null) : AppState
    data class UpdateRequired(val info: AppVersionDto) : AppState
    /** [reverify]: the rep asked from Settings to change SIM or verify again. */
    data class NeedsOnboarding(val me: MeDto, val reverify: Boolean = false) : AppState
    data class Ready(val me: MeDto, val update: AppVersionDto?) : AppState
}

@HiltViewModel
class AppViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val session: SessionRepository,
    private val devices: DeviceRepository,
    private val settings: AppSettings,
) : ViewModel() {

    private val _state = MutableStateFlow<AppState>(AppState.Loading)
    val state: StateFlow<AppState> = _state.asStateFlow()

    init {
        refresh()
        viewModelScope.launch {
            session.events.expired.collect { expired -> if (expired) _state.value = AppState.LoggedOut }
        }
    }

    fun refresh() = viewModelScope.launch {
        _state.value = AppState.Loading
        val update = session.checkForUpdate()
        if (update?.updateRequired == true) {
            _state.value = AppState.UpdateRequired(update)
            return@launch
        }
        if (!session.isLoggedIn) {
            _state.value = AppState.LoggedOut
            return@launch
        }
        when (val me = session.loadMe()) {
            is ApiResult.Ok -> _state.value = resolveReady(me.value, update)
            is ApiResult.Err -> _state.value = when {
                me.httpStatus == 401 -> AppState.LoggedOut
                // The server tells us the role is unsupported but not which role it is;
                // the last signed-in address is the useful half of that answer.
                else -> AppState.Blocked(me.message, settings.current().lastEmail, null)
            }
            ApiResult.Empty -> _state.value = AppState.LoggedOut
        }
    }

    private suspend fun resolveReady(me: MeDto, update: AppVersionDto?): AppState {
        val deviceId = settings.current().deviceId
        val verified = deviceId != null && (devices.status(deviceId) as? ApiResult.Ok)?.value?.status == "verified"
        return if (verified && DialerRole.isHeld(context)) AppState.Ready(me, update) else AppState.NeedsOnboarding(me)
    }

    /**
     * Settings → Calling SIM. Straight to setup with a fresh verification, even though
     * this phone is verified: the rep is here because the SIM or the number changed.
     */
    fun reverify() {
        val current = _state.value as? AppState.Ready ?: return
        _state.value = AppState.NeedsOnboarding(current.me, reverify = true)
    }

    fun onLoggedIn() = refresh()
    fun onOnboarded() = refresh()

    /**
     * Cheap re-check on every resume. A rep can hand the default-dialer role to another
     * app from system settings at any moment, and docs 05 §3 requires us to notice —
     * without it the next run fails at `placeCall` with no explanation.
     */
    fun recheckDeviceReadiness() {
        val current = _state.value
        if (current !is AppState.Ready) return
        if (!DialerRole.isHeld(context)) {
            _state.value = AppState.NeedsOnboarding(current.me)
        }
    }

    fun logout() = viewModelScope.launch {
        session.logout()
        _state.value = AppState.LoggedOut
    }
}
