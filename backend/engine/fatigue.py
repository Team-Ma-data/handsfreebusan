# -*- coding: utf-8 -*-
"""
피로도 — 수직 이동 횟수 × 무게. 가정 계수를 두지 않는다.

    피로도 = Σ(구간별 가중치) × 무게가중치
    무게가중치 = 1 + 캐리어 무게(kg) / 20

가중치는 셋뿐이고 전부 Compendium of Physical Activities(Ainsworth et al.)의
MET 값에서 엘리베이터를 1로 정규화해 얻는다.

  | 구간         | Compendium MET      | 가중치 |
  |--------------|---------------------|--------|
  | 엘리베이터   | 1.3 (standing quietly)  | 1    |
  | 에스컬레이터 | 1.3~1.5             | 1.5    |
  | 계단         | 4.0~5.0 (일반 속도) | 4      |

무게가중치의 분모 20은 임의 상수가 아니라 **항공 위탁수하물 표준 허용치(20kg)**다.
20kg에서 정확히 2배가 되도록 정규화한 것이며, 이 값이 곧 '표준 캐리어 한 개'의 기준선이다.

## 평지 보행은 왜 없는가

피로도는 **수직 이동**만 센다. 평지 이동의 부담은 세 축 중 **시간(분)**이 담당한다.
같은 부담을 두 축에 나눠 넣으면 이중계상이 되고, 어느 축이 결론을 만들었는지 알 수 없게 된다.
축을 나눈 이유가 그것이므로 여기서 다시 섞지 않는다.

## 신호등을 쓰지 않는 이유

절대 등급(초록/노랑/빨강)은 기준선을 우리가 정해야 하는데, 그 기준선에 댈 근거가 없다.
대신 **같은 여정의 대안 대비 몇 % 인가**만 말한다. 비교는 근거가 필요 없다 —
두 경로를 같은 식으로 계산한 결과의 비율이기 때문이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SegKind(str, Enum):
    """수직 이동 구간. 이 셋만 센다."""

    ELEVATOR = "엘리베이터"
    ESCALATOR = "에스컬레이터"
    STAIRS = "계단"


#: 구간 가중치. 엘리베이터를 1로 둔 Compendium MET 비율.
WEIGHT: dict[SegKind, float] = {
    SegKind.ELEVATOR: 1.0,      # [문헌] MET 1.3 — standing quietly
    SegKind.ESCALATOR: 1.5,     # [문헌] MET 1.3~1.5
    SegKind.STAIRS: 4.0,        # [문헌] MET 4.0~5.0 — 계단 오르기 일반 속도
}

#: 무게가중치 분모. [기준] 항공 위탁수하물 표준 허용 20kg.
WEIGHT_REFERENCE_KG = 20.0


def weight_factor(luggage_kg: float) -> float:
    return 1.0 + max(0.0, luggage_kg) / WEIGHT_REFERENCE_KG


@dataclass
class FatigueScore:
    total: float
    luggage_kg: float
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def stairs(self) -> int:
        return self.counts.get(SegKind.STAIRS.value, 0)

    def as_evidence(self) -> dict:
        return {
            "피로도": round(self.total, 1),
            "구간": " · ".join(f"{k} {v}회" for k, v in self.counts.items() if v),
            "무게가중치": round(weight_factor(self.luggage_kg), 2),
            "출처": "Compendium of Physical Activities (Ainsworth et al.) MET 비율",
        }


def score(segments: list[SegKind], luggage_kg: float) -> FatigueScore:
    """구간 목록 + 짐 무게 → 피로도. 딕셔너리 lookup + 곱셈 한 줄."""
    total = sum(WEIGHT[s] for s in segments) * weight_factor(luggage_kg)
    counts: dict[str, int] = {}
    for s in segments:
        counts[s.value] = counts.get(s.value, 0) + 1
    return FatigueScore(total=total, luggage_kg=luggage_kg, counts=counts)


# ══════════════════════════════════════════════════════════════════
# 방안 D — 대안 대비 비교. 절대 등급은 쓰지 않는다.
# ══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Comparison:
    """이 선택지가 최선 대비 얼마나 더 힘든가."""

    score: float
    best_score: float
    excess_pct: float        # 최선 대비 초과율(%). 최선이면 0
    reduction_pct: float     # 최악 대비 감소율(%). 발표에 쓰는 숫자
    is_best: bool

    def phrase(self, lang: str = "ko") -> str:
        if self.is_best:
            if self.reduction_pct <= 0:
                return "가장 덜 힘든 경로예요" if lang == "ko" else "Least strenuous option"
            return (f"다른 경로보다 피로가 {self.reduction_pct:.0f}% 낮아요" if lang == "ko"
                    else f"{self.reduction_pct:.0f}% less strenuous than the alternative")
        return (f"가장 편한 선택지보다 {self.excess_pct:.0f}% 더 힘들어요" if lang == "ko"
                else f"{self.excess_pct:.0f}% more strenuous than the easiest option")


def compare(scores: list[float]) -> list[Comparison]:
    """여러 선택지의 피로도를 서로 견준다. 기준선이 필요 없는 게 요점이다."""
    if not scores:
        return []
    best, worst = min(scores), max(scores)
    out = []
    for s in scores:
        excess = (s - best) / best * 100 if best > 0 else 0.0
        reduction = (worst - s) / worst * 100 if worst > 0 else 0.0
        out.append(Comparison(score=s, best_score=best, excess_pct=excess,
                              reduction_pct=reduction, is_best=(s <= best + 1e-9)))
    return out


def reduction_pct(best: FatigueScore, baseline: FatigueScore) -> float:
    """기준 경로 대비 피로 감소율(%)."""
    if baseline.total <= 0:
        return 0.0
    return max(0.0, (baseline.total - best.total) / baseline.total * 100)
