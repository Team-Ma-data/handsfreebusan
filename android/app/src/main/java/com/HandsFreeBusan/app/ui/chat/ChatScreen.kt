package com.HandsFreeBusan.app.ui.chat

import android.content.Intent
import android.net.Uri
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.HandsFreeBusan.app.data.api.Card
import com.HandsFreeBusan.app.data.api.FaqChip
import com.HandsFreeBusan.app.data.api.FaqResponse
import com.HandsFreeBusan.app.data.api.SessionSummary
import com.HandsFreeBusan.app.data.api.Suggestion
import com.HandsFreeBusan.app.ui.theme.BlueAccent
import com.HandsFreeBusan.app.ui.theme.BlueSoftBg
import com.HandsFreeBusan.app.ui.theme.CardBg
import com.HandsFreeBusan.app.ui.theme.ChipBorder
import com.HandsFreeBusan.app.ui.theme.HairLine
import com.HandsFreeBusan.app.ui.theme.HandsFreeBusanTheme
import com.HandsFreeBusan.app.ui.theme.ScreenBg
import com.HandsFreeBusan.app.ui.theme.TextPrimary
import com.HandsFreeBusan.app.ui.theme.TextSecondary
import com.HandsFreeBusan.app.ui.theme.WarnBg
import com.HandsFreeBusan.app.ui.theme.WarnBorder
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull

/* Offline fallback chips (used when /faq is unreachable). */
private val fallbackChips = listOf(
    FaqChip("luggage", "🧳", "Store my luggage", "Store my luggage"),
    FaqChip("subway", "🚇", "Subway routes", "How do I get around by subway?"),
    FaqChip("food", "🍜", "Food nearby", "What's good to eat nearby?"),
    FaqChip("airport", "✈️", "To the airport", "How do I get to the airport?"),
    FaqChip("card", "💳", "Transit card", "Where do I buy a transit card?"),
    FaqChip("plan", "🗺️", "2-hour plan", "Plan me a 2-hour trip nearby."),
)

/* ---------------------------------------------------------------------------
 * Shared pieces
 * ------------------------------------------------------------------------- */

@Composable
private fun AppBar(title: String, onBack: () -> Unit, onMore: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .height(52.dp)
            .padding(horizontal = 20.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            "‹",
            fontSize = 26.sp,
            color = TextPrimary,
            fontWeight = FontWeight.Light,
            modifier = Modifier
                .clip(CircleShape)
                .clickable(onClick = onBack)
                .padding(horizontal = 6.dp),
        )
        Spacer(Modifier.width(4.dp))
        Text(
            "⋯",
            fontSize = 22.sp,
            color = TextPrimary,
            modifier = Modifier
                .clip(CircleShape)
                .clickable(onClick = onMore)
                .padding(horizontal = 6.dp),
        )
        Text(
            text = title,
            modifier = Modifier.weight(1f),
            fontSize = 17.sp,
            fontWeight = FontWeight.SemiBold,
            color = TextPrimary,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.width(52.dp))
    }
}

@Composable
private fun ChatInputBar(
    value: String,
    onValueChange: (String) -> Unit,
    onSend: () -> Unit,
    enabled: Boolean = true,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 20.dp, vertical = 8.dp)
            .height(56.dp)
            .clip(RoundedCornerShape(28.dp))
            .background(CardBg)
            .padding(start = 16.dp, end = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("＋", fontSize = 22.sp, color = TextSecondary)
        Spacer(Modifier.width(10.dp))
        Box(modifier = Modifier.weight(1f)) {
            if (value.isEmpty()) {
                Text("Ask me anything", fontSize = 16.sp, color = TextSecondary)
            }
            BasicTextField(
                value = value,
                onValueChange = onValueChange,
                textStyle = LocalTextStyle.current.copy(fontSize = 16.sp, color = TextPrimary),
                cursorBrush = SolidColor(BlueAccent),
                singleLine = true,
                enabled = enabled,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { onSend() }),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        Spacer(Modifier.width(8.dp))
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(CircleShape)
                .background(if (enabled) BlueAccent else TextSecondary)
                .clickable(enabled = enabled, onClick = onSend),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.Send,
                contentDescription = "Send",
                tint = ScreenBg,
                modifier = Modifier.size(20.dp),
            )
        }
    }
}

