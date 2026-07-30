"""툴콜링 오케스트레이터.

흐름: 사용자 발화 → Solar 호출 → tool_calls 있으면 실행 → 결과를 다시 Solar에 → 최종 문장.
도구가 만든 `_cards` 는 LLM을 거치지 않고 그대로 앱으로 나간다 (환각이 카드에 섞이지 않도록).

LLM이 없거나 죽어도 도구는 살아 있으므로, 키워드 폴백으로 카드만이라도 내보낸다.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from .config import get_settings
from .engine_adapter import engine_status
from .prompts import OFFLINE_NOTICE, build_system
from .schemas import Card, ChatRequest, ChatResponse, SessionSummary, Suggestion, ToolTrace
from .solar import SolarUnavailable, get_client
from .stations import nearest
from .tools import TOOL_SPECS, call_tool

log = logging.getLogger("timecarry.agent")

_INTERNAL = ("_cards", "_notes", "_suggestions")


# --------------------------------------------------------------- 세션 저장소

class SessionStore:
    """인메모리 세션. 해커톤 규모엔 충분하고, 필요해지면 Redis로 바꾸면 된다."""

    def __init__(self, max_sessions: int = 500, ttl_sec: int = 60 * 60 * 24 * 7):
        self._d: OrderedDict[str, dict] = OrderedDict()
        self.max_sessions = max_sessions
        self.ttl = ttl_sec

    def _sweep(self) -> None:
        now = time.time()
        for k in [k for k, v in self._d.items() if now - v["ts"] > self.ttl]:
            self._d.pop(k, None)

    def get(self, sid: str | None) -> tuple[str, list[dict]]:
        self._sweep()
        now = time.time()
        if sid and sid in self._d:
            self._d[sid]["ts"] = now
            self._d.move_to_end(sid)
            return sid, self._d[sid]["messages"]
        sid = sid or uuid.uuid4().hex[:16]
        self._d[sid] = {"ts": now, "messages": [], "title": "", "icon": "💬"}
        while len(self._d) > self.max_sessions:
            self._d.popitem(last=False)
        return sid, self._d[sid]["messages"]

    def save(self, sid: str, messages: list[dict], limit: int,
             title: str = "", icon: str = "") -> None:
        s = self._d.get(sid)
        if not s:
            return
        s["messages"] = messages[-limit:]
        s["ts"] = time.time()
        if title and not s["title"]:
            s["title"] = title[:60]
        if icon:
            s["icon"] = icon

    def reset(self, sid: str) -> None:
        self._d.pop(sid, None)

    def recent(self, limit: int = 20) -> list[SessionSummary]:
        self._sweep()
        out = []
        for sid, v in sorted(self._d.items(), key=lambda kv: -kv[1]["ts"]):
            if not v["title"]:
                continue
            out.append(SessionSummary(
                session_id=sid, icon=v["icon"], title=v["title"],
                relative_time=_relative(v["ts"]),
                updated_at=datetime.fromtimestamp(v["ts"], timezone.utc).isoformat(),
            ))
            if len(out) >= limit:
                break
        return out


def _relative(ts: float) -> str:
    days = int((time.time() - ts) // 86400)
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    return f"{days} days ago"


SESSIONS = SessionStore()

#: 최근 대화 아이콘 — 첫 발화 키워드로 고른다 (피그마 Recent chats 의 🧳 / ✈️)
_ICON_HINTS = (
    ("🧳", ("짐", "캐리어", "가방", "보관", "luggage", "bag", "suitcase", "locker", "storage")),
    ("🚚", ("배송", "보내", "deliver", "ship", "send")),
    ("🏧", ("현금", "atm", "환전", "cash", "money", "exchange")),
    ("🎫", ("승차권", "교통카드", "ticket", "transit card")),
    ("✈️", ("공항", "airport", "김해")),
)


def _icon_for(text: str) -> str:
    low = text.lower()
    for icon, kws in _ICON_HINTS:
        if any(k in low for k in kws):
            return icon
    return "💬"


# --------------------------------------------------------------- 유틸

def _strip(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k not in _INTERNAL}


def _collect(payload: dict, cards: list[Card], notes: list[str], sugg: list[Suggestion]) -> None:
    for c in payload.get("_cards", []):
        try:
            cards.append(Card(**c))
        except Exception as e:  # 카드 하나가 깨져도 대화는 살린다
            log.warning("카드 변환 실패: %s", e)
    notes.extend(payload.get("_notes", []))
    for s in payload.get("_suggestions", []):
        try:
            item = Suggestion(**s) if isinstance(s, dict) else Suggestion(label=s, prompt=s)
        except Exception:
            continue
        if all(item.prompt != x.prompt for x in sugg):
            sugg.append(item)


_LANG_NAMES = {"ko": "Korean", "en": "English", "ja": "Japanese", "zh": "Chinese"}
_HANGUL = re.compile(r"[가-힣]")
_KANA = re.compile(r"[぀-ヿ]")
_LATIN = re.compile(r"[A-Za-z]")


def _effective_lang(message: str, hint: str) -> str:
    """사용자 발화의 실제 문자를 보고 답변 언어를 정한다.

    툴 결과가 한국어라 LLM이 한국어로 끌려가는 것을 막기 위해, req.lang(힌트)이
    아니라 '실제로 무슨 언어로 썼는지'를 기준으로 강제한다.
    """
    if _HANGUL.search(message):
        return "ko"
    if _KANA.search(message):
        return "ja"
    if _LATIN.search(message):
        return "en"
    return hint or "en"


def _lang_reminder(lang: str) -> str:
    name = _LANG_NAMES.get(lang, lang)
    return (
        f"Reminder before you write your answer: reply to the user in {name}. "
        f"The tool JSON above is often in Korean — render place names, prices, opening "
        f"hours and every sentence in {name} (keep an untranslatable Korean proper noun, "
        f"then add a short romanization the first time). "
        f"Do not answer in Korean unless the user actually wrote in Korean."
    )


def _context_hint(req: ChatRequest) -> str:
    bits = [f"Current local time is {time.strftime('%Y-%m-%d %H:%M')} (Asia/Seoul, KST)."]
    if req.lat is not None and req.lng is not None:
        st = nearest(req.lat, req.lng)
        if st:
            bits.append(f"The user's GPS puts them nearest to {st['name']} station.")
    return " ".join(bits)


# --------------------------------------------------------------- 메인

def run_chat(req: ChatRequest) -> ChatResponse:
    settings = get_settings()
    sid, history = SESSIONS.get(req.session_id)
    client = get_client()

    cards: list[Card] = []
    notes: list[str] = []
    suggestions: list[Suggestion] = []
    traces: list[ToolTrace] = []

    if not client.ready:
        return _fallback(req, sid, history, "no_api_key")

    out_lang = _effective_lang(req.message, req.lang)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system(req.lang, _context_hint(req))},
        *history,
        {"role": "user", "content": req.message},
    ]

    reply = ""
    reminded = False
    try:
        for _ in range(settings.max_tool_turns):
            resp = client.chat(messages, tools=TOOL_SPECS)
            msg = resp.choices[0].message
            calls = getattr(msg, "tool_calls", None) or []

            if not calls:
                reply = (msg.content or "").strip()
                break

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in calls
                ],
            })

            for c in calls:
                name = c.function.name
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                args.setdefault("lang", req.lang)

                result = call_tool(name, args)
                _collect(result, cards, notes, suggestions)
                traces.append(ToolTrace(name=name, arguments=args,
                                        ok="error" not in result,
                                        notes=result.get("_notes", [])))
                messages.append({
                    "role": "tool", "tool_call_id": c.id, "name": name,
                    "content": json.dumps(_strip(result), ensure_ascii=False)[:6000],
                })

            # 툴의 한국어 데이터가 최종 답변 언어를 오염시키지 않도록, 답변 직전에
            # 사용자 발화 언어로 답하라고 다시 못박는다 (프롬프트 맨 앞 지시보다 근접).
            if not reminded:
                messages.append({"role": "system", "content": _lang_reminder(out_lang)})
                reminded = True

    except SolarUnavailable as e:
        log.error("Solar 호출 실패: %s", e)
        return _fallback(req, sid, history, f"llm_error: {e}")

    if not reply:
        reply = OFFLINE_NOTICE.get(req.lang, OFFLINE_NOTICE["en"])

    history = history + [{"role": "user", "content": req.message},
                         {"role": "assistant", "content": reply}]
    SESSIONS.save(sid, history, settings.history_limit,
                  title=req.message, icon=_icon_for(req.message))

    return ChatResponse(session_id=sid, reply=reply, cards=cards,
                        suggestions=suggestions[:4], tools=traces,
                        engine=engine_status()["source"])


# --------------------------------------------------------------- 폴백

_LUGGAGE_KW = ("짐", "캐리어", "가방", "보관", "배송", "luggage", "bag", "suitcase", "locker",
               "storage", "deliver")
_CASH_KW = ("현금", "atm", "환전", "돈", "cash", "money", "exchange", "withdraw", "승차권", "ticket")


def _fallback(req: ChatRequest, sid: str, history: list[dict], why: str) -> ChatResponse:
    """LLM 없이 도구만으로 최소한의 답을 만든다 — 화면이 비지 않게."""
    text = req.message.lower()
    cards: list[Card] = []
    notes: list[str] = [f"fallback: {why}"]
    sugg: list[Suggestion] = []
    traces: list[ToolTrace] = []

    if any(k in text for k in _CASH_KW):
        out = call_tool("cash_and_atm_guide", {"purpose": "unknown", "lang": req.lang})
        _collect(out, cards, notes, sugg)
        traces.append(ToolTrace(name="cash_and_atm_guide", arguments={"purpose": "unknown"},
                                notes=out.get("_notes", [])))
        reply = out.get("question", "")
    elif any(k in text for k in _LUGGAGE_KW):
        out = call_tool("find_luggage_points", {"lang": req.lang})
        _collect(out, cards, notes, sugg)
        traces.append(ToolTrace(name="find_luggage_points", arguments={},
                                notes=out.get("_notes", [])))
        reply = ("부산에서 짐을 맡길 수 있는 곳이에요. 어느 역에 계신지 알려주시면 딱 맞는 방법을 찾아드릴게요."
                 if req.lang == "ko" else
                 "Here are the luggage drop-off points in Busan. Tell me which station you're at and "
                 "I'll find the best option for you.")
    else:
        reply = OFFLINE_NOTICE.get(req.lang, OFFLINE_NOTICE["en"])

    SESSIONS.save(sid, history + [{"role": "user", "content": req.message},
                                  {"role": "assistant", "content": reply}],
                  get_settings().history_limit, title=req.message, icon=_icon_for(req.message))
    return ChatResponse(session_id=sid, reply=reply, cards=cards, suggestions=sugg[:4],
                        tools=traces, engine=engine_status()["source"])
