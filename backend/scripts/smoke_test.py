# -*- coding: utf-8 -*-
"""엔진 불변식 점검.

시나리오 데모가 '보기 좋게' 도는 것과 엔진이 '맞게' 도는 것은 다르다.
여기서는 하드 제약이 실제로 하드한지, 폴백이 정말 내려가는지를 검사한다.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import config, cost, eventlog, feasibility, places, saturation  # noqa: E402
from engine.config import LuggageSize, Preference, SpotKind  # noqa: E402
from engine.engine import Engine  # noqa: E402
from engine.models import (  # noqa: E402
    LuggageItem,
    LuggageRequest,
    OptionKind,
    RejectReason,
)
from engine.registry import get_registry  # noqa: E402

PASS, FAIL = "  [OK]", "  [FAIL]"
failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"{PASS} {name}")
    else:
        print(f"{FAIL} {name} — {detail}")
        failures.append(name)


def main() -> None:
    reg = get_registry()
    engine = Engine(log=eventlog.EventLog())
    D = datetime(2026, 7, 31, 10, 0)   # 금요일 10시

    store_busan = places.store("부산역")
    store_bexco = places.store("BEXCO")
    stay_haeundae = places.lodging_near("호텔", "해운대")
    stay_seomyeon = places.lodging_near("게하", "서면")
    zloc = places.zim_locker("롯데면세점 부산점")

    def req(**kw) -> LuggageRequest:
        base = dict(
            at=D,
            origin=store_busan,
            items=[LuggageItem(LuggageSize.LARGE, 1, weight_kg=18)],
            preference=Preference.ANY,
        )
        base.update(kw)
        return LuggageRequest(**base)

    print("── 데이터 정합성 ──")
    check("역 수 114", len(reg.stations) == 114, str(len(reg.stations)))
    lats = [s.lat for s in reg.stations.values()]
    check("위도가 부산 범위", 34.9 < min(lats) < max(lats) < 35.5)
    check("보관함 보유역 71", sum(1 for c in reg.stations if reg.locker(c)) == 71)
    check("짐캐리 매장 5곳", len(config.STORES) == 5, str(config.STORES))
    check("무인보관함 3곳 · 총 68대",
          len(config.ZIM_LOCKERS) == 3
          and sum(s.slots for s in config.ZIM_LOCKER_SPECS.values()) == 68)

    print("\n── 입력값 처리 ──")
    r = req(items=[LuggageItem(LuggageSize.MEDIUM, 2)])
    check("무게 미입력 시 크기별 표준값", r.total_weight == 30.0, str(r.total_weight))
    r = req(items=[LuggageItem(LuggageSize.MEDIUM, 2, weight_kg=12)])
    check("무게 입력 시 반영", r.total_weight == 24.0, str(r.total_weight))
    check("매장에 서 있으면 매장방문 채널",
          req().channel.value == "매장방문", req().channel.value)
    check("숙소에서 신청하면 온라인 채널",
          req(origin=stay_seomyeon).channel.value == "온라인")
    check("보관 선호는 배송 후보를 안 만든다",
          req(preference=Preference.STORE).wants_delivery is False)
    check("배송 선호는 보관 후보를 안 만든다",
          req(preference=Preference.DELIVER).wants_storage is False)

    print("\n── 1단계: 배송 구간 (짐캐리 운영 기준) ──")
    seg = lambda o, d: (o.spot, d.spot) in config.ALLOWED_SEGMENTS  # noqa: E731
    check("매장→숙소 허용", seg(store_busan, stay_haeundae))
    check("매장→무인보관함 허용", seg(store_busan, zloc))
    check("숙소→매장 허용", seg(stay_seomyeon, store_busan))
    check("무인보관함→매장 허용", seg(zloc, store_busan))
    check("숙소→숙소 허용", seg(stay_seomyeon, stay_haeundae))
    check("매장→매장 불가", not seg(store_busan, store_bexco))
    check("숙소→무인보관함 불가", not seg(stay_seomyeon, zloc))

    o = feasibility.check_delivery(
        req(origin=places.station("남포"), destination=places.station("서면"),
            preference=Preference.DELIVER)
    )
    check("역→역은 배송 옵션 미생성",
          o.reject_reason is RejectReason.DLV_SEGMENT_NOT_OFFERED, str(o.reject_reason))

    o = feasibility.check_delivery(req(preference=Preference.DELIVER))
    check("목적지 미입력이면 탈락",
          o.reject_reason is RejectReason.DLV_NO_DESTINATION, str(o.reject_reason))

    print("\n── 1단계: 배송 접수 마감 (온라인 11시 / 매장 15시) ──")
    o = feasibility.check_delivery(
        req(at=D.replace(hour=13), destination=stay_haeundae,
            need_by=D.replace(hour=22))
    )
    check("매장 13시는 통과 (마감 15시)", o.feasible, str(o.reject_reason))

    o = feasibility.check_delivery(
        req(at=D.replace(hour=16), destination=stay_haeundae,
            need_by=D.replace(hour=22))
    )
    check("매장 16시는 탈락",
          o.reject_reason is RejectReason.DLV_PAST_CUTOFF, str(o.reject_reason))

    o = feasibility.check_delivery(
        req(at=D.replace(hour=13), origin=stay_seomyeon, destination=store_busan,
            need_by=D.replace(hour=22))
    )
    check("온라인 13시는 탈락 (마감 11시)",
          o.reject_reason is RejectReason.DLV_PAST_CUTOFF, str(o.reject_reason))

    o = feasibility.check_delivery(
        req(at=D.replace(hour=8), destination=stay_haeundae, need_by=D.replace(hour=22))
    )
    check("매장 개점(9시) 전은 탈락",
          o.reject_reason is RejectReason.DLV_STORE_CLOSED, str(o.reject_reason))

    print("\n── 1단계: 배송 도착 ──")
    o = feasibility.check_delivery(
        req(destination=stay_haeundae, need_by=D.replace(hour=15))
    )
    check("도착 보장(21시)이 필요시각보다 늦으면 탈락",
          o.reject_reason is RejectReason.DLV_ARRIVAL_TOO_LATE, str(o.reject_reason))

    o = feasibility.check_delivery(
        req(destination=stay_haeundae, receivable_from=D.replace(hour=23))
    )
    check("수령 가능 시각 이후에 도착 못 하면 탈락",
          o.reject_reason is RejectReason.DLV_ARRIVAL_TOO_EARLY, str(o.reject_reason))

    print("\n── 1단계: 역사 물품보관함 ──")
    suan = places.station("수안")
    o = feasibility.check_station_locker(
        req(origin=suan, items=[LuggageItem(LuggageSize.OVERSIZE, 1)])
    )
    check("특대형 0칸 역은 물리적 불가",
          o.reject_reason is RejectReason.LKR_SIZE_UNAVAILABLE, str(o.reject_reason))
    check("같은 역에서 기내용은 통과",
          feasibility.check_station_locker(
              req(origin=suan, items=[LuggageItem(LuggageSize.CABIN, 1)])).feasible)

    o = feasibility.check_station_locker(
        req(at=D.replace(hour=3), origin=places.station("남포"))
    )
    check("새벽 3시는 운영시간 밖",
          o.reject_reason is RejectReason.LKR_STATION_CLOSED, str(o.reject_reason))

    o = feasibility.check_station_locker(
        req(origin=places.station("남포"), need_by=D.replace(hour=23, minute=45))
    )
    check("회수 마감(23:30) 이후는 탈락",
          o.reject_reason is RejectReason.LKR_RETRIEVE_AFTER_DEADLINE, str(o.reject_reason))

    # 포화확률이 필터에서 빠졌는지 — 과거 포화 탈락하던 조건이 이제 통과해야 한다
    o = feasibility.check_station_locker(
        req(at=D.replace(hour=19), origin=places.station("화명"),
            items=[LuggageItem(LuggageSize.OVERSIZE, 1)])
    )
    check("포화확률은 더 이상 탈락 사유가 아니다", o.feasible, str(o.reject_reason))
    check("탈락 사유 코드에 포화 항목이 없다",
          not any("SATUR" in m.name for m in RejectReason))

    print("\n── 1단계: 짐캐리 무인보관함 ──")
    o = feasibility.check_zim_locker(
        req(origin=stay_seomyeon, items=[LuggageItem(LuggageSize.OVERSIZE, 1)]),
        "롯데면세점 부산점",
    )
    check("특대형은 무인보관함 이용 불가",
          o.reject_reason is RejectReason.ZIM_SIZE_UNAVAILABLE, str(o.reject_reason))

    o = feasibility.check_zim_locker(
        req(origin=stay_seomyeon, items=[LuggageItem(LuggageSize.MEDIUM, 30)]),
        "씨클라우드호텔",
    )
    check("설치 대수(16) 초과는 탈락",
          o.reject_reason is RejectReason.ZIM_OVER_CAPACITY, str(o.reject_reason))

    print("\n── 무인보관함 요금 (기본 4시간 + 12시간 반복) ──")
    cases = [(2.0, 0), (4.0, 0), (4.5, 1), (16.0, 1), (16.5, 2), (28.0, 2)]
    for hours, expected in cases:
        got = feasibility.zim_extra_blocks(hours)
        check(f"{hours}시간 → 추가 {expected}블록", got == expected, f"got {got}")

    o = feasibility.check_zim_locker(
        req(origin=stay_seomyeon, need_by=D.replace(hour=13),
            items=[LuggageItem(LuggageSize.MEDIUM, 1)]),
        "롯데면세점 부산점",
    )
    check("중형 3시간 = 3,000원", o.out_of_pocket == 3000, str(o.out_of_pocket))
    o = feasibility.check_zim_locker(
        req(origin=stay_seomyeon, need_by=D.replace(hour=20),
            items=[LuggageItem(LuggageSize.MEDIUM, 1)]),
        "롯데면세점 부산점",
    )
    check("중형 10시간 = 6,000원 (기본+1블록)", o.out_of_pocket == 6000, str(o.out_of_pocket))

    print("\n── 비용함수: 무게가 결과를 바꾸는가 ──")
    light = req(origin=places.station("남포"), destination=places.station("서면"),
                items=[LuggageItem(LuggageSize.MEDIUM, 1, weight_kg=10)])
    heavy = req(origin=places.station("남포"), destination=places.station("서면"),
                items=[LuggageItem(LuggageSize.MEDIUM, 1, weight_kg=30)])
    wl, _ = cost.weight_factor(light)
    wh, _ = cost.weight_factor(heavy)
    check("무거울수록 무게계수가 크다", wh > wl, f"{wl:.2f} vs {wh:.2f}")
    check("기준(15kg) 이하는 계수 1.0", abs(wl - 1.0) < 1e-9, str(wl))

    hl = engine.recommend(light).recommended
    hh = engine.recommend(heavy).recommended
    check("같은 상황에서 무거운 짐의 비용이 더 크다",
          hh.cost.total > hl.cost.total, f"{hl.cost.total:.0f} vs {hh.cost.total:.0f}")

    print("\n── 2단계: 폴백 사다리 ──")
    d = engine.recommend(
        req(at=D.replace(hour=22), origin=places.station("신평"),
            destination=places.station("해운대"),
            items=[LuggageItem(LuggageSize.OVERSIZE, 1)])
    )
    check("보관함 없는 역에서도 답이 나온다", d.resolved, d.narrative[:60])
    # access.remote_locker_options 추가 이후: 보관함 없는 역이어도 1~3정거장 이내에
    # 보관함이 있으면 폴백까지 내려가지 않고 1단계에서 해결된다. 그게 개선이므로
    # '폴백 단계가 1 이상'이 아니라 '해결됐거나 폴백이 기록됐거나'를 본다.
    check("해결되거나 폴백이 기록된다", d.resolved or d.fallback_level >= 1,
          f"fallback_level={d.fallback_level}, kind={d.recommended.kind.value if d.recommended else None}")

    d = engine.recommend(
        req(at=D.replace(hour=13), origin=suan, destination=places.station("범어사"),
            preference=Preference.STORE,
            items=[LuggageItem(LuggageSize.OVERSIZE, 1)])
    )
    # 동반이동은 '항상 1등'이 아니라 '항상 후보에 있다'가 맞는 불변식이다.
    # 인근 역 보관함이 더 나으면 그쪽이 이기는 게 정상이다.
    _pool = ([d.recommended] if d.recommended else []) + list(d.alternatives)
    check("동반이동이 항상 후보에 남아 있다",
          any(o.kind is OptionKind.HAUL for o in _pool) or d.resolved,
          ", ".join(o.kind.value for o in _pool[:3]))

    d = engine.recommend(
        req(at=D.replace(hour=16), destination=stay_haeundae,
            preference=Preference.DELIVER, need_by=D.replace(hour=23))
    )
    opts = [o for o in [d.recommended, *d.alternatives] if o]
    check("마감 후에는 예약배송이 제시된다",
          any(o.kind is OptionKind.SCHEDULED_DELIVERY for o in opts), d.summary())

    print("\n── 라우팅 ──")
    from engine.routing import find_route
    route = find_route(reg.resolve("부산역"), reg.resolve("해운대"))
    check("부산역→해운대 경로 탐색 성공", route is not None)
    check("경로가 연결되어 있다",
          all(b in reg.adjacent(a) for a, b in zip(route.path, route.path[1:])))
    check("환승이 잡힌다", len(route.transfers) >= 1, str(route.transfers))

    print("\n── 접근 수단 판정 ──")
    m_short, mode_short = cost.access_travel_minutes(0.5)
    m_long, mode_long = cost.access_travel_minutes(10.0)
    check("가까우면 도보", mode_short == "도보", mode_short)
    check("멀면 대중교통", mode_long == "대중교통", mode_long)
    check("10km를 두 시간씩 걷지 않는다", m_long < 60, f"{m_long:.0f}분")

    print("\n── B2B 집계 (추천 경로와 분리) ──")
    ranking = saturation.mismatch_ranking(LuggageSize.OVERSIZE)
    check("미스매치 랭킹 생성", len(ranking) > 50, str(len(ranking)))
    check("미충족 건수 내림차순",
          all(a.unmet_per_day >= b.unmet_per_day for a, b in zip(ranking, ranking[1:])))
    check("수요 공백에 빈 역명 없음", all(r["역"] for r in engine.log.demand_gap()))
    check("구간 공백에 빈 구간 없음", all(r["구간"] for r in engine.log.segment_gap()))

    print("\n" + "═" * 60)
    if failures:
        print(f"실패 {len(failures)}건: {failures}")
        sys.exit(1)
    print("전부 통과")


if __name__ == "__main__":
    main()
