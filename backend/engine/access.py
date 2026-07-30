# -*- coding: utf-8 -*-
"""
접근 구간 — "거기까지 가는 것"까지 계산에 넣는다.

두 가지 구멍을 메운다.

① **매장까지 이동해서 접수하는 배송** (기존: 현재 위치가 매장이 아니면 온라인 11시 마감으로만 판정)
   현재 위치가 매장에서 떨어져 있어도, 매장까지 이동해 **도착 시각이 마감 전이면 배송은 가능하다.**
   부산역 매장이 15시 마감인데 13시에 서면에 있는 사람은 지금 규칙으로는 배송이 막히지만,
   실제로는 20분이면 도착해 접수할 수 있다. 그 20분을 계산해 넣는 게 이 모듈이다.

② **도보권 밖 역의 보관함** (기존: 현재 위치에서 도보 10분(800m) 반경만 후보)
   한두 정거장 떨어진 역의 보관함은 도보가 아니라 **지하철로** 간다. 그 이동을
   실제 경로(routing)로 계산해 시간과 피로도에 얹는다. 그래야 "해운대는 3칸뿐이니
   두 정거장 옆 장산에 맡기세요"가 근거 있는 제안이 된다.

두 경우 모두 접근 구간의 **시간·피로도·요금**이 옵션에 전부 반영된다.
접근이 공짜인 척하지 않는 게 요점이다.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from . import config, cost, fatigue, feasibility, places, routing
from .config import CostWeights, DEFAULT_WEIGHTS
from .models import LuggageRequest, Option, OptionKind, Place, PlaceKind
from .registry import get_registry, haversine_km

log = logging.getLogger("timecarry.access")

#: 접근을 위해 감수할 최대 이동시간(분). 이보다 멀면 '인근'이 아니다.
#: [가정] 30분 — 짐을 끌고 이 이상 움직이느니 다른 전략이 낫다.
MAX_ACCESS_MINUTES = 30.0

#: 매장 경유 배송에서, 매장 도착 후 접수까지의 여유(분). 길 찾기·줄서기.
#: [가정] 10분 — 마감 직전 아슬아슬한 제안을 하지 않기 위한 안전 여유.
INTAKE_BUFFER_MINUTES = 10.0


# ══════════════════════════════════════════════════════════════════
# 접근 구간 계산
# ══════════════════════════════════════════════════════════════════

def leg(origin: Place, dest_code: int, luggage_kg: float,
        w: CostWeights = DEFAULT_WEIGHTS) -> tuple[float, fatigue.FatigueScore, list[str]] | None:
    """현재 위치 → 목표 역까지 짐을 들고 가는 (분, 피로도, 근거).

    같은 역이면 역사 내 이동만, 도보권이면 도보, 그보다 멀면 실제 지하철 경로.
    """
    reg = get_registry()
    origin_code = origin.station_code
    if origin_code is None:
        origin_code, _ = places.nearest_station(origin.lat, origin.lon)

    segs: list[fatigue.SegKind] = []
    notes: list[str] = []

    if origin_code == dest_code:
        #: 같은 역 — 개찰구↔대합실 수직 이동 1회만 센다
        fac = reg.facility(dest_code)
        segs.append(fatigue.SegKind.ELEVATOR if fac.has_elevator
                    else (fatigue.SegKind.ESCALATOR if fac.escalator_running > 0
                          else fatigue.SegKind.STAIRS))
        return 6.0, fatigue.score(segs, luggage_kg), ["현재 역 — 역사 내 이동만"]

    # 도보가 더 빠른 짧은 거리인지 먼저 본다
    st = reg.station(dest_code)
    km = haversine_km(origin.lat, origin.lon, st.lat, st.lon)
    walk_min = km / config.HAUL_WALK_KMPH * 60

    route = routing.find_route(origin_code, dest_code, w)
    if route is None and walk_min > MAX_ACCESS_MINUTES:
        return None

    if route is None or walk_min <= route.travel_minutes:
        #: 지상 도보 — 수직 이동이 없으므로 피로도에는 안 들어가고 시간 축에만 잡힌다
        notes.append(f"도보 {walk_min:.0f}분 ({km:.1f}km)")
        total = walk_min
    else:
        segs.extend(_route_segments(route, reg))
        notes.append(f"{reg.station(origin_code).name} → {st.name} "
                     f"{route.hops}정거장 · 환승 {len(route.transfers)}회")
        notes.extend(route.notes[:2])
        total = route.travel_minutes

    if total > MAX_ACCESS_MINUTES:
        return None

    return total + 6.0, fatigue.score(segs, luggage_kg), notes


def _route_segments(route: routing.HaulRoute, reg) -> list[fatigue.SegKind]:
    """경로를 피로도 구간으로 분해한다.

    수직 이동이 일어나는 곳(진입·환승·진출)에만 계단/엘리베이터 구간을 만들고,
    통과역은 승차 구간으로만 둔다 — 열차 안에 앉아 있으므로. (팀원 설계 원칙 유지)
    """
    segs: list[fatigue.SegKind] = []
    #: 수직 이동이 일어나는 곳만 — 진입 · 환승 · 진출. 통과역은 열차 안이라 세지 않는다.
    for code in [route.path[0], *route.transfers, route.path[-1]]:
        fac = reg.facility(code)
        if fac.has_elevator:
            segs.append(fatigue.SegKind.ELEVATOR)
        elif fac.escalator_running > 0:
            segs.append(fatigue.SegKind.ESCALATOR)
        else:
            segs.append(fatigue.SegKind.STAIRS)
    return segs


# ══════════════════════════════════════════════════════════════════
# ① 매장 경유 배송
# ══════════════════════════════════════════════════════════════════

def store_visit_delivery(req: LuggageRequest,
                         w: CostWeights = DEFAULT_WEIGHTS) -> list[Option]:
    """현재 위치가 매장이 아니어도, 매장까지 가서 마감 전에 접수할 수 있으면 배송 가능."""
    if req.destination is None or req.origin.kind is PlaceKind.STORE:
        return []

    out: list[Option] = []
    for name, km in places.nearest_stores(req.origin.lat, req.origin.lon):
        spec = config.STORE_SPECS[name]
        store = places.store(name)
        got = leg(req.origin, store.station_code, req.total_weight, w) if store.station_code else None
        if got is None:
            continue
        move_min, fs, notes = got
        move_min += spec.anchor_access_min          # 연결역 → 매장 (경전철·셔틀 등)
        arrive = req.at + timedelta(minutes=move_min + INTAKE_BUFFER_MINUTES)

        opt = feasibility.check_delivery(req, via_store=store, arrive_at=arrive)
        opt.kind = OptionKind.DELIVERY
        opt.fallback_level = 0
        opt.label = f"{name} 매장까지 이동해 접수 → 숙소 배송"
        opt.evidence["매장까지 이동(분)"] = round(move_min, 1)
        opt.evidence["매장 도착 예상"] = arrive.strftime("%H:%M")
        opt.evidence["이동 근거"] = notes
        opt.evidence.update(fs.as_evidence())

        if opt.feasible:
            opt.duration_min = (opt.duration_min or 0) + move_min
            cost.price_delivery(req, opt, store_access_minutes=move_min,
                                store_access_difficulty=1.0, w=w)
            #: 접수 시각이 마감에 얼마나 붙어 있는지 — 사용자에게 급함을 알려 준다
            cutoff = config.CUTOFF[config.Channel.OFFLINE]
            slack = (arrive.replace(hour=cutoff.hour, minute=cutoff.minute) - arrive)
            opt.evidence["마감까지 여유(분)"] = round(slack.total_seconds() / 60)
        out.append(opt)

    #: 가능한 것 중 가장 가까운 매장 하나 + 불가 사유 하나만 남긴다(카드가 넘치지 않게)
    ok = [o for o in out if o.feasible]
    no = [o for o in out if not o.feasible]
    return (ok[:1] + no[:1]) if ok else no[:1]


# ══════════════════════════════════════════════════════════════════
# ② 도보권 밖 역의 보관함
# ══════════════════════════════════════════════════════════════════

def remote_locker_options(req: LuggageRequest, max_hops: int = 3,
                          w: CostWeights = DEFAULT_WEIGHTS) -> list[Option]:
    """1~3정거장 떨어진 역의 보관함. 이동을 실제 경로로 계산해 얹는다."""
    reg = get_registry()
    origin_code = req.origin.station_code
    if origin_code is None:
        origin_code, _ = places.nearest_station(req.origin.lat, req.origin.lon)

    out: list[Option] = []
    for code, hops in reg.neighbors_within(origin_code, max_hops).items():
        if hops == 0:
            continue
        supply = reg.locker_complex(code)
        if supply is None:
            continue
        st = reg.station(code)
        probe = Place(kind=PlaceKind.STATION, name=st.name, lat=st.lat, lon=st.lon,
                      station_code=code)
        opt = feasibility.check_station_locker(req, probe)
        if not opt.feasible:
            continue

        got = leg(req.origin, code, req.total_weight, w)
        if got is None:
            continue
        move_min, fs, notes = got

        opt.label = f"{st.label} 보관함 ({hops}정거장 이동)"
        opt.evidence["이동(분)"] = round(move_min, 1)
        opt.evidence["이동 근거"] = notes
        opt.evidence.update(fs.as_evidence())

        difficulty, _ = cost.haul_difficulty(code)
        cost.price_station_locker(req, opt, access_minutes=move_min,
                                  access_difficulty=difficulty,
                                  retrieval_detour_minutes=0.0, w=w)
        out.append(opt)

    out.sort(key=lambda o: o.cost.total)
    return out[:3]
