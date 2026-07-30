# -*- coding: utf-8 -*-
"""2단계 — 폴백 사다리.

굿럭 챗봇은 배송 마감이면 대화가 끝난다. 우리 엔진은 내려갈 계단이 있다.
여기가 진짜 차별화 지점이다.

  1단 캐리어 동반 최적 경로 — 짐을 못 맡기면 "짐과 함께 가장 덜 고생하는 길"을
       준다. (#3.1 E/L · #3.3 대체경로 복잡도 · #3.4 곡선 승강장)
       모든 게 실패해도 발제 데이터만으로 답이 나온다.
  2단 시간 시프트 — "지금은 매장 개점 전이니 09시 접수", "오늘은 마감이니 내일 09시"

예전에 '1단 인근 역 보관함 재탐색'이 있었지만 없앴다. 이제 1단계에서 현재 위치
도보 10분 반경 내 모든 역의 보관함을 처음부터 후보로 펼치기 때문에, 실패한 뒤에
다시 찾을 인근 역이 남아 있지 않다. 사다리를 내려가는 대신 선택지를 먼저 다 보여
주는 쪽이 이용자에게 낫다.

시간 시프트는 배송에만 있다. 보관함 쪽 시간 시프트(포화가 풀리는 시각 제안)는
포화확률을 추천 경로에서 뺐으므로 함께 제거했다 — 근거 없이 기다리라고 할 수 없다.
"""

from __future__ import annotations

from datetime import timedelta

from . import config, cost, feasibility, places, routing
from .config import CostWeights, DEFAULT_WEIGHTS
from .models import (
    LuggageRequest,
    Option,
    OptionKind,
    Place,
    PlaceKind,
    RejectReason,
)
from .registry import get_registry


# ══════════════════════════════════════════════════════════════════
# 짐캐리 무인보관함 (1차 후보)
# ══════════════════════════════════════════════════════════════════


def zim_locker_options(
    req: LuggageRequest,
    *,
    fallback_level: int = 0,
    w: CostWeights = DEFAULT_WEIGHTS,
) -> tuple[list[Option], list[Option]]:
    """짐캐리 무인보관함 3곳 전부를 검사한다. (통과, 탈락)"""
    feasible: list[Option] = []
    rejected: list[Option] = []

    for name, km in places.nearest_zim_lockers(req.origin.lat, req.origin.lon):
        opt = feasibility.check_zim_locker(req, name)
        opt.fallback_level = fallback_level
        if not opt.feasible:
            rejected.append(opt)
            continue

        spec = config.ZIM_LOCKER_SPECS[name]
        access_min, mode = cost.access_travel_minutes(km)
        detour = _retrieval_detour_to(req, spec.lat, spec.lon)
        cost.price_zim_locker(
            req, opt, access_minutes=access_min, retrieval_detour_minutes=detour, w=w
        )
        opt.evidence["접근수단"] = mode
        feasible.append(opt)

    feasible.sort(key=lambda o: o.cost.total)
    return feasible, rejected


def _retrieval_detour_to(req: LuggageRequest, lat: float, lon: float) -> float:
    """짐을 찾으러 그 지점으로 되돌아오는 우회 시간(분)."""
    end = req.destination or req.origin
    from .registry import haversine_km

    km = haversine_km(end.lat, end.lon, lat, lon)
    if km < 0.3:
        return 0.0
    # 회수는 짐 없이 이동하므로 대중교통 기준으로 본다.
    return config.TRANSIT_OVERHEAD_MIN + km / config.TRANSIT_KMPH * 60


# ══════════════════════════════════════════════════════════════════
# 폴백 1단 — 캐리어 동반 최적 경로
# ══════════════════════════════════════════════════════════════════


