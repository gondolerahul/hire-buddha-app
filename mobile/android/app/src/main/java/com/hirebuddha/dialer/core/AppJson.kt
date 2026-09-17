package com.hirebuddha.dialer.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

val AppJson = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    coerceInputValues = true
    encodeDefaults = true
}

/** Flattens a JSON value to display text (contact fields may be strings or numbers). */
fun JsonElement?.asText(): String? = when (this) {
    null, JsonNull -> null
    is JsonPrimitive -> contentOrNull
    is JsonArray -> joinToString(", ") { it.asText().orEmpty() }
    is JsonObject -> toString()
}

fun JsonObject?.stringMap(): Map<String, String> =
    this?.mapNotNull { (k, v) -> v.asText()?.let { k to it } }?.toMap() ?: emptyMap()
