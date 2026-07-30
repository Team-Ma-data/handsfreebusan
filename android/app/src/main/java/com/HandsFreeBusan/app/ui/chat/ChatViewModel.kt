package com.HandsFreeBusan.app.ui.chat

import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.HandsFreeBusan.app.data.api.ApiClient
import com.HandsFreeBusan.app.data.api.Card
import com.HandsFreeBusan.app.data.api.ChatRequest
import com.HandsFreeBusan.app.data.api.FaqResponse
import com.HandsFreeBusan.app.data.api.SessionSummary
import com.HandsFreeBusan.app.data.api.Suggestion
import kotlinx.coroutines.launch

enum class Sender { User, Bot }

/** A single rendered chat row. */
data class UiMessage(
    val sender: Sender,
    val text: String,
    val cards: List<Card> = emptyList(),
    val suggestions: List<Suggestion> = emptyList(),
    val isTyping: Boolean = false,
    val isError: Boolean = false,
)

class ChatViewModel(
    private val api: ApiClient = ApiClient(),
) : ViewModel() {

    // ----- Home (01 Empty state) -----
    var faq by mutableStateOf<FaqResponse?>(null)
        private set
    var sessions by mutableStateOf<List<SessionSummary>>(emptyList())
        private set

    // ----- Conversation (02) -----
    var messages by mutableStateOf<List<UiMessage>>(emptyList())
        private set
    var draft by mutableStateOf("")
        private set
    var sending by mutableStateOf(false)
        private set
    var inConversation by mutableStateOf(false)
        private set

    private var sessionId: String? = null
    private val lang: String = "en"

    init {
        refreshHome()
    }

    /** Loads greeting/chips and recent chats. Failures are non-fatal (offline fallback). */
    fun refreshHome() {
        viewModelScope.launch {
            faq = runCatching { api.faq(lang) }.getOrNull()
        }
        viewModelScope.launch {
            sessions = runCatching { api.sessions().sessions }.getOrElse { emptyList() }
        }
        viewModelScope.launch {
            runCatching { api.health() }
                .onSuccess { Log.i(TAG, "health: $it") }
                .onFailure { Log.w(TAG, "health check failed: ${it.message}") }
        }
    }

    fun updateDraft(value: String) {
        draft = value
    }

    /** Start a brand-new conversation from a home chip or the home input bar. */
    fun startFromPrompt(prompt: String) {
        val text = prompt.trim()
        if (text.isEmpty()) return
        sessionId = null
        messages = emptyList()
        inConversation = true
        draft = ""
        deliver(text)
    }

    /** Resume an existing session from the Recent chats list. */
    fun openSession(session: SessionSummary) {
        sessionId = session.session_id
        messages = emptyList()
        draft = ""
        inConversation = true
    }

    /** Send whatever is currently in the draft field. */
    fun send() {
        val text = draft.trim()
        if (text.isEmpty()) return
        draft = ""
        deliver(text)
    }

    /** Tap a follow-up suggestion chip. */
    fun sendSuggestion(prompt: String) = deliver(prompt.trim())

    private fun deliver(text: String) {
        if (text.isEmpty() || sending) return
        sending = true
        messages = messages +
            UiMessage(Sender.User, text) +
            UiMessage(Sender.Bot, "", isTyping = true)

        viewModelScope.launch {
            val result = runCatching {
                api.chat(ChatRequest(message = text, session_id = sessionId, lang = lang))
            }
            messages = messages.dropLast(1) // remove typing indicator
            result
                .onSuccess { res ->
                    sessionId = res.session_id
                    Log.d(TAG, "engine=${res.engine} tools=${res.tools}")
                    messages = messages + UiMessage(
                        sender = Sender.Bot,
                        text = res.reply,
                        cards = res.cards,
                        suggestions = res.suggestions,
                    )
                }
                .onFailure { e ->
                    Log.e(TAG, "chat failed", e)
                    messages = messages + UiMessage(
                        sender = Sender.Bot,
                        text = "잠시 후 다시 시도해 주세요.",
                        isError = true,
                    )
                }
            sending = false
        }
    }

    /** Retry the last user message after an error. */
    fun retryLast() {
        val lastUser = messages.lastOrNull { it.sender == Sender.User } ?: return
        // drop the trailing error bubble if present
        if (messages.lastOrNull()?.isError == true) {
            messages = messages.dropLast(1)
        }
        deliver(lastUser.text)
    }

    fun back() {
        inConversation = false
        draft = ""
        refreshHome()
    }

    /** DELETE /chat/{id} then return home. */
    fun resetConversation() {
        val id = sessionId
        viewModelScope.launch {
            if (id != null) runCatching { api.deleteChat(id) }
            sessionId = null
            messages = emptyList()
            inConversation = false
            refreshHome()
        }
    }

    companion object {
        private const val TAG = "ChatViewModel"
    }
}