@Composable
private fun Chip(text: String, onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .border(1.dp, ChipBorder, RoundedCornerShape(999.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 10.dp),
    ) {
        Text(text, fontSize = 14.sp, color = TextPrimary, fontWeight = FontWeight.Medium)
    }
}

/* ---------------------------------------------------------------------------
 * Screen 1 — Empty / home state
 * ------------------------------------------------------------------------- */

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ChatHomeScreen(
    faq: FaqResponse? = null,
    sessions: List<SessionSummary> = emptyList(),
    draft: String = "",
    onDraftChange: (String) -> Unit = {},
    onStartPrompt: (String) -> Unit = {},
    onOpenSession: (SessionSummary) -> Unit = {},
) {
    val chips = faq?.chips?.takeIf { it.isNotEmpty() } ?: fallbackChips

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(ScreenBg)
            .systemBarsPadding()
            .imePadding(),
    ) {
        AppBar(title = "HandsFreeBusan", onBack = {}, onMore = {})

        Column(
            modifier = Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp),
        ) {
            Spacer(Modifier.height(34.dp))

            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(999.dp))
                    .background(BlueSoftBg)
                    .padding(horizontal = 12.dp, vertical = 6.dp),
            ) {
                Text("✦ AI Travel Assistant", fontSize = 13.sp, color = BlueAccent, fontWeight = FontWeight.Medium)
            }
            Spacer(Modifier.height(14.dp))
            Text(
                faq?.greeting_title?.takeIf { it.isNotBlank() } ?: "Hi there 👋",
                fontSize = 28.sp, fontWeight = FontWeight.Bold, color = TextPrimary,
            )
            Text(
                faq?.greeting_subtitle?.takeIf { it.isNotBlank() } ?: "How can I help?",
                fontSize = 28.sp, fontWeight = FontWeight.Bold, color = TextPrimary,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                faq?.greeting_caption?.takeIf { it.isNotBlank() }
                    ?: "From luggage storage to directions — just ask.",
                fontSize = 15.sp, color = TextSecondary,
            )

            Spacer(Modifier.height(38.dp))
            Text(
                faq?.section_label?.takeIf { it.isNotBlank() } ?: "Try asking",
                fontSize = 14.sp, color = TextSecondary, fontWeight = FontWeight.Medium,
            )
            Spacer(Modifier.height(12.dp))

            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                chips.forEach { c ->
                    Chip("${c.icon} ${c.label}".trim()) { onStartPrompt(c.prompt.ifBlank { c.label }) }
                }
            }

            if (sessions.isNotEmpty()) {
                Spacer(Modifier.height(34.dp))
                Text("Recent chats", fontSize = 14.sp, color = TextSecondary, fontWeight = FontWeight.Medium)
                Spacer(Modifier.height(12.dp))
                RecentChatsCard(sessions, onOpenSession)
            }

            Spacer(Modifier.height(24.dp))
        }

        ChatInputBar(value = draft, onValueChange = onDraftChange, onSend = { onStartPrompt(draft) })
        Spacer(Modifier.height(4.dp))
    }
}

@Composable
private fun RecentChatsCard(sessions: List<SessionSummary>, onOpen: (SessionSummary) -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .border(1.dp, HairLine, RoundedCornerShape(16.dp)),
    ) {
        sessions.forEachIndexed { i, s ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { onOpen(s) }
                    .padding(horizontal = 14.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(s.icon.ifBlank { "💬" }, fontSize = 18.sp)
                Spacer(Modifier.width(10.dp))
                Text(
                    s.title,
                    modifier = Modifier.weight(1f),
                    fontSize = 15.sp,
                    color = TextPrimary,
                    fontWeight = FontWeight.Medium,
                    maxLines = 1,
                )
                Spacer(Modifier.width(8.dp))
                Text(s.relative_time, fontSize = 13.sp, color = TextSecondary)
            }
            if (i < sessions.lastIndex) {
                Box(Modifier.fillMaxWidth().height(1.dp).background(HairLine))
            }
        }
    }
}

