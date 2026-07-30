package com.HandsFreeBusan.app.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

/* ---------- GET /faq ---------- */

@Serializable
data class FaqResponse(
    val lang: String = "en",
    val greeting_title: String = "",
    val greeting_subtitle: String = "",
    val greeting_caption: String = "",
    val section_label: String = "Try asking",
    val chips: List<FaqChip> = emptyList(),
)

@Serializable
data class FaqChip(
    val id: String = "",
    val icon: String = "",
    val label: String = "",
    val prompt: String = "",
)

/* ---------- GET /sessions ---------- */

@Serializable
data class SessionsResponse(
    val sessions: List<SessionSummary> = emptyList(),
)

@Serializable
data class SessionSummary(
    val session_id: String,
    val icon: String = "",
    val title: String = "",
    val relative_time: String = "",
    val updated_at: String? = null,
)

/* ---------- POST /chat ---------- */

@Serializable
data class ChatRequest(
    val message: String,
    val session_id: String? = null,
    val lang: String = "en",
    val lat: Double? = null,
    val lng: Double? = null,
)

@Serializable
data class ChatResponse(
    val session_id: String,
    val reply: String = "",
    val cards: List<Card> = emptyList(),
    val suggestions: List<Suggestion> = emptyList(),
    // `tools`/`engine` are dev-only; kept for logging, not rendered.
    val tools: List<JsonElement> = emptyList(),
    val engine: String? = null,
)

@Serializable
data class Card(
    val type: String = "info",
    val icon: String = "",
    val title: String = "",
    val meta: String = "",
    val badges: List<String> = emptyList(),
    val lines: List<String> = emptyList(),
    val action_label: String? = null,
    val action_url: String? = null,
    // Raw payload for app logic only — never rendered directly.
    val data: JsonElement? = null,
)

@Serializable
data class Suggestion(
    val icon: String = "",
    val label: String = "",
    val prompt: String = "",
)

/* ---------- GET /health ---------- */

@Serializable
data class HealthResponse(
    val status: String = "",
    val model: String? = null,
    val llm_configured: Boolean = false,
    val engine: String? = null,
    val engine_error: String? = null,
)
