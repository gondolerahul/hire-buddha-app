package com.hirebuddha.dialer.data.api

import com.hirebuddha.dialer.core.AppJson
import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import retrofit2.Response

sealed interface ApiResult<out T> {
    data class Ok<T>(val value: T) : ApiResult<T>
    /** HTTP 204 — e.g. "no more leads". */
    data object Empty : ApiResult<Nothing>
    data class Err(
        val httpStatus: Int,
        val code: String,
        val message: String,
        /**
         * The whole `detail` object, when the server sent one. Errors that name the thing
         * in the way — `device_busy` returns the run to stop — let the app offer the fix
         * instead of a dead end.
         */
        val detail: JsonObject? = null,
    ) : ApiResult<Nothing> {
        val isNetwork get() = httpStatus == 0
        fun field(key: String): String? = (detail?.get(key) as? JsonPrimitive)?.contentOrNull
    }
}

inline fun <T, R> ApiResult<T>.map(f: (T) -> R): ApiResult<R> = when (this) {
    is ApiResult.Ok -> ApiResult.Ok(f(value))
    ApiResult.Empty -> ApiResult.Empty
    is ApiResult.Err -> this
}

fun <T> ApiResult<T>.getOrNull(): T? = (this as? ApiResult.Ok)?.value

/** Executes a Retrofit call and maps transport + FastAPI errors ({"detail": {code, message}} or {"detail": "..."}). */
suspend fun <T> apiCall(block: suspend () -> Response<T>): ApiResult<T> = try {
    val r = block()
    when {
        r.code() == 204 -> ApiResult.Empty
        r.isSuccessful -> r.body()?.let { ApiResult.Ok(it) } ?: ApiResult.Empty
        else -> parseError(r.code(), r.errorBody()?.string())
    }
} catch (e: CancellationException) {
    throw e
} catch (e: IOException) {
    ApiResult.Err(0, "network", "No connection to HireBuddha. Check your internet.")
} catch (e: Exception) {
    ApiResult.Err(-1, "client_error", e.message ?: "Unexpected error")
}

fun parseError(status: Int, body: String?): ApiResult.Err {
    val fallback = when (status) {
        401 -> "Your session expired. Please log in again."
        403 -> "You don't have access to this."
        404 -> "Not found."
        in 500..599 -> "HireBuddha is having trouble. Try again shortly."
        else -> "Request failed ($status)."
    }
    val detail = runCatching { AppJson.parseToJsonElement(body.orEmpty()).jsonObject["detail"] }.getOrNull()
    return when (detail) {
        is JsonObject -> ApiResult.Err(
            status,
            (detail["code"] as? JsonPrimitive)?.contentOrNull ?: "http_$status",
            (detail["message"] as? JsonPrimitive)?.contentOrNull ?: fallback,
            detail,
        )
        is JsonPrimitive -> ApiResult.Err(status, "http_$status", detail.contentOrNull ?: fallback)
        else -> ApiResult.Err(status, "http_$status", fallback)
    }
}
