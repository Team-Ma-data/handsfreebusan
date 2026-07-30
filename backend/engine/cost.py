# -*- coding: utf-8 -*-
"""비용함수.

네 옵션(역사 보관함·짐캐리 무인보관함·배송·동반이동)은 성격이 전혀 달라
요금만으로는 비교가 안 된다. 전부 원(KRW)으로 환산해 더한 뒤 비교한다.

  총비용 = 지출 + 시간 기회비용 + 신체 부담 + 실패 리스크 + 분리 불안

각 옵션의 성격이 어느 항에 실리는지가 이 설계의 요점이다.
  역사 보관함   — 지출은 싸지만 '찾으러 돌아가는' 시간과 부담이 붙는다.
  무인보관함    — 3곳뿐이라 접근 우회가 붙지만, 기본 4시간 요금이 저렴하다.
  배송          — 지출은 비싸지만 회수 이동이 0이다. 대신 분리 불안이 붙는다.
  동반이동      — 지출은 0이지만 신체 부담을 전부 이용자가 진다. 이 부담을
                  정직하게 계산하는 데 #3 시리즈(E/L·대체경로·곡선승강장)가 쓰인다.

부담 항만 유일하게 승수 구조다.
  부담 = 짐을 든 시간(분) × 분당 단가 × 역 난이도계수 × 무게계수 + 지점 페널티
사용자가 입력한 무게가 실제로 결과를 바꾸는 지점이 여기다.
"""

from __future__ import annotations

from . import config
from .config import CostWeights, DEFAULT_WEIGHTS
from .models import CostBreakdown, LuggageRequest, Option, Place
from .registry import StationFacility, get_registry, haversine_km


# ══════════════════════════════════════════════════════════════════
# 승수 — 역 난이도(#3 시리즈)와 짐 무게
# ══════════════════════════════════════════════════════════════════


def haul_difficulty(code: int) -> tuple[float, dict]:
    """역 하나를 캐리어와 함께 통과할 때의 난이도 계수와 근거.

    1.0 = 무난(엘리베이터 있고 직선 승강장). 값이 클수록 고생한다.
    """
    fac: StationFacility = get_registry().facility(code)
    factor = 1.0
    why: dict = {}

    if not fac.has_elevator:
        factor += 0.60
        why["E/L"] = "없음 — 계단·에스컬레이터 의존"
    else:
        why["E/L"] = f"{fac.elevator_running}대 운행"

    if fac.escalator_running == 0 and not fac.has_elevator:
        factor += 0.30
        why["E/S"] = "없음"

    if fac.platform_curved_ratio > 0:
        factor += 0.25 * fac.platform_curved_ratio
        why["곡선승강장"] = f"{fac.platform_curved_ratio:.0%} 구간"

    if fac.platform_wide_gap_ratio > 0:
        factor += 0.35 * fac.platform_wide_gap_ratio
        why["광폭연단"] = f"{fac.platform_wide_gap_ratio:.0%} 구간"

    if fac.alt_route_mean_complexity is not None:
        # 1~10 점수를 0~0.36 가산으로. E/L이 멈췄을 때의 취약성이다.
        factor += 0.04 * (fac.alt_route_mean_complexity - 1)
        why["대체경로복잡도"] = round(fac.alt_route_mean_complexity, 1)

    if fac.alt_route_blocked > 0:
        factor += 0.20
        why["이동불가경로"] = f"{fac.alt_route_blocked}건"

    return factor, why


def weight_factor(req: LuggageRequest) -> tuple[float, dict]:
    """짐 무게가 신체 부담을 얼마나 키우는지.

    기준 15kg까지는 1.0. 초과분에 kg당 가산하고, 항공 위탁 허용(23kg)을
    넘으면 '혼자 계단으로 들 수 없는 무게'로 보고 한 번 더 가산한다.
    """
    heaviest = req.heaviest
    factor = 1.0 + config.WEIGHT_BURDEN_PER_KG * max(
        0.0, heaviest - config.WEIGHT_BURDEN_BASELINE_KG
    )
    why = {"최대 개당 무게(kg)": round(heaviest, 1), "총 무게(kg)": round(req.total_weight, 1)}
    if heaviest > config.HEAVY_THRESHOLD_KG:
        factor += 0.15
        why["중량 가산"] = f"{config.HEAVY_THRESHOLD_KG:.0f}kg 초과"
    # 여러 개를 동시에 끄는 것도 부담이다.
    if req.total_qty > 1:
        factor += 0.10 * (req.total_qty - 1)
        why["다개수 가산"] = f"{req.total_qty}개"
    return factor, why


