"""
ATM · 현금 도구 — **2단 라우팅**

이 도구의 존재 이유는 "ATM 위치를 반환하는 것"이 아니다.
외국인이 부산 지하철역에서 현금이 필요해지는 가장 큰 이유는 '지하철을 타기 위해서'인데
(발권기 현금 전용), 그 수요의 해법(해외카드 되는 공식 모바일 승차권 앱)은 이미 존재하는데도
3개월간 외국인 이용이 880건뿐이다. 그래서:

    ① 왜 현금이 필요한지 먼저 묻는다
    ② 교통 목적이면 → ATM을 알려주지 않고 앱으로 수요 자체를 해소한다
    ③ 진짜 현금 수요일 때만 → 외국인이 실제로 쓸 수 있는 접점으로 라우팅한다

★ 이 분기는 프롬프트가 아니라 여기 코드에 있다. 모델이 바뀌어도 정책은 안 흔들린다.
★ 역내 효성 ATM은 해외카드 수용 여부가 미확인이므로 외국인에게 기본 안내하지 않는다(보수 원칙).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..stations import resolve

DATA = Path(__file__).resolve().parent.parent.parent / "data"
CFG = json.loads((DATA / "transit_payment.json").read_text(encoding="utf-8"))

TRANSIT_PURPOSES = {"transit_ticket", "transit_card_recharge"}
CASH_PURPOSES = {"traditional_market", "small_shop", "taxi", "other_cash"}

_T = {
    "ko": {
        "ask": "현금이 어떤 용도로 필요하신지 먼저 알려주시겠어요? 용도에 따라 더 나은 방법이 있을 수 있어요.",
        "opt_ticket": "지하철 승차권을 사려고요",
        "opt_recharge": "교통카드를 충전하려고요",
        "opt_market": "시장·노점에서 쓰려고요",
        "opt_other": "그 외 현금이 필요해요",
        "app_title": "부산도시철도 모바일 승차권",
        "app_sub": "해외 발급 신용카드 결제 가능 (2025년 12월부터)",
        "app_action": "앱 설치하기",
        "kiosk_title": "역내 무인환전 키오스크",
        "cvs_title": "24시간 편의점 ATM",
        "bank_title": "은행 Global ATM",
        "night": "지금은 역내 ATM 운영시간(05:30~23:30) 밖이에요",
    },
    "en": {
        "ask": "Before I point you to an ATM — what do you need the cash for? There may be a better option.",
        "opt_ticket": "To buy a subway ticket",
        "opt_recharge": "To top up a transit card",
        "opt_market": "For markets or street stalls",
        "opt_other": "Something else",
        "app_title": "Busan Metro Mobile Ticket app",
        "app_sub": "Accepts foreign-issued credit cards (since Dec 2025)",
        "app_action": "Get the app",
        "kiosk_title": "Currency exchange kiosk (in station)",
        "cvs_title": "24h convenience-store ATM",
        "bank_title": "Bank Global ATM",
        "night": "Station ATMs are closed right now (they run 05:30–23:30)",
    },
}


def _t(lang: str) -> dict:
    return _T.get(lang, _T["en"])


def cash_and_atm_guide(
    purpose: Optional[str] = None,
    station: Optional[str] = None,
    lang: str = "en",
    time_hhmm: Optional[str] = None,
    preferred_payment: Optional[str] = None,
) -> dict:
    t = _t(lang)
    now = datetime.now()
    hhmm = time_hhmm or now.strftime("%H:%M")
    st = resolve(station)

    # ---------------------------------------------------------- ① 목적 분기
    if not purpose or purpose == "unknown":
        return {
            "needs_clarification": True,
            "reason": "Cash purpose is unknown. Ask the user WHY they need cash before giving any ATM location.",
            "question": t["ask"],
            "options": [
                {"value": "transit_ticket", "label": t["opt_ticket"]},
                {"value": "transit_card_recharge", "label": t["opt_recharge"]},
                {"value": "traditional_market", "label": t["opt_market"]},
                {"value": "other_cash", "label": t["opt_other"]},
            ],
            "instruction_to_assistant": (
                "Do NOT list any ATM yet. Ask the clarifying question above in the user's language, "
                "and present the four options naturally."
            ),
            "_suggestions": [
                {"icon": "🎫", "label": t["opt_ticket"], "prompt": t["opt_ticket"]},
                {"icon": "💳", "label": t["opt_recharge"], "prompt": t["opt_recharge"]},
                {"icon": "🏪", "label": t["opt_market"], "prompt": t["opt_market"]},
            ],
        }

    # ---------------------------------------------------------- ② 교통 목적 → 수요 해소
    if purpose in TRANSIT_PURPOSES:
        app = CFG["mobile_ticket_app"]
        cards = [{
            "type": "app_promo",
            "icon": "🎫",
            "title": t["app_title"],
            "meta": t["app_sub"],
            "badges": ["Visa/Master OK", "No cash needed"],
            "lines": [
                "Ticket machines in Busan Metro stations are cash-only — that's why you were looking for an ATM."
                if lang != "ko" else
                "부산 지하철 발권기는 현금 전용이에요. 그래서 ATM을 찾게 되신 거예요.",
                "You can buy the same ticket in the app with your foreign credit card."
                if lang != "ko" else
                "같은 승차권을 앱에서 해외 신용카드로 살 수 있어요.",
            ],
            "action_label": t["app_action"],
            "action_url": app["android_url"],
            "data": {"ios_url": app["ios_url"], "since": app["since"]},
        }]

        alt = []
        if preferred_payment in ("wechat", "kakao"):
            q = next((x for x in CFG["qr_alternatives"] if x["id"] == preferred_payment), None)
            if q:
                alt.append(q["name_en"] if lang != "ko" else q["name_ko"])
                cards.append({
                    "type": "info", "icon": "📱",
                    "title": q["name_ko"] if lang == "ko" else q["name_en"],
                    "meta": f"since {q['since']}",
                    "lines": ["QR ticketing is supported at Busan Metro gates."
                              if lang != "ko" else "부산 도시철도 개찰구에서 QR 승차권을 쓸 수 있어요."],
                    "badges": [],
                })

        return {
            "purpose": purpose,
            "recommendation": "USE_MOBILE_TICKET_APP",
            "atm_intentionally_withheld": True,
            "why": (
                "Busan Metro ticket machines and card top-up are cash-only, but the official mobile ticket app "
                "accepts foreign credit cards. Recommending the app removes the need for cash entirely."
            ),
            "app": {"name": app["name_en"], "foreign_card_supported": True, "since": app["since"],
                    "android_url": app["android_url"], "ios_url": app["ios_url"]},
            "qr_alternatives": alt,
            "note_for_assistant": (
                "Explain warmly in ONE short paragraph: ticket machines are cash-only, but the official app takes "
                "foreign cards, so no ATM trip is needed. Then ask if they still need cash for anything else."
            ),
            "_cards": cards,
            "_notes": [
                f"ATM 안내 보류 — 목적={purpose} (교통) → 모바일 승차권 앱으로 수요 해소",
                "근거: 발권기 현금 전용 / 앱 해외카드 지원 2025.12~ / 외국인 이용 3개월 880건",
            ],
            "_suggestions": (
                [{"icon": "💵", "label": "그래도 현금이 필요해요", "prompt": "다른 곳에서 쓸 현금이 필요해요"},
                 {"icon": "🚇", "label": "지하철 타는 법", "prompt": "지하철 타는 법 알려줘"}] if lang == "ko"
                else [{"icon": "💵", "label": "Still need cash",
                       "prompt": "I still need cash for something else"},
                      {"icon": "🚇", "label": "How to ride", "prompt": "How do I ride the subway?"}]
            ),
        }

    # ---------------------------------------------------------- ③ 진짜 현금 수요 → 접점 라우팅
    cards, points, notes = [], [], []
    kiosk = CFG["exchange_kiosk_stations"]
    st_name = st["name"] if st else None

    if st_name and st_name in kiosk["confirmed"]:
        points.append({"kind": "exchange_kiosk", "station": st_name, "status": "confirmed"})
        cards.append({
            "type": "place", "icon": "💱", "title": f"{st_name} · {t['kiosk_title']}",
            "meta": ("16개 통화 · 수수료 무료 · 역 구내" if lang == "ko"
                     else "16 currencies · No fee · Inside the station"),
            "badges": [], "lines": [],
        })
        notes.append(f"① 역내 환전 키오스크 보유역({st_name}) → 최우선 안내")
    elif st_name and st_name in kiosk["planned"]:
        points.append({"kind": "exchange_kiosk", "station": st_name, "status": "planned_unverified"})
        notes.append(f"△ {st_name}은 키오스크 확대 계획 역(2024.4 보도) — 설치 확인 필요, 단정 금지")

    open_t, close_t = CFG["station_atm"]["open"], CFG["station_atm"]["close"]
    within_hours = open_t <= hhmm <= close_t
    cvs = CFG["fallback_cash_points"]["convenience_store_atm"]

    if not within_hours:
        notes.append(f"현재 {hhmm} — 역내 ATM 운영시간({open_t}~{close_t}) 밖 → 24시간 편의점 ATM으로 전환")
        cards.append({
            "type": "warning", "icon": "🌙", "title": t["night"], "meta": f"{open_t}–{close_t}",
            "badges": [], "lines": [
                "Use a 24-hour convenience-store ATM (CU / GS25 / 7-Eleven) instead."
                if lang != "ko" else "24시간 편의점 ATM(CU·GS25·세븐일레븐)을 이용하세요."],
        })

    points.append({"kind": "convenience_store_atm", "brands": cvs["brands"], "hours": "24h",
                   "foreign_card": "usually supported (look for the Global ATM label)"})
    cards.append({
        "type": "place", "icon": "🏧", "title": t["cvs_title"],
        "meta": " · ".join(cvs["brands"] + ["24h", "Global ATM"]),
        "badges": [],
        "lines": ["Look for the 'Global ATM' label — that's the one that reliably takes foreign cards."
                  if lang != "ko" else "'Global ATM' 표시가 있는 기기를 찾으세요. 해외카드가 안정적으로 됩니다."],
    })

    points.append({"kind": "bank_global_atm",
                   "note": CFG["fallback_cash_points"]["bank_global_atm"]["note_ko"]})
    cards.append({
        "type": "place", "icon": "🏦", "title": t["bank_title"],
        "meta": ("BNK부산은행 · 외화 인출 가능" if lang == "ko"
                 else "BNK Busan Bank · Foreign currency"),
        "badges": [],
        "lines": ["Bank ATMs marked 'Global' also handle overseas-issued cards."
                  if lang != "ko" else "'Global' 표시가 있는 은행 ATM도 해외 발급 카드를 취급해요."],
        "action_label": "BNK 외화 ATM 찾기" if lang == "ko" else "Find BNK foreign-currency ATM",
        "action_url": CFG["fallback_cash_points"]["bank_global_atm"]["bnk_url"],
    })

    if st and st.get("has_atm") is False:
        notes.append(f"{st_name}은 역내 ATM 미보유역 → 역세권 접점만 안내")

    return {
        "purpose": purpose,
        "station": st_name,
        "current_time": hhmm,
        "station_atm_policy": (
            "In-station ATMs are VAN machines (Hyosung TNS) and their support for overseas-issued cards is "
            "NOT officially confirmed, so they are deliberately excluded from recommendations to foreign visitors."
        ),
        "station_atm_hours": f"{open_t}-{close_t}",
        "recommended_points": points,
        "note_for_assistant": (
            "Give 2-3 concrete options in ONE short paragraph. Never claim the in-station ATM accepts foreign cards."
        ),
        "_cards": cards,
        "_notes": notes or ["일반 현금 수요 → 확인된 접점으로 라우팅"],
        "_suggestions": (
            [{"icon": "💱", "label": "환전 싼 곳", "prompt": "환전 수수료가 제일 싼 곳은?"},
             {"icon": "🧳", "label": "짐 맡기기", "prompt": "짐 맡길 데 있어?"}] if lang == "ko"
            else [{"icon": "💱", "label": "Cheapest exchange",
                   "prompt": "Where's the cheapest place to exchange money?"},
                  {"icon": "🧳", "label": "Store luggage", "prompt": "Where can I store my luggage?"}]),
    }


TOOLS = {
    "cash_and_atm_guide": {
        "fn": cash_and_atm_guide,
        "spec": {
            "type": "function",
            "function": {
                "name": "cash_and_atm_guide",
                "description": (
                    "Call this for ANY question about cash, ATMs, money exchange, or paying for the subway. "
                    "IMPORTANT: on the first call, if you do not yet know WHY the user needs cash, call this with "
                    "purpose='unknown' — the tool will give you the clarifying question to ask. Never invent an ATM "
                    "location yourself."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "purpose": {
                            "type": "string",
                            "enum": ["unknown", "transit_ticket", "transit_card_recharge",
                                     "traditional_market", "small_shop", "taxi", "other_cash"],
                            "description": "Why the user needs cash. Use 'unknown' if not stated yet.",
                        },
                        "station": {"type": "string", "description": "Nearest station name, if known (KO or EN)."},
                        "lang": {"type": "string", "enum": ["ko", "en", "ja", "zh"],
                                 "description": "Language of the user."},
                        "time_hhmm": {"type": "string", "description": "Current local time HH:MM; omit to use now."},
                        "preferred_payment": {"type": "string", "enum": ["wechat", "kakao", "card"],
                                              "description": "Only if the user mentioned it themselves."},
                    },
                    "required": ["purpose"],
                },
            },
        },
    }
}