def haul_option(
    req: LuggageRequest, *, w: CostWeights = DEFAULT_WEIGHTS
) -> Option | None:
    """짐을 들고 가는 가장 덜 고생하는 경로. 목적지가 있어야 의미가 있다."""
    if req.destination is None:
        return None

    reg = get_registry()
    origin_code = req.origin.station_code
    if origin_code is None:
        origin_code, _ = places.nearest_station(req.origin.lat, req.origin.lon)

    dest_code = req.destination.station_code
    dest_walk_min = 0.0
    if dest_code is None:
        dest_code, km = places.nearest_station(req.destination.lat, req.destination.lon)
        dest_walk_min = km / config.HAUL_WALK_KMPH * 60

    route = routing.find_route(origin_code, dest_code, w)
    if route is None:
        return None

    opt = Option(
        kind=OptionKind.HAUL,
        label="짐과 함께 이동 (최소부담 경로)",
        station_code=origin_code,
        fallback_level=1,
    )
    cost.price_haul(
        req,
        opt,
        route_codes=[route.path[0], *route.transfers, route.path[-1]],
        travel_minutes=route.travel_minutes + dest_walk_min,
        w=w,
    )
    opt.out_of_pocket = 0

    comparison = routing.compare_routes(origin_code, dest_code, w)
    opt.evidence["경로"] = [reg.station(c).label for c in route.path]
    opt.evidence["환승"] = [reg.station(c).label for c in route.transfers] or "없음"
    opt.evidence["정거장수"] = route.hops
    opt.evidence["회피근거"] = route.notes
    if comparison and not comparison.get("동일여부", True):
        opt.evidence["최단시간경로와 다름"] = comparison["최단시간경로"]
        opt.label = "짐과 함께 이동 (최단시간 대신 최소부담 경로)"
    if dest_walk_min > 0:
        opt.evidence["하차 후 도보(분)"] = round(dest_walk_min, 1)
    return opt


# ══════════════════════════════════════════════════════════════════
# 폴백 2단 — 시간 시프트 (배송 전용)
# ══════════════════════════════════════════════════════════════════


def time_shift_delivery(req: LuggageRequest) -> Option | None:
    """접수 마감을 놓쳤을 때의 예약형 대안."""
    probe = feasibility.check_delivery(req)
    if probe.feasible:
        return None
    if probe.reject_reason not in {
        RejectReason.DLV_PAST_CUTOFF,
        RejectReason.DLV_STORE_CLOSED,
        RejectReason.DLV_ARRIVAL_TOO_EARLY,
    }:
        # 구간 자체가 상품에 없으면 내일도 안 된다.
        return None

    channel = req.channel
    cutoff_t = config.CUTOFF[channel]
    open_t = config.STORE_OPEN

    def _at(day, t):
        return day.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)

    # 매장이 아직 안 열었을 뿐이고 오늘 마감 전에 열린다면, 내일이 아니라
    # 오늘 개점 시각을 제안해야 한다. 공항에 새벽 도착한 여행자가 여기 걸린다.
    today_open = _at(req.at, open_t)
    same_day = req.at < today_open and today_open <= _at(req.at, cutoff_t)

    if same_day:
        accept_at = today_open
        headline = f"오늘 {open_t.strftime('%H:%M')} 매장 개점 시 접수"
        guide = (
            f"지금은 매장 개점({open_t.strftime('%H:%M')}) 전입니다. "
            f"{open_t.strftime('%H:%M')}에 접수하면 오늘 "
            f"{config.DELIVERY_ARRIVE_FROM.strftime('%H:%M')}에 도착합니다."
        )
    else:
        accept_at = _at(req.at + timedelta(days=1), open_t)
        headline = f"내일 {open_t.strftime('%H:%M')} 접수 예약"
        guide = (
            f"오늘은 {channel.value} 접수 마감({cutoff_t.strftime('%H:%M')})이 "
            f"지났습니다. 내일 {open_t.strftime('%H:%M')} 접수하면 "
            f"{config.DELIVERY_ARRIVE_FROM.strftime('%H:%M')}에 도착합니다."
        )

    arrive = _at(accept_at, config.DELIVERY_ARRIVE_FROM)

    opt = Option(
        kind=OptionKind.SCHEDULED_DELIVERY,
        label=headline,
        fallback_level=2,
    )
    opt.out_of_pocket = feasibility.delivery_fare(req)
    opt.evidence["접수예정"] = accept_at.strftime("%m/%d %H:%M")
    opt.evidence["도착예정"] = arrive.strftime("%m/%d %H:%M")
    opt.evidence["오늘 탈락사유"] = probe.reject_reason.value
    opt.evidence["안내"] = guide

    hours_until = (accept_at - req.at).total_seconds() / 3600
    opt.evidence["대기(시간)"] = round(hours_until, 1)
    opt.cost.money = float(opt.out_of_pocket)
    # 오늘 밤을 짐과 함께 보내야 한다. 그 시간을 절반 가중으로 계산한다.
    opt.cost.anxiety = hours_until * DEFAULT_WEIGHTS.separation_anxiety_per_hour * 0.5
    opt.duration_min = hours_until * 60
    return opt