/* ---------------------------------------------------------------------------
 * Screen 2 — In conversation
 * ------------------------------------------------------------------------- */

@Composable
fun ChatConversationScreen(
    messages: List<UiMessage>,
    draft: String,
    sending: Boolean,
    onDraftChange: (String) -> Unit,
    onSend: () -> Unit,
    onSuggestion: (String) -> Unit,
    onBack: () -> Unit,
    onReset: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(ScreenBg)
            .systemBarsPadding()
            .imePadding(),
    ) {
        AppBar(title = "HandsFreeBusan", onBack = onBack, onMore = onReset)

        val listState = rememberLazyListState()
        LaunchedEffect(messages.size) {
            if (messages.isNotEmpty()) listState.animateScrollToItem(messages.lastIndex)
        }

        LazyColumn(
            state = listState,
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth()
                .padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            item { Spacer(Modifier.height(2.dp)) }
            items(messages) { msg ->
                when (msg.sender) {
                    Sender.User -> UserBubble(msg.text)
                    Sender.Bot -> BotBubble(msg)
                }
            }
            item { Spacer(Modifier.height(2.dp)) }
        }

        // Follow-up suggestions from the latest bot reply.
        val followUps = messages.lastOrNull { it.sender == Sender.Bot && !it.isTyping }?.suggestions.orEmpty()
        if (followUps.isNotEmpty()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 20.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                followUps.forEach { s ->
                    Chip("${s.icon} ${s.label}".trim()) { onSuggestion(s.prompt.ifBlank { s.label }) }
                }
            }
        }

        ChatInputBar(
            value = draft,
            onValueChange = onDraftChange,
            onSend = onSend,
            enabled = !sending,
        )
        Spacer(Modifier.height(4.dp))
    }
}

@Composable
private fun UserBubble(text: String) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
        Box(
            modifier = Modifier
                .widthIn(max = 280.dp)
                .clip(RoundedCornerShape(20.dp))
                .background(BlueAccent)
                .padding(horizontal = 16.dp, vertical = 12.dp),
        ) {
            Text(text, color = ScreenBg, fontSize = 15.sp, fontWeight = FontWeight.Medium)
        }
    }
}

@Composable
private fun BotBubble(msg: UiMessage) {
    Row(modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .size(30.dp)
                .clip(CircleShape)
                .background(BlueSoftBg),
            contentAlignment = Alignment.Center,
        ) {
            Text("✦", fontSize = 14.sp, color = BlueAccent)
        }
        Spacer(Modifier.width(8.dp))
        Column(
            modifier = Modifier
                .widthIn(max = 300.dp)
                .clip(RoundedCornerShape(20.dp))
                .border(1.dp, HairLine, RoundedCornerShape(20.dp))
                .background(ScreenBg)
                .padding(16.dp),
        ) {
            if (msg.isTyping) {
                TypingDots()
            } else {
                Text(
                    msg.text,
                    color = if (msg.isError) Color(0xFFC0392B) else TextPrimary,
                    fontSize = 15.sp,
                    lineHeight = 21.sp,
                )
                msg.cards.forEach { card ->
                    Spacer(Modifier.height(12.dp))
                    CardView(card)
                }
            }
        }
    }
}

@Composable
private fun TypingDots() {
    val transition = rememberInfiniteTransition(label = "typing")
    Row(verticalAlignment = Alignment.CenterVertically) {
        repeat(3) { i ->
            val a by transition.animateFloat(
                initialValue = 0.3f,
                targetValue = 1f,
                animationSpec = infiniteRepeatable(
                    animation = tween(600, delayMillis = i * 150),
                    repeatMode = RepeatMode.Reverse,
                ),
                label = "dot$i",
            )
            Box(
                modifier = Modifier
                    .padding(end = 4.dp)
                    .size(7.dp)
                    .alpha(a)
                    .clip(CircleShape)
                    .background(TextSecondary),
            )
        }
    }
}

/* ---------- Card rendering (by type) ---------- */

private fun Card.isFeasible(): Boolean {
    val obj = data as? JsonObject ?: return true
    return (obj["feasible"] as? JsonPrimitive)?.booleanOrNull ?: true
}

