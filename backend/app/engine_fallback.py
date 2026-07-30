"""
축소 모드 — 발제사 데이터가 없어 팀원 엔진(registry)이 뜨지 못할 때만 동작한다.

존재 이유는 두 가지뿐이다.
  1. 데이터 없이도 프론트 개발·API 검증이 가능해야 한다 (프론트 팀원이 지금 바로 붙일 수 있게)
  2. 데모 당일 엔진이 죽어도 화면이 비지 않게 한다

★ 여기 숫자는 발표에 인용하지 말 것. 하드 제약(매장 운영시간·접수 마감·특대형 미취급)만
  실제 조사값을 쓰므로, '어디서 막히는지'는 축소 모드에서도 진짜와 같게 나온다.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, time
from pathlib import Path
from typing import Optional

from .plan_types import PlanOption, PlanResult

DATA = Path(__file__).resolve().parent.parent / "data"
_ZIM = json.loads((DATA / "zimcarry.json").read_text(encoding="utf-8"))

#: 팀원 config 와 같은 값으로 맞춰 둔다 (온라인 11:00 / 매장 15:00)
CUTOFF_ONLINE = time(11, 0)
CUTOFF_OFFLINE = time(15, 0)
BIG = ("대형", "특대형", "LARGE", "OVERSIZE", "large", "oversize")


def _hav(a, b, c, d) -> float:
    r = 6371.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _t(hhmm: str) -> time:
    return time(int(hhmm[:2]), int(hhmm[3:5]))


def _open_now(depot: dict, now: datetime) -> bool:
    if now.weekday() in depot.get("closed_weekdays", []):
        return False
    return _t(depot["open"]) <= now.time() <= _t(depot["close"])


def _stn(name: str) -> str:
    """'부산역' 처럼 이미 '역'으로 끝나면 덧붙이지 않는다."""
    return name if name.endswith("역") else f"{name}역"


def _resolve(name: Optional[str]) -> Optional[dict]:
    from .stations import resolve
    return resolve(name)


def plan(*, origin: str, destination: Optional[str], items: list[dict],
         at: datetime, preference: Optional[str] = None, reason: str = "") -> PlanResult:
    notes = [f"축소 모드 (실엔진 미탑재: {reason or '발제사 데이터 없음'})"]
    o = _resolve(origin)
    d = _resolve(destination)
    if o is None:
        return PlanResult(ok=False, source="fallback", recommended=None,
                          notes=notes + [f"역을 찾지 못함: {origin}"], error="unknown_origin")

    total = sum(max(1, int(i.get("count", i.get("qty", 1)))) for i in items or [])
    need_big = any(str(i.get("size", "")).strip() in BIG for i in items or [])
    opts: list[PlanOption] = []

    # ── 역사 보관함 ────────────────────────────────────────────────
    slots = o.get("locker_large_slots")
    if slots and (not need_big or slots >= 3):
        opts.append(PlanOption(
            kind="역사 보관함", label=f"{_stn(o['name'])} 물품보관함", feasible=True,
            out_of_pocket=4000 * total, duration_min=6.0,
            evidence={"대형이상 칸수": slots, "실시간 점유": "확인 불가 — 잔여 칸수 API 미제공"},
            pressure="보통", cost_index=4000 * total + 1200,
        ))
    else:
        why = "칸 정보 없음" if slots is None else f"대형이상 {slots}칸 — 부족"
        opts.append(PlanOption(kind="역사 보관함", label=f"{_stn(o['name'])} 물품보관함",
                               feasible=False, reject_reason=why))

    # ── 짐캐리 배송 ────────────────────────────────────────────────
    depot = None
    for dp in _ZIM["depots"]:
        if dp.get("station") and (dp["station"] in o["name"] or o["name"] in dp["station"]):
            depot = dp
            break

    at_store = depot is not None
    cutoff = CUTOFF_OFFLINE if at_store else CUTOFF_ONLINE
    channel = "매장방문" if at_store else "온라인"

    if d is None:
        opts.append(PlanOption(kind="짐캐리 배송", label="숙소로 짐배송", feasible=False,
                               reject_reason="구간 불가: 배송 목적지가 지정되지 않음"))
    elif at_store and not _open_now(depot, at):
        closed = ("토·일 휴무" if at.weekday() in depot.get("closed_weekdays", [])
                  else f"영업시간 {depot['open']}~{depot['close']} 밖")
        opts.append(PlanOption(kind="짐캐리 배송", label=f"{depot['name_ko']} 접수", feasible=False,
                               reject_reason=f"시간 불가: {closed}"))
    elif at.time() > cutoff:
        opts.append(PlanOption(
            kind="짐캐리 배송", label="숙소로 짐배송", feasible=False,
            reject_reason=f"시간 불가: {channel} 접수 마감({cutoff.strftime('%H:%M')}) 경과"))
    else:
        fee = 15000 * total + (5000 * total if need_big else 0)
        opts.append(PlanOption(
            kind="짐캐리 배송",
            label=(f"{depot['name_ko']}에서 숙소로 배송" if depot else "숙소 픽업으로 배송"),
            feasible=True, out_of_pocket=fee, duration_min=15.0,
            evidence={"접수채널": channel, "접수마감": cutoff.strftime("%H:%M"),
                      "도착시각": "지정 불가 — 체크인 전 도착을 약속하지 않음"},
            cost_index=fee + 3000,
        ))

    # ── 동반이동 (항상 바닥에 깔린다) ──────────────────────────────
    if d:
        km = _hav(o["lat"], o["lng"], d["lat"], d["lng"])
        mins = 12 + km / 20.0 * 60
        opts.append(PlanOption(
            kind="동반이동", label="짐과 함께 이동 (엘리베이터 우선 경로)", feasible=True,
            out_of_pocket=0, duration_min=round(mins, 1), fallback_level=1,
            evidence={"직선거리(km)": round(km, 1), "주의": "축소 모드 — 역별 난이도 미반영"},
            cost_index=mins * 250 * (1 + 0.1 * (total - 1)) + mins / 60 * 12000,
        ))

    feas = sorted([x for x in opts if x.feasible], key=lambda x: x.cost_index)
    rec = feas[0] if feas else None
    if rec and "보관함" in rec.kind:
        rec.backups = [x.label for x in feas if "보관함" in x.kind and x is not rec][:2]

    return PlanResult(
        ok=rec is not None, source="fallback", recommended=rec,
        alternatives=[x for x in feas if x is not rec],
        rejected=[x for x in opts if not x.feasible],
        fallback_level=(rec.fallback_level if rec else 0), notes=notes,
    )
