package com.HandsFreeBusan.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.Composable
import androidx.lifecycle.viewmodel.compose.viewModel
import com.HandsFreeBusan.app.ui.chat.ChatConversationScreen
import com.HandsFreeBusan.app.ui.chat.ChatHomeScreen
import com.HandsFreeBusan.app.ui.chat.ChatViewModel
import com.HandsFreeBusan.app.ui.theme.HandsFreeBusanTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            HandsFreeBusanTheme(dynamicColor = false) {
                ChatApp()
            }
        }
    }
}

@Composable
private fun ChatApp(vm: ChatViewModel = viewModel()) {
    if (vm.inConversation) {
        BackHandler { vm.back() }
        ChatConversationScreen(
            messages = vm.messages,
            draft = vm.draft,
            sending = vm.sending,
            onDraftChange = vm::updateDraft,
            onSend = vm::send,
            onSuggestion = vm::sendSuggestion,
            onBack = vm::back,
            onReset = vm::resetConversation,
        )
    } else {
        ChatHomeScreen(
            faq = vm.faq,
            sessions = vm.sessions,
            draft = vm.draft,
            onDraftChange = vm::updateDraft,
            onStartPrompt = vm::startFromPrompt,
            onOpenSession = vm::openSession,
        )
    }
}
