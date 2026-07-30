# -*- coding: utf-8 -*-
"""
계수 민감도 = **뒤집힘 지점(flip point)** 분석.

"time_value_per_hour 12,000원이 맞느냐"는 질문에는 아무도 답할 수 없다. 답할 수 있는 질문은
이것이다: **"이 값이 얼마가 되면 추천이 바뀌는가, 그리고 그 값이 현실적인가?"**

  나쁜 발표: "시간가치를 12,000원으로 가정했습니다."          → 심사위원: "왜 12,000이죠?"
  좋은 발표: "배송과 동반이동이 뒤집히는 시간가치는 7,400원입니다.
             부산 관광객의 시간가치가 그보다 낮다고 볼 근거가 없으므로 이 추천은 견고합니다."

전자는 방어할 수 없고 후자는 방어할 필요가 없다. 이 스크립트는 후자를 만든다.

실행:
    cd backend && python3 scripts/sensitivity.py
    (발제사 데이터 폴더가 있어야 한다. 없으면 무엇이 필요한지 알려주고 종료한다.)
"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from engine import places
    from engine.config import DEFAULT_WEIGHTS, LuggageSize, Preference
    from engine.engine import Engine
    from engine.models import LuggageItem, LuggageRequest
    from engine.registry import get_registry

    get_registry()
except Exception as e:  # noqa: BLE001
    print("엔진을 불러오지 못했습니다:", e)
    print("\nbackend/발제사 데이터/ 폴더에 원본 CSV를 넣고 다시 실행하세요.")
    print("필요 파일: #1 역사 정보 마스터 · #2 시간대별 승하차 · #3-1~3-4 · #4-1 물품보관함 · #5 짐배송 흐름")
    raise SystemExit(1)


# ══════════════════════════════════════════════════════════════════
# 시나리오 — '뒤집힐 만한' 경계에 있는 것만 고른다
# ══════════════════════════════════════════════════════════════════

def _req(origin, dest, items, when, pref=Preference.ANY):
    return LuggageRequest(
        at=when, origin=origin, items=items, preference=pref, destination=dest, foreign=True
    )


def scenarios() -> list[tuple[str, LuggageRequest]]:
    S = LuggageSize
    mon10 = datetime(2026, 7, 27, 10, 0)   # 월 오전 — 온라인 마감(11시) 직전
    mon14 = datetime(2026, 7, 27, 14, 0)   # 월 오후 — 온라인 마감 후, 매장 마감(15시) 직전
    sat11 = datetime(2026, 7, 25, 11, 30)  # 토 — BEXCO 휴무
    out = []

    busan = places.store("부산역")
    haeundae = places.lodging_near("해운대 숙소", "해운대")
    seomyeon = places.lodging_near("서면 숙소", "서면")
    gimhae = places.store("김해공항 국제선")

    out.append(("A. 부산역→해운대 · 대형 2개 · 월 10시 (배송 vs 보관의 정면 충돌)",
                _req(busan, haeundae, [LuggageItem(S.LARGE, 2)], mon10)))
    out.append(("B. 부산역→해운대 · 특대형 1개 · 월 10시 (특대형은 무인보관함 불가)",
                _req(busan, haeundae, [LuggageItem(S.OVERSIZE, 1)], mon10)))
    out.append(("C. 부산역→서면 · 기내용 1개 · 월 10시 (가벼운 짐 — 동반이동이 이길 만한가)",
                _req(busan, seomyeon, [LuggageItem(S.CABIN, 1)], mon10)))
    out.append(("D. 부산역→해운대 · 대형 2개 · 월 14시 (매장 접수만 살아 있는 시간대)",
                _req(busan, haeundae, [LuggageItem(S.LARGE, 2)], mon14)))
    out.append(("E. 김해공항→서면 · 대형 1개+기내용 1개 · 토 11시 30분",
                _req(gimhae, seomyeon, [LuggageItem(S.LARGE, 1), LuggageItem(S.CABIN, 1)], sat11)))
    out.append(("F. 부산역→해운대 · 특대형 2개 30kg · 월 10시 (무게가 결과를 바꾸는가)",
                _req(busan, haeundae, [LuggageItem(S.OVERSIZE, 2, weight_kg=30.0)], mon10)))
    return out


# ══════════════════════════════════════════════════════════════════
# 스윕
# ══════════════════════════════════════════════════════════════════

#: (필드명, 표시명, 스윕 범위)
SWEEPS = [
    ("time_value_per_hour", "시간가치(원/시간)", [0, 2000, 4000, 6000, 8000, 10000,
                                            12000, 15000, 20000, 30000, 50000]),
    ("haul_burden_per_min", "동반부담(원/분)", [0, 50, 100, 150, 200, 250, 300, 400, 600]),
    ("separation_anxiety_per_hour", "분리불안(원/시간)", [0, 500, 1000, 1500, 2000, 3000, 5000]),
    ("stair_segment_penalty", "계단 페널티(원)", [0, 1000, 2000, 3000, 5000, 8000]),
    ("failure_recovery_cost", "실패 복구비용(원)", [0, 10000, 20000, 40000, 80000]),
]


def pick(req: LuggageRequest, weights) -> str:
    d = Engine(weights=weights).recommend(req)
    return d.recommended.kind.value if d.recommended else "없음"


def flip_report(name: str, req: LuggageRequest) -> None:
    base = pick(req, DEFAULT_WEIGHTS)
    print(f"\n{'─' * 78}\n{name}\n  기본 추천: {base}")

    for field, label, values in SWEEPS:
        default = getattr(DEFAULT_WEIGHTS, field)
        picks = [(v, pick(req, replace(DEFAULT_WEIGHTS, **{field: v}))) for v in values]

        flips = [(v, p) for v, p in picks if p != base]
        if not flips:
            print(f"  · {label:<18} 안 뒤집힘 (범위 {values[0]:,}~{values[-1]:,}) — 결론이 이 값에 의존하지 않음")
            continue

        # 기본값에서 가장 가까운 뒤집힘 지점
        lo = max((v for v, p in flips if v < default), default=None)
        hi = min((v for v, p in flips if v > default), default=None)
        parts = []
        if lo is not None:
            parts.append(f"↓{lo:,} 이하 → {dict(picks)[lo]}")
        if hi is not None:
            parts.append(f"↑{hi:,} 이상 → {dict(picks)[hi]}")
        margin = _margin(default, lo, hi)
        print(f"  · {label:<18} {' / '.join(parts)}   [기본 {default:,} · 여유 {margin}]")


def _margin(default: int, lo, hi) -> str:
    """기본값이 뒤집힘 지점에서 얼마나 떨어져 있는가 = 결론의 견고함."""
    dists = [abs(default - x) / max(default, 1) for x in (lo, hi) if x is not None]
    if not dists:
        return "매우 큼"
    d = min(dists)
    if d >= 1.0:
        return "큼 (2배 이상 움직여야 뒤집힘)"
    if d >= 0.4:
        return "보통"
    return "★작음 — 이 계수는 근거를 보강할 것"


def cost_table(name: str, req: LuggageRequest) -> None:
    """항별 기여도. '어느 항이 결론을 만들고 있는가'를 눈으로 본다."""
    d = Engine(weights=DEFAULT_WEIGHTS).recommend(req)
    print(f"\n{'─' * 78}\n{name} — 항별 기여")
    rows = [d.recommended, *d.alternatives] if d.recommended else []
    print(f"  {'옵션':<22}{'지출':>9}{'시간':>9}{'부담':>9}{'리스크':>8}{'불안':>8}{'합계':>10}")
    for o in rows[:4]:
        c = o.cost
        print(f"  {o.kind.value:<22}{c.money:>9,.0f}{c.time:>9,.0f}{c.burden:>9,.0f}"
              f"{c.risk:>8,.0f}{c.anxiety:>8,.0f}{c.total:>10,.0f}")


def main() -> None:
    print("=" * 78)
    print("계수 민감도 — 뒤집힘 지점 분석")
    print("=" * 78)
    print("읽는 법: '여유 ★작음'이 붙은 계수만 근거를 보강하면 된다.")
    print("        나머지는 값이 두 배로 틀려도 결론이 안 바뀌므로 방어할 필요가 없다.")

    sc = scenarios()
    for name, req in sc:
        flip_report(name, req)
    for name, req in sc[:3]:
        cost_table(name, req)

    print(f"\n{'=' * 78}\n발표용 문장 만들기:")
    print('  "이 추천은 시간가치를 X원 이하로 잡아야만 뒤집힙니다. 관광객의 시간가치가')
    print('   그보다 낮다고 볼 근거가 없으므로, 계수의 정확한 값과 무관하게 결론은 같습니다."')


if __name__ == "__main__":
    main()