def route_difficulty(codes: list[int]) -> tuple[float, list[dict]]:
    """경로 전체의 평균 난이도와 역별 근거."""
    if not codes:
        return 1.0, []
    reg = get_registry()
    details, total = [], 0.0
    for c in codes:
        f, why = haul_difficulty(c)
        total += f
        details.append({"역": reg.station(c).label, "난이도": round(f, 2), **why})
    return total / len(codes), details


# ══════════════════════════════════════════════════════════════════
# 옵션별 비용 산출
# ══════════════════════════════════════════════════════════════════


def price_station_locker(
    req: LuggageRequest,
    opt: Option,
    *,
    access_minutes: float = 0.0,
    access_difficulty: float = 1.0,
    retrieval_detour_minutes: float = 0.0,
    w: CostWeights = DEFAULT_WEIGHTS,
) -> Option:
    """역사 보관함 가격 산정."""
    c = CostBreakdown()
    c.money = float(opt.out_of_pocket)

    # 역사 안에서 보관함까지 가는 시간. #4.1 상세위치가 전부 대합실권이라 일정하게 본다.
    in_station_min = 6.0
    total_min = access_minutes + in_station_min + retrieval_detour_minutes
    c.time = total_min / 60 * w.time_value_per_hour

    # 부담은 짐을 든 구간에만 붙는다. 이미 그 역에 서 있어도 대합실까지는 끌어야
    # 하므로, 역사 내 구간은 그 역의 난이도로 따로 계산한다.
    wf, wwhy = weight_factor(req)
    station_difficulty = 1.0
    if opt.station_code is not None:
        station_difficulty, _ = haul_difficulty(opt.station_code)
    hauled = access_minutes * access_difficulty + in_station_min * station_difficulty
    c.burden = hauled * w.haul_burden_per_min * wf

    # 실시간 점유 API가 없어 '가서 빈 칸이 없을 확률'을 값으로 매기지 않는다.
    c.risk = 0.0
    c.anxiety = 0.0

    opt.cost = c
    opt.duration_min = total_min
    opt.evidence["접근시간(분)"] = round(access_minutes + in_station_min, 1)
    opt.evidence["회수우회(분)"] = round(retrieval_detour_minutes, 1)
    opt.evidence["무게계수"] = round(wf, 2)
    opt.evidence.update(wwhy)
    opt.evidence["실시간 점유"] = "확인 불가 — 잔여 칸수 API 미제공"
    return opt


def price_zim_locker(
    req: LuggageRequest,
    opt: Option,
    *,
    access_minutes: float,
    retrieval_detour_minutes: float = 0.0,
    w: CostWeights = DEFAULT_WEIGHTS,
) -> Option:
    """짐캐리 무인보관함 가격 산정. 역사가 아니라 지상 지점이라 난이도는 1.0."""
    c = CostBreakdown()
    c.money = float(opt.out_of_pocket)

    total_min = access_minutes + retrieval_detour_minutes
    c.time = total_min / 60 * w.time_value_per_hour

    wf, wwhy = weight_factor(req)
    # 지상 지점이라 역사 계단 난이도는 없지만, 끌고 가는 부담과 무게는 그대로다.
    c.burden = access_minutes * w.haul_burden_per_min * wf
    c.risk = 0.0
    c.anxiety = 0.0

    opt.cost = c
    opt.duration_min = total_min
    opt.evidence["접근시간(분)"] = round(access_minutes, 1)
    opt.evidence["회수우회(분)"] = round(retrieval_detour_minutes, 1)
    opt.evidence["무게계수"] = round(wf, 2)
    opt.evidence.update(wwhy)
    return opt


