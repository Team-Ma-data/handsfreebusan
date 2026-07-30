# -*- coding: utf-8 -*-
"""서비스 플로우 데모.

입력값 4가지(현재 위치 · 시간 · 원하는 상황 · 짐 크기와 무게)를 받아
1단계 필터와 2단계 폴백 사다리가 갈라지는 지점들을 시나리오로 만든다.
각 시나리오는 서로 다른 탈락 사유를 밟도록 설계했다.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import eventlog, places  # noqa: E402
from engine.config import LuggageSize, Preference  # noqa: E402
from engine.engine import Engine  # noqa: E402
from engine.models import LuggageItem, LuggageRequest  # noqa: E402

BAR = "═" * 78
HIDE = {"역별근거", "회피근거"}


def show(title: str, req: LuggageRequest, engine: Engine) -> None:
    print(f"\n{BAR}\n▶ {title}\n{BAR}")
    items = " + ".join(
        f"{i.size.value}×{i.qty}({i.effective_weight:.0f}kg)" for i in req.items
    )
    print("  [입력]")
    print(f"    현재 위치 : {req.origin.label}")
    print(f"    시간      : {req.at:%m/%d(%a) %H:%M}  → 접수채널 {req.channel.value}")
    print(f"    원하는 상황: {req.preference.value}"
          + (f" → 목적지 {req.destination.label}" if req.destination else ""))
    print(f"    짐        : {items} / 총 {req.total_weight:.0f}kg")
    if req.need_by:
        print(f"    회수·수령 : {req.need_by:%H:%M}까지")

    d = engine.recommend(req)
    print("\n  [판정]")
    for line in d.narrative.splitlines():
        print(f"    {line}")

    if d.recommended:
        print("\n  [근거]")
        for k, v in d.recommended.evidence.items():
            if k in HIDE:
                continue
            print(f"    {k}: {v}")
        print(f"    실지출: {d.recommended.out_of_pocket:,}원")

    if d.alternatives:
        print(f"\n  [대안 {len(d.alternatives)}건]")
        for o in d.alternatives[:4]:
            print(
                f"    · {o.kind.value} {o.label} — "
                f"{o.out_of_pocket:,}원 / 비용지수 {o.cost.total:,.0f}"
            )


def main() -> None:
    engine = Engine(log=eventlog.EventLog())

    busan_store = places.store("부산역")
    airport_intl = places.store("김해공항 국제선")
    bexco = places.store("BEXCO")
    haeundae_stay = places.lodging_near("해운대 호텔", "해운대")
    seomyeon_stay = places.lodging_near("서면 게스트하우스", "서면")
    nampo_stay = places.lodging_near("남포동 호스텔", "남포")

    # ── 1. 매장 접수 · 배송 vs 보관 비교 ─────────────────────────
    show(
        "1 — 부산역 매장 10시 · 무관 · 특대형 2개 28kg · 해운대 숙소",
        LuggageRequest(
            at=datetime(2026, 7, 31, 10, 0),
            origin=busan_store,
            destination=haeundae_stay,
            preference=Preference.ANY,
            items=[LuggageItem(LuggageSize.OVERSIZE, 2, weight_kg=28)],
            receivable_from=datetime(2026, 7, 31, 15, 0),
            need_by=datetime(2026, 7, 31, 21, 0),
            foreign=True,
        ),
        engine,
    )

    # ── 2. 매장 마감(15시) 경과 ─────────────────────────────────
    show(
        "2 — 부산역 매장 16시 · 배송 · 매장 마감 15시 경과",
        LuggageRequest(
            at=datetime(2026, 7, 31, 16, 0),
            origin=busan_store,
            destination=haeundae_stay,
            preference=Preference.ANY,
            items=[LuggageItem(LuggageSize.LARGE, 1, weight_kg=18)],
            need_by=datetime(2026, 7, 31, 22, 0),
            foreign=True,
        ),
        engine,
    )

    # ── 3. 온라인 마감(11시) 경과 — 숙소→매장 픽업 ──────────────
    show(
        "3 — 서면 숙소 13시 · 배송 · 부산역 매장으로 픽업 (온라인 마감 11시 경과)",
        LuggageRequest(
            at=datetime(2026, 7, 31, 13, 0),
            origin=seomyeon_stay,
            destination=busan_store,
            preference=Preference.ANY,
            items=[LuggageItem(LuggageSize.LARGE, 2, weight_kg=20)],
            need_by=datetime(2026, 7, 31, 18, 30),
        ),
        engine,
    )

    # ── 4. 보관만 원함 (목적지 없음) ────────────────────────────
    show(
        "4 — 남포역 11시 · 보관 · 중형 1개 14kg (목적지 미입력)",
        LuggageRequest(
            at=datetime(2026, 7, 31, 11, 0),
            origin=places.station("남포"),
            preference=Preference.STORE,
            items=[LuggageItem(LuggageSize.MEDIUM, 1, weight_kg=14)],
            need_by=datetime(2026, 7, 31, 17, 0),
        ),
        engine,
    )

    # ── 5. 특대형 0칸 → 폴백 1단 ────────────────────────────────
    show(
        "5 — 4호선 수안역 13시 · 보관 · 특대형 1개 26kg (해당 역 특대형 0칸)",
        LuggageRequest(
            at=datetime(2026, 7, 31, 13, 0),
            origin=places.station("수안"),
            destination=places.station("범어사"),
            preference=Preference.STORE,
            items=[LuggageItem(LuggageSize.OVERSIZE, 1, weight_kg=26)],
            need_by=datetime(2026, 7, 31, 18, 0),
        ),
        engine,
    )

    # ── 6. 구간 불가 — 역 → 역 ──────────────────────────────────
    show(
        "6 — 토성역 11시 · 배송 · 남포역으로 (매장이 아닌 구간)",
        LuggageRequest(
            at=datetime(2026, 7, 31, 11, 0),
            origin=places.station("토성"),
            destination=places.station("남포"),
            preference=Preference.DELIVER,
            items=[LuggageItem(LuggageSize.OVERSIZE, 1, weight_kg=25)],
            need_by=datetime(2026, 7, 31, 17, 0),
        ),
        engine,
    )

    # ── 7. 숙소 → 숙소 (허용 구간) ──────────────────────────────
    show(
        "7 — 남포동 호스텔 10시 · 배송 · 해운대 호텔로 숙소 간 이동",
        LuggageRequest(
            at=datetime(2026, 7, 31, 10, 0),
            origin=nampo_stay,
            destination=haeundae_stay,
            preference=Preference.DELIVER,
            items=[LuggageItem(LuggageSize.MEDIUM, 2, weight_kg=13)],
            receivable_from=datetime(2026, 7, 31, 15, 0),
            need_by=datetime(2026, 7, 31, 22, 0),
        ),
        engine,
    )

    # ── 8. 무인보관함이 이기는 경우 ─────────────────────────────
    show(
        "8 — 서면 숙소 10시 · 보관 · 소형 1개 7kg (짐캐리 무인보관함 인근)",
        LuggageRequest(
            at=datetime(2026, 7, 31, 10, 0),
            origin=seomyeon_stay,
            preference=Preference.STORE,
            items=[LuggageItem(LuggageSize.CABIN, 1, weight_kg=7)],
            need_by=datetime(2026, 7, 31, 13, 30),
        ),
        engine,
    )

    # ── 9. BEXCO 매장 · 무인보관함 특대형 미취급 ────────────────
    show(
        "9 — BEXCO 매장 12시 · 무관 · 특대형 1개 30kg · 광안리 숙소",
        LuggageRequest(
            at=datetime(2026, 7, 31, 12, 0),
            origin=bexco,
            destination=places.lodging_near("광안리 호텔", "광안"),
            preference=Preference.ANY,
            items=[LuggageItem(LuggageSize.OVERSIZE, 1, weight_kg=30)],
            need_by=datetime(2026, 7, 31, 22, 0),
            foreign=True,
        ),
        engine,
    )

    # ── 10. 심야 · 보관함 없는 역 → 사다리 끝까지 ───────────────
    show(
        "10 — 신평역 22시 · 무관 · 특대형 1개 27kg · 해운대까지",
        LuggageRequest(
            at=datetime(2026, 7, 31, 22, 0),
            origin=places.station("신평"),
            destination=places.station("해운대"),
            preference=Preference.ANY,
            items=[LuggageItem(LuggageSize.OVERSIZE, 1, weight_kg=27)],
        ),
        engine,
    )

    # ── 11. 김해공항 국제선 아침 · 배송 ─────────────────────────
    show(
        "11 — 김해공항 국제선 08시 · 배송 · 해운대 숙소 (매장 개점 9시 전)",
        LuggageRequest(
            at=datetime(2026, 7, 31, 8, 0),
            origin=airport_intl,
            destination=haeundae_stay,
            preference=Preference.DELIVER,
            items=[LuggageItem(LuggageSize.LARGE, 2, weight_kg=21)],
            need_by=datetime(2026, 7, 31, 22, 0),
            foreign=True,
        ),
        engine,
    )

    # ── B2B 로그 ────────────────────────────────────────────────
    print(f"\n{BAR}\n▶ B2B 이벤트 로그 (이번 데모에서 발생한 미충족 수요)\n{BAR}")
    s = engine.log.summary()
    print(f"  총 이벤트 {s['총 이벤트']}건 | {s['이벤트별']}")
    print("\n  탈락 사유 분포:")
    for code, n in s["탈락사유 상위"].items():
        print(f"    {code}: {n}건")

    for title, rows, fmt in (
        ("수요 공백 — 부산교통공사 (역사 보관함 증설·신설)",
         engine.log.demand_gap(),
         lambda r: f"{r['역']} {r['시간대']} {r['짐크기']} {r['건수']}건 ({r['주사유']})"),
        ("구간 공백 — 짐캐리 (배송 상품 확장)",
         engine.log.segment_gap(),
         lambda r: f"{r['구간']} {r['시간대']} {r['건수']}건 ({r['주사유']}, 외국인 {r['외국인']})"),
        ("접수점 공백 — 짐캐리 (역 밖 접수 포인트 신설)",
         engine.log.intake_point_gap(),
         lambda r: f"{r['위치']}({r['유형']}) {r['시간대']} {r['건수']}건"),
        ("마감 공백 — 짐캐리 (접수 마감 연장 가치)",
         engine.log.cutoff_loss_by_hour(),
         lambda r: f"{r['시간대']} {r['채널']} {r['건수']}건 {r['위치분포']}"),
    ):
        if not rows:
            continue
        print(f"\n  [{title}]")
        for r in rows[:6]:
            print(f"    {fmt(r)}")

    print(f"\n  로그 저장: {engine.log.flush()}")


if __name__ == "__main__":
    main()
