# -*- coding: utf-8 -*-
"""엔진 도메인 모델.

사용자 입력(LuggageRequest) → 옵션 후보(Option) → 판정(Decision).

탈락 사유(RejectReason)를 문자열이 아닌 코드로 다루는 게 핵심이다.
이 코드가 그대로 B2B 미충족수요 로그의 집계 축이 되기 때문이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from .config import (
    DEFAULT_WEIGHT_KG,
    Channel,
    LuggageSize,
    Preference,
    SpotKind,
)


# ══════════════════════════════════════════════════════════════════
# 장소
# ══════════════════════════════════════════════════════════════════


class PlaceKind(str, Enum):
    """화면 표기용 장소 종류."""

    STORE = "짐캐리 매장"
    ZIM_LOCKER = "짐캐리 무인보관함"
    LODGING = "숙소"
    STATION = "역"
    POI = "관광지"


#: 배송 구간 판정은 지점 유형으로만 한다. 역·관광지는 배송 구간의 끝점이 못 된다.
_SPOT_OF: dict[PlaceKind, SpotKind] = {
    PlaceKind.STORE: SpotKind.STORE,
    PlaceKind.ZIM_LOCKER: SpotKind.ZIM_LOCKER,
    PlaceKind.LODGING: SpotKind.LODGING,
    PlaceKind.STATION: SpotKind.OTHER,
    PlaceKind.POI: SpotKind.OTHER,
}


@dataclass(frozen=True)
class Place:
    kind: PlaceKind
    name: str
    lat: float
    lon: float
    #: 접근 가능한 도시철도역. 역사 물품보관함 후보를 여는 열쇠다.
    station_code: int | None = None
    #: 이 장소에서 station_code 역까지 실제 소요(분).
    #: 공항→사상처럼 직선거리로 재면 안 되는 연결에 쓴다.
    station_access_min: float = 0.0
    #: 짐캐리 매장명 / 무인보관함명
    store_name: str | None = None
    zim_locker_name: str | None = None
    #: #5 권역 라벨. 하드 제약이 아니라 B2B 수요 가중치용.
    zone: str | None = None

    @property
    def spot(self) -> SpotKind:
        return _SPOT_OF[self.kind]

    @property
    def label(self) -> str:
        return f"{self.name}({self.kind.value})"


# ══════════════════════════════════════════════════════════════════
# 사용자 입력
# ══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class LuggageItem:
    size: LuggageSize
    qty: int = 1
    #: 개당 무게(kg). 미입력이면 크기별 표준값을 쓴다.
    weight_kg: float | None = None

    @property
    def effective_weight(self) -> float:
        return self.weight_kg if self.weight_kg is not None else DEFAULT_WEIGHT_KG[self.size]


@dataclass
class LuggageRequest:
    """사용자 입력 한 건.

    필수: 현재 위치(origin), 시간(at), 원하는 상황(preference), 짐 크기·무게(items)
    배송을 원하면 목적지(destination)가 함께 온다.
    """

    at: datetime
    origin: Place
    items: list[LuggageItem]
    preference: Preference = Preference.ANY
    destination: Place | None = None

    #: 짐을 다시 손에 넣어야 하는 시각. 보관이면 회수 시각, 배송이면 수령 마감.
    need_by: datetime | None = None
    #: 이 시각 이전에는 짐을 받을 수 없다. 숙소 체크인 시각 등.
    receivable_from: datetime | None = None

    #: 짐 없이 다닐 동안 실제로 들를 역들(선택). 회수 우회 계산에 쓴다.
    itinerary: list[int] = field(default_factory=list)
    foreign: bool = False
    party_size: int = 1

    # ── 파생 ─────────────────────────────────────────────────────
    @property
    def total_qty(self) -> int:
        return sum(i.qty for i in self.items)

    @property
    def max_size(self) -> LuggageSize:
        """가장 까다로운 짐이 옵션 전체의 실행 가능성을 결정한다."""
        order = list(LuggageSize)
        return max((i.size for i in self.items), key=order.index)

    @property
    def total_weight(self) -> float:
        return sum(i.effective_weight * i.qty for i in self.items)

    @property
    def heaviest(self) -> float:
        return max((i.effective_weight for i in self.items), default=0.0)

    @property
    def storage_hours(self) -> float:
        """보관 예정 시간. need_by 가 없으면 기본 4시간(무인보관함 기본 이용 시간)."""
        if self.need_by is None:
            return 4.0
        return max((self.need_by - self.at).total_seconds() / 3600, 0.5)

    @property
    def channel(self) -> Channel:
        """접수 채널. 짐캐리 매장에 서 있으면 매장 방문, 아니면 온라인 신청.

        마감 시각이 채널마다 다르므로(온라인 11시 / 매장 15시) 이 판정이
        배송 가능 여부를 직접 가른다.
        """
        return (
            Channel.OFFLINE
            if self.origin.spot is SpotKind.STORE
            else Channel.ONLINE
        )

    @property
    def wants_storage(self) -> bool:
        return self.preference in (Preference.STORE, Preference.ANY)

    @property
    def wants_delivery(self) -> bool:
        return self.preference in (Preference.DELIVER, Preference.ANY)


# ══════════════════════════════════════════════════════════════════
# 옵션과 탈락 사유
# ══════════════════════════════════════════════════════════════════


class OptionKind(str, Enum):
    STATION_LOCKER = "역사 보관함"
    ZIM_LOCKER = "짐캐리 무인보관함"
    DELIVERY = "짐캐리 배송"
    HAUL = "동반이동"
    SCHEDULED_DELIVERY = "예약배송"


class RejectReason(str, Enum):
    """탈락 사유 코드. B2B 로그의 집계 축이므로 값을 함부로 바꾸지 않는다."""

    # ── 배송 ──
    DLV_SEGMENT_NOT_OFFERED = "구간 불가: 짐캐리 배송 상품이 없는 구간"
    DLV_NO_DESTINATION = "구간 불가: 배송 목적지가 지정되지 않음"
    DLV_PAST_CUTOFF = "시간 불가: 당일 접수 마감 경과"
    DLV_STORE_CLOSED = "시간 불가: 매장 영업시간 밖"
    DLV_ARRIVAL_TOO_LATE = "도착 불가: 배송 도착이 필요 시각보다 늦음"
    DLV_ARRIVAL_TOO_EARLY = "도착 불가: 수령 가능 시각 이전에만 도착 가능"

    # ── 역사 물품보관함 ──
    LKR_NOT_A_STATION = "현재 위치에서 접근 가능한 도시철도역 없음"
    LKR_NO_LOCKER_AT_STATION = "해당 역에 물품보관함 없음"
    LKR_SIZE_UNAVAILABLE = "필요 규격 0칸 (물리적 불가)"
    LKR_STATION_CLOSED = "역사 운영시간·막차 밖"
    LKR_RETRIEVE_AFTER_DEADLINE = "회수 시각이 보관 마감 이후"

    # ── 짐캐리 무인보관함 ──
    ZIM_SIZE_UNAVAILABLE = "무인보관함에 해당 규격 없음 (특대형 미취급)"
    ZIM_TOO_FAR = "무인보관함이 현재 위치에서 지나치게 멂"
    ZIM_OVER_CAPACITY = "요청 수량이 설치 대수를 초과"


@dataclass
class CostBreakdown:
    """모든 항목을 원(KRW)으로 환산. 합계가 비교 기준이다."""

    money: float = 0.0      # 실제 지출
    time: float = 0.0       # 소요 시간의 기회비용
    burden: float = 0.0     # 캐리어 동반 신체 부담 (난이도 × 무게)
    risk: float = 0.0       # 실패확률 × 복구비용
    anxiety: float = 0.0    # 짐과 떨어져 있는 심리 비용

    @property
    def total(self) -> float:
        return self.money + self.time + self.burden + self.risk + self.anxiety

    def as_dict(self) -> dict[str, float]:
        return {
            "금액": round(self.money),
            "시간": round(self.time),
            "부담": round(self.burden),
            "리스크": round(self.risk),
            "불안": round(self.anxiety),
            "합계": round(self.total),
        }


@dataclass
class Option:
    kind: OptionKind
    label: str
    cost: CostBreakdown = field(default_factory=CostBreakdown)

    feasible: bool = True
    reject_reason: RejectReason | None = None
    reject_detail: str = ""

    #: 화면과 로그에 함께 실을 근거. 어떤 데이터로 이 판단을 했는지 남긴다.
    evidence: dict = field(default_factory=dict)

    out_of_pocket: int = 0
    duration_min: float = 0.0
    station_code: int | None = None
    zim_locker_name: str | None = None
    fallback_level: int = 0   # 0=1차 후보, 1~3=폴백 사다리 단계

    def reject(self, reason: RejectReason, detail: str = "") -> "Option":
        self.feasible = False
        self.reject_reason = reason
        self.reject_detail = detail
        return self


# ══════════════════════════════════════════════════════════════════
# 판정
# ══════════════════════════════════════════════════════════════════


@dataclass
class Decision:
    request: LuggageRequest
    recommended: Option | None
    alternatives: list[Option] = field(default_factory=list)
    rejected: list[Option] = field(default_factory=list)
    fallback_level: int = 0
    narrative: str = ""

    @property
    def resolved(self) -> bool:
        return self.recommended is not None

    def summary(self) -> str:
        if not self.resolved:
            return "제안 가능한 옵션 없음"
        r = self.recommended
        return f"{r.kind.value} · {r.label} · {r.out_of_pocket:,}원 · 비용지수 {r.cost.total:,.0f}"


def billing_units(hours: float, unit_hours: int) -> int:
    """단위 시간당 올림 과금."""
    units = int(hours // unit_hours) + (1 if hours % unit_hours > 0 else 0)
    return max(units, 1)
