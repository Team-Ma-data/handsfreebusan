# -*- coding: utf-8 -*-
"""장소 생성.

배송 가능 여부는 '좌표가 어느 권역에 드는가'가 아니라 '이 지점이 어떤 유형인가'로
갈린다. 짐캐리는 매장 5곳을 한쪽 끝에 두는 상품이기 때문이다.
권역(zone)은 하드 제약에서 빠지고 B2B 수요 가중치 라벨로만 남는다.
"""

from __future__ import annotations

from . import config
from .models import Place, PlaceKind
from .registry import get_registry, haversine_km


def station(name: str, line: int | None = None) -> Place:
    """도시철도역. 환승역은 대표 승강장 코드를 쓴다."""
    reg = get_registry()
    st = reg.get(name, line)
    if st is None:
        raise KeyError(f"역을 찾을 수 없습니다: {name} (호선={line})")
    return Place(
        kind=PlaceKind.STATION,
        name=st.name,
        lat=st.lat,
        lon=st.lon,
        station_code=st.code,
        zone=resolve_zone(st.lat, st.lon),
    )


def store(name: str) -> Place:
    """짐캐리 오프라인 매장. 배송 접수와 짐 보관이 되는 지점."""
    spec = config.STORE_SPECS.get(name)
    if spec is None:
        raise KeyError(f"짐캐리 매장이 아닙니다: {name} (가능: {', '.join(config.STORES)})")
    reg = get_registry()
    code = reg.resolve(spec.anchor_station) if spec.anchor_station else None
    return Place(
        kind=PlaceKind.STORE,
        name=spec.name,
        lat=spec.lat,
        lon=spec.lon,
        station_code=code,
        station_access_min=spec.anchor_access_min,
        store_name=spec.name,
        zone=resolve_zone(spec.lat, spec.lon),
    )


def zim_locker(name: str) -> Place:
    """짐캐리 무인보관함 지점."""
    spec = config.ZIM_LOCKER_SPECS.get(name)
    if spec is None:
        raise KeyError(
            f"짐캐리 무인보관함이 아닙니다: {name} (가능: {', '.join(config.ZIM_LOCKERS)})"
        )
    reg = get_registry()
    code = reg.resolve(spec.anchor_station)
    return Place(
        kind=PlaceKind.ZIM_LOCKER,
        name=spec.name,
        lat=spec.lat,
        lon=spec.lon,
        station_code=code,
        station_access_min=spec.anchor_access_min,
        zim_locker_name=spec.name,
        zone=resolve_zone(spec.lat, spec.lon),
    )


def lodging(name: str, lat: float, lon: float) -> Place:
    """숙소. 좌표로 최근접 역을 연결해 역사 보관함 후보를 열어 준다."""
    code, km = nearest_station(lat, lon)
    return Place(
        kind=PlaceKind.LODGING,
        name=name,
        lat=lat,
        lon=lon,
        station_code=code,
        station_access_min=km / config.HAUL_WALK_KMPH * 60,
        zone=resolve_zone(lat, lon),
    )


def lodging_near(name: str, station_name: str, line: int | None = None) -> Place:
    """대표역 좌표를 그대로 쓰는 숙소. 데모·시뮬레이션 편의용."""
    st = station(station_name, line)
    return Place(
        kind=PlaceKind.LODGING,
        name=name,
        lat=st.lat,
        lon=st.lon,
        station_code=st.station_code,
        zone=st.zone,
    )


def poi(name: str, lat: float, lon: float) -> Place:
    """관광지 등 일반 지점. 배송 구간의 끝점은 될 수 없다."""
    code, km = nearest_station(lat, lon)
    return Place(
        kind=PlaceKind.POI,
        name=name,
        lat=lat,
        lon=lon,
        station_code=code,
        station_access_min=km / config.HAUL_WALK_KMPH * 60,
        zone=resolve_zone(lat, lon),
    )


# ── 보조 ─────────────────────────────────────────────────────────


def resolve_zone(lat: float, lon: float) -> str:
    """좌표 → #5 권역 라벨. 어느 반경에도 안 들면 '기타'.

    배송 가능 여부를 가르지 않는다. '기타' 권역에도 실제 배송 실적이
    5~9% 잡혀 있어(#5), 권역 밖이 곧 서비스 불가는 아니다.
    """
    reg = get_registry()
    hits: list[tuple[float, str]] = []
    for zone_name, spec in config.ZONE_SPECS.items():
        anchor = reg.get(spec.anchor_station)
        if anchor is None:
            continue
        d = haversine_km(lat, lon, anchor.lat, anchor.lon)
        if d <= spec.radius_km:
            hits.append((d, zone_name))
    return min(hits)[1] if hits else config.OTHER_ZONE


def locker_candidate_stations(
    place: Place, minutes: float | None = None
) -> list[tuple[int, float]]:
    """역사 물품보관함 후보 역 — (역번호, 접근 소요분), 가까운 순.

    기준은 '역에서 몇 정거장'이 아니라 '현재 위치에서 도보 몇 분'이다.
    이용자는 역이 아니라 임의의 지점에 서 있고, 짐을 끌고 갈 수 있는 거리가
    실제 제약이기 때문이다.

    반경은 관용 기준(도보 1분 = 80m)으로 정하고, 돌려주는 소요시간은 캐리어를
    실제로 끌고 가는 속도(3.2km/h)로 계산한다. 둘을 분리한 이유는 config 주석 참조.

    매장 연결역처럼 도보가 아닌 연결(경전철·셔틀)은 직선거리로 재면 안 되므로
    Place 에 명시된 station_access_min 을 우선한다.
    """
    reg = get_registry()
    limit = config.LOCKER_SEARCH_WALK_MINUTES if minutes is None else minutes
    radius_km = limit * config.WALK_RADIUS_METERS_PER_MIN / 1000

    best: dict[int, float] = {}

    # 명시적 연결역 — 경전철·셔틀 등 도보가 아닌 경로
    if place.station_code is not None:
        primary = min(reg.complex_codes(place.station_code))
        if place.station_access_min <= config.LOCKER_SEARCH_MAX_ACCESS_MINUTES:
            best[primary] = place.station_access_min

    for code, st in reg.stations.items():
        primary = min(reg.complex_codes(code))
        km = haversine_km(place.lat, place.lon, st.lat, st.lon)
        if km > radius_km:
            continue
        haul_min = km / config.HAUL_WALK_KMPH * 60
        if primary not in best or haul_min < best[primary]:
            best[primary] = haul_min

    return sorted(best.items(), key=lambda x: x[1])


def nearest_station(lat: float, lon: float) -> tuple[int, float]:
    """좌표에서 가장 가까운 도시철도역 (역번호, 거리km)."""
    reg = get_registry()
    return min(
        ((c, haversine_km(lat, lon, s.lat, s.lon)) for c, s in reg.stations.items()),
        key=lambda x: x[1],
    )


def nearest_zim_lockers(lat: float, lon: float) -> list[tuple[str, float]]:
    """가까운 순서대로 짐캐리 무인보관함 (이름, 거리km)."""
    out = [
        (name, haversine_km(lat, lon, spec.lat, spec.lon))
        for name, spec in config.ZIM_LOCKER_SPECS.items()
    ]
    return sorted(out, key=lambda x: x[1])


def nearest_stores(lat: float, lon: float) -> list[tuple[str, float]]:
    """가까운 순서대로 짐캐리 매장 (이름, 거리km)."""
    out = [
        (name, haversine_km(lat, lon, spec.lat, spec.lon))
        for name, spec in config.STORE_SPECS.items()
    ]
    return sorted(out, key=lambda x: x[1])
