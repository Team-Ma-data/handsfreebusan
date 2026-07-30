# -*- coding: utf-8 -*-
"""레지스트리 정합성 점검. 조인 실패·좌표 오류를 조기에 잡는다."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import datasets, naming  # noqa: E402
from engine.registry import get_registry  # noqa: E402


def main() -> None:
    reg = get_registry()
    print(f"역 수: {len(reg.stations)}")

    print("\n[좌표 범위]")
    lats = [s.lat for s in reg.stations.values()]
    lons = [s.lon for s in reg.stations.values()]
    print(f"  위도 {min(lats):.4f}~{max(lats):.4f} / 경도 {min(lons):.4f}~{max(lons):.4f}")
    assert 34.9 < min(lats) and max(lats) < 35.5, "위도 범위 이상"
    assert 128.8 < min(lons) and max(lons) < 129.4, "경도 범위 이상"
    print("  → 부산 범위 정상 (스왑 보정 확인)")

    print("\n[조인 실패 점검]")
    checks = [
        ("보관함", datasets.load_lockers(), "호선", "역명"),
        ("엘리베이터", datasets.load_elevators(), "호선명", "역명"),
        ("에스컬레이터", datasets.load_escalators(), "호선명", "역명"),
    ]
    ok = True
    for label, df, line_col, name_col in checks:
        miss = sorted(
            {
                str(r[name_col])
                for _, r in df.iterrows()
                if reg.resolve(r[name_col], naming.parse_line_no(r[line_col])) is None
            }
        )
        print(f"  {label}: 미해결 {len(miss)}건 {miss if miss else ''}")
        ok = ok and not miss
    print("  → 전부 해결" if ok else "  → 미해결 있음")

    print("\n[보관함 공급 요약]")
    lockers = {c: reg.locker(c) for c in reg.stations if reg.locker(c)}
    print(f"  보관함 보유역: {len(lockers)} / {len(reg.stations)}")
    total = {}
    for sup in lockers.values():
        for size, n in sup.counts.items():
            total[size] = total.get(size, 0) + n
    print(f"  총 칸수: {total}")
    zero_xl = [reg.station(c).label for c, s in lockers.items() if s.counts.get("특대형", 0) == 0]
    print(f"  특대형 0칸(보유역 중): {len(zero_xl)}곳 {zero_xl}")

    print("\n[요금 파싱]")
    for c in list(lockers)[:3]:
        print(f"  {reg.station(c).label}: {lockers[c].price_per_3h} / {lockers[c].operators}")

    print("\n[인접 그래프] 부산역 기준 2정거장 이내")
    busan = reg.get("부산역")
    print(f"  기준역: {busan.label} ({busan.lat:.5f}, {busan.lon:.5f})")
    for code, hops in sorted(reg.neighbors_within(busan.code, 2).items(), key=lambda x: x[1]):
        sup = reg.locker(code)
        xl = sup.counts.get("특대형", 0) if sup else "-"
        print(f"    {hops}홉 {reg.station(code).label:<14} 특대형 {xl}")

    print("\n[환승 쌍둥이] 서면")
    for code in reg._by_name[naming.match_key("서면")]:
        st = reg.station(code)
        sup = reg.locker(code)
        print(f"  {st.label} 특대형 {sup.counts.get('특대형') if sup else '-'} / 환승 {st.transfer_lines}")

    print("\n[시설] 토성 / 부산")
    for nm in ("토성", "부산역"):
        st = reg.get(nm)
        f = reg.facility(st.code)
        print(
            f"  {st.label}: E/L {f.elevator_running}/{f.elevator_count} "
            f"E/S {f.escalator_running}/{f.escalator_count} "
            f"대체경로 평균복잡도 {f.alt_route_mean_complexity} 최대 {f.alt_route_max_complexity} "
            f"차단 {f.alt_route_blocked} 곡선비 {f.platform_curved_ratio:.2f} "
            f"광폭연단비 {f.platform_wide_gap_ratio:.2f} 승강장 {f.platform_type}"
        )


if __name__ == "__main__":
    main()
