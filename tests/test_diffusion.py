"""확산 표시(사용자 결정 2026-10-29): 과매도 블록 지표 점수 ≥ high / ≤ low / 가용 개수. 합성 데이터는 테스트 전용."""
import copy

import numpy as np
import pandas as pd
import pytest

from conftest import synth_daily, to_panel
from mtscore import ScoringEngine, build_config
from mtscore.api import _diffusion

T = "2015-06-30"


def _rows(scores, block="oversold"):
    return [{"block": block, "score": s} for s in scores]


def test_diffusion_counts_hand_rows():
    rows = _rows([80.0, 79.99, 20.0, 20.01, np.nan, 100.0, 0.0]) + _rows([95.0, 5.0], block="valuation")
    r = _diffusion(rows, {"high": 80, "low": 20}, is_stale=False)
    # 손으로 센 값: ≥80 → 80·100 = 2, ≤20 → 20·0 = 2, 가용 → NaN 제외 6. valuation 행은 세지 않는다
    assert (r["n_high"], r["n_low"], r["n_available"], r["reason"]) == (2, 2, 6, "")
    assert (r["block"], r["high"], r["low"]) == ("oversold", 80.0, 20.0)


def test_diffusion_thresholds_come_from_config():
    rows = _rows([80.0, 79.99, 60.0, 20.0, 40.0, 40.01])
    r = _diffusion(rows, {"high": 60, "low": 40}, is_stale=False)
    # ≥60 → 80·79.99·60 = 3, ≤40 → 20·40 = 2
    assert (r["n_high"], r["n_low"], r["n_available"]) == (3, 2, 6)


def test_diffusion_stale_and_no_config():
    rows = _rows([90.0, 10.0])
    st = _diffusion(rows, {"high": 80, "low": 20}, is_stale=True)
    assert (st["n_high"], st["n_low"], st["n_available"], st["reason"]) == (0, 0, 0, "unavailable_at_as_of")
    off = _diffusion(rows, None, is_stale=False)
    assert off["n_high"] is None and off["n_available"] is None and off["reason"] == "diffusion 설정 없음"


def _expected_from_history(res, aid, hi, lo):
    """기대값: 일별 이력의 지표 점수(h.score)에서 그날 과매도 사용 지표 열을 직접 센다(결과 빌더 경로와 독립)."""
    h = res.history[aid]
    cov = h.coverage
    names = list(cov[(cov.block == "oversold") & cov.used.astype(bool)].indicator)
    s = h.score.loc[res.dates[aid], names].astype(float).dropna()
    return int((s >= hi).sum()), int((s <= lo).sum()), int(len(s))


def test_diffusion_in_result_matches_history_and_pit(mini_config, mini_panel):
    eng = ScoringEngine(mini_config)
    for t in (T, "2014-03-31", "2016-11-30"):
        res = eng.score(mini_panel, as_of=t)
        d = res.diffusion.loc["EQ"]
        assert (d["n_high"], d["n_low"], d["n_available"]) == _expected_from_history(res, "EQ", 80, 20)
        assert d["n_available"] == 3   # disparity_20·rsi_14·ccy_shock 모두 가용
        # PIT: 기준일 이후 행을 지워도 같은 값
        cut = mini_panel[mini_panel["as_of"] <= pd.Timestamp(t)]
        d2 = eng.score(cut, as_of=t).diffusion.loc["EQ"]
        assert d2.to_dict() == d.to_dict()


def test_diffusion_counts_reflect_missing_indicator(mini_config, mini_panel):
    # FX(ccy_shock 의 원천)가 기준일 한참 전에 끊기면 그 지표가 빠져 가용 수가 정확히 1 줄어든다
    cut = mini_panel[~((mini_panel.asset_id == "FX") & (mini_panel.date > "2015-01-31"))]
    res = ScoringEngine(mini_config).score(cut, as_of=T, asset_ids=["EQ"])
    d = res.diffusion.loc["EQ"]
    cov = res.coverage.set_index("indicator")
    assert not bool(cov.at["ccy_shock", "available"])
    assert d["n_available"] == 2
    assert (d["n_high"], d["n_low"], d["n_available"]) == _expected_from_history(res, "EQ", 80, 20)


def test_diffusion_stale_asset(mini_config, mini_panel):
    cut = mini_panel[mini_panel.date <= "2015-03-31"]
    res = ScoringEngine(mini_config).score(cut, as_of=T)
    assert bool(res.stale["EQ"])
    d = res.diffusion.loc["EQ"]
    assert (d["n_high"], d["n_low"], d["n_available"], d["reason"]) == (0, 0, 0, "unavailable_at_as_of")


def test_diffusion_does_not_change_scores(mini_universe, mini_profiles, scoring_cfg, mini_panel):
    on = ScoringEngine(build_config(mini_universe, mini_profiles, scoring_cfg)).score(mini_panel, as_of=T)
    sc = copy.deepcopy(scoring_cfg)
    sc.pop("diffusion")
    off = ScoringEngine(build_config(mini_universe, mini_profiles, sc)).score(mini_panel, as_of=T)
    pd.testing.assert_frame_equal(on.blocks, off.blocks)
    pd.testing.assert_frame_equal(on.regime, off.regime)
    pd.testing.assert_frame_equal(on.contributions, off.contributions)
    pd.testing.assert_frame_equal(on.staged_entry, off.staged_entry)
    pd.testing.assert_frame_equal(on.trend, off.trend)
    assert off.diffusion.at["EQ", "reason"] == "diffusion 설정 없음" and off.diffusion.at["EQ", "n_high"] is None
    sc2 = copy.deepcopy(scoring_cfg)
    sc2["diffusion"] = {"high": 1, "low": 0}   # 임계값을 바꿔도 점수 불변, 개수만 바뀐다
    alt = ScoringEngine(build_config(mini_universe, mini_profiles, sc2)).score(mini_panel, as_of=T)
    pd.testing.assert_frame_equal(on.blocks, alt.blocks)
    assert alt.diffusion.at["EQ", "n_high"] == _expected_from_history(alt, "EQ", 1, 0)[0]
