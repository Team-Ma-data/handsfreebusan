# -*- coding: utf-8 -*-
"""추천 엔진 오케스트레이터.

  사용자 입력(현재 위치·시간·원하는 상황·짐 크기와 무게)
    → 원하는 상황으로 후보군을 좁히고
    → 1단계 실행 가능성 필터로 불가능한 것을 떨어뜨리고
    → 통과한 것끼리만 비용 비교
    → 둘 다 탈락하면 폴백 사다리를 내려간다
    → 내려가는 모든 순간을 로그로 남긴다 (그게 B2B 자산이 된다)

한 문장으로: 관광객에게 최선의 선택지를 주면서, 그 과정에서 짐캐리와
부산교통공사에게 다음 거점을 알려준다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import access, config, cost, eventlog, fallback, feasibility, places

log = logging.getLogger("timecarry.engine")
from .config import CostWeights, DEFAULT_WEIGHTS, Preference
from .eventlog import EventLog, EventType
from .models import Decision, LuggageRequest, Option, OptionKind, Place, PlaceKind
from .registry import get_registry, haversine_km


@dataclass
class Engine:
    weights: CostWeights = DEFAULT_WEIGHTS
    log: EventLog = field(default_factory=lambda: eventlog.GLOBAL_LOG)

    # ── 진입점 ──────────────────────────────────────────────────
    def recommend(self, req: LuggageRequest) -> Decision:
        primary, rejected = self._stage1(req)

        if primary:
            primary.sort(key=lambda o: o.cost.total)
            decision = Decision(
                request=req,
                recommended=primary[0],
                alternatives=primary[1:],
                rejected=rejected,
                fallback_level=0,
            )
            decision.narrative = self._narrate(decision)
            self.log.record_decision(decision)
            return decision

        return self._stage2(req, rejected)

    # ── 1단계: 원하는 상황으로 좁히고 하드 제약 통과 ────────────
    def _stage1(self, req: LuggageRequest) -> tuple[list[Option], list[Option]]:
        feasible: list[Option] = []
        rejected: list[Option] = []

        if req.wants_storage:
            # 역사 물품보관함 — 현재 위치에서 도보 10분 이내의 모든 역을 후보로.
            # 한 곳만 보고 실패하면 끝내는 대신 처음부터 선택지를 다 펼친다.
            station_opts = self._station_lockers(req)
            feasible.extend(o for o in station_opts if o.feasible)
            rejected.extend(o for o in station_opts if not o.feasible)

            # 짐캐리 무인보관함 3곳
            zim_ok, zim_no = fallback.zim_locker_options(req, w=self.weights)
            feasible.extend(zim_ok)
            rejected.extend(zim_no)

            # 도보권 밖(1~3정거장) 역의 보관함 — 이동을 실제 경로로 계산해 얹는다.
            # 해운대 대형 3칸처럼 공급이 얇은 역에서 "두 정거장 옆" 제안이 여기서 나온다.
            try:
                feasible.extend(access.remote_locker_options(req, w=self.weights))
            except Exception as e:  # noqa: BLE001
                log.warning("원거리 보관함 탐색 실패(무시): %s", e)

        if req.wants_delivery:
            delivery = feasibility.check_delivery(req)

            # 현재 위치가 매장이 아니어도, 매장까지 가서 마감 전에 접수할 수 있으면 배송은 가능하다.
            # 이걸 안 하면 "지금 서면이니 배송 불가"라는 틀린 답이 나온다.
            try:
                for o in access.store_visit_delivery(req, w=self.weights):
                    (feasible if o.feasible else rejected).append(o)
            except Exception as e:  # noqa: BLE001
                log.warning("매장 경유 배송 탐색 실패(무시): %s", e)

            if delivery.feasible:
                store_min, store_difficulty = self._store_access(req)
                cost.price_delivery(
                    req,
                    delivery,
                    store_access_minutes=store_min,
                    store_access_difficulty=store_difficulty,
                    w=self.weights,
                )
                feasible.append(delivery)
            else:
                rejected.append(delivery)

        return feasible, rejected

    # ── 2단계: 폴백 사다리 ──────────────────────────────────────
    def _stage2(self, req: LuggageRequest, rejected: list[Option]) -> Decision:
        candidates: list[Option] = []
        extra_rejected = list(rejected)
        level_reached = 0

        # 1단 — 캐리어 동반 최적 경로 (항상 바닥에 깔린다)
        haul = fallback.haul_option(req, w=self.weights)
        if haul is not None:
            level_reached = 1
            candidates.append(haul)

        # 2단 — 시간 시프트 (배송을 원했던 경우에만)
        shifted: list[Option] = []
        if req.wants_delivery:
            s = fallback.time_shift_delivery(req)
            if s is not None:
                level_reached = max(level_reached, 2)
                shifted.append(s)

        if not candidates and not shifted:
            decision = Decision(
                request=req,
                recommended=None,
                rejected=extra_rejected,
                fallback_level=level_reached,
            )
            decision.narrative = "제안 가능한 옵션이 없습니다."
            self.log.record_decision(decision)
            return decision

        # 사다리는 '무엇을 시도하는가'의 순서지, 무조건 위 칸을 고르라는 뜻이 아니다.
        # 세 단에서 나온 후보를 한 풀에 놓고 비용으로 고른다. 공항에 새벽 도착해
        # 한 시간만 기다리면 배송이 되는 상황에서 25정거장을 끌게 하면 안 된다.
        pool = candidates + shifted
        pool.sort(key=lambda o: o.cost.total)
        best = pool[0]
        others = list(pool[1:])

        decision = Decision(
            request=req,
            recommended=best,
            alternatives=others,
            rejected=extra_rejected,
            fallback_level=best.fallback_level or level_reached,
        )
        decision.narrative = self._narrate(decision)
        self.log.record_decision(decision)
        return decision

    def _station_lockers(self, req: LuggageRequest) -> list[Option]:
        """도보 10분 반경 내 역들의 보관함 후보. 통과·탈락을 모두 돌려준다."""
        reg = get_registry()
        out: list[Option] = []

        for code, access_min in places.locker_candidate_stations(req.origin):
            st = reg.station(code)
            probe = Place(
                kind=PlaceKind.STATION,
                name=st.name,
                lat=st.lat,
                lon=st.lon,
                station_code=code,
            )
            opt = feasibility.check_station_locker(req, probe)
            opt.evidence["현재 위치에서"] = (
                "도착 지점" if access_min < 1 else f"도보 {access_min:.0f}분"
            )
            if access_min >= 1:
                opt.label = f"{st.label} 보관함 (도보 {access_min:.0f}분)"

            if not opt.feasible:
                out.append(opt)
                continue

            difficulty, _ = cost.haul_difficulty(code)
            cost.price_station_locker(
                req,
                opt,
                access_minutes=access_min,
                access_difficulty=difficulty,
                retrieval_detour_minutes=self._retrieval_detour(req, code),
                w=self.weights,
            )
            out.append(opt)

        return out

    # ── 보조 계산 ───────────────────────────────────────────────
    def _retrieval_detour(self, req: LuggageRequest, station_code: int | None) -> float:
        """짐을 찾으러 그 역으로 되돌아오는 우회 시간(분).

        일정(itinerary)의 마지막 지점 기준. 없으면 목적지, 목적지도 없으면
        제자리로 보고 0으로 둔다(보관만 하고 같은 역으로 돌아오는 경우).
        """
        if station_code is None:
            return 0.0
        reg = get_registry()
        if req.itinerary:
            end_code = req.itinerary[-1]
        elif req.destination is not None:
            end_code = req.destination.station_code
            if end_code is None:
                end_code, _ = places.nearest_station(
                    req.destination.lat, req.destination.lon
                )
        else:
            return 0.0

        if end_code == station_code:
            return 0.0
        hops = reg.neighbors_within(end_code, 40).get(station_code)
        return 20.0 if hops is None else reg.hop_travel_seconds(hops) / 60

    def _store_access(self, req: LuggageRequest) -> tuple[float, float]:
        """접수 매장까지 짐을 들고 가는 시간과 난이도.

        이미 매장에 서 있으면 0. 숙소·보관함에서 신청하는 경우엔 짐캐리가
        수거하러 오므로 이용자의 운반 부담은 없다.
        """
        if req.origin.kind is PlaceKind.STORE:
            return 0.0, 1.0
        return 0.0, 1.0

    # ── 설명 생성 ───────────────────────────────────────────────
    def _narrate(self, d: Decision) -> str:
        r = d.recommended
        if r is None:
            return "제안 가능한 옵션이 없습니다."

        lines: list[str] = []
        blocked = [o for o in d.rejected if o.reject_reason is not None]

        if d.fallback_level == 0:
            lines.append(f"추천: {r.kind.value} — {r.label}")
        else:
            step = {1: "캐리어 동반 최적 경로", 2: "시간 시프트"}
            lines.append(
                f"1차 후보가 모두 막혀 폴백 {d.fallback_level}단"
                f"({step.get(d.fallback_level, '')})으로 내려갔습니다."
            )
            lines.append(f"추천: {r.kind.value} — {r.label}")

        if blocked:
            lines.append("탈락한 옵션:")
            seen: set[str] = set()
            for o in blocked:
                key = f"{o.kind.value}|{o.reject_reason.name}"
                if key in seen:
                    continue
                seen.add(key)
                lines.append(
                    f"  · {o.kind.value}: {o.reject_detail or o.reject_reason.value}"
                )

        c = r.cost
        lines.append(
            f"비용지수 {c.total:,.0f} "
            f"(지출 {c.money:,.0f} / 시간 {c.time:,.0f} / 부담 {c.burden:,.0f} / "
            f"리스크 {c.risk:,.0f} / 불안 {c.anxiety:,.0f})"
        )
        return "\n".join(lines)


#: 기본 엔진 인스턴스
default_engine = Engine()


def recommend(req: LuggageRequest) -> Decision:
    return default_engine.recommend(req)
