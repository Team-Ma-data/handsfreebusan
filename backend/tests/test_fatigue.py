"""피로도 — 사용자 확정 공식의 성질을 고정한다.

    피로도 = Σ(구간 가중치) × (1 + kg/20)
    엘리베이터 1 · 에스컬레이터 1.5 · 계단 4   (Compendium MET 비율, 엘베=1 정규화)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from engine.fatigue import (  # noqa: E402
    WEIGHT,
    WEIGHT_REFERENCE_KG,
    SegKind,
    compare,
    reduction_pct,
    score,
    weight_factor,
)

EL, ES, ST = SegKind.ELEVATOR, SegKind.ESCALATOR, SegKind.STAIRS


def test_weights_match_the_compendium_ratio():
    """엘베=1 기준. 계단이 4배, 에스컬레이터가 1.5배."""
    assert WEIGHT[EL] == 1.0
    assert WEIGHT[ES] == 1.5
    assert WEIGHT[ST] == 4.0


def test_weight_reference_is_the_checked_baggage_standard():
    assert WEIGHT_REFERENCE_KG == 20.0
    assert weight_factor(20) == pytest.approx(2.0)
    assert weight_factor(0) == pytest.approx(1.0)
    assert weight_factor(30) == pytest.approx(2.5)


def test_reference_example_from_the_spec():
    """사용자가 제시한 예시가 그대로 재현되어야 한다.

    추천 경로: 엘베 2 + 에스컬 1, 20kg → (1*2 + 1.5) * 2.0 = 7
    기본 경로: 계단 2,        20kg → (4*2) * 2.0 = 16
    감소율 = (16-7)/16 = 56%
    """
    rec = score([EL, EL, ES], 20)
    base = score([ST, ST], 20)
    assert rec.total == pytest.approx(7.0)
    assert base.total == pytest.approx(16.0)
    assert reduction_pct(rec, base) == pytest.approx(56.25, abs=0.1)


def test_luggage_always_matters():
    """무게가 늘면 어떤 구간 구성이든 피로도가 늘어야 한다."""
    for segs in ([EL], [ES], [ST], [EL, ST, ES]):
        assert score(segs, 30).total > score(segs, 10).total > score(segs, 0).total


def test_stairs_are_hit_hardest_by_weight():
    """같은 무게 증가가 계단에서 가장 크게 작용해야 한다."""
    d = {k: score([k], 20).total - score([k], 0).total for k in (EL, ES, ST)}
    assert d[ST] > d[ES] > d[EL]
    assert d[ST] == pytest.approx(4.0)   # 계단 4 × (2.0-1.0)


def test_no_assumed_coefficients_remain():
    """모듈에 남은 숫자는 가중치 3개와 기준무게 1개뿐이어야 한다."""
    import engine.fatigue as f

    floats = {k: v for k, v in vars(f).items()
              if isinstance(v, float) and not k.startswith("_")}
    assert set(floats) == {"WEIGHT_REFERENCE_KG"}, floats


# ─────────────────────────────────────────── 방안 D — 대안 대비 비교

def test_comparison_needs_no_threshold():
    """절대 등급(신호등) 없이 대안 대비로만 말한다."""
    cs = compare([7.0, 16.0, 11.0])
    assert cs[0].is_best and cs[0].excess_pct == pytest.approx(0.0)
    assert cs[1].excess_pct == pytest.approx((16 - 7) / 7 * 100)
    assert cs[2].excess_pct == pytest.approx((11 - 7) / 7 * 100)


def test_best_option_reports_reduction_against_worst():
    cs = compare([7.0, 16.0])
    assert cs[0].reduction_pct == pytest.approx(56.25, abs=0.1)
    assert "56%" in cs[0].phrase("ko")


def test_non_best_option_reports_excess():
    cs = compare([7.0, 16.0])
    assert "더 힘들어요" in cs[1].phrase("ko")
    assert "more strenuous" in cs[1].phrase("en")


def test_single_option_is_trivially_best():
    cs = compare([12.0])
    assert cs[0].is_best and cs[0].excess_pct == 0.0


def test_no_traffic_light_api_exists():
    """신호등은 제거됐다 — 실수로 되살아나면 여기서 걸린다."""
    import engine.fatigue as f

    assert not hasattr(f, "signal")
    assert not hasattr(f, "Signal")


def test_evidence_names_its_source():
    ev = score([EL, ST], 20).as_evidence()
    assert ev["피로도"] == pytest.approx(10.0)
    assert "Compendium" in ev["출처"]
    assert ev["무게가중치"] == pytest.approx(2.0)
