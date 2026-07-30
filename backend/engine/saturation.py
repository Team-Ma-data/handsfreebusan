# -*- coding: utf-8 -*-
"""보관함 수요·공급 압력 — B2B 전용.

⚠ 이 모듈은 B2C 추천 경로에서 쓰지 않는다.
   실시간 잔여 칸수 API가 없는 상태에서 이용자에게 "지금 가면 빈 칸이 없을
   확률 86%"라고 제시할 근거가 없다. 그래서 실행 가능성 필터에서 포화확률을
   빼고, 역 단위 공급 부족을 집계하는 B2B 랭킹에만 남겼다.

   역설적으로 이 부재가 협상 카드다. 아래 랭킹이 "공사가 우리에게 실시간
   점유 데이터를 열어 줘야 하는 이유"를 숫자로 보여 준다.

전 역에 대해 돌리면 그대로 '수요 공백 지도'가 된다.

모델
  보관함은 c개의 창구에 대기열이 없는 손실 시스템이다. 도착한 사람은 빈 칸이
  없으면 그냥 떠난다(= 배송으로 전환하거나 짐을 끌고 간다). 이 구조는 Erlang-B
  손실확률과 정확히 같은 형태라, 임의의 로지스틱 곡선을 쓰는 대신 Erlang-B를 쓴다.

    제공부하 a(h) = 직전 T시간 동안의 누적 도착량      [단위: Erlang = 평균 점유칸수]
    포화확률     = B(c, a)

  a 를 λ(h)×T 가 아니라 시간별 도착을 실제로 누적해 만든다. 보관함은 아침에
  차서 저녁까지 안 빠지는 물건이라, 시간대별 편차를 평탄화하면 피크가 사라진다.

캘리브레이션
  '하차 인원 중 몇 %가 보관함을 시도하는가'는 아무도 모른다. 지어내는 대신
  부산역 설치 칸수(135칸)를 관측치로 삼아 역산한다. 절대 수준만 이 앵커에서 오고,
  역별·시간대별 상대 분포는 전부 #2 승하차에서 온다. 서비스가 돌면 앵커가
  실측 전환 로그로 교체되는 것이지 구조가 바뀌지 않는다.

규격 중첩
  큰 칸은 작은 짐을 수용한다. 따라서 규격 z의 가용 용량은 'z 이상 규격의 칸 수',
  경쟁 수요는 'z 이상 규격의 짐'이다. 특대형은 특대형 칸만 놓고 다투고,
  대형은 대형+특대형 칸을 대형+특대형 짐과 나눠 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from . import config
from .config import LuggageSize
from .demand import SATURDAY, SUNDAY, WEEKDAY, get_demand  # noqa: F401
from .registry import LOCKER_SIZES, LockerSupply, get_registry

_SIZE_RANK = {s: i for i, s in enumerate(LOCKER_SIZES)}

#: B2B 랭킹에서 '공급 부족'으로 분류하는 기준. 추천 경로와 무관하다.
PRESSURE_HIGH = 0.70
PRESSURE_WATCH = 0.40


def day_type_of(dt: datetime) -> str:
    """datetime → 수요 프로파일의 요일유형."""
    wd = dt.weekday()  # 월=0
    if wd == 5:
        return SATURDAY
    if wd == 6:
        return SUNDAY
    return WEEKDAY


def erlang_b(servers: int, load: float) -> float:
    """B(c, a). 반복식이라 계승 오버플로가 없다."""
    if servers <= 0:
        return 1.0
    if load <= 0:
        return 0.0
    b = 1.0
    for n in range(1, servers + 1):
        b = (load * b) / (n + load * b)
    return min(max(b, 0.0), 1.0)


@dataclass(frozen=True)
class SaturationEstimate:
    station_code: int
    size: LuggageSize
    hour: int
    day_type: str
    capacity: int            # 해당 규격 이상 칸 수
    arrival_rate: float      # 개/시간 (해당 규격 이상 짐)
    offered_load: float      # Erlang
    probability: float       # 포화확률
    alighting: float         # 근거가 된 하차 인원

    @property
    def high_pressure(self) -> bool:
        return self.probability >= PRESSURE_HIGH

    @property
    def watch(self) -> bool:
        return self.probability >= PRESSURE_WATCH

    def as_evidence(self) -> dict:
        return {
            "포화확률": round(self.probability, 3),
            "가용칸수": self.capacity,
            "시간당도착": round(self.arrival_rate, 2),
            "제공부하(Erlang)": round(self.offered_load, 2),
            "근거 하차인원": round(self.alighting),
            "기준": f"{self.day_type} {self.hour:02d}시",
        }


def _size_mix_at_or_above(size: LuggageSize) -> float:
    """size 이상 규격 짐이 전체에서 차지하는 비율."""
    order = list(LuggageSize)
    floor = order.index(size)
    return sum(share for s, share in config.SIZE_MIX.items() if order.index(s) >= floor)


@lru_cache(maxsize=1)
def attempt_rate() -> float:
    """하차 1명당 보관함 시도 확률. 부산역 설치 칸수를 앵커로 역산한다.

    시도율 1.0 을 가정했을 때 앵커 역의 피크 점유량을 구하고,
    그 점유량이 실제 칸수의 CALIBRATION_PEAK_OCCUPANCY 가 되도록 스케일을 잡는다.
    """
    reg = get_registry()
    dem = get_demand()
    code = reg.resolve(config.CALIBRATION_ANCHOR_STATION)
    supply = reg.locker_complex(code)
    if code is None or supply is None:
        raise RuntimeError(f"캘리브레이션 앵커 역을 찾을 수 없습니다: {config.CALIBRATION_ANCHOR_STATION}")

    capacity = sum(supply.counts.values())
    window = config.LOCKER_MEAN_STORAGE_HOURS
    unit_peak = max(
        sum(dem.at(code, WEEKDAY, h - i, "하차") for i in range(window))
        for h in range(24)
    )
    if unit_peak <= 0:
        raise RuntimeError("앵커 역의 하차 수요가 0입니다")
    return config.CALIBRATION_PEAK_OCCUPANCY * capacity / unit_peak


def arrival_rate(code: int, size: LuggageSize, hour: int, day_type: str) -> tuple[float, float]:
    """(해당 규격 이상 짐의 시간당 보관 시도 건수, 근거 하차 인원)."""
    alight = get_demand().at(code, day_type, hour, "하차")
    return alight * attempt_rate() * _size_mix_at_or_above(size), alight


def offered_load(code: int, size: LuggageSize, hour: int, day_type: str) -> float:
    """직전 T시간 누적 도착량 = 평균 점유 칸수(Erlang)."""
    return sum(
        arrival_rate(code, size, hour - i, day_type)[0]
        for i in range(config.LOCKER_MEAN_STORAGE_HOURS)
    )


def estimate(
    code: int,
    size: LuggageSize,
    when: datetime,
    supply: LockerSupply | None = None,
) -> SaturationEstimate:
    """한 역·한 규격·한 시각의 포화확률."""
    reg = get_registry()
    if supply is None:
        supply = reg.locker_complex(code)

    min_size = config.MIN_LOCKER_SIZE[size]
    capacity = supply.capacity_for(min_size) if supply else 0
    day_type = day_type_of(when)
    hour = when.hour

    rate, alight = arrival_rate(code, size, hour, day_type)
    load = offered_load(code, size, hour, day_type)
    prob = 1.0 if capacity == 0 else erlang_b(capacity, load)

    return SaturationEstimate(
        station_code=code,
        size=size,
        hour=hour,
        day_type=day_type,
        capacity=capacity,
        arrival_rate=rate,
        offered_load=load,
        probability=prob,
        alighting=alight,
    )


# ══════════════════════════════════════════════════════════════════
# B2B: 같은 계산을 전 역으로 확장한 미스매치 랭킹
# ══════════════════════════════════════════════════════════════════


def leisure_index(code: int) -> float:
    """주말 하차 / 주중 하차. 관광·여가 성격이 강한 역일수록 크다.

    포화확률 계산에는 넣지 않는다. 짐 보관 수요와 여가 통행은 다른 축이고
    (토성역은 여가지수가 낮지만 공급 대비 하차가 가장 빡빡한 역이다),
    섞으면 어느 쪽 신호인지 알 수 없게 된다. B2B 판단 보조 지표로만 쓴다.
    """
    dem = get_demand()
    weekday = dem.daily(code, WEEKDAY, "하차")
    if weekday <= 0:
        return 0.0
    weekend = (dem.daily(code, SATURDAY, "하차") + dem.daily(code, SUNDAY, "하차")) / 2
    return weekend / weekday


@dataclass(frozen=True)
class MismatchRow:
    station_code: int
    label: str
    size: LuggageSize
    capacity: int
    peak_hour: int
    peak_probability: float
    daily_alighting: float
    #: 1칸이 하루에 받아내야 하는 하차 인원. 클수록 공급이 모자라다.
    persons_per_slot: float
    #: 포화로 돌려보낸 것으로 추정되는 하루 건수.
    unmet_per_day: float
    #: 주말/주중 하차 비. 여가 성격 보조 지표.
    leisure_index: float = 0.0

    def as_dict(self) -> dict:
        return {
            "역": self.label,
            "규격": self.size.value,
            "가용칸수": self.capacity,
            "피크시": f"{self.peak_hour:02d}시",
            "피크포화확률": round(self.peak_probability, 3),
            "일하차": round(self.daily_alighting),
            "1칸당인원": round(self.persons_per_slot, 1),
            "일미충족건수": round(self.unmet_per_day, 1),
            "여가지수": round(self.leisure_index, 2),
        }


def mismatch_ranking(
    size: LuggageSize = LuggageSize.OVERSIZE,
    day_type: str = WEEKDAY,
    include_no_locker: bool = True,
) -> list[MismatchRow]:
    """전 역의 [수요 ÷ 공급] 미스매치 랭킹.

    실사용 전환 로그가 쌓이기 전까지 이 랭킹이 '보관하고 싶었는데 못 한 수요'의
    시뮬레이션 버전 역할을 한다.
    """
    reg = get_registry()
    dem = get_demand()
    min_size = config.MIN_LOCKER_SIZE[size]

    rows: list[MismatchRow] = []
    seen_complex: set[int] = set()

    for code in reg.stations:
        primary = min(reg.complex_codes(code))
        if primary in seen_complex:
            continue
        seen_complex.add(primary)

        supply = reg.locker_complex(primary)
        capacity = supply.capacity_for(min_size) if supply else 0
        if capacity == 0 and not include_no_locker:
            continue

        daily = dem.daily(primary, day_type, "하차")
        if daily <= 0:
            continue

        best_hour, best_prob, best_rank, unmet = 0, 0.0, -1.0, 0.0
        for hour in range(24):
            rate, _ = arrival_rate(primary, size, hour, day_type)
            load = offered_load(primary, size, hour, day_type)
            prob = 1.0 if capacity == 0 else erlang_b(capacity, load)
            unmet += rate * prob
            # 칸이 0이면 확률이 전 시간대 1.0이라 최댓값으로는 피크를 못 찾는다.
            # 실제로 사람이 가장 많이 몰리는 시각을 함께 봐야 한다.
            rank = prob * 1000 + rate
            if rank > best_rank:
                best_hour, best_prob, best_rank = hour, prob, rank

        rows.append(
            MismatchRow(
                station_code=primary,
                label=reg.station(primary).label,
                size=size,
                capacity=capacity,
                peak_hour=best_hour,
                peak_probability=best_prob,
                daily_alighting=daily,
                persons_per_slot=daily / capacity if capacity else float("inf"),
                unmet_per_day=unmet,
                leisure_index=leisure_index(primary),
            )
        )

    return sorted(rows, key=lambda r: (-r.unmet_per_day, -r.persons_per_slot))


@lru_cache(maxsize=8)
def cached_mismatch(size: LuggageSize, day_type: str) -> tuple[MismatchRow, ...]:
    return tuple(mismatch_ranking(size, day_type))
