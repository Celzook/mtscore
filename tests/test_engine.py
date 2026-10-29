import copy
import json

import numpy as np
import pandas as pd
import pytest

from conftest import ROOT, synth_daily, to_panel
from mtscore import ConfigError, ScoringEngine, build_config, load_config
from mtscore.core.scoring import regime

T = "2015-06-30"


def test_score_basic_shape(mini_config, mini_panel):
    res = ScoringEngine(mini_config).score(mini_panel, as_of=T)
    assert res.as_of == pd.Timestamp(T)
    assert list(res.blocks.columns) == ["oversold", "valuation", "fundamental"]
    eq = res.blocks.loc["EQ"]
    assert eq.notna().all() and ((eq >= 0) & (eq <= 100)).all()


def test_pit_no_leakage_from_future_rows(mini_config, mini_panel):
    """기준일 이후 기준일의 값, 그리고 기준일 이전 기준일이라도 as_of 가 기준일 이후인 값을 바꿔도 점수 불변."""
    eng = ScoringEngine(mini_config)
    base = eng.score(mini_panel, as_of=T)
    p = mini_panel.copy()
    t = pd.Timestamp(T)
    future = pd.to_datetime(p["date"]) > t
    p.loc[future, "value"] = p.loc[future, "value"] * 7.3 + 11
    # 6월 말 기준 월별값은 as_of 가 7월 초(5일 지연) → 기준일엔 몰랐던 값
    late = (pd.to_datetime(p["date"]) <= t) & (pd.to_datetime(p["as_of"]) > t)
    assert late.any()
    p.loc[late, "value"] = p.loc[late, "value"] * 100
    alt = eng.score(p, as_of=T)
    pd.testing.assert_frame_equal(base.blocks, alt.blocks)
    pd.testing.assert_frame_equal(base.contributions, alt.contributions)


def test_history_equals_cut_score(mini_config, mini_panel):
    """전체 이력 계산의 t 시점 값 = t 까지만 잘라 계산한 값(미래 정보가 이력 계산에 섞이지 않음)."""
    eng = ScoringEngine(mini_config)
    full = eng.score_history(mini_panel)["EQ"].blocks.loc[T]
    cut = eng.score(mini_panel, as_of=T).blocks.loc["EQ"]
    pd.testing.assert_series_equal(full, cut, check_names=False)


def test_missing_block_gives_partial_regime_and_coverage(mini_config, mini_panel):
    p = mini_panel[mini_panel["field"] != "pbr"]
    res = ScoringEngine(mini_config).score(p, as_of=T)
    assert np.isnan(res.blocks.at["EQ", "valuation"])
    assert res.regime.at["EQ", "partial"] is True or res.regime.at["EQ", "partial"] == True  # noqa: E712
    assert res.regime.at["EQ", "v"] is None
    cov = res.coverage.set_index(["asset_id", "indicator"])
    assert cov.at[("EQ", "pbr"), "reason"] == "missing_field:pbr"
    assert cov.at[("EQ", "rev_ratio"), "reason"] == "status:na_until_found"
    assert bool(cov.at[("EQ", "disparity_20"), "used"])


def test_direction_inversion_in_scores(mini_config, mini_panel):
    res = ScoringEngine(mini_config).score(mini_panel, as_of=T)
    c = res.contributions.set_index(["asset_id", "indicator"])
    r = c.loc[("EQ", "disparity_20")]       # direction '-'
    assert r["score"] == pytest.approx(100 - r["percentile"])
    r = c.loc[("EQ", "eps_chg_1m")]         # direction '+'
    assert r["score"] == pytest.approx(r["percentile"])


def test_contributions_sum_to_block(mini_config, mini_panel):
    res = ScoringEngine(mini_config).score(mini_panel, as_of=T)
    c = res.contributions[res.contributions["asset_id"] == "EQ"]
    for blk, g in c.groupby("block"):
        assert g["contribution"].sum(min_count=1) == pytest.approx(res.blocks.at["EQ", blk])


def test_ref_field_is_used(mini_config, mini_panel):
    res = ScoringEngine(mini_config).score(mini_panel, as_of=T)
    cov = res.coverage.set_index(["asset_id", "indicator"])
    assert bool(cov.at[("EQ", "ccy_shock"), "used"])     # FX.close 를 fx_home 으로 빌려 씀
    assert cov.at[("FX", "ccy_shock"), "reason"] == "missing_field:fx_home"


