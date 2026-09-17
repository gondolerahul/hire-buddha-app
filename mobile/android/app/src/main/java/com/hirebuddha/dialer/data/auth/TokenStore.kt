package com.hirebuddha.dialer.data.auth

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import dagger.hilt.android.qualifiers.ApplicationContext
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

data class Session(val accessToken: String, val refreshToken: String)

/**
 * Tokens: the access token stays in memory; the refresh token is encrypted with an
 * AES-GCM key held in the Android Keystore (docs 05 §8). The key never leaves the TEE.
 */
@Singleton
class TokenStore @Inject constructor(@ApplicationContext context: Context) {

    private val prefs = context.getSharedPreferences("secure_session", Context.MODE_PRIVATE)
    private val _session = MutableStateFlow(load())
    val session: StateFlow<Session?> = _session.asStateFlow()

    val accessToken: String? get() = _session.value?.accessToken
    val refreshToken: String? get() = _session.value?.refreshToken

    @Synchronized
    fun save(accessToken: String, refreshToken: String?) {
        val refresh = refreshToken ?: _session.value?.refreshToken ?: return clear()
        prefs.edit()
            .putString(KEY_REFRESH, encrypt(refresh))
            .putString(KEY_ACCESS, encrypt(accessToken))
            .apply()
        _session.value = Session(accessToken, refresh)
    }

    @Synchronized
    fun clear() {
        prefs.edit().clear().apply()
        _session.value = null
    }

    private fun load(): Session? = runCatching {
        val refresh = prefs.getString(KEY_REFRESH, null)?.let(::decrypt) ?: return null
        val access = prefs.getString(KEY_ACCESS, null)?.let(::decrypt).orEmpty()
        Session(access, refresh)
    }.getOrElse {
        prefs.edit().clear().apply() // key invalidated (e.g. screen-lock reset): force re-login
        null
    }

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getEntry(ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(
                KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .setKeySize(256)
                    .build()
            )
        }.generateKey()
    }

    private fun encrypt(plain: String): String {
        val cipher = Cipher.getInstance(TRANSFORMATION).apply { init(Cipher.ENCRYPT_MODE, key()) }
        val out = cipher.iv + cipher.doFinal(plain.toByteArray())
        return Base64.encodeToString(out, Base64.NO_WRAP)
    }

    private fun decrypt(encoded: String): String {
        val bytes = Base64.decode(encoded, Base64.NO_WRAP)
        val cipher = Cipher.getInstance(TRANSFORMATION).apply {
            init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes, 0, IV_LEN))
        }
        return String(cipher.doFinal(bytes, IV_LEN, bytes.size - IV_LEN))
    }

    private companion object {
        const val ALIAS = "hirebuddha_session_key"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_LEN = 12
        const val KEY_REFRESH = "refresh"
        const val KEY_ACCESS = "access"
    }
}
