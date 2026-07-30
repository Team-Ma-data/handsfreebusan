"""
짐 보관·배송 도구 — 팀원 추천 엔진으로 가는 유일한 통로.

여기서 판정은 하지 않는다. 하는 일은 셋뿐이다.
  1. 필수 슬롯이 찼는지 검사한다 (되묻기 UX는 챗봇 책임, 판정은 엔진 책임)
  2. engine_adapter.plan() 을 부른다
  3. PlanResult 를 피그마 카드 모양으로 옮긴다
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from ..engine_adapter import engine_status, plan
from ..plan_types import PlanOption, PlanResult
from ..stations import known_names, resolve

DATA = Path(__file__).resolve().parent.parent.parent / "data"
ZIM = json.loads((DATA / "zimcarry.json").read_text(encoding="utf-8"))

ICON = {"역사 보관함": "🧳", "짐캐리 무인보관함": "🔐", "짐캐리 배송": "🚚",
        "예약배송": "🗓️", "동반이동": "🚇"}


# ─────────────────────────────────────────────────────────────────────────
# 카드 텍스트 영어화 (비한국어 사용자용)
#
# 카드는 LLM을 거치지 않는 '신뢰 사실' 계층이라, 여기서도 LLM을 쓰지 않고
# 엔진이 내는 한국어를 결정적(deterministic) 매핑으로만 옮긴다. 데모 데이터셋이
# 고정이라 아래 표로 실제 출력이 전부 커버된다. 매핑에 없는 새 문자열이 들어오면
# 억지 번역 대신 원문을 남기고(제목·meta), 보조 설명줄이면 숨겨서(_en_lines)
# 한국어가 화면에 노출되지 않도록 방어한다.
# ─────────────────────────────────────────────────────────────────────────

_HANGUL_RE = re.compile(r"[가-힣]")

def _has_hangul(s: str) -> bool:
    return bool(_HANGUL_RE.search(s or ""))

#: 고유명사 — 긴 것부터 치환해야 부분 매칭 사고가 안 난다.
_NAME_MAP = [
    ("KT&G 상상마당 부산", "KT&G Sangsang Madang"),
    ("롯데면세점 부산점", "Lotte Duty Free Busan"),
    ("부산역", "Busan Station"),
    ("해운대", "Haeundae"),
    ("서면", "Seomyeon"),
    ("부산", "Busan"),
]

#: 구조 토큰 / 시설 종류 — 이것도 긴 것부터.
_TOKEN_MAP = [
    ("무인보관함", "self-storage lockers"),
    ("보관함", "lockers"),
    ("인근 숙소", "area hotel"),
    ("짐캐리 배송", "ZimCarry delivery"),
    ("짐과 함께 이동", "Travel with your bags"),
    ("최소부담 경로", "lowest-effort route"),
    ("정거장수", "stops"),
    ("환승", "transfers"),
    ("접수마감", "cut-off"),
    ("접수채널", "channel"),
    ("무료", "Free"),
]

#: 자주 나오는 고정 문장 — 숫자만 바뀌므로 정규식으로 잡아 숫자를 보존한다.
_SENTENCE_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(\d{1,2}:\d{2}) 매장 개점 시 접수$"),
     r"Drop off when the store opens at \1"),
    (re.compile(r"^오늘 (\d{1,2}:\d{2}) 매장 개점 시 접수$"),
     r"Drop off when the store opens at \1 today"),
    (re.compile(r"^(\d{1,2}호선) (.+) 보관함$"),  # "1호선 부산 보관함"
     None),  # 특수 처리 (아래 _en_line 에서)
    (re.compile(r"실시간 점유: 확인 불가 — 잔여 칸수 API 미제공"),
     "Live occupancy: unknown (no remaining-slot API)"),
    (re.compile(r"안내: 지금은 매장 개점\((\d{1,2}:\d{2})\) 전입니다\. "
                r"(\d{1,2}:\d{2})에 접수하면 오늘 (\d{1,2}:\d{2})에 도착합니다\."),
     r"Note: the store opens at \1. Drop off at \2 for delivery by \3 today."),
    (re.compile(r"(.+?) 매장 영업시간 (\d{1,2}:\d{2})~(\d{1,2}:\d{2}) 밖입니다\."),
     r"Outside store hours (\2–\3)."),
]

_LINE_NUM = re.compile(r"^(\d+)호선$")

def _en(text: str) -> str:
    """한국어 카드 문자열을 결정적으로 영어화한다 (없는 건 원문 유지)."""
    if not text or not _has_hangul(text):
        return text
    s = text
    # 1) 통째로 매칭되는 고정 문장 먼저
    for pat, repl in _SENTENCE_RULES:
        if repl is None:
            continue
        new = pat.sub(repl, s)
        if new != s:
            s = new
    # 2) "N호선 X 보관함" → "X Line N lockers"
    m = re.match(r"^(\d+)호선 (.+?) (보관함|무인보관함)$", s)
    if m:
        line_no, place, kind = m.groups()
        place_en = place
        for ko, en in _NAME_MAP:
            place_en = place_en.replace(ko, en)
        kind_en = "self-storage lockers" if kind == "무인보관함" else "lockers"
        s = f"{place_en} Line {line_no} {kind_en}"
    # 3) 고유명사 → 영문
    for ko, en in _NAME_MAP:
        s = s.replace(ko, en)
    # 4) 구조 토큰
    for ko, en in _TOKEN_MAP:
        s = s.replace(ko, en)
    return s.strip()


def _en_lines(lines: list[str]) -> list[str]:
    """설명줄을 영어화하고, 그래도 한국어가 남으면 화면에서 숨긴다."""
    out = []
    for ln in lines:
        t = _en(ln)
        if not _has_hangul(t):
            out.append(t)
    return out


def engine_kind() -> str:
    return engine_status()["source"]


def _parse_dt(v: Optional[str], now: datetime) -> Optional[datetime]:
    if not v:
        return None
    v = v.strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%H:%M"):
        try:
            d = datetime.strptime(v, fmt)
            if fmt == "%H:%M":
                d = now.replace(hour=d.hour, minute=d.minute, second=0, microsecond=0)
                if d < now:
                    d += timedelta(days=1)
            return d
        except ValueError:
            continue
    return None


def _meta(o: PlanOption, lang: str) -> str:
    """피그마의 '4 min walk · Open 24h · Small ₩4,000' 자리."""
    if not o.feasible:
        reason = o.reject_reason or ("이용 불가" if lang == "ko" else "Not available")
        return _en(reason) if lang != "ko" else reason
    bits: list[str] = []
    if o.duration_min:
        bits.append(f"{o.duration_min:.0f}분 소요" if lang == "ko"
                    else f"{o.duration_min:.0f} min")
    if o.out_of_pocket == 0:
        bits.append("무료" if lang == "ko" else "Free")
    else:
        bits.append(f"{o.out_of_pocket:,}원" if lang == "ko" else f"₩{o.out_of_pocket:,}")
    if o.fatigue_note:
        bits.append(o.fatigue_note)
    for key in ("접수마감", "접수채널", "정거장수", "환승"):
        if key in o.evidence:
            bits.append(f"{key} {o.evidence[key]}")
            break
    s = " · ".join(bits)
    return _en(s) if lang != "ko" else s


def _card(o: PlanOption, lang: str) -> dict:
    badges: list[str] = []
    if o.fallback_level:
        badges.append(f"폴백 {o.fallback_level}단" if lang == "ko" else f"Fallback {o.fallback_level}")
    if not o.feasible:
        badges.append("불가" if lang == "ko" else "Blocked")
    if o.backups:
        badges.append("2안 있음" if lang == "ko" else "Backup ready")

    lines: list[str] = []
    if o.backups:
        lines.append(
            ("실시간 잔여 칸수는 공개 API가 없어요. 가서 꽉 찼으면 " + " 또는 ".join(o.backups) + " 로 가시면 됩니다."
             if lang == "ko" else
             "Live locker availability isn't published. If it's full, try " + " or ".join(o.backups) + ".")
        )
    for key in ("안내", "도착시각", "실시간 점유", "회피근거", "최단시간경로와 다름"):
        v = o.evidence.get(key)
        if v:
            lines.append(f"{key}: {v if not isinstance(v, list) else ', '.join(map(str, v[:2]))}")
    return {
        "type": "option",
        "icon": ICON.get(o.kind, "🧳"),
        "title": _en(o.label) if lang != "ko" else o.label,
        "meta": _meta(o, lang),
        "badges": badges,
        "lines": (_en_lines(lines) if lang != "ko" else lines)[:3],
        "data": {"kind": o.kind, "feasible": o.feasible, "out_of_pocket": o.out_of_pocket,
                 "duration_min": o.duration_min, "fallback_level": o.fallback_level,
                 "pressure": o.pressure, "backups": o.backups, "station_code": o.station_code,
                 "fatigue": o.fatigue, "fatigue_note": o.fatigue_note},
    }


def _brief(o: PlanOption, lang: str = "ko") -> dict:
    """LLM에게 넘길 사실. cost_index 는 **일부러 빼서** 모델이 총비용을 말하지 못하게 한다.

    비한국어 요청이면 label 을 영어로 넘겨야 모델이 지명을 한국어로 쓰지 않는다.
    """
    return {
        "kind": o.kind, "label": _en(o.label) if lang != "ko" else o.label, "feasible": o.feasible,
        "paid_krw": o.out_of_pocket, "minutes": round(o.duration_min, 1),
        "blocked_because": o.reject_reason, "fallback_level": o.fallback_level,
        "demand_pressure": o.pressure, "backup_spots": o.backups,
        "evidence": {k: v for k, v in o.evidence.items() if not isinstance(v, (list, dict))},
    }


def plan_luggage_strategy(
    origin_station: Optional[str] = None,
    dest_station: Optional[str] = None,
    luggage: Optional[list] = None,
    checkin_time: Optional[str] = None,
    preference: Optional[str] = None,
    lang: str = "en",
) -> dict:
    now = datetime.now()
    origin = resolve(origin_station)
    dest = resolve(dest_station)

    missing = []
    if not origin:
        missing.append("origin_station")
    if luggage is None:
        missing.append("luggage")
    #: 목적지는 배송을 원할 때만 필수다. 보관만 원하면 없어도 답이 나온다.
    wants_delivery = (preference or "").lower() in ("deliver", "delivery", "배송", "any", "무관", "")
    if not dest and wants_delivery and preference not in (None, "", "store", "storage", "보관"):
        missing.append("dest_station")

    if missing:
        qs = {
            "origin_station": ("지금 어느 역에 계신가요?" if lang == "ko"
                               else "Which station are you at right now?"),
            "dest_station": ("숙소는 어느 역 근처인가요?" if lang == "ko"
                             else "Which station is your accommodation near?"),
            "luggage": ("짐은 어떤 크기로 몇 개인가요? (기내용 / 중형 / 대형 / 특대형)" if lang == "ko"
                        else "What luggage do you have? (cabin / medium / large / oversized, and how many)"),
        }
        return {
            "needs_clarification": True,
            "missing_slots": missing,
            "questions": [qs[m] for m in missing],
            "known_stations_hint": known_names()[:12],
            "instruction_to_assistant": (
                "Ask ONLY for the missing items, in one friendly sentence, in the user's language. "
                "Do not guess and do not recommend anything yet."
            ),
            "_notes": [f"슬롯 부족: {', '.join(missing)} → 엔진 호출 보류"],
        }

    res: PlanResult = plan(
        origin=origin["name"],
        destination=dest["name"] if dest else None,
        items=[{"size": i.get("size", "대형"), "count": i.get("count", 1),
                "weight_kg": i.get("weight_kg")} for i in (luggage or [])],
        at=now,
        preference=preference,
        need_by=_parse_dt(checkin_time, now),
        lang=lang,
    )

    if not res.ok or res.recommended is None:
        return {
            "resolved": False,
            "reason": "제안 가능한 옵션이 없습니다",
            "blocked": [_brief(o, lang) for o in res.rejected],
            "engine": res.source,
            "note_for_assistant": (
                "Tell the user honestly that nothing works right now, name the specific blocker "
                "(e.g. the cut-off time), and offer the earliest time it would work."
            ),
            "_notes": res.notes,
        }

    rec = res.recommended
    feas_alts = [o for o in res.alternatives if o.feasible][:2]
    blocked = [o for o in res.rejected if o.reject_reason][:1]

    cards = [_card(rec, lang)] + [_card(o, lang) for o in feas_alts] + [_card(o, lang) for o in blocked]

    return {
        "resolved": True,
        "origin": origin["name"],
        "destination": dest["name"] if dest else None,
        "now": now.strftime("%Y-%m-%d %H:%M"),
        "recommended": _brief(rec, lang),
        "alternatives": [_brief(o, lang) for o in feas_alts],
        "blocked": [_brief(o, lang) for o in blocked],
        "fallback_level": res.fallback_level,
        "engine": res.source,
        "hard_rules": {
            "delivery_arrival_time_guaranteed": False,
            "note": "짐캐리는 배송 도착 시각을 지정할 수 없다. '체크인 전 도착'을 약속하지 말 것.",
        },
        "note_for_assistant": (
            "Recommend the top option in 2-3 warm sentences and say WHY, naming the concrete constraint "
            "(cut-off time, locker size, store hours). Mention one alternative. "
            "NEVER promise the delivery arrives before check-in. "
            "NEVER state a total 'cost index' — only the paid_krw amount is a real price. "
            "If backup_spots exist, tell the user live locker availability is not published and name the backup."
        ),
        "_cards": cards,
        "_notes": [f"engine={res.source}"] + res.notes,
        "_suggestions": (
            [{"icon": "🔄", "label": "다른 방법은?", "prompt": "다른 방법도 알려줘"},
             {"icon": "🗺️", "label": "짐 맡기고 갈 곳", "prompt": "짐 맡기고 근처에 뭘 보면 좋아?"}]
            if lang == "ko" else
            [{"icon": "🔄", "label": "Other options", "prompt": "Show me the other options"},
             {"icon": "🗺️", "label": "What to see", "prompt": "What can I see nearby while my bags are away?"}]
        ),
    }


def find_luggage_points(station: Optional[str] = None, lang: str = "en") -> dict:
    """사실 조회 전용(판정 없음). 피그마 01 화면의 'Store my luggage' 첫 응답이 여기로 온다."""
    st = resolve(station)
    name = st["name"] if st else None

    depots = [d for d in ZIM["depots"] if d.get("station") == name] if name else ZIM["depots"]
    lockers = [s for s in ZIM["smart_lockers"] if s.get("station") == name] if name else ZIM["smart_lockers"]

    cards = []
    for d in depots:
        meta = [f"{d['open']}–{d['close']}"]
        if d.get("closed_weekdays"):
            meta.append("토·일 휴무" if lang == "ko" else "Closed weekends")
        meta.append("배송·보관" if lang == "ko" else "Delivery & storage")
        cards.append({"type": "place", "icon": "🏪",
                      "title": d["name_ko"] if lang == "ko" else d["name_en"],
                      "meta": " · ".join(meta), "badges": [], "lines": [],
                      "data": {"lat": d["lat"], "lng": d["lng"], "id": d["id"]}})
    for s in lockers:
        cards.append({"type": "place", "icon": "🔐",
                      "title": s["name_ko"] if lang == "ko" else s["name_en"],
                      "meta": (f"{s['slots']}칸 · 발송 접수 가능" if lang == "ko"
                               else f"{s['slots']} lockers · can ship from here"),
                      "badges": [], "lines": [],
                      "data": {"lat": s["lat"], "lng": s["lng"], "id": s["id"]}})

    return {
        "station": name,
        "station_locker_large_slots": (st or {}).get("locker_large_slots"),
        "manned_depots": [{"name": d["name_ko"], "station": d.get("station"),
                           "hours": f"{d['open']}-{d['close']}",
                           "closed_weekends": bool(d.get("closed_weekdays"))} for d in depots],
        "smart_lockers": [{"name": s["name_ko"], "slots": s["slots"]} for s in lockers],
        "live_availability": "not published — there is no public API for remaining locker slots",
        "note_for_assistant": (
            "List what exists, factually. If the user wants a recommendation rather than a list, "
            "call plan_luggage_strategy instead."
        ),
        "_cards": cards,
        "_notes": [f"조회: station={name}, 거점 {len(depots)}곳 · 무인보관함 {len(lockers)}곳"],
    }


TOOLS = {
    "plan_luggage_strategy": {
        "fn": plan_luggage_strategy,
        "spec": {
            "type": "function",
            "function": {
                "name": "plan_luggage_strategy",
                "description": (
                    "Recommend what to do with the traveler's luggage — store it at a station locker, "
                    "ship it to their accommodation, or carry it along the least-strenuous route. "
                    "Call this whenever the user wants advice about their bags. If details are missing, "
                    "call it anyway with what you have; the tool tells you exactly what to ask for."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "origin_station": {"type": "string", "description": "Where the user is now."},
                        "dest_station": {"type": "string",
                                         "description": "Station nearest their accommodation. Needed for delivery."},
                        "luggage": {
                            "type": "array",
                            "description": "Their bags. Empty array means no luggage.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "size": {"type": "string",
                                             "enum": ["CARRY_ON", "MEDIUM", "LARGE", "OVERSIZE"]},
                                    "count": {"type": "integer", "minimum": 1},
                                    "weight_kg": {"type": "number",
                                                  "description": "Per-bag kg, only if the user said so."},
                                },
                                "required": ["size"],
                            },
                        },
                        "checkin_time": {"type": "string", "description": "Check-in time 'HH:MM' or ISO."},
                        "preference": {"type": "string", "enum": ["store", "deliver", "any"],
                                       "description": "Only if the user expressed one."},
                        "lang": {"type": "string", "enum": ["ko", "en", "ja", "zh"]},
                    },
                    "required": [],
                },
            },
        },
    },
    "find_luggage_points": {
        "fn": find_luggage_points,
        "spec": {
            "type": "function",
            "function": {
                "name": "find_luggage_points",
                "description": (
                    "Look up which luggage drop-off points exist at or near a station (staffed stores, "
                    "smart lockers) — a factual listing. For a recommendation, use plan_luggage_strategy."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "station": {"type": "string"},
                        "lang": {"type": "string", "enum": ["ko", "en", "ja", "zh"]},
                    },
                    "required": [],
                },
            },
        },
    },
}