@pytest.mark.parametrize("variant,dropped", [("oversold_only", "ccy_trend"), ("fundamental_only", "ccy_shock")])
def test_currency_variants(mini_universe, mini_profiles, scoring_cfg, mini_panel, variant, dropped):
    cfg = build_config(mini_universe, mini_profiles, {**scoring_cfg, "currency_variant": variant})
    cov = ScoringEngine(cfg).score(mini_panel, as_of=T).coverage.set_index(["asset_id", "indicator"])
    assert cov.at[("EQ", dropped), "reason"] == f"currency_variant:{variant}"
    kept = {"ccy_trend", "ccy_shock"} - {dropped}
    assert bool(cov.at[("EQ", kept.pop()), "used"])


def test_override_exclude_and_unknown_name(mini_universe, mini_profiles, scoring_cfg, mini_panel):
    u = copy.deepcopy(mini_universe)
    u[0]["overrides"] = {"exclude": ["fundamental.macro", "rsi_14"]}
    cfg = build_config(u, mini_profiles, scoring_cfg)
    cov = ScoringEngine(cfg).score(mini_panel, as_of=T).coverage.set_index(["asset_id", "indicator"])
    assert cov.at[("EQ", "ccy_trend"), "reason"].startswith("override_exclude")
    assert cov.at[("EQ", "rsi_14"), "reason"].startswith("override_exclude")
    u[0]["overrides"] = {"exclude": ["no_such_indicator"]}
    with pytest.raises(ConfigError, match="exclude"):
        build_config(u, mini_profiles, scoring_cfg)


def test_weight_override_changes_block(mini_universe, mini_profiles, scoring_cfg, mini_panel):
    base = ScoringEngine(build_config(mini_universe, mini_profiles, scoring_cfg)).score(mini_panel, as_of=T)
    u = copy.deepcopy(mini_universe)
    u[0]["overrides"] = {"weights": {"rsi_14": 3.0, "oversold.fx": 0.0}}
    res = ScoringEngine(build_config(u, mini_profiles, scoring_cfg)).score(mini_panel, as_of=T)
    c = res.contributions.set_index(["asset_id", "indicator"])
    d20, r14 = c.loc[("EQ", "disparity_20"), "score"], c.loc[("EQ", "rsi_14"), "score"]
    assert res.blocks.at["EQ", "oversold"] == pytest.approx((d20 + 3 * r14) / 4)
    assert res.blocks.at["EQ", "oversold"] != pytest.approx(base.blocks.at["EQ", "oversold"])


def test_insufficient_history_reported(mini_config, mini_panel):
    res = ScoringEngine(mini_config).score(mini_panel, as_of="2011-06-30")
    cov = res.coverage.set_index(["asset_id", "indicator"])
    assert cov.at[("EQ", "disparity_20"), "reason"] == "insufficient_history"
    assert res.blocks.loc["EQ"].isna().all() and res.regime.at["EQ", "label"] is None


REG = {"threshold": 50, "matrix": [
    {"o": "high", "v": "high", "f": "high", "label": "최우선 매수"},
    {"o": "high", "v": "high", "f": "low", "label": "저평가 패닉 분할 진입"},
    {"o": "high", "v": "low", "f": "high", "label": "단기 반등 트레이드"},
    {"o": "high", "v": "low", "f": "low", "label": "가치함정 경계"},
    {"o": "low", "v": "high", "f": "high", "label": "보유 분할 매수"},
    {"o": "low", "v": None, "f": "low", "label": "고점 경계"},
    {"o": "low", "v": "low", "f": None, "label": "비중 축소"}]}


@pytest.mark.parametrize("o,v,f,label", [
    (80, 80, 80, "최우선 매수"), (80, 80, 20, "저평가 패닉 분할 진입"), (80, 20, 80, "단기 반등 트레이드"),
    (80, 20, 20, "가치함정 경계"), (20, 80, 80, "보유 분할 매수"), (20, 80, 20, "고점 경계"),
    (20, 20, 20, "고점 경계"), (20, 20, 80, "비중 축소"), (50, 50, 50, "최우선 매수")])
def test_regime_matrix_full(o, v, f, label):
    r = regime({"oversold": o, "valuation": v, "fundamental": f}, REG)
    assert r["label"] == label and r["partial"] is False


def test_regime_partial_unique_and_abbreviated():
    r = regime({"oversold": 20, "valuation": np.nan, "fundamental": 20}, REG)
    assert r["label"] == "고점 경계" and r["partial"] is True
    r = regime({"oversold": 80, "valuation": np.nan, "fundamental": 80}, REG)
    assert r["label"].startswith("축약:") and r["partial"] is True
    r = regime({"oversold": np.nan, "valuation": np.nan, "fundamental": np.nan}, REG)
    assert r["label"] is None


