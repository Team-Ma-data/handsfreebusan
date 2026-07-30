"""
챗봇 ↔ 팀원 추천 엔진의 **유일한 접합면**.

원칙
  1. `backend/engine/` 은 팀원 코드다. 여기서 **한 줄도 고치지 않는다.**
     필요한 보정·표현은 전부 이 어댑터에서 한다. 그래야 팀원이 엔진을 계속 고쳐도 머지 충돌이 없다.
  2. 엔진이 못 뜨면(발제사 데이터 폴더 부재 등) 챗봇 전체가 죽으면 안 된다 → 경량 폴백으로 자동 강등.
  3. 챗봇은 `plan()` 하나만 부른다. Place·LuggageRequest 조립의 지저분함은 전부 여기 가둔다.

여기서 하는 '보정' 세 가지 (전부 팀원 코드를 건드리지 않고)
  · 목적지를 LODGING 으로 만든다 — STATION 을 목적지로 주면 ALLOWED_SEGMENTS 밖이라
    배송이 항상 DLV_SEGMENT_NOT_OFFERED 로 탈락한다. 챗봇 사용자의 '숙소'는 숙소여야 한다.
  · 출발지가 짐캐리 매장 직결역이면 STORE 로 승격한다 — 접수 채널이 온라인(11시)→매장(15시)으로
    바뀌어 판정이 실제로 달라지므로, 자동 판정하되 근거를 반드시 남긴다.
  · 보관함 추천에 '2안'을 강제로 붙인다 — 실시간 잔여 API가 없으므로 단일 지점 추천을 금지한다.
    (자세한 근거는 docs/02_엔진_검토와_답변.md §2)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from .plan_types import PlanOption, PlanResult

log = logging.getLogger("timecarry.engine")

# ---------------------------------------------------------------- 엔진 로딩

ENGINE_OK = False
ENGINE_ERROR = ""

try:  # 팀원 엔진
    from engine import config as ecfg
    from engine import places as eplaces
    from engine.config import LuggageSize, Preference
    from engine.engine import recommend as _recommend
    from engine.models import LuggageItem, LuggageRequest, OptionKind
    from engine.registry import get_registry

    _ = get_registry()          # 발제사 데이터가 없으면 여기서 터진다
    ENGINE_OK = True
except Exception as e:          # noqa: BLE001
    ENGINE_ERROR = f"{type(e).__name__}: {e}"
    log.warning("추천 엔진을 불러오지 못했습니다 → 경량 폴백으로 동작합니다. (%s)", ENGINE_ERROR)

from . import engine_fallback  # noqa: E402  (엔진 유무와 무관하게 항상 준비)


# ---------------------------------------------------------------- 상태

def engine_status() -> dict:
    return {"available": ENGINE_OK, "source": "engine" if ENGINE_OK else "fallback",
            "error": ENGINE_ERROR or None}


# ---------------------------------------------------------------- 입력 조립

SIZE_ALIASES = {
    "carry_on": "기내용", "cabin": "기내용", "small": "기내용", "기내용": "기내용", "s": "기내용",
    "medium": "중형", "중형": "중형", "m": "중형",
    "large": "대형", "checked": "대형", "big": "대형", "대형": "대형", "l": "대형",
    "oversize": "특대형", "extra_large": "특대형", "특대형": "특대형", "xl": "특대형",
}

PREF_ALIASES = {
    "store": "보관", "storage": "보관", "보관": "보관", "keep": "보관",
    "deliver": "배송", "delivery": "배송", "배송": "배송", "ship": "배송",
    "any": "무관", "무관": "무관", None: "무관", "": "무관",
}


def _size(raw: str):
    label = SIZE_ALIASES.get(str(raw).strip().lower(), "대형")
    return next(s for s in LuggageSize if s.value == label)


def _pref(raw):
    label = PREF_ALIASES.get(str(raw).strip().lower() if raw else None, "무관")
    return next(p for p in Preference if p.value == label)


def _store_at(station_name: str) -> Optional[str]:
    """이 역에 직결된 짐캐리 매장 이름 (있으면)."""
    for name, spec in ecfg.STORE_SPECS.items():
        if spec.anchor_station and spec.anchor_access_min == 0.0:
            if spec.anchor_station in station_name or station_name in spec.anchor_station:
                return name
    return None


def _origin_place(name: str, at_store: Optional[bool], notes: list[str]):
    """출발지 Place. 매장 직결역이면 STORE 로 승격 — 접수 마감이 11시→15시로 바뀐다."""
    for store_name in ecfg.STORES:
        if store_name.replace(" ", "") in name.replace(" ", ""):
            notes.append(f"출발지를 짐캐리 매장으로 인식: {store_name} (매장 접수 마감 15:00 적용)")
            return eplaces.store(store_name)
    for zim in ecfg.ZIM_LOCKERS:
        if zim.replace(" ", "") in name.replace(" ", ""):
            return eplaces.zim_locker(zim)

    place = eplaces.station(name)
    linked = _store_at(place.name)
    if linked and at_store is not False:
        notes.append(f"{place.name}역에는 짐캐리 매장({linked})이 직결돼 있어 매장 접수(마감 15:00) 기준으로 판정")
        return eplaces.store(linked)
    return place


def _dest_place(name: str, notes: list[str]):
    """목적지 Place.

    ★ 여기가 통합에서 제일 잘 틀리는 자리다. 목적지를 STATION 으로 만들면 배송 구간
      허용표(ALLOWED_SEGMENTS) 밖이라 배송이 무조건 탈락한다. 챗봇에서 사용자가 말하는
      목적지는 사실상 '숙소'이므로 그 역 근처 숙소로 만든다.
    """
    for store_name in ecfg.STORES:
        if store_name.replace(" ", "") in name.replace(" ", ""):
            return eplaces.store(store_name)
    notes.append(f"목적지를 '{name}역 인근 숙소'로 해석 (배송 상품의 끝점은 숙소·매장·무인보관함)")
    return eplaces.lodging_near(f"{name} 인근 숙소", name)


# ---------------------------------------------------------------- 결과 변환

_PRESSURE_BANDS = (
    (0.60, "붐빔"),
    (0.30, "보통"),
    (0.00, "여유"),
)


def _pressure_label(prob: float) -> str:
    for threshold, label in _PRESSURE_BANDS:
        if prob >= threshold:
            return label
    return "여유"


def _contention(station_code: int, size, when: datetime, evidence: dict):
    """2안을 붙일지 판정한다. 확률이 아니라 **미스매치 순위 기반 트리아지**다.

    근거와 임계값의 이유는 engine/contention.py 파일 상단 참조.
    실패하면 None 이 아니라 '보수적으로 2안 동반'이 나오도록 contention 쪽에서 처리한다.
    """
    try:
        from engine import contention

        cap = evidence.get("가용칸수") or evidence.get("해당 규격 칸수") or 1
        return contention.assess(station_code, size, when, int(cap))
    except Exception as e:  # noqa: BLE001
        log.debug("혼잡 트리아지 실패(무시): %s", e)
        return None


def _convert(opt, when: datetime, size) -> PlanOption:
    c = opt.cost
    po = PlanOption(
        kind=opt.kind.value,
        label=opt.label,
        feasible=opt.feasible,
        out_of_pocket=int(opt.out_of_pocket or 0),
        duration_min=float(opt.duration_min or 0.0),
        reject_reason=(opt.reject_detail or (opt.reject_reason.value if opt.reject_reason else None)),
        fallback_level=opt.fallback_level,
        station_code=opt.station_code,
        evidence=dict(opt.evidence),
        cost_index=float(c.total),
        cost_parts={"지출": c.money, "시간": c.time, "부담": c.burden, "리스크": c.risk, "불안": c.anxiety},
    )
    # 피로도 — access.py 가 evidence 에 실어 보낸 점수. 문구는 뒤에서 대안과 견줘 채운다.
    po.fatigue = opt.evidence.get("피로도")
    # 혼잡 — 확률이 아니라 미스매치 순위 기반 트리아지 (engine/contention.py)
    if opt.kind is OptionKind.STATION_LOCKER and opt.station_code is not None and opt.feasible:
        c = _contention(opt.station_code, size, when, opt.evidence)
        if c is not None:
            po.pressure = "2안필요" if c.needs_backup else "여유"
            po.evidence.update(c.as_evidence())
    return po


def _annotate_fatigue(options: list[PlanOption], lang: str) -> None:
    """방안 D — 절대 등급을 매기지 않고 **대안 대비**로만 말한다.

    기준선을 우리가 정할 필요가 없다는 게 요점이다. 같은 식으로 계산한 두 값의 비율이라
    근거를 따로 댈 게 없다.
    """
    from engine import fatigue as F

    #: 피로도가 0(수직 이동 없음)이거나 미산출인 옵션은 비교 대상에서 뺀다.
    #: "피로가 100% 낮아요" 같은 무의미한 문구를 만들지 않기 위해서다.
    scored = [o for o in options if o.feasible and o.fatigue]
    if len(scored) < 2:
        for o in scored:
            o.fatigue_note = ("가장 덜 힘든 경로" if lang == "ko" else "Least strenuous")
        return
    for o, c in zip(scored, F.compare([o.fatigue for o in scored])):
        #: 차이가 5% 미만이면 굳이 말하지 않는다. 사실상 같은 경로다.
        if c.is_best and c.reduction_pct < 5:
            continue
        if not c.is_best and c.excess_pct < 5:
            continue
        o.fatigue_note = c.phrase(lang)


def _attach_backups(rec: PlanOption, alts: list[PlanOption]) -> None:
    """Q2 — 보관함을 추천할 땐 반드시 '가서 꽉 찼을 때의 2안'을 함께 붙인다.

    실시간 잔여 칸수 API가 없다는 사실을 숨기지 않고, 대신 헛걸음의 복구 비용을 0으로 만든다.
    """
    if "보관함" not in rec.kind:
        return
    for a in alts:
        if a.feasible and "보관함" in a.kind and a.label != rec.label:
            rec.backups.append(a.label)
        if len(rec.backups) >= 2:
            break


# ---------------------------------------------------------------- 진입점

def plan(
    *,
    origin: str,
    destination: Optional[str],
    items: list[dict],
    at: Optional[datetime] = None,
    preference: Optional[str] = None,
    need_by: Optional[datetime] = None,
    receivable_from: Optional[datetime] = None,
    at_store: Optional[bool] = None,
    foreign: bool = True,
    lang: str = "ko",
) -> PlanResult:
    """챗봇이 부르는 단 하나의 함수."""
    when = at or datetime.now()

    if not ENGINE_OK:
        return engine_fallback.plan(
            origin=origin, destination=destination, items=items, at=when,
            preference=preference, reason=ENGINE_ERROR,
        )

    notes: list[str] = []
    try:
        o = _origin_place(origin, at_store, notes)
        d = _dest_place(destination, notes) if destination else None

        li = [LuggageItem(size=_size(i.get("size", "대형")),
                          qty=max(1, int(i.get("count", i.get("qty", 1)))),
                          weight_kg=i.get("weight_kg"))
              for i in (items or [])]

        req = LuggageRequest(
            at=when, origin=o, items=li, preference=_pref(preference),
            destination=d, need_by=need_by, receivable_from=receivable_from,
            foreign=foreign,
        )
        decision = _recommend(req)
    except Exception as e:  # noqa: BLE001
        log.exception("엔진 호출 실패 → 폴백")
        return engine_fallback.plan(origin=origin, destination=destination, items=items,
                                    at=when, preference=preference, reason=f"{type(e).__name__}: {e}")

    size = req.max_size
    rec = _convert(decision.recommended, when, size) if decision.recommended else None
    alts = [_convert(o_, when, size) for o_ in decision.alternatives]
    rejs = [_convert(o_, when, size) for o_ in decision.rejected]

    if rec:
        _annotate_fatigue([rec, *alts], lang)
        _attach_backups(rec, alts)
        if rec.pressure == "붐빔" and not rec.backups:
            notes.append("혼잡 등급이 높은데 인근 대체 보관함이 없다 — 배송·동반이동 쪽 안내를 우선할 것")

    if decision.fallback_level:
        notes.append(f"1차 후보가 모두 막혀 폴백 {decision.fallback_level}단으로 내려감")
    notes.extend(_reject_notes(rejs))

    return PlanResult(
        ok=rec is not None, source="engine", recommended=rec,
        alternatives=alts, rejected=rejs,
        fallback_level=decision.fallback_level, notes=notes,
    )


def _reject_notes(rejected: list[PlanOption]) -> list[str]:
    seen, out = set(), []
    for r in rejected:
        key = f"{r.kind}|{r.reject_reason}"
        if key in seen or not r.reject_reason:
            continue
        seen.add(key)
        out.append(f"탈락 {r.kind}: {r.reject_reason}")
    return out