@Composable
private fun CardView(card: Card) {
    val feasible = card.isFeasible()
    Box(modifier = Modifier.alpha(if (feasible) 1f else 0.55f)) {
        when (card.type) {
            "route" -> RouteCard(card)
            else -> BlockCard(card)
        }
    }
}

@Composable
private fun RouteCard(card: Card) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(CardBg)
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            "${card.icon} ${card.title}".trim(),
            fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = BlueAccent,
        )
        if (card.meta.isNotBlank()) {
            Spacer(Modifier.width(8.dp))
            Text(card.meta, fontSize = 13.sp, color = TextSecondary)
        }
    }
}

@Composable
private fun BlockCard(card: Card) {
    val isWarning = card.type == "warning"
    val isPromo = card.type == "app_promo"

    val container = if (isWarning) WarnBg else CardBg
    val borderColor = when {
        isWarning -> WarnBorder
        isPromo -> BlueAccent
        else -> null
    }
    val titleColor = if (isWarning) Color(0xFF8A6D00) else TextPrimary

    var mod = Modifier
        .fillMaxWidth()
        .clip(RoundedCornerShape(12.dp))
    if (borderColor != null) mod = mod.border(1.dp, borderColor, RoundedCornerShape(12.dp))
    mod = mod.background(container).padding(12.dp)

    Column(modifier = mod) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "${card.icon} ${card.title}".trim(),
                fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = titleColor,
                modifier = Modifier.weight(1f, fill = false),
            )
        }
        if (card.meta.isNotBlank()) {
            Spacer(Modifier.height(4.dp))
            Text(card.meta, fontSize = 13.sp, color = TextSecondary)
        }
        if (card.badges.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                card.badges.forEach { b -> Badge(b) }
            }
        }
        card.lines.forEach { line ->
            Spacer(Modifier.height(4.dp))
            Text(line, fontSize = 12.sp, color = TextSecondary, lineHeight = 17.sp)
        }
        if (card.action_label != null && card.action_url != null) {
            Spacer(Modifier.height(10.dp))
            ActionButton(card.action_label, card.action_url)
        }
    }
}

@Composable
private fun Badge(text: String) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(ScreenBg)
            .border(1.dp, ChipBorder, RoundedCornerShape(999.dp))
            .padding(horizontal = 8.dp, vertical = 3.dp),
    ) {
        Text(text, fontSize = 11.sp, color = TextPrimary, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun ActionButton(label: String, url: String) {
    val context = LocalContext.current
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(BlueAccent)
            .clickable {
                runCatching {
                    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                }
            }
            .padding(vertical = 10.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = ScreenBg)
    }
}

/* ---------------------------------------------------------------------------
 * Previews
 * ------------------------------------------------------------------------- */

@Preview(showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun ChatHomePreview() {
    HandsFreeBusanTheme(dynamicColor = false) { ChatHomeScreen() }
}

@Preview(showBackground = true, widthDp = 390, heightDp = 844)
@Composable
private fun ChatConversationPreview() {
    val sample = listOf(
        UiMessage(Sender.User, "Store my luggage"),
        UiMessage(
            Sender.Bot,
            "Sure! There are 3 luggage storage spots within a 5-minute walk from you.",
            cards = listOf(
                Card(
                    type = "place",
                    icon = "🧳",
                    title = "Hongdae Stn. Exit 3 Lockers",
                    meta = "4 min walk · Open 24h · Small ₩4,000",
                ),
            ),
        ),
        UiMessage(Sender.User, "Get around by subway"),
        UiMessage(
            Sender.Bot,
            "Take Line 2 from Hongik Univ. Station.",
            cards = listOf(
                Card(
                    type = "route",
                    icon = "🚇",
                    title = "Line 2",
                    meta = "Hongik Univ. → Euljiro 1-ga · 21 min",
                ),
            ),
            suggestions = listOf(
                Suggestion("🎫", "Where to buy a transit card", "Where do I buy a transit card?"),
                Suggestion("⏱", "Last train time", "When is the last train?"),
            ),
        ),
    )
    HandsFreeBusanTheme(dynamicColor = false) {
        ChatConversationScreen(sample, "", false, {}, {}, {}, {}, {})
    }
}