def test_to_json_schema(mini_config, mini_panel):
    res = ScoringEngine(mini_config).score(mini_panel, as_of=T)
    d = json.loads(res.to_json())
    assert d["schema_version"] == "1.2" and d["as_of"] == T
    a = {x["asset_id"]: x for x in d["assets"]}["EQ"]
    assert set(a) == {"asset_id", "date", "stale", "blocks", "bands", "regime", "staged_entry", "trend",
                      "contributions", "coverage"}
    assert set(a["regime"]) == {"label", "display", "partial", "states"}
    assert set(a["staged_entry"]) == {"flag", "oversold", "vol_ratio", "vol_indicator", "reason"}
    assert set(a["trend"]) == {"sign", "value", "months", "basis", "reason"}
    assert a["trend"]["basis"] == "현금 대비"
    assert a["date"] == T
    json.dumps(d, allow_nan=False)   # NaN 이 남아 있으면 실패


def test_ranking_is_descending(mini_config, mini_panel):
    res = ScoringEngine(mini_config).score(mini_panel, as_of=T)
    rk = res.ranking
    for blk in rk.columns:
        top = res.blocks[blk].idxmax()
        if not np.isnan(res.blocks[blk].max()):
            assert rk.at[top, blk] == 1


def test_repo_config_loads_and_all_functions_registered():
    cfg = load_config(ROOT / "config")
    assert len(cfg.universe) == 10
    for a in cfg.universe:
        defs, _, _ = cfg.indicator_defs(a)
        for d in defs:
            assert d.func.n_inputs == len(d.fields)


def test_new_asset_via_config_only(scoring_cfg):
    """기존 자산군 프로파일을 쓰는 새 자산은 코드 수정 없이 universe 항목만으로 점수가 나온다."""
    import yaml
    profiles = {}
    for p in sorted((ROOT / "config" / "profiles").glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        profiles[d["asset_class"]] = d
    cfg = build_config([{"asset_id": "NEWCMD", "asset_class": "commodity"}], profiles, scoring_cfg)
    s = synth_daily(seed=9)
    panel = pd.concat([to_panel("NEWCMD", "close", s), to_panel("NEWCMD", "close_c2", s * 1.01)], ignore_index=True)
    res = ScoringEngine(cfg).score(panel, as_of="2015-12-31")
    assert not np.isnan(res.blocks.at["NEWCMD", "oversold"])
    assert not np.isnan(res.blocks.at["NEWCMD", "fundamental"])
    assert np.isnan(res.blocks.at["NEWCMD", "valuation"])   # cpi 없음 → N/A
    assert res.regime.at["NEWCMD", "partial"]


def test_field_transform_reciprocal(scoring_cfg, mini_profiles):
    u = [{"asset_id": "FX", "asset_class": "equity_index", "field_transforms": {"close": "reciprocal"}},
         {"asset_id": "FX2", "asset_class": "equity_index"}]
    cfg = build_config(u, mini_profiles, scoring_cfg)
    s = synth_daily(seed=5)
    panel = pd.concat([to_panel("FX", "close", s), to_panel("FX2", "close", 1.0 / s)], ignore_index=True)
    res = ScoringEngine(cfg).score(panel, as_of="2015-06-30")
    c = res.contributions.set_index(["asset_id", "indicator"])
    assert c.at[("FX", "disparity_20"), "score"] == pytest.approx(c.at[("FX2", "disparity_20"), "score"])


def test_bad_config_rejected(mini_universe, mini_profiles, scoring_cfg):
    p = copy.deepcopy(mini_profiles)
    p["equity_index"]["blocks"]["valuation"]["multiples"][0]["direction"] = "up"
    with pytest.raises(ConfigError, match="direction"):
        build_config(mini_universe, p, scoring_cfg)
    p = copy.deepcopy(mini_profiles)
    p["equity_index"]["blocks"]["valuation"]["multiples"][0]["params"] = {"window": 3}
    with pytest.raises(ConfigError, match="params"):
        build_config(mini_universe, p, scoring_cfg)
    u = copy.deepcopy(mini_universe)
    u[0]["refs"] = {"fx_home": "NOPE.close"}
    with pytest.raises(ConfigError, match="refs"):
        build_config(u, mini_profiles, scoring_cfg)
