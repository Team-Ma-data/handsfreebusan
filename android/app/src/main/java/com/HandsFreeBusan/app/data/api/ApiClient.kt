package com.HandsFreeBusan.app.data.api

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

/**
 * Thin OkHttp + kotlinx.serialization client for the HandsFreeBusan backend.
 *
 * On the Android emulator the host machine's `localhost` is reachable at
 * `10.0.2.2`. Point [baseUrl] elsewhere (e.g. a LAN IP) when testing on a
 * physical device.
 */
class ApiClient(
    private val baseUrl: String = "http://10.0.2.2:8000",
) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        // LLM replies can take a few seconds; keep the read timeout generous.
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    private val jsonMedia = "application/json; charset=utf-8".toMediaType()

    suspend fun health(): HealthResponse = getJson("/health")

    suspend fun faq(lang: String): FaqResponse =
        getJson("/faq", mapOf("lang" to lang))

    suspend fun sessions(): SessionsResponse = getJson("/sessions")

    suspend fun chat(request: ChatRequest): ChatResponse = withContext(Dispatchers.IO) {
        val payload = json.encodeToString(ChatRequest.serializer(), request)
        val req = Request.Builder()
            .url(baseUrl.trimEnd('/') + "/chat")
            .post(payload.toRequestBody(jsonMedia))
            .build()
        readBody(req).let { json.decodeFromString(ChatResponse.serializer(), it) }
    }

    suspend fun deleteChat(sessionId: String): Unit = withContext(Dispatchers.IO) {
        val req = Request.Builder()
            .url(baseUrl.trimEnd('/') + "/chat/" + sessionId)
            .delete()
            .build()
        readBody(req)
    }

    private suspend inline fun <reified T> getJson(
        path: String,
        query: Map<String, String> = emptyMap(),
    ): T = withContext(Dispatchers.IO) {
        val urlBuilder = (baseUrl.trimEnd('/') + path).toHttpUrl().newBuilder()
        query.forEach { (k, v) -> urlBuilder.addQueryParameter(k, v) }
        val req = Request.Builder().url(urlBuilder.build()).get().build()
        json.decodeFromString<T>(readBody(req))
    }

    /** Runs [request] synchronously, returning the body text or throwing on non-2xx. */
    fun readBody(request: Request): String {
        client.newCall(request).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                error("HTTP ${resp.code} for ${request.url}: ${text.take(200)}")
            }
            return text
        }
    }
}