def price_delivery(
    req: LuggageRequest,
    opt: Option,
    *,
    store_access_minutes: float = 0.0,
    store_access_difficulty: float = 1.0,
    w: CostWeights = DEFAULT_WEIGHTS,
) -> Option:
    """배송 가격 산정."""
    c = CostBreakdown()
    c.money = float(opt.out_of_pocket)

    intake_min = config.DELIVERY_INTAKE_MINUTES
    spent_min = store_access_minutes + intake_min
    c.time = spent_min / 60 * w.time_value_per_hour

    wf, wwhy = weight_factor(req)
    c.burden = store_access_minutes * w.haul_burden_per_min * store_access_difficulty * wf

    # 배송 지연·사고 리스크. 운영 구간 안이면 낮게 본다.
    c.risk = 0.03 * w.failure_recovery_cost

    separation_h = float(opt.evidence.get("수령까지(시간)", 0))
    c.anxiety = separation_h * w.separation_anxiety_per_hour

    opt.cost = c
    opt.evidence["매장접근(분)"] = round(store_access_minutes, 1)
    opt.evidence["분리시간(시간)"] = round(separation_h, 1)
    opt.evidence["무게계수"] = round(wf, 2)
    opt.evidence.update(wwhy)
    return opt


def price_haul(
    req: LuggageRequest,
    opt: Option,
    *,
    route_codes: list[int],
    travel_minutes: float,
    w: CostWeights = DEFAULT_WEIGHTS,
) -> Option:
    """캐리어 동반 이동 가격 산정. 부담 항이 전부를 좌우한다."""
    c = CostBreakdown()
    c.money = 0.0
    c.time = travel_minutes / 60 * w.time_value_per_hour

    difficulty, details = route_difficulty(route_codes)
    wf, wwhy = weight_factor(req)
    c.burden = travel_minutes * w.haul_burden_per_min * difficulty * wf

    reg = get_registry()
    stair_stations = [x for x in route_codes if not reg.facility(x).has_elevator]
    c.burden += len(stair_stations) * w.stair_segment_penalty * wf

    curved = [x for x in route_codes if reg.facility(x).platform_curved_ratio > 0]
    c.burden += len(curved) * w.curved_platform_penalty

    c.risk = 0.0
    c.anxiety = 0.0

    opt.cost = c
    opt.duration_min = travel_minutes
    opt.evidence["평균난이도"] = round(difficulty, 2)
    opt.evidence["무게계수"] = round(wf, 2)
    opt.evidence.update(wwhy)
    opt.evidence["역별근거"] = details
    opt.evidence["E/L없는역"] = [reg.station(x).label for x in stair_stations]
    opt.evidence["곡선승강장역"] = [reg.station(x).label for x in curved]
    return opt


# ══════════════════════════════════════════════════════════════════
# 접근 시간
# ══════════════════════════════════════════════════════════════════


def access_minutes_between(place: Place, station_code: int) -> tuple[float, float]:
    """현 위치에서 특정 역까지 짐을 들고 가는 (시간(분), 난이도)."""
    reg = get_registry()
    if place.station_code == station_code:
        # 매장→연결역처럼 직선거리로 재면 안 되는 구간은 명시된 소요시간을 쓴다.
        if place.station_access_min:
            difficulty, _ = haul_difficulty(station_code)
            return place.station_access_min, difficulty
        return 0.0, 1.0
    target = reg.station(station_code)
    km = haversine_km(place.lat, place.lon, target.lat, target.lon)
    minutes = km / config.HAUL_WALK_KMPH * 60
    difficulty, _ = haul_difficulty(station_code)
    return minutes, difficulty


def walk_minutes(place: Place, lat: float, lon: float) -> float:
    """지상 도보 소요(분). 캐리어 감속 반영."""
    km = haversine_km(place.lat, place.lon, lat, lon)
    return km / config.HAUL_WALK_KMPH * 60


def access_travel_minutes(km: float) -> tuple[float, str]:
    """거리에 맞는 현실적 이동 수단과 소요(분).

    전부 도보로 계산하면 남포→서면 6.6km가 124분이 되어, 실제로는 지하철로
    30분이면 갈 거리를 '선택지가 아님'으로 잘못 판정한다. 도보와 대중교통 중
    짧은 쪽을 쓴다.
    """
    walk = km / config.HAUL_WALK_KMPH * 60
    transit = config.TRANSIT_OVERHEAD_MIN + km / config.TRANSIT_KMPH * 60
    return (walk, "도보") if walk <= transit else (transit, "대중교통")
