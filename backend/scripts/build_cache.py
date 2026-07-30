# -*- coding: utf-8 -*-
"""전처리 캐시 생성. 데이터가 바뀌면 다시 돌린다."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import demand  # noqa: E402
from engine.registry import get_registry  # noqa: E402


def main() -> None:
    t0 = time.time()
    print("승하차 프로파일 집계 중 (409k행)...")
    profile = demand.build_profile()
    print(f"  완료 {time.time() - t0:.1f}s | {len(profile):,}행 → {demand.CACHE_PATH}")
    print(f"  기준 연도: {profile['연도'].iloc[0]}")

    d = demand.get_demand()
    reg = get_registry()
    print("\n[검증] 주요역 하차 피크 시간대 (주중 기준)")
    for name in ("부산역", "서면", "해운대", "남포", "토성", "광안", "중앙"):
        st = reg.get(name)
        if st is None:
            continue
        peaks = d.peak_hours(st.code, demand.WEEKDAY, "하차", top=3)
        peak_str = ", ".join(f"{h:02d}시 {v:,.0f}명" for h, v in peaks)
        print(f"  {st.label:<14} 일 하차 {d.daily(st.code, demand.WEEKDAY, '하차'):>8,.0f}명 | {peak_str}")

    print("\n[검증] 부산역 승차 시간대 분포 (주중) — 짐캐리 접수 마감 논거")
    st = reg.get("부산역")
    for h in range(6, 24):
        v = d.at(st.code, demand.WEEKDAY, h, "승차")
        bar = "█" * int(v / 200)
        print(f"  {h:02d}시 {v:>7,.0f} {bar}")


if __name__ == "__main__":
    main()
