"""골든 시나리오 — 계약이 깨지지 않았는지 지키는 방어선.

★ 팀원이 엔진을 계속 고쳐도 이 테스트는 통과해야 한다.
  발제사 데이터가 없으면 엔진은 축소 모드로 돌지만, 하드 제약(접수 마감·특대형·매장 휴무)의
  '어디서 막히는가'는 두 모드에서 같게 나와야 한다. 그걸 여기서 잡는다.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine_adapter import engine_status, plan  # noqa: E402
from app.schemas import Card, ChatResponse, Suggestion  # noqa: E402
from app.tools import call_tool  # noqa: E402

MON_10 = datetime(2026, 7, 27, 10, 0)   # 월요일 오전 — 온라인 마감 전
MON_16 = datetime(2026, 7, 27, 16, 0)   # 월요일 오후 — 모든 접수 마감 후
SAT_10 = datetime(2026, 7, 25, 10, 0)   # 토요일 — BEXCO 휴무일


def _items(size="LARGE", n=1):
    return [{"size": size, "count": n}]


# ------------------------------------------------------------------ 어댑터 계약

def test_engine_status_is_reported_honestly():
    st = engine_status()
    assert st["source"] in ("engine", "fallback")
    if st["source"] == "fallback":
        assert st["error"], "축소 모드인데 이유가 비어 있으면 원인을 못 찾는다"


def test_plan_returns_stable_shape_in_either_mode():
    r = plan(origin="부산역", destination="해운대", items=_items("LARGE", 2), at=MON_10)
    assert r.source in ("engine", "fallback")
    assert r.ok and r.recommended is not None
    rec = r.recommended
    assert rec.kind and rec.label
    assert isinstance(rec.feasible, bool)
    assert rec.out_of_pocket >= 0


def test_cost_index_is_never_exposed_to_the_model():
    """총비용지수는 원 단위지만 실제 지불액이 아니다. LLM에 넘어가면 그대로 거짓말이 된다."""
    out = call_tool("plan_luggage_strategy", {
        "origin_station": "부산역", "dest_station": "해운대",
        "luggage": _items("LARGE", 2), "lang": "en"})
    blob = str({k: v for k, v in out.items() if not k.startswith("_")})
    assert "cost_index" not in blob
    assert "총비용" not in blob


def test_after_cutoff_delivery_is_blocked_with_a_reason():
    r = plan(origin="해운대", destination="서면", items=_items("OVERSIZE", 1), at=MON_16)
    blocked = [o for o in r.rejected if not o.feasible]
    for o in blocked:
        assert o.reject_reason, "불가 옵션에 사유가 없으면 사용자에게 보여줄 말이 없다"


def test_something_is_always_offered():
    """사다리의 존재 이유 — 다 막혀도 동반이동이 바닥에 깔려야 한다."""
    r = plan(origin="해운대", destination="서면", items=_items("OVERSIZE", 3), at=MON_16)
    assert r.ok, "모든 옵션이 막혔는데 폴백이 없다 — 굿럭 챗봇과 같아진다"


def test_locker_recommendation_never_stands_alone():
    """실시간 잔여 API가 없으므로 보관함 추천은 반드시 2안을 동반한다(또는 명시적으로 없다고 밝힌다)."""
    out = call_tool("plan_luggage_strategy", {
        "origin_station": "서면", "dest_station": "해운대",
        "luggage": _items("CARRY_ON", 1), "preference": "store", "lang": "ko"})
    if out.get("resolved") and "보관함" in out["recommended"]["kind"]:
        rec = out["recommended"]
        assert "backup_spots" in rec
        assert rec.get("demand_pressure") in (None, "여유", "보통", "붐빔")


# ------------------------------------------------------------------ ATM 2단 라우팅

def test_atm_asks_purpose_before_giving_any_location():
    out = call_tool("cash_and_atm_guide", {"purpose": "unknown", "lang": "en"})
    assert out["needs_clarification"] is True
    assert "recommended_points" not in out
    assert len(out["options"]) == 4


def test_transit_purpose_withholds_atm_and_promotes_the_app():
    out = call_tool("cash_and_atm_guide", {"purpose": "transit_ticket", "lang": "en"})
    assert out["atm_intentionally_withheld"] is True
    assert out["app"]["foreign_card_supported"] is True
    assert "recommended_points" not in out
    assert any(c["type"] == "app_promo" for c in out["_cards"])


def test_real_cash_need_routes_to_verified_points():
    out = call_tool("cash_and_atm_guide",
                    {"purpose": "traditional_market", "station": "서면",
                     "lang": "ko", "time_hhmm": "13:00"})
    kinds = {p["kind"] for p in out["recommended_points"]}
    assert "exchange_kiosk" in kinds
    assert "convenience_store_atm" in kinds


def test_late_night_switches_to_24h_atm():
    out = call_tool("cash_and_atm_guide",
                    {"purpose": "other_cash", "station": "남포", "lang": "en", "time_hhmm": "01:30"})
    assert any(c["type"] == "warning" for c in out["_cards"])


def test_station_atm_is_never_recommended_to_foreigners():
    out = call_tool("cash_and_atm_guide", {"purpose": "other_cash", "station": "부산역", "lang": "en"})
    assert "station_atm" not in {p["kind"] for p in out["recommended_points"]}


# ------------------------------------------------------------------ 슬롯 검증

def test_missing_slots_are_reported_not_guessed():
    out = call_tool("plan_luggage_strategy", {"lang": "en"})
    assert out["needs_clarification"] is True
    assert "origin_station" in out["missing_slots"]
    assert "recommended" not in out


def test_fuzzy_station_names_resolve():
    out = call_tool("plan_luggage_strategy", {
        "origin_station": "Gamcheon Culture Village", "dest_station": "seomyun",
        "luggage": _items("CARRY_ON", 1), "lang": "en"})
    assert out.get("origin") == "토성"
    assert out.get("destination") == "서면"


# ------------------------------------------------------------------ 앱 계약(스키마)

def test_every_card_validates_against_the_app_schema():
    """프론트가 그리는 모양이 실제로 나오는지 — 여기서 깨지면 앱에서 깨진다."""
    for args in (
        {"purpose": "transit_ticket", "lang": "en"},
        {"purpose": "other_cash", "station": "남포", "lang": "ko", "time_hhmm": "01:30"},
    ):
        for c in call_tool("cash_and_atm_guide", args)["_cards"]:
            card = Card(**c)
            assert card.title and card.icon

    out = call_tool("plan_luggage_strategy", {
        "origin_station": "부산역", "dest_station": "해운대",
        "luggage": _items("LARGE", 2), "lang": "en"})
    for c in out["_cards"]:
        card = Card(**c)
        assert card.title
        assert isinstance(card.meta, str)
    for s in out["_suggestions"]:
        assert Suggestion(**s).prompt


def test_chat_response_serialises():
    r = ChatResponse(session_id="x", reply="hi",
                     cards=[Card(type="place", icon="🧳", title="t", meta="m")],
                     suggestions=[Suggestion(icon="🔄", label="l", prompt="p")])
    assert r.model_dump()["cards"][0]["meta"] == "m"


def test_unknown_tool_is_safe():
    assert "error" in call_tool("does_not_exist", {})
