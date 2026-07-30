# -*- coding: utf-8 -*-
"""엔진 운영 파라미터.

원칙: 발제 데이터로 뒷받침되는 값, 짐캐리 실제 운영 조건, 우리가 세운 가정을
섞지 않는다. 각 상수에 [데이터] / [운영조건] / [가정] 표기를 달고,
[가정]에는 근거를 남긴다. "이 숫자 어디서 나왔냐"에 이 파일 하나로 답한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from enum import Enum

# ══════════════════════════════════════════════════════════════════
# 짐 규격과 무게
# ══════════════════════════════════════════════════════════════════


class LuggageSize(str, Enum):
    """짐 크기. 보관함 규격명(소/중/대/특대)은 #4.1 원본 컬럼명과 맞춘다.

    [가정] 인치 구간은 시중 캐리어 표준 규격.
    """

    CABIN = "기내용"      # 20인치 이하
    MEDIUM = "중형"       # 24인치
    LARGE = "대형"        # 26~28인치
    OVERSIZE = "특대형"   # 28인치 초과 · 골프백 · 유모차


#: 짐 크기 → 들어갈 수 있는 최소 보관함 규격 (#4.1 컬럼명 기준)
MIN_LOCKER_SIZE: dict[LuggageSize, str] = {
    LuggageSize.CABIN: "소형",
    LuggageSize.MEDIUM: "중형",
    LuggageSize.LARGE: "대형",
    LuggageSize.OVERSIZE: "특대형",
}

#: [가정] 크기별 표준 무게(kg). 사용자가 무게를 입력하지 않았을 때의 기본값.
DEFAULT_WEIGHT_KG: dict[LuggageSize, float] = {
    LuggageSize.CABIN: 8.0,
    LuggageSize.MEDIUM: 15.0,
    LuggageSize.LARGE: 20.0,
    LuggageSize.OVERSIZE: 25.0,
}

#: [가정] 이 무게를 넘으면 계단·환승 부담이 급격히 커진다.
#: 항공 위탁수하물 기본 허용(23kg)을 경계로 잡았다.
HEAVY_THRESHOLD_KG = 23.0
#: [가정] 무게 1kg당 동반이동 부담 가산율. 기준 15kg 대비 초과분에 적용.
WEIGHT_BURDEN_PER_KG = 0.020
WEIGHT_BURDEN_BASELINE_KG = 15.0


class Preference(str, Enum):
    """사용자가 원하는 상황. 실행 가능성 필터 이전에 후보군을 좁힌다."""

    STORE = "보관"      # 짐을 맡기고 몸만 이동
    DELIVER = "배송"    # 목적지로 짐을 보냄
    ANY = "무관"        # 엔진이 알아서 최선을 고름


# ══════════════════════════════════════════════════════════════════
# 짐캐리 — 오프라인 매장 (짐보관 · 짐배송 접수)
# ══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class StoreSpec:
    name: str
    lat: float
    lon: float
    #: 연결 도시철도역. 그 역의 물품보관함이 이 지점에서 접근 가능한 선택지가 된다.
    anchor_station: str | None
    #: 매장에서 연결역까지 실제 소요(분). 직결이면 0.
    #: 직선거리로 재면 경전철·셔틀 구간을 도보로 오인한다.
    anchor_access_min: float
    source: str


#: [운영조건] 짐캐리 오프라인 매장 5곳. 짐 보관과 배송 접수가 되는 지점.
#: 배송은 임의 OD가 아니라 이 매장을 한쪽 끝에 두는 상품이다.
STORE_SPECS: dict[str, StoreSpec] = {
    "부산역": StoreSpec(
        "부산역", 35.11522, 129.03970, "부산", 0.0,
        "[데이터] #1 역사 마스터 좌표. 역사 직결.",
    ),
    "김해공항 국내선": StoreSpec(
        "김해공항 국내선", 35.17170, 128.94900, "사상", 18.0,
        "[가정] 국내선 청사 좌표. 도시철도 연결은 경전철 환승역인 2호선 사상, 약 18분.",
    ),
    "김해공항 국제선": StoreSpec(
        "김해공항 국제선", 35.17950, 128.93820, "사상", 20.0,
        "[가정] 국제선 청사 좌표. 경전철 경유 2호선 사상, 약 20분.",
    ),
    "부산항 국제여객터미널": StoreSpec(
        "부산항 국제여객터미널", 35.11500, 129.04990, "초량", 12.0,
        "[가정] 터미널 좌표. 최근접 도시철도역 1호선 초량, 도보·셔틀 약 12분.",
    ),
    "BEXCO": StoreSpec(
        "BEXCO", 35.16900, 129.13480, "벡스코", 0.0,
        "[가정] 벡스코역(2호선) 직결. 좌표는 연결역 기준.",
    ),
}

STORES: tuple[str, ...] = tuple(STORE_SPECS)


# ══════════════════════════════════════════════════════════════════
# 짐캐리 — 무인보관함
# ══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ZimLockerSpec:
    name: str
    detail: str
    slots: int
    lat: float
    lon: float
    anchor_station: str
    anchor_access_min: float
    source: str


#: [운영조건] 짐캐리 무인보관함 3곳. 규격은 소·중·대만 있고 특대형이 없다.
#: 좌표는 연결역 기준 근사이며, 정확한 위경도는 확인이 필요하다(아래 SOURCE 참조).
ZIM_LOCKER_SPECS: dict[str, ZimLockerSpec] = {
    "씨클라우드호텔": ZimLockerSpec(
        "씨클라우드호텔", "1층 로비", 16, 35.15850, 129.16040, "해운대", 8.0,
        "[운영조건] 설치 대수 16개. [가정·확인필요] 좌표는 해운대해수욕장 앞 기준 근사.",
    ),
    "롯데면세점 부산점": ZimLockerSpec(
        "롯데면세점 부산점", "8층 안내데스크 옆", 25, 35.15600, 129.05960, "서면", 5.0,
        "[운영조건] 설치 대수 25개. [가정·확인필요] 좌표는 서면 롯데백화점 부산본점 기준 근사.",
    ),
    "KT&G 상상마당 부산": ZimLockerSpec(
        "KT&G 상상마당 부산", "1층", 27, 35.15320, 129.06180, "전포", 6.0,
        "[운영조건] 설치 대수 27개. [가정·확인필요] 좌표는 서면·전포 일대 기준 근사.",
    ),
}

ZIM_LOCKERS: tuple[str, ...] = tuple(ZIM_LOCKER_SPECS)

#: [운영조건] 무인보관함 규격. 특대형이 없다 — 특대형 짐은 이 선택지를 못 쓴다.
ZIM_LOCKER_SIZES: tuple[str, ...] = ("소형", "중형", "대형")

#: [운영조건] 무인보관함 요금. 기본 4시간 + 이후 12시간 단위 반복 과금.
#: 값은 (기본 4시간 요금, 추가 12시간당 요금).
ZIM_LOCKER_PRICE: dict[str, tuple[int, int]] = {
    "소형": (2000, 2000),
    "중형": (3000, 3000),
    "대형": (4000, 4000),
}
ZIM_LOCKER_BASE_HOURS = 4
ZIM_LOCKER_EXTRA_BLOCK_HOURS = 12

#: [가정] 무인보관함이 3곳뿐이라 현재 위치에서 너무 멀면 실질적 선택지가 아니다.
#: 이 거리를 넘으면 후보에서 제외한다.
ZIM_LOCKER_MAX_DETOUR_KM = 12.0


# ══════════════════════════════════════════════════════════════════
# 짐캐리 — 배송 구간과 접수 마감
# ══════════════════════════════════════════════════════════════════


class SpotKind(str, Enum):
    """배송 구간 판정에 쓰이는 지점 유형."""

    STORE = "매장"            # 역·공항·터미널·BEXCO 오프라인 매장
    ZIM_LOCKER = "무인보관함"  # 짐캐리 무인보관함
    LODGING = "숙소"
    OTHER = "역·관광지"       # 도시철도역·관광지 등. 배송 구간의 끝점이 될 수 없다.


#: [운영조건] 허용 배송 구간. (출발 유형, 도착 유형) 집합.
#:   역/공항 → 숙소·보관함  |  숙소·보관함 → 역/공항  |  숙소·보관함 → 숙소
#: 매장→매장, 보관함→보관함은 상품이 없다.
ALLOWED_SEGMENTS: frozenset[tuple[SpotKind, SpotKind]] = frozenset({
    (SpotKind.STORE, SpotKind.LODGING),
    (SpotKind.STORE, SpotKind.ZIM_LOCKER),
    (SpotKind.LODGING, SpotKind.STORE),
    (SpotKind.ZIM_LOCKER, SpotKind.STORE),
    (SpotKind.LODGING, SpotKind.LODGING),
    (SpotKind.ZIM_LOCKER, SpotKind.LODGING),
})


class Channel(str, Enum):
    ONLINE = "온라인"
    OFFLINE = "매장방문"


#: [운영조건] 당일 접수 마감. 채널에 따라 다르다.
#:   온라인 당일 예약 신청 — 오전 11시까지
#:   매장 방문 접수       — 오후 3시까지
#: 매장에 서 있는 사람은 15시까지, 숙소에서 신청하는 사람은 11시까지가 된다.
CUTOFF: dict[Channel, time] = {
    Channel.ONLINE: time(11, 0),
    Channel.OFFLINE: time(15, 0),
}

#: [운영조건] 매장 영업시간. 이 시간 밖에는 매장 접수가 불가능하다.
STORE_OPEN = time(9, 0)
STORE_CLOSE = time(19, 0)

#: [가정] 매장 카운터 접수 처리 소요(분).
DELIVERY_INTAKE_MINUTES = 15

#: [가정] 배송 도착 보장 시간대. 짐캐리 공표 값이 확인되면 교체할 자리다.
DELIVERY_ARRIVE_FROM = time(18, 0)
DELIVERY_ARRIVE_UNTIL = time(21, 0)

#: [가정] 짐캐리 배송 요금. 개당 기본 + 특대 할증.
DELIVERY_BASE_FARE = 15000
DELIVERY_OVERSIZE_SURCHARGE = 5000


# ══════════════════════════════════════════════════════════════════
# 역사 물품보관함 (#4.1)
# ══════════════════════════════════════════════════════════════════

#: [데이터] #4.1 이용요금 컬럼을 역별로 파싱해 쓴다(운영사 3사 요금 상이).
#: 아래는 운영사 미상일 때의 폴백. 3시간당 원.
LOCKER_PRICE_FALLBACK: dict[str, int] = {
    "소형": 2000, "중형": 3000, "대형": 4000, "특대형": 6000,
}
LOCKER_BILLING_UNIT_HOURS = 3   # [데이터] '(3시간당)'

#: [가정] 도시철도 운영시간. 보관함은 역사 개방 시간 내에서만 쓸 수 있다.
STATION_OPEN = time(5, 0)
STATION_CLOSE = time(23, 59)
#: [가정] 막차 기준 회수 마감. 이후는 익일 이월이라 당일 옵션에서 제외.
LOCKER_RETRIEVE_DEADLINE = time(23, 30)


# ══════════════════════════════════════════════════════════════════
# B2B 전용 — 수요·공급 미스매치 추정
# ══════════════════════════════════════════════════════════════════
#
# 아래 값들은 B2C 추천 경로에서 쓰지 않는다.
# 실시간 점유 API가 없는 상태에서 이용자에게 "지금 빈 칸이 없을 확률"을
# 제시하는 것은 근거가 없어서, 포화확률은 실행 가능성 필터에서 제외했다.
# 대신 역 단위 공급 부족을 집계하는 B2B 랭킹에만 남긴다.

CALIBRATION_ANCHOR_STATION = "부산"
CALIBRATION_PEAK_OCCUPANCY = 0.70
LOCKER_MEAN_STORAGE_HOURS = 6

#: [가정] 보관함 1칸의 하루 회전 횟수. B2B 매출 추정 전용.
LOCKER_TURNOVER_PER_DAY = 2.2

#: [가정] 관광객 짐 크기 분포. 규격별 수요를 쪼갤 때 쓴다.
SIZE_MIX: dict[LuggageSize, float] = {
    LuggageSize.CABIN: 0.30,
    LuggageSize.MEDIUM: 0.32,
    LuggageSize.LARGE: 0.26,
    LuggageSize.OVERSIZE: 0.12,
}


# ══════════════════════════════════════════════════════════════════
# #5 주요거점·권역별 짐배송 이동 흐름 — B2B 수요 가중치
# ══════════════════════════════════════════════════════════════════
#
# 이 매트릭스는 실행 가능성 필터의 하드 제약이 아니다.
# '기타' 권역에도 5~9%의 실제 배송 실적이 잡혀 있으므로, 권역 밖이라고
# 배송이 불가능한 게 아니라 수요 분포가 그렇다는 뜻으로 읽어야 한다.
# 따라서 여기서는 B2B 수요 가중치로만 쓴다.


class Direction(str, Enum):
    INBOUND = "거점→숙소"   # 짐 배송 (입고)
    OUTBOUND = "숙소→거점"  # 짐 픽업 (출고)


#: [데이터] #5 방향별요약.
DIRECTION_SHARE: dict[Direction, dict[str, float]] = {
    Direction.INBOUND: {"전체": 0.570, "내국인": 0.829, "외국인": 0.171},
    Direction.OUTBOUND: {"전체": 0.430, "내국인": 0.903, "외국인": 0.097},
}

ZONES: tuple[str, ...] = (
    "해운대·기장", "광안리", "서면·부산진구", "원도심(동구·중구)",
)
OTHER_ZONE = "기타"

#: [데이터] #5 ①②시트. P(권역 | 거점, 방향). 행 합계 = 1.
COVERAGE_MATRIX: dict[Direction, dict[str, dict[str, float]]] = {
    Direction.INBOUND: {
        "부산역": {
            "해운대·기장": 0.640, "광안리": 0.236, "서면·부산진구": 0.051,
            "원도심(동구·중구)": 0.018, OTHER_ZONE: 0.055,
        },
        "김해국제공항": {
            "해운대·기장": 0.383, "광안리": 0.105, "서면·부산진구": 0.205,
            "원도심(동구·중구)": 0.248, OTHER_ZONE: 0.059,
        },
        "부산항 국제여객터미널": {
            "해운대·기장": 0.273, "광안리": 0.136, "서면·부산진구": 0.182,
            "원도심(동구·중구)": 0.318, OTHER_ZONE: 0.091,
        },
    },
    Direction.OUTBOUND: {
        "부산역": {
            "해운대·기장": 0.665, "광안리": 0.228, "서면·부산진구": 0.049,
            "원도심(동구·중구)": 0.013, OTHER_ZONE: 0.045,
        },
        "김해국제공항": {
            "해운대·기장": 0.490, "광안리": 0.156, "서면·부산진구": 0.166,
            "원도심(동구·중구)": 0.136, OTHER_ZONE: 0.052,
        },
        "부산항 국제여객터미널": {
            "해운대·기장": 0.446, "광안리": 0.046, "서면·부산진구": 0.262,
            "원도심(동구·중구)": 0.200, OTHER_ZONE: 0.046,
        },
    },
}

#: [데이터] #5. P(거점 | 방향).
HUB_SHARE: dict[Direction, dict[str, float]] = {
    Direction.INBOUND: {"부산역": 0.821, "김해국제공항": 0.176, "부산항 국제여객터미널": 0.003},
    Direction.OUTBOUND: {"부산역": 0.829, "김해국제공항": 0.161, "부산항 국제여객터미널": 0.010},
}


@dataclass(frozen=True)
class ZoneSpec:
    name: str
    anchor_station: str
    radius_km: float
    source: str


#: [데이터] 대표역은 #5 시트 헤더 표기. [가정] 반경은 권역 라벨링용.
ZONE_SPECS: dict[str, ZoneSpec] = {
    "해운대·기장": ZoneSpec("해운대·기장", "해운대", 6.0, "#5 헤더 '해운대역·기장역'"),
    "광안리": ZoneSpec("광안리", "광안", 2.5, "#5 헤더 '광안역'"),
    "서면·부산진구": ZoneSpec("서면·부산진구", "서면", 3.0, "#5 헤더 '서면역'"),
    "원도심(동구·중구)": ZoneSpec("원도심(동구·중구)", "중앙", 2.5, "#5 헤더 '중앙역'"),
}


# ══════════════════════════════════════════════════════════════════
# 비용함수 가중치
# ══════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CostWeights:
    """모든 항을 원(KRW)으로 환산해 더한다. 단위를 통일해야 비교가 된다."""

    #: [가정] 관광객의 시간 기회비용(원/시간).
    time_value_per_hour: int = 12000
    #: [가정] 캐리어 동반 1분당 추가 부담(원). 난이도·무게 계수와 곱해진다.
    haul_burden_per_min: int = 250
    #: [가정] 계단 구간 1개소 통과 부담(원). E/L 부재 시 발생.
    stair_segment_penalty: int = 3000
    #: [가정] 곡선 승강장·광폭 연단 통과 부담(원).
    curved_platform_penalty: int = 1500
    #: [가정] 옵션이 현장에서 실패했을 때의 복구 비용(원).
    failure_recovery_cost: int = 20000
    #: [가정] 짐과 떨어져 있는 시간에 대한 불안 비용(원/시간).
    separation_anxiety_per_hour: int = 1500


DEFAULT_WEIGHTS = CostWeights()

#: [가정] 캐리어 동반 도보 속도(km/h). 일반 보행 4.5 대비 감속.
HAUL_WALK_KMPH = 3.2

#: [가정] 도시철도 표정속도(km/h)와 승하차·대기 오버헤드(분).
#: 먼 지점은 도보가 아니라 대중교통으로 접근한다고 봐야 판정이 맞는다.
TRANSIT_KMPH = 20.0
TRANSIT_OVERHEAD_MIN = 12.0

#: 역사 물품보관함 후보로 삼을 역의 범위 — 현재 위치에서 도보 몇 분까지인가.
#: 기준을 '역에서 1정거장'이 아니라 '현재 위치에서 도보'로 잡는다. 이용자는
#: 역에 서 있는 게 아니라 임의의 지점에 서 있고, 짐을 끌고 갈 수 있는 거리가
#: 실제 제약이기 때문이다.
LOCKER_SEARCH_WALK_MINUTES = 10

#: 반경 환산 기준(m/분). 지도·부동산에서 쓰는 관용 '도보 1분 = 80m'.
#: 반경 정의와 비용 계산을 일부러 분리했다. 캐리어 실제 속도(3.2km/h = 53m/분)로
#: 반경을 잡으면 10분이 533m가 되는데, 부산 도시철도 역간 거리가 약 1km라
#: 사실상 '지금 서 있는 역 하나'만 남아 '인근 역'이라는 말이 무의미해진다.
#: 그래서 후보를 고르는 반경은 관용 기준(800m), 그 거리를 실제로 끌고 가는 데
#: 드는 시간·부담은 HAUL_WALK_KMPH(3.2km/h)로 정직하게 계산한다.
WALK_RADIUS_METERS_PER_MIN = 80

#: 매장 연결역처럼 도보가 아닌 연결(경전철·셔틀)은 명시된 소요시간으로 판정하되,
#: 이 시간을 넘으면 '인근'으로 보지 않는다.
LOCKER_SEARCH_MAX_ACCESS_MINUTES = 10
