"""실엔진과 폴백이 공통으로 뱉는 결과 타입. 챗봇이 아는 유일한 모양이다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class PlanOption:
    kind: str                       # "역사 보관함" / "짐캐리 배송" / "동반이동" ...
    label: str
    feasible: bool
    out_of_pocket: int = 0          # 실제 결제 금액(원). 화면에 보여도 되는 유일한 금액
    duration_min: float = 0.0
    reject_reason: Optional[str] = None
    fallback_level: int = 0
    station_code: Optional[int] = None
    evidence: dict[str, Any] = field(default_factory=dict)
    #: 실시간 잔여 API 부재 하의 서수 등급 — "여유" / "보통" / "붐빔"
    pressure: Optional[str] = None
    #: 가서 꽉 찼을 때의 2안 지점 이름들
    backups: list[str] = field(default_factory=list)
    #: 피로도 점수와, 대안 대비 한 줄 문구 (절대 등급·신호등은 쓰지 않는다)
    fatigue: Optional[float] = None
    fatigue_note: Optional[str] = None
    #: 내부 비교용 총비용지수(원). ★ 사용자 화면에 절대 노출 금지
    cost_index: float = 0.0
    cost_parts: dict[str, float] = field(default_factory=dict)


@dataclass
class PlanResult:
    ok: bool
    source: str                     # "engine" | "fallback"
    recommended: Optional[PlanOption]
    alternatives: list[PlanOption] = field(default_factory=list)
    rejected: list[PlanOption] = field(default_factory=list)
    fallback_level: int = 0
    notes: list[str] = field(default_factory=list)
    error: Optional[str] = None
