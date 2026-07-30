# -*- coding: utf-8 -*-
"""1단계 — 실행 가능성 필터 (하드 제약).

비용 비교는 여기를 통과한 옵션끼리만 한다. 순서를 뒤집으면 "싸지만 애초에
불가능한 옵션"이 1등으로 올라온다.

배송이 탈락하는 조건 (짐캐리 운영 기준)
  ① 구간 불가 — 짐캐리 배송은 매장 5곳을 한쪽 끝에 두는 상품이다.
     역/공항 → 숙소·보관함 | 숙소·보관함 → 역/공항 | 숙소·보관함 → 숙소
     이 세 패턴 밖(도시철도역→역, 매장→매장 등)이면 옵션 자체가 생성되지 않는다.
  ② 시간 불가 — 당일 접수 마감. 온라인 신청 11시 / 매장 방문 15시로 다르다.
  ③ 도착 불가 — 배송 도착 시간대가 체크인·출발 시각과 맞지 않는다.

역사 물품보관함이 탈락하는 조건
  특대형 0칸(물리적 불가) / 역사 운영시간·막차 / 회수 마감.
  포화확률은 쓰지 않는다 — 실시간 점유 API가 없는 상태에서 "지금 빈 칸이
  없을 확률"을 이용자에게 제시할 근거가 없다. 그 계산은 B2B 쪽에만 남겼다.

짐캐리 무인보관함이 탈락하는 조건
  특대형 미취급 / 설치 대수 초과 / 현재 위치에서 과도한 우회.

탈락 사유는 전부 RejectReason 코드로 남는다. 이 코드가 B2B 로그의 집계 축이다.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from . import config
from .config import Channel, LuggageSize, SpotKind
from .models import (
    LuggageRequest,
    Option,
    OptionKind,
    Place,
    PlaceKind,
    RejectReason,
)
from .registry import get_registry, haversine_km


def _at(day: datetime, t: time) -> datetime:
    return day.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)


# ══════════════════════════════════════════════════════════════════
# 짐캐리 배송
# ══════════════════════════════════════════════════════════════════


def check_delivery(
    req: LuggageRequest,
    *,
    via_store: Place | None = None,
    arrive_at: datetime | None = None,
) -> Option:
    """배송 옵션의 실행 가능성. 탈락해도 Option 객체는 돌려준다.

    via_store / arrive_at 를 주면 **'지금 여기서'가 아니라 '이 매장에 이 시각에 도착해서'**
    접수하는 경우를 판정한다. 현재 위치가 매장이 아니어도, 매장까지 이동해 마감 전에
    닿을 수 있으면 배송은 가능하기 때문이다. (access.py 가 이 인자를 채워 부른다)
    """
    opt = Option(kind=OptionKind.DELIVERY, label="짐캐리 배송")

    # ── ① 구간 ────────────────────────────────────────────────────
    if req.destination is None:
        return opt.reject(
            RejectReason.DLV_NO_DESTINATION,
            "배송받을 목적지를 입력해 주세요.",
        )

    #: 매장 경유면 접수 지점은 그 매장이고, 판정 시각은 도착 시각이다.
    intake_place = via_store or req.origin
    now = arrive_at or req.at

    origin_spot, dest_spot = intake_place.spot, req.destination.spot
    opt.evidence["구간"] = f"{origin_spot.value} → {dest_spot.value}"
    opt.evidence["출발"] = intake_place.label
    opt.evidence["도착"] = req.destination.label

    if (origin_spot, dest_spot) not in config.ALLOWED_SEGMENTS:
        return opt.reject(
            RejectReason.DLV_SEGMENT_NOT_OFFERED,
            f"{intake_place.kind.value}→{req.destination.kind.value} 구간은 "
            f"짐캐리 배송 상품이 없습니다. 배송은 매장(역·공항·터미널·BEXCO)↔"
            f"숙소·무인보관함, 숙소·무인보관함→숙소만 가능합니다.",
        )

    opt.label = f"짐캐리 배송 ({intake_place.name} → {req.destination.name})"

    # ── ② 시간 ────────────────────────────────────────────────────
    from .config import Channel as _Ch
    channel = _Ch.OFFLINE if via_store is not None else req.channel
    cutoff_t = config.CUTOFF[channel]
    cutoff = _at(now, cutoff_t)
    ready = now + timedelta(minutes=config.DELIVERY_INTAKE_MINUTES)

    opt.evidence["접수채널"] = channel.value
    opt.evidence["당일마감"] = cutoff_t.strftime("%H:%M")
    opt.evidence["접수완료예상"] = ready.strftime("%H:%M")

    if channel is Channel.OFFLINE:
        open_at = _at(now, config.STORE_OPEN)
        close_at = _at(now, config.STORE_CLOSE)
        opt.evidence["매장영업"] = (
            f"{config.STORE_OPEN.strftime('%H:%M')}~{config.STORE_CLOSE.strftime('%H:%M')}"
        )
        if not (open_at <= now <= close_at):
            return opt.reject(
                RejectReason.DLV_STORE_CLOSED,
                f"{intake_place.name} 매장 영업시간 "
                f"{config.STORE_OPEN.strftime('%H:%M')}~"
                f"{config.STORE_CLOSE.strftime('%H:%M')} 밖입니다.",
            )

    if ready > cutoff:
        return opt.reject(
            RejectReason.DLV_PAST_CUTOFF,
            f"{channel.value} 당일 접수 마감 {cutoff_t.strftime('%H:%M')} 경과 "
            f"(매장 도착 {now.strftime('%H:%M')} + 접수 "
            f"{config.DELIVERY_INTAKE_MINUTES}분).",
        )

    # ── ③ 도착 ────────────────────────────────────────────────────
    arrive_from = _at(now, config.DELIVERY_ARRIVE_FROM)
    arrive_until = _at(now, config.DELIVERY_ARRIVE_UNTIL)
    opt.evidence["도착시간대"] = (
        f"{config.DELIVERY_ARRIVE_FROM.strftime('%H:%M')}~"
        f"{config.DELIVERY_ARRIVE_UNTIL.strftime('%H:%M')}"
    )

    if req.need_by is not None and arrive_until > req.need_by:
        return opt.reject(
            RejectReason.DLV_ARRIVAL_TOO_LATE,
            f"배송 완료 보장 {config.DELIVERY_ARRIVE_UNTIL.strftime('%H:%M')}이(가) "
            f"필요 시각 {req.need_by.strftime('%H:%M')}보다 늦습니다.",
        )

    if req.receivable_from is not None and arrive_until < req.receivable_from:
        return opt.reject(
            RejectReason.DLV_ARRIVAL_TOO_EARLY,
            f"배송 도착 시간대가 수령 가능 시각 "
            f"{req.receivable_from.strftime('%H:%M')} 이전에 끝납니다.",
        )

    # ── 통과 ──────────────────────────────────────────────────────
    opt.out_of_pocket = delivery_fare(req)
    opt.duration_min = (arrive_until - req.at).total_seconds() / 60
    opt.evidence["도착예정"] = arrive_until.strftime("%H:%M")
    opt.evidence["수령까지(시간)"] = round(
        max((arrive_from - req.at).total_seconds() / 3600, 0), 1
    )
    return opt


def delivery_fare(req: LuggageRequest) -> int:
    fare = 0
    for item in req.items:
        unit = config.DELIVERY_BASE_FARE
        if item.size is LuggageSize.OVERSIZE:
            unit += config.DELIVERY_OVERSIZE_SURCHARGE
        fare += unit * item.qty
    return fare


# ══════════════════════════════════════════════════════════════════
# 역사 물품보관함 (#4.1)
# ══════════════════════════════════════════════════════════════════


def check_station_locker(req: LuggageRequest, place: Place | None = None) -> Option:
    """역사 보관함의 실행 가능성. place 를 주면 그 역으로 검사한다(폴백용)."""
    reg = get_registry()
    place = place or req.origin
    size = req.max_size
    min_size = config.MIN_LOCKER_SIZE[size]

    opt = Option(
        kind=OptionKind.STATION_LOCKER,
        label=f"{place.name} 보관함",
        station_code=place.station_code,
    )
    opt.evidence["필요규격"] = min_size
    opt.evidence["짐"] = f"{size.value} {req.total_qty}개 / {req.total_weight:.0f}kg"

    if place.station_code is None:
        return opt.reject(
            RejectReason.LKR_NOT_A_STATION,
            f"'{place.name}' 주변에 접근 가능한 도시철도역이 없습니다.",
        )

    code = place.station_code
    station = reg.station(code)
    opt.label = f"{station.label} 보관함"

    # ── 운영시간 · 막차 ───────────────────────────────────────────
    open_at = _at(req.at, config.STATION_OPEN)
    close_at = _at(req.at, config.STATION_CLOSE)
    opt.evidence["역사운영"] = (
        f"{config.STATION_OPEN.strftime('%H:%M')}~{config.STATION_CLOSE.strftime('%H:%M')}"
    )
    if not (open_at <= req.at <= close_at):
        return opt.reject(
            RejectReason.LKR_STATION_CLOSED,
            f"역사 운영시간 {config.STATION_OPEN.strftime('%H:%M')}~"
            f"{config.STATION_CLOSE.strftime('%H:%M')} 밖입니다.",
        )

    if req.need_by is not None:
        deadline = _at(req.need_by, config.LOCKER_RETRIEVE_DEADLINE)
        if req.need_by > deadline:
            return opt.reject(
                RejectReason.LKR_RETRIEVE_AFTER_DEADLINE,
                f"회수 예정 {req.need_by.strftime('%H:%M')}이(가) 보관 마감 "
                f"{config.LOCKER_RETRIEVE_DEADLINE.strftime('%H:%M')} 이후입니다.",
            )

    # ── 공급 · 규격 ───────────────────────────────────────────────
    supply = reg.locker_complex(code)
    if supply is None:
        return opt.reject(
            RejectReason.LKR_NO_LOCKER_AT_STATION,
            f"{station.label}에는 물품보관함이 없습니다.",
        )

    opt.evidence["보유칸수"] = dict(supply.counts)
    opt.evidence["운영사"] = ", ".join(supply.operators)
    capacity = supply.capacity_for(min_size)
    opt.evidence["가용칸수"] = capacity

    if capacity == 0:
        return opt.reject(
            RejectReason.LKR_SIZE_UNAVAILABLE,
            f"{station.label}은(는) {min_size} 이상 규격이 0칸입니다. "
            f"({size.value} 짐은 물리적으로 들어가지 않습니다)",
        )

    if req.total_qty > capacity:
        return opt.reject(
            RejectReason.LKR_SIZE_UNAVAILABLE,
            f"짐 {req.total_qty}개 > {min_size} 이상 총 {capacity}칸.",
        )

    # ── 통과 — 요금 ───────────────────────────────────────────────
    fit = supply.cheapest_fit(min_size)
    if fit is None:
        return opt.reject(
            RejectReason.LKR_SIZE_UNAVAILABLE, "요금 정보가 있는 가용 규격이 없습니다."
        )
    used_size, price = fit
    units = station_billing_units(req.storage_hours)
    opt.out_of_pocket = price * units * req.total_qty
    opt.duration_min = 0.0
    opt.evidence["사용규격"] = used_size
    opt.evidence["과금"] = (
        f"{price:,}원 × {units}구간({config.LOCKER_BILLING_UNIT_HOURS}시간당) "
        f"× {req.total_qty}개"
    )
    opt.evidence["보관시간"] = f"{req.storage_hours:.1f}시간"
    return opt


def station_billing_units(hours: float) -> int:
    """역사 보관함은 3시간 단위 올림 과금."""
    unit = config.LOCKER_BILLING_UNIT_HOURS
    return max(int(hours // unit) + (1 if hours % unit > 0 else 0), 1)


# ══════════════════════════════════════════════════════════════════
# 짐캐리 무인보관함
# ══════════════════════════════════════════════════════════════════


def check_zim_locker(req: LuggageRequest, name: str) -> Option:
    """짐캐리 무인보관함 한 지점의 실행 가능성."""
    spec = config.ZIM_LOCKER_SPECS[name]
    size = req.max_size
    min_size = config.MIN_LOCKER_SIZE[size]

    opt = Option(
        kind=OptionKind.ZIM_LOCKER,
        label=f"{spec.name} 무인보관함",
        zim_locker_name=name,
    )
    km = haversine_km(req.origin.lat, req.origin.lon, spec.lat, spec.lon)
    opt.evidence["위치"] = f"{spec.name} {spec.detail}"
    opt.evidence["설치대수"] = spec.slots
    opt.evidence["직선거리(km)"] = round(km, 1)
    opt.evidence["필요규격"] = min_size

    # ── 규격: 특대형 미취급 ───────────────────────────────────────
    if min_size not in config.ZIM_LOCKER_SIZES:
        return opt.reject(
            RejectReason.ZIM_SIZE_UNAVAILABLE,
            f"짐캐리 무인보관함은 소·중·대형만 취급합니다 "
            f"({size.value} 짐은 이용할 수 없습니다).",
        )

    if req.total_qty > spec.slots:
        return opt.reject(
            RejectReason.ZIM_OVER_CAPACITY,
            f"짐 {req.total_qty}개 > 설치 {spec.slots}개.",
        )

    if km > config.ZIM_LOCKER_MAX_DETOUR_KM:
        return opt.reject(
            RejectReason.ZIM_TOO_FAR,
            f"현재 위치에서 {km:.1f}km — 실질적 선택지가 아닙니다 "
            f"(기준 {config.ZIM_LOCKER_MAX_DETOUR_KM:.0f}km).",
        )

    # ── 통과 — 요금 ───────────────────────────────────────────────
    base, extra = config.ZIM_LOCKER_PRICE[min_size]
    blocks = zim_extra_blocks(req.storage_hours)
    opt.out_of_pocket = (base + extra * blocks) * req.total_qty
    opt.duration_min = 0.0
    opt.evidence["사용규격"] = min_size
    opt.evidence["보관시간"] = f"{req.storage_hours:.1f}시간"
    opt.evidence["과금"] = (
        f"기본 {config.ZIM_LOCKER_BASE_HOURS}시간 {base:,}원"
        + (
            f" + 추가 {blocks}블록({config.ZIM_LOCKER_EXTRA_BLOCK_HOURS}시간당) "
            f"{extra * blocks:,}원"
            if blocks
            else ""
        )
        + f" × {req.total_qty}개"
    )
    return opt


def zim_extra_blocks(hours: float) -> int:
    """기본 4시간 초과분을 12시간 단위로 올림."""
    over = hours - config.ZIM_LOCKER_BASE_HOURS
    if over <= 0:
        return 0
    block = config.ZIM_LOCKER_EXTRA_BLOCK_HOURS
    return int(over // block) + (1 if over % block > 0 else 0)
