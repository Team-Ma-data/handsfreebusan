# -*- coding: utf-8 -*-
"""캐리어 동반 최적 경로 탐색.

일반 길찾기는 최단시간을 준다. 여기서는 "짐을 끌고 가장 덜 고생하는 길"을 준다.
같은 목적지라도 환승역에 엘리베이터가 없으면 한 정거장 더 타고 가서 갈아타는
편이 낫다 — 그 판단을 하는 게 이 모듈이다.

비용이 붙는 지점
  - 승차 구간: 시간 기회비용 + 짐을 지고 있는 기본 부담
  - 출발역 진입 / 도착역 진출 / 환승역: 수직 이동이 일어나는 곳.
    #3.1 E/L 유무, #3.4 곡선승강장·연단간격, #3.3 대체경로 복잡도가 여기서 곱해진다.
  통과역은 열차 안에 있으므로 부담을 물리지 않는다. 이게 현실과 맞다.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from . import config
from .config import CostWeights, DEFAULT_WEIGHTS
from .cost import haul_difficulty
from .registry import get_registry

#: [가정] 역 진입·진출 시 수직 이동에 드는 시간(분).
ENTRY_EXIT_MINUTES = 5.0
#: [가정] 환승 통로 이동 시간(분).
TRANSFER_MINUTES = 8.0


@dataclass
class HaulRoute:
    path: list[int]
    travel_minutes: float
    transfers: list[int] = field(default_factory=list)
    cost_krw: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def hops(self) -> int:
        reg = get_registry()
        return sum(
            1
            for a, b in zip(self.path, self.path[1:])
            if reg.station(a).name != reg.station(b).name
        )


def vertical_penalty(code: int, minutes: float, w: CostWeights) -> tuple[float, list[str]]:
    """한 역에서 수직 이동할 때 붙는 부담(원)과 그 이유."""
    reg = get_registry()
    fac = reg.facility(code)
    difficulty, _ = haul_difficulty(code)
    label = reg.station(code).label

    penalty = minutes * w.haul_burden_per_min * difficulty
    notes: list[str] = []

    if not fac.has_elevator:
        penalty += w.stair_segment_penalty
        notes.append(f"{label}: 엘리베이터 없음 (계단 부담)")
    if fac.platform_curved_ratio > 0:
        penalty += w.curved_platform_penalty * fac.platform_curved_ratio
        notes.append(f"{label}: 곡선 승강장 {fac.platform_curved_ratio:.0%}")
    if fac.platform_wide_gap_ratio > 0:
        notes.append(f"{label}: 연단간격 넓음 {fac.platform_wide_gap_ratio:.0%}")
    if fac.alt_route_blocked > 0:
        notes.append(f"{label}: E/L 고장 시 이동 불가 경로 {fac.alt_route_blocked}건")

    return penalty, notes


def find_route(
    origin: int, dest: int, w: CostWeights = DEFAULT_WEIGHTS
) -> HaulRoute | None:
    """짐 부담까지 반영한 최소비용 경로. 다익스트라."""
    reg = get_registry()
    if origin == dest:
        return HaulRoute(path=[origin], travel_minutes=0.0, cost_krw=0.0)

    ride_cost_per_min = w.time_value_per_hour / 60 + w.haul_burden_per_min

    dist: dict[int, float] = {origin: 0.0}
    prev: dict[int, int] = {}
    time_to: dict[int, float] = {origin: 0.0}
    pq: list[tuple[float, int]] = [(0.0, origin)]
    visited: set[int] = set()

    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        if u == dest:
            break

        for v in reg.adjacent(u):
            is_transfer = reg.station(u).name == reg.station(v).name
            if is_transfer:
                minutes = TRANSFER_MINUTES
                pen, _ = vertical_penalty(u, TRANSFER_MINUTES, w)
                edge = minutes * (w.time_value_per_hour / 60) + pen
            else:
                minutes = reg.SECONDS_PER_HOP / 60
                edge = minutes * ride_cost_per_min

            nd = d + edge
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = u
                time_to[v] = time_to[u] + minutes
                heapq.heappush(pq, (nd, v))

    if dest not in dist:
        return None

    path = [dest]
    while path[-1] != origin:
        path.append(prev[path[-1]])
    path.reverse()

    notes: list[str] = []
    entry_pen, n1 = vertical_penalty(origin, ENTRY_EXIT_MINUTES, w)
    exit_pen, n2 = vertical_penalty(dest, ENTRY_EXIT_MINUTES, w)
    notes.extend(n1)
    notes.extend(n2)

    transfers = [
        b for a, b in zip(path, path[1:]) if reg.station(a).name == reg.station(b).name
    ]
    for t in transfers:
        _, n = vertical_penalty(t, TRANSFER_MINUTES, w)
        notes.extend(n)

    total_minutes = time_to[dest] + 2 * ENTRY_EXIT_MINUTES
    total_cost = dist[dest] + entry_pen + exit_pen

    return HaulRoute(
        path=path,
        travel_minutes=total_minutes,
        transfers=transfers,
        cost_krw=total_cost,
        notes=list(dict.fromkeys(notes)),
    )


def compare_routes(
    origin: int, dest: int, w: CostWeights = DEFAULT_WEIGHTS
) -> dict:
    """부담 반영 경로 vs 최단시간 경로. 둘이 다르면 그게 우리 엔진의 값어치다."""
    reg = get_registry()

    # 최단시간 경로: 부담을 0으로 두고 같은 탐색을 돌린다.
    flat = CostWeights(
        time_value_per_hour=w.time_value_per_hour,
        haul_burden_per_min=0,
        stair_segment_penalty=0,
        curved_platform_penalty=0,
        failure_recovery_cost=w.failure_recovery_cost,
        separation_anxiety_per_hour=w.separation_anxiety_per_hour,
    )
    burden_aware = find_route(origin, dest, w)
    time_only = find_route(origin, dest, flat)
    if burden_aware is None or time_only is None:
        return {}

    same = burden_aware.path == time_only.path
    return {
        "부담반영경로": [reg.station(c).label for c in burden_aware.path],
        "최단시간경로": [reg.station(c).label for c in time_only.path],
        "동일여부": same,
        "부담반영 소요(분)": round(burden_aware.travel_minutes, 1),
        "최단시간 소요(분)": round(time_only.travel_minutes, 1),
        "회피근거": burden_aware.notes,
    }
