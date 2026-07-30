# -*- coding: utf-8 -*-
"""시간대별 수요 프로파일.

#2 승하차 원본은 409,026행 48MB라 요청마다 읽을 수 없다. 한 번 집계해
[역 × 요일유형 × 시간대 × 승하차] 평균으로 캐시하고, 엔진은 캐시만 본다.

이 프로파일은 두 곳에 쓰인다.
  - 포화확률: 해당 역·시간대 하차 인원이 보관함 공급 대비 얼마나 큰가
  - B2B 미스매치 랭킹: 수요 대비 공급이 얼마나 모자란가

집계 기준
  - 대상 연도: 최근 연도(기본 2025). 코로나 회복 이후 수요 수준을 쓰기 위함.
  - 요일유형: 주중 / 토 / 일·공휴일. 관광 수요는 요일 편차가 커서 평균 하나로
    뭉개면 주말 피크가 사라진다.
  - 결측 역: #2 에 3호선 수영(301)·4호선 미남(401)이 없다. 환승 상대 노선
    코드에 합산돼 있어, 조회 시 형제 코드로 폴백한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import pandas as pd

from . import datasets
from .registry import get_registry

HOUR_COLUMNS: list[str] = (
    [f"{h:02d}시-{h + 1:02d}시" for h in range(1, 24)] + ["24시-01시"]
)
# 컬럼명의 시간 → 0~23 정수 시(始)
HOUR_OF = {c: (int(c[:2]) % 24) for c in HOUR_COLUMNS}

WEEKDAY, SATURDAY, SUNDAY = "주중", "토", "일"
DAY_TYPES = (WEEKDAY, SATURDAY, SUNDAY)

CACHE_PATH = datasets.CACHE_DIR / "demand_profile.csv"


def _day_type(korean_dow: str) -> str:
    dow = str(korean_dow).strip()
    if dow == "토":
        return SATURDAY
    if dow == "일":
        return SUNDAY
    return WEEKDAY


def build_profile(year: int | None = None, save: bool = True) -> pd.DataFrame:
    """원본을 집계해 프로파일을 만든다. 컬럼: 역번호, 요일유형, 시, 구분, 인원."""
    usecols = ["역번호", "년월일", "요일", "구분"] + HOUR_COLUMNS
    df = datasets.load_ridership(usecols=usecols)

    df["년월일"] = pd.to_datetime(df["년월일"], errors="coerce")
    df = df.dropna(subset=["년월일"])
    if year is None:
        year = int(df["년월일"].dt.year.max())
    df = df[df["년월일"].dt.year == year]

    df["요일유형"] = df["요일"].map(_day_type)

    long = df.melt(
        id_vars=["역번호", "요일유형", "구분"],
        value_vars=HOUR_COLUMNS,
        var_name="시간대",
        value_name="인원",
    )
    long["시"] = long["시간대"].map(HOUR_OF)
    long["인원"] = pd.to_numeric(long["인원"], errors="coerce").fillna(0)

    profile = (
        long.groupby(["역번호", "요일유형", "시", "구분"], as_index=False)["인원"]
        .mean()
        .rename(columns={"인원": "일평균인원"})
    )
    profile["연도"] = year

    if save:
        datasets.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        profile.to_csv(CACHE_PATH, index=False, encoding="utf-8-sig")
    return profile


@dataclass(frozen=True)
class DemandProfile:
    """역·요일유형·시간대별 승하차 조회기."""

    table: dict[tuple[int, str, int, str], float]
    year: int
    daily_total: dict[tuple[int, str, str], float]

    def at(self, code: int, day_type: str, hour: int, kind: str = "하차") -> float:
        """해당 시간대 1시간 동안의 일평균 인원."""
        v = self.table.get((code, day_type, hour % 24, kind))
        if v is not None:
            return v
        # #2 에 없는 환승 쌍둥이 코드는 상대 노선 코드에 합산돼 있다.
        for sib in get_registry().siblings(code):
            v = self.table.get((sib, day_type, hour % 24, kind))
            if v is not None:
                return v
        return 0.0

    def window(
        self, code: int, day_type: str, start_hour: int, hours: int, kind: str = "하차"
    ) -> float:
        """start_hour 부터 hours 시간 동안의 누적 인원."""
        return sum(self.at(code, day_type, start_hour + i, kind) for i in range(hours))

    def daily(self, code: int, day_type: str, kind: str = "하차") -> float:
        v = self.daily_total.get((code, day_type, kind))
        if v is not None:
            return v
        for sib in get_registry().siblings(code):
            v = self.daily_total.get((sib, day_type, kind))
            if v is not None:
                return v
        return 0.0

    def peak_hours(
        self, code: int, day_type: str, kind: str = "하차", top: int = 3
    ) -> list[tuple[int, float]]:
        vals = [(h, self.at(code, day_type, h, kind)) for h in range(24)]
        return sorted(vals, key=lambda x: -x[1])[:top]


@lru_cache(maxsize=1)
def get_demand() -> DemandProfile:
    """캐시가 없으면 즉석에서 만든다."""
    if not CACHE_PATH.exists():
        build_profile()
    df = pd.read_csv(CACHE_PATH, encoding="utf-8-sig")
    table = {
        (int(r.역번호), str(r.요일유형), int(r.시), str(r.구분)): float(r.일평균인원)
        for r in df.itertuples(index=False)
    }
    daily = (
        df.groupby(["역번호", "요일유형", "구분"])["일평균인원"].sum().to_dict()
    )
    daily_total = {(int(k[0]), str(k[1]), str(k[2])): float(v) for k, v in daily.items()}
    year = int(df["연도"].iloc[0])
    return DemandProfile(table=table, year=year, daily_total=daily_total)
