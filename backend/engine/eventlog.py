# -*- coding: utf-8 -*-
"""B2B 미충족수요 로그.

엔진이 관광객에게 답을 주려고 이미 계산한 값을, 집계하는 순간 그대로
입지 인텔리전스로 바꾸는 자리다. 별도 분석 파이프라인이 아니라
추천 런타임에 한 줄 붙는 구조여야 한다.

남기는 공백 네 가지
  수요 공백     — [역 × 시간대 × 짐 크기] 역사 보관함에 맡히지 못한 건수.
                  → 부산교통공사에 "여기 증설·신설" 근거.
  구간 공백     — [구간 × 시간대] 배송 상품이 없어 못 권한 건수.
                  → 짐캐리에 "이 구간 상품화" 근거.
  접수점 공백   — [위치 × 시간대] 배송을 원했으나 매장이 아니어서 못 받은 건수.
                  → 짐캐리에 "역 밖 접수 포인트 신설" 근거.
  마감 공백     — [시간대] 접수 마감 때문에 놓친 건수.
                  → 짐캐리에 "온라인 11시 / 매장 15시 마감 연장" 근거.

지금은 데모 시뮬레이션이 로그를 채우지만, 스키마는 실서비스 로그와 동일하다.
서비스가 크면 추정이 실측으로 교체되는 것이지 구조가 바뀌지 않는다.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from . import datasets
from .models import Decision, LuggageRequest, Option, OptionKind, RejectReason
from .registry import get_registry

EVENT_PATH = datasets.CACHE_DIR / "unmet_demand_events.csv"


class EventType:
    REJECTED = "REJECTED"        # 옵션이 하드 제약에 걸려 탈락
    FALLBACK = "FALLBACK"        # 폴백 사다리를 내려가 해결
    RESOLVED = "RESOLVED"        # 1차 후보에서 바로 해결
    UNRESOLVED = "UNRESOLVED"    # 어떤 옵션도 못 줌


@dataclass
class Event:
    ts: str
    event: str
    option_kind: str
    reason_code: str = ""
    reason_text: str = ""

    #: 옵션이 가리키는 지점
    station_code: int | None = None
    station_label: str = ""
    zim_locker: str = ""

    #: 요청자가 실제로 서 있던 곳. 매장이 아닌 곳에서 배송을 원했다는 사실이
    #: 짐캐리의 '역 밖 접수 포인트 신설' 근거가 되므로 별도로 남긴다.
    origin_label: str = ""
    origin_spot: str = ""
    dest_label: str = ""
    dest_spot: str = ""
    segment: str = ""
    store: str = ""
    zone: str = ""

    #: 요청 내용
    preference: str = ""
    channel: str = ""
    size: str = ""
    qty: int = 0
    weight_kg: float = 0.0
    hour: int = 0
    day_type: str = ""
    fallback_level: int = 0
    foreign: bool = False


class EventLog:
    """메모리 누적 + CSV 영속화."""

    FIELDS = list(Event.__annotations__.keys())

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or EVENT_PATH
        self.events: list[Event] = []

    # ── 기록 ────────────────────────────────────────────────────
    def record(self, req: LuggageRequest, opt: Option, event: str) -> Event:
        from .saturation import day_type_of

        reg = get_registry()

        label = ""
        if opt.station_code is not None:
            label = reg.station(opt.station_code).label

        origin_code = req.origin.station_code
        origin_label = (
            reg.station(origin_code).label
            if origin_code is not None and req.origin.kind.value == "역"
            else req.origin.name
        )
        dest = req.destination
        store = req.origin.store_name or (dest.store_name if dest else None) or ""

        e = Event(
            ts=req.at.isoformat(timespec="minutes"),
            event=event,
            option_kind=opt.kind.value,
            reason_code=opt.reject_reason.name if opt.reject_reason else "",
            reason_text=opt.reject_reason.value if opt.reject_reason else "",
            station_code=opt.station_code,
            station_label=label,
            zim_locker=opt.zim_locker_name or "",
            origin_label=origin_label,
            origin_spot=req.origin.spot.value,
            dest_label=dest.name if dest else "",
            dest_spot=dest.spot.value if dest else "",
            segment=f"{req.origin.spot.value}→{dest.spot.value}" if dest else "",
            store=store,
            zone=(dest.zone if dest else req.origin.zone) or "",
            preference=req.preference.value,
            channel=req.channel.value,
            size=req.max_size.value,
            qty=req.total_qty,
            weight_kg=round(req.total_weight, 1),
            hour=req.at.hour,
            day_type=day_type_of(req.at),
            fallback_level=opt.fallback_level,
            foreign=req.foreign,
        )
        self.events.append(e)
        return e

    def record_decision(self, decision: Decision) -> None:
        req = decision.request
        for opt in decision.rejected:
            self.record(req, opt, EventType.REJECTED)
        if decision.recommended is not None:
            evt = (
                EventType.RESOLVED
                if decision.fallback_level == 0
                else EventType.FALLBACK
            )
            self.record(req, decision.recommended, evt)
        else:
            self.record(req, Option(kind=OptionKind.HAUL, label="해결 실패"),
                        EventType.UNRESOLVED)

    # ── 영속화 ──────────────────────────────────────────────────
    def flush(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        exists = self.path.exists()
        with self.path.open("a", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=self.FIELDS)
            if not exists:
                w.writeheader()
            for e in self.events:
                w.writerow(asdict(e))
        return self.path

    # ── 집계 1: 수요 공백 (부산교통공사용) ───────────────────────
    def demand_gap(self) -> list[dict]:
        """[역 × 시간대 × 짐크기] 역사 보관함에 맡기지 못한 건수."""
        agg: dict[tuple, dict] = {}
        for e in self.events:
            if e.option_kind != OptionKind.STATION_LOCKER.value:
                continue
            if e.event != EventType.REJECTED or not e.station_label:
                continue
            key = (e.station_label, e.hour, e.size)
            slot = agg.setdefault(
                key,
                {"역": e.station_label, "시간대": f"{e.hour:02d}시", "짐크기": e.size,
                 "건수": 0, "사유": Counter()},
            )
            slot["건수"] += e.qty or 1
            slot["사유"][e.reason_code] += 1

        return self._finish(agg)

    # ── 집계 2: 구간 공백 (짐캐리용) ────────────────────────────
    def segment_gap(self) -> list[dict]:
        """[구간 × 시간대] 배송 상품이 없거나 시간이 안 맞아 못 권한 건수."""
        agg: dict[tuple, dict] = {}
        for e in self.events:
            if e.option_kind != OptionKind.DELIVERY.value:
                continue
            if e.event != EventType.REJECTED or not e.segment:
                continue
            key = (e.segment, e.hour)
            slot = agg.setdefault(
                key,
                {"구간": e.segment, "시간대": f"{e.hour:02d}시",
                 "건수": 0, "사유": Counter(), "외국인": 0},
            )
            slot["건수"] += e.qty or 1
            slot["사유"][e.reason_code] += 1
            slot["외국인"] += (e.qty or 1) if e.foreign else 0

        return self._finish(agg)

    # ── 집계 3: 접수점 공백 (짐캐리용) ──────────────────────────
    def intake_point_gap(self) -> list[dict]:
        """[위치 × 시간대] 매장이 아닌 곳에서 배송을 원했다 못 받은 건수.

        서면·남포처럼 쇼핑으로 짐이 새로 생기는 곳에서 이 수가 크면,
        그 자리가 짐캐리 접수 포인트 후보다. 역사 안이 아니라 역 밖 거점이라
        부산교통공사가 아니라 짐캐리에게 가는 제안이 된다.
        """
        agg: dict[tuple, dict] = {}
        for e in self.events:
            if e.option_kind != OptionKind.DELIVERY.value:
                continue
            if e.reason_code != RejectReason.DLV_SEGMENT_NOT_OFFERED.name:
                continue
            key = (e.origin_label, e.hour)
            slot = agg.setdefault(
                key,
                {"위치": e.origin_label, "유형": e.origin_spot,
                 "시간대": f"{e.hour:02d}시", "건수": 0, "사유": Counter(), "외국인": 0},
            )
            slot["건수"] += e.qty or 1
            slot["사유"][e.reason_code] += 1
            slot["외국인"] += (e.qty or 1) if e.foreign else 0

        return self._finish(agg)

    # ── 집계 4: 마감 공백 (짐캐리용) ────────────────────────────
    def cutoff_loss_by_hour(self) -> list[dict]:
        """접수 마감 때문에 탈락한 건수를 시간대·채널별로.

        온라인 11시 / 매장 15시라는 두 마감선이 각각 얼마를 놓치는지 보여 준다.
        """
        agg: dict[tuple, dict] = {}
        for e in self.events:
            if e.reason_code not in {
                RejectReason.DLV_PAST_CUTOFF.name,
                RejectReason.DLV_STORE_CLOSED.name,
            }:
                continue
            key = (e.hour, e.channel)
            slot = agg.setdefault(
                key,
                {"시간대": f"{e.hour:02d}시", "채널": e.channel,
                 "건수": 0, "사유": Counter(), "위치": Counter()},
            )
            slot["건수"] += e.qty or 1
            slot["사유"][e.reason_code] += 1
            slot["위치"][e.origin_label] += e.qty or 1

        rows = self._finish(agg)
        for r in rows:
            r["위치분포"] = dict(r.pop("위치"))
        return sorted(rows, key=lambda r: r["시간대"])

    # ── 공통 마무리 ─────────────────────────────────────────────
    @staticmethod
    def _finish(agg: dict) -> list[dict]:
        rows = []
        for slot in agg.values():
            counter = slot.pop("사유")
            slot["주사유"] = counter.most_common(1)[0][0] if counter else ""
            slot["사유분포"] = dict(counter)
            rows.append(slot)
        return sorted(rows, key=lambda r: -r["건수"])

    def summary(self) -> dict:
        by_event = Counter(e.event for e in self.events)
        by_reason = Counter(e.reason_code for e in self.events if e.reason_code)
        return {
            "총 이벤트": len(self.events),
            "이벤트별": dict(by_event),
            "탈락사유 상위": dict(by_reason.most_common(10)),
        }


#: 프로세스 전역 로그. 엔진이 기본으로 여기에 쓴다.
GLOBAL_LOG = EventLog()
