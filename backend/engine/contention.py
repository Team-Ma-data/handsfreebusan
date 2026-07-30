# -*- coding: utf-8 -*-
"""
보관함 혼잡 트리아지 — "2안을 함께 줄 것인가"를 정한다.

## 왜 칸수가 아니라 미스매치인가

칸수만 보면 "서면 255칸이니 여유"가 되는데, 서면은 수요도 최대라 여유가 아니다.
공급 단독도 수요 단독도 답이 아니고 **공급 대비 수요**가 답이다. 그게 미스매치다.

## 그런데 미스매치를 그대로 쓰면 안 되는 이유 (이 모듈이 존재하는 이유)

`saturation.mismatch_ranking()` 의 수요는 **하차 인원**에서 온다. 그런데 하차객이 많다고
보관함 수요가 많은 게 아니다. 서면 하차 12.4만 명의 대부분은 짐이 없는 통근·쇼핑객이고,
부산역 하차객은 KTX 도착객이라 짐 보유율이 압도적으로 높다. `attempt_rate()` 가
**부산역 한 곳을 앵커로 역산한 전역 상수**라 이 차이가 통째로 뭉개진다.

같은 함정이 미스매치 v1에서 이미 확인됐다 — raw 승하차로 계산했더니 명륜·괴정이 1~2위로
올라왔고, 카드 실측(v3)으로 생활상권임이 드러나 기각됐다. B2C 화면에서 이 실수를 반복할 수 없다.

## 보정 — 여가지수를 곱한다

`saturation.leisure_index()` = 주말 하차 / 주중 하차. **발제 데이터 안에서** 통근역과
관광역을 가르는 지표다. 외부 데이터가 필요 없다.

    혼잡지수 = 미스매치 점수 × 여가가중(여가지수)

팀원은 여가지수를 포화확률에서 일부러 뺐다("섞으면 어느 쪽 신호인지 알 수 없게 된다").
그 판단은 **확률을 계산할 때는** 옳다. 여기서 다시 넣는 이유는 우리가 계산하는 게 확률이
아니라 **트리아지 순위**이기 때문이다. 순위는 신호가 섞여도 순서만 맞으면 쓸 수 있고,
우리는 그 순위를 "2안을 붙일까 말까"라는 이진 결정에만 쓴다.

## 트리아지 계수 — 정확히 무엇을 곱하는가

    트리아지 점수 = persons_per_slot × 여가가중

**persons_per_slot** (`saturation.MismatchRow.persons_per_slot`)
    = 그 역의 일 하차 인원 ÷ 해당 규격 이상 보관함 칸수
    = **보관함 1칸이 하루에 받아내야 하는 하차 인원.** 클수록 공급이 모자라다.
    분자·분모 모두 발제 원본이다 — 하차는 #2 시간대별 승하차, 칸수는 #4-1 물품보관함.
    파생 가정이 하나도 없는 순수 관측량이라, 미스매치 지표 중 가장 방어하기 쉽다.
    (포화확률 `peak_probability` 는 쓰지 않는다. 그건 Erlang-B + 시도율 앵커 가정 위에 있다.)

**여가가중** = clamp(여가지수, 0.5, 2.0)

    여가지수 = 주말 하차 일평균 ÷ 주중 하차 일평균
             = ( (토요일 일평균 하차) + (일요일 일평균 하차) ) / 2  ÷  (주중 일평균 하차)

    구현은 `saturation.leisure_index(code)` 이고 계산식은 그게 전부다. 계수도 가정도 없다.
    #2 승하차 데이터를 요일유형(주중/토/일)으로 나눠 역별 일평균을 낸 뒤 나눈 값이다.
    (요일유형 분류는 `demand.build_profile()` 이 원본의 요일 컬럼으로 만든다.)

    · 여가지수 1.0  = 주말과 주중 하차가 같다 → 보정 없음
    · 여가지수 1.6  = 주말이 60% 더 많다 → 관광·여가 성격. 짐 든 이용자 비중이 높다고 본다
    · 여가지수 0.6  = 주말이 훨씬 적다 → 통근역. 하차가 많아도 짐 수요는 아니다

    상·하한 0.5~2.0은 **한 지표가 순위를 독점하지 못하게 자르는 클램프**이며, 이것만이
    이 모듈에서 우리가 정한 유일한 숫자다(`LEISURE_CAP`). 클램프를 풀면 여가지수가
    극단적인 소수 역이 순위를 지배한다.

왜 이 둘을 곱하는가: persons_per_slot 은 **수요의 크기**를, 여가지수는 **그 수요가 짐 든
사람일 가능성**을 각각 말한다. 서면은 앞이 크고 뒤가 작으며(통근), 해운대는 뒤가 크다(관광).
곱해야 둘 다 큰 역이 위로 온다.

## 임계값의 근거 — 분포가 아니라 오류비용의 비대칭

"왜 상위 33%인가"에 분포로 답할 수는 없다. 분포는 절단점을 알려주지 않는다.
답은 두 오류의 비용이 다르다는 데 있다.

    2안을 붙였는데 불필요했다  → 카드 한 장 더 본다. 비용 ≈ 0
    2안을 안 붙였는데 꽉 찼다  → 짐 끌고 헛걸음 왕복 10~20분 + 신뢰 상실. 회복 불가

비용이 이렇게 비대칭이면 최적 임계는 중앙이 아니다. **확실히 여유로운 경우에만 생략**해야 한다.
그래서 규칙은 "상위 X%면 2안을 준다"가 아니라 **"하위 33%가 아니면 2안을 준다"** 로 쓴다.
방향이 반대인 게 요점이다. 기본값이 '2안 있음'이고, 생략이 예외다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

log = logging.getLogger("timecarry.contention")

#: 하위 이 비율 안에 들면 2안을 생략해도 좋다. 위 주석의 비대칭 근거로 보수적으로 잡았다.
SAFE_QUANTILE = 0.33

#: 여가지수 → 가중치. 주중·주말 하차가 같으면(=1.0) 보정 없음.
#: 주말이 2배면 관광 성격이 강해 짐 수요 비중이 높다고 본다.
#: [가정] 상한 2.0 — 한 지표가 순위를 독점하지 않게 자른다.
LEISURE_CAP = 2.0


@dataclass(frozen=True)
class Contention:
    station_code: int
    score: float                 # 보정된 혼잡지수 (임의 단위 — 순위로만 쓴다)
    percentile: float            # 0=여유 … 1=가장 빡빡
    capacity: int                # 해당 규격 이상 칸수
    needs_backup: bool
    basis: str                   # 화면 툴팁·발표용 한 줄 설명

    def as_evidence(self) -> dict:
        return {
            "공급 대비 수요 순위": f"상위 {100 * (1 - self.percentile):.0f}%",
            "해당 규격 칸수": self.capacity,
            "실시간 점유": "확인 불가 — 잔여 칸수 API 미제공",
            "2안 동반": "예" if self.needs_backup else "아니오",
            "판단 근거": self.basis,
        }


def _leisure_weight(code: int) -> float:
    from .saturation import leisure_index

    try:
        idx = leisure_index(code)
    except Exception:  # noqa: BLE001
        return 1.0
    return max(0.5, min(LEISURE_CAP, idx if idx > 0 else 1.0))


@lru_cache(maxsize=8)
def _ranking(size_value: str, day_type: str) -> tuple[tuple[int, float], ...]:
    """(역코드, 보정 혼잡지수) 전 역 — 낮은 순. 캐시한다(전 역 계산이라 비싸다)."""
    from .config import LuggageSize
    from .saturation import mismatch_ranking

    size = next(s for s in LuggageSize if s.value == size_value)
    rows = mismatch_ranking(size=size, day_type=day_type)
    out = []
    for r in rows:
        #: persons_per_slot = 일 하차 ÷ 칸수. 발제 원본만으로 만들어지는 순수 관측량이다.
        out.append((r.station_code, float(r.persons_per_slot) * _leisure_weight(r.station_code)))
    out.sort(key=lambda x: x[1])
    return tuple(out)


def assess(station_code: int, size, when: datetime, capacity: int) -> Contention:
    """이 역·이 규격·이 시각에 2안을 붙여야 하는가."""
    from .saturation import day_type_of

    # 칸이 0이면 애초에 선택지가 아니다(실행가능성 필터가 이미 걸러낸다).
    if capacity <= 0:
        return Contention(station_code, float("inf"), 1.0, capacity, True,
                          "해당 규격 칸 없음")

    try:
        ranking = _ranking(size.value, day_type_of(when))
        codes = [c for c, _ in ranking]
        idx = codes.index(station_code)
        pct = idx / max(1, len(codes) - 1)
        score = ranking[idx][1]
    except Exception as e:  # noqa: BLE001
        # 랭킹을 못 구하면 **보수적으로** 2안을 붙인다. 모를 때는 붙이는 쪽이 싸다.
        log.debug("미스매치 랭킹 조회 실패(보수적 처리): %s", e)
        return Contention(station_code, 0.0, 1.0, capacity, True,
                          "혼잡 순위 산출 불가 — 보수적으로 2안 동반")

    safe = pct <= SAFE_QUANTILE
    basis = (
        f"공급 대비 수요가 하위 {100 * pct:.0f}% — 여유로운 편이라 2안 생략"
        if safe else
        f"공급 대비 수요 상위 {100 * (1 - pct):.0f}% — 실시간 잔여를 알 수 없어 2안 동반"
    )
    return Contention(station_code, score, pct, capacity, not safe, basis)


def rank_table(size, day_type: str, top: int = 15) -> list[tuple[int, float]]:
    """B2B 발표용 — 보정 후 상위 역. 같은 계산이 B2C 트리아지와 B2B 제안을 동시에 만든다."""
    return list(reversed(_ranking(size.value, day_type)))[:top]
