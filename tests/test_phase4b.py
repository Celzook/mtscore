"""Phase 4 B(사전 등록 2026-10-29): 조건부 변동성 지표·분할 진입 표시·추세 표시. 합성 데이터는 테스트 전용."""
import copy

import numpy as np
import pandas as pd
import pytest

from conftest import ROOT, synth_daily, to_panel
from mtscore import ConfigError, ScoringEngine, build_config
from mtscore.core import backtest as bt
from mtscore.core.registry import get_func
from mtscore.core.scoring import staged_entry_flag

T = "2015-06-30"


def f(name, *s, **kw):
    spec = get_func(name)
    return spec.func(*s, **{**spec.defaults, **kw})


# ---- B1. 조건부 변동성 지표
@pytest.fixture
def px():
    return synth_daily(seed=21, vol=0.012)


def test_rv_ratio_if_oversold_equals_rv_on_lower_break_else_one(px):
    out = f("rv_ratio_if_oversold", px, oversold_side="lower", pctb_edge=0.0)
    rv = f("rv_ratio", px, window=20, lookback=252)
    pb = f("bb_pctb", px, window=20, k=2.0)
    ok = pb.notna() & rv.notna()
    brk, calm = ok & (pb < 0), ok & (pb >= 0)
    assert brk.sum() > 20 and calm.sum() > 200
    pd.testing.assert_series_equal(out[brk], rv[brk], check_names=False)
    assert (out[calm] == 1.0).all()
    assert out[~ok].isna().all()


def test_conditional_nan_propagation(px):
    x = px.copy()
    x.iloc[600] = np.nan   # %b 는 20일 창 전체가 NaN, rv 는 min_periods 0.8 이라 값이 남는 날이 생긴다
    out = f("rv_ratio_if_oversold", x, oversold_side="lower", pctb_edge=0.0)
    pb = f("bb_pctb", x, window=20, k=2.0)
    rv = f("rv_ratio", x, window=20, lookback=252)
    pb_only_nan = pb.isna() & rv.notna()
    assert pb_only_nan.sum() > 0 and out[pb_only_nan].isna().all()
    rv_only_nan = rv.isna() & pb.notna()   # 앞쪽 lookback 워밍업
    assert rv_only_nan.sum() > 0 and out[rv_only_nan].isna().all()


def test_band_side_param_on_level_series():
    y = pd.Series(3.0 + np.cumsum(np.random.default_rng(5).normal(0, 0.03, 1500)), index=pd.bdate_range("2010-01-01", periods=1500))
    up = f("level_rv_ratio_if_oversold", y, oversold_side="upper", pctb_edge=1.0)
    lo = f("level_rv_ratio_if_oversold", y, oversold_side="lower", pctb_edge=0.0)
    rv = f("level_rv_ratio", y, window=20, lookback=252)
    pb = f("bb_pctb", y, window=20, k=2.0)
    ok = pb.notna() & rv.notna()
    hi, low = ok & (pb > 1), ok & (pb < 0)
    assert hi.sum() > 10 and low.sum() > 10
    pd.testing.assert_series_equal(up[hi], rv[hi], check_names=False)
    assert (up[ok & ~hi] == 1.0).all()
    pd.testing.assert_series_equal(lo[low], rv[low], check_names=False)
    assert (lo[ok & ~low] == 1.0).all()
    # 기본값: level 판은 upper·1, 가격판은 lower·0
    pd.testing.assert_series_equal(f("level_rv_ratio_if_oversold", y), up)


def test_neutral_param_and_bad_side(px):
    out = f("rv_ratio_if_oversold", px, neutral=2.5)
    pb = f("bb_pctb", px, window=20, k=2.0)
    calm = out.notna() & (pb >= 0)
    assert (out[calm] == 2.5).all()
    with pytest.raises(ValueError, match="oversold_side"):
        f("rv_ratio_if_oversold", px, oversold_side="below")


def test_conditional_indicator_in_profile_via_config(scoring_cfg):
    """프로파일 params 로 band side 를 지정해 엔진에서 점수가 나온다(코드 수정 없이 설정만)."""
    prof = {"commodity": {"asset_class": "commodity", "blocks": {"oversold": {"volatility": [
        {"name": "rv_cond", "indicator": "rv_ratio_if_oversold", "direction": "+", "fields": ["close"],
         "params": {"window": 20, "lookback": 252, "bb_window": 20, "bb_k": 2, "oversold_side": "lower",
                    "pctb_edge": 0, "neutral": 1.0}}]}}}}
    sc = copy.deepcopy(scoring_cfg)
    sc["sub_block_agg"] = {}
    cfg = build_config([{"asset_id": "C", "asset_class": "commodity"}], prof, sc)
    h = ScoringEngine(cfg).score_history(to_panel("C", "close", synth_daily(seed=8)))["C"]
    assert h.raw["rv_cond"].eq(1.0).mean() > 0.5 and h.blocks["oversold"].notna().sum() > 500


# ---- 설정 검증
@pytest.mark.parametrize("sec,key,val,msg", [
    ("staged_entry", "oversold_min", 120, "oversold_min"),
    ("staged_entry", "oversold_min", "75", "oversold_min"),
    ("staged_entry", "vol_ratio_min", 0, "vol_ratio_min"),
    ("staged_entry", "vol_ratio_min", float("nan"), "vol_ratio_min"),
    ("staged_entry", "vol_functions", [], "vol_functions"),
    ("staged_entry", "vol_functions", ["no_such_func"], "vol_functions"),
    ("trend", "months", 0, "months"),
    ("trend", "months", 1.5, "months"),
    ("trend", "cash_field", "", "cash_field"),
    ("trend", "cash_days_per_year", -1, "cash_days_per_year"),
])
def test_display_config_values_rejected(mini_universe, mini_profiles, scoring_cfg, sec, key, val, msg):
    sc = copy.deepcopy(scoring_cfg)
    sc[sec][key] = val
    with pytest.raises(ConfigError, match=msg):
        build_config(mini_universe, mini_profiles, sc)


@pytest.mark.parametrize("sec", ["staged_entry", "trend"])
def test_display_config_unknown_or_missing_key(mini_universe, mini_profiles, scoring_cfg, sec):
    sc = copy.deepcopy(scoring_cfg)
    sc[sec]["typo"] = 1
    with pytest.raises(ConfigError, match="알 수 없는 키"):
        build_config(mini_universe, mini_profiles, sc)
    sc = copy.deepcopy(scoring_cfg)
    sc[sec].pop(next(iter(sc[sec])))
    with pytest.raises(ConfigError, match="빠진 키"):
        build_config(mini_universe, mini_profiles, sc)


# ---- B2. 분할 진입 표시
def test_staged_entry_flag_rule():
    assert staged_entry_flag(80.0, 1.6, 75, 1.5) is True
    assert staged_entry_flag(75.0, 1.5, 75, 1.5) is True      # 경계 포함(≥)
    assert staged_entry_flag(74.9, 3.0, 75, 1.5) is False
    assert staged_entry_flag(90.0, 1.49, 75, 1.5) is False
    assert staged_entry_flag(np.nan, 2.0, 75, 1.5) is None
    assert staged_entry_flag(90.0, np.nan, 75, 1.5) is None


def _commodity_engine(scoring_cfg, **se):
    import yaml
    profiles = {}
    for p in sorted((ROOT / "config" / "profiles").glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        profiles[d["asset_class"]] = d
    sc = copy.deepcopy(scoring_cfg)
    sc["staged_entry"].update(se)
    return ScoringEngine(build_config([{"asset_id": "CMD", "asset_class": "commodity"}], profiles, sc))


def test_staged_entry_in_result_is_score_neutral(scoring_cfg):
    s = synth_daily(seed=9)
    panel = pd.concat([to_panel("CMD", "close", s), to_panel("CMD", "close_c2", s * 1.01)], ignore_index=True)
    on = _commodity_engine(scoring_cfg, oversold_min=0, vol_ratio_min=1e-9).score(panel, as_of=T)
    off = _commodity_engine(scoring_cfg, vol_ratio_min=1e9).score(panel, as_of=T)
    a, b = on.staged_entry.loc["CMD"], off.staged_entry.loc["CMD"]
    assert a["vol_indicator"] == "rv_ratio_20" and a["reason"] == ""
    t = on.dates["CMD"]
    assert a["vol_ratio"] == pytest.approx(on.history["CMD"].raw.at[t, "rv_ratio_20"])
    assert a["flag"] is True and b["flag"] is False
    pd.testing.assert_frame_equal(on.blocks, off.blocks)
    pd.testing.assert_frame_equal(on.regime, off.regime)
    # 실제 임계값(75·1.5)으로 낸 표시는 규칙 그대로
    real = _commodity_engine(scoring_cfg).score(panel, as_of=T).staged_entry.loc["CMD"]
    assert real["flag"] is staged_entry_flag(on.blocks.at["CMD", "oversold"], a["vol_ratio"], 75, 1.5)


def test_staged_entry_na_reasons(mini_config, mini_panel, scoring_cfg):
    r = ScoringEngine(mini_config).score(mini_panel, as_of=T).staged_entry.loc["EQ"]
    assert r["flag"] is None and r["reason"] == "no_vol_indicator"   # mini 프로파일에는 변동성비 지표가 없다
    s = synth_daily(seed=9, end="2015-06-30")
    panel = pd.concat([to_panel("CMD", "close", s), to_panel("CMD", "close_c2", s * 1.01)], ignore_index=True)
    st = _commodity_engine(scoring_cfg).score(panel, as_of="2015-09-30")
    assert bool(st.stale["CMD"])
    r = st.staged_entry.loc["CMD"]
    assert r["flag"] is None and r["reason"] == "unavailable_at_as_of"


# ---- B3. 추세 표시
def test_tsmom_excess_hand_computed():
    cal = pd.bdate_range("2012-01-02", "2014-12-31")
    idx = pd.Series(1.0005 ** np.arange(len(cal)), index=cal)
    cash = pd.Series(3.0, index=cal)
    out = bt.tsmom_excess(idx, cash, 12, 252.0)
    t = pd.Timestamp("2014-06-16")
    lag = cal[cal <= t - pd.DateOffset(months=12)][-1]
    i_t, i_l = cal.get_loc(t), cal.get_loc(lag)
    exp = (1.0005 ** (i_t - i_l) - 1.0) - ((1 + 0.03 / 252) ** (i_t - i_l) - 1.0)
    assert out[t] == pytest.approx(exp, rel=1e-10)
    first = pd.Timestamp("2013-01-01")   # 첫 달력일 + 12개월 이전은 비교 시점이 없어 결측
    assert out[out.index < first].isna().all() and out[out.index >= pd.Timestamp("2013-01-03")].notna().all()
    gap = cash.copy()
    gap.loc["2014-03-03"] = np.nan   # 12개월 창 안의 금리 결측 → 결측(채우지 않음)
    assert np.isnan(bt.tsmom_excess(idx, gap, 12, 252.0)[t])


@pytest.fixture
def trend_setup(mini_profiles, scoring_cfg):
    u = [{"asset_id": "EQ", "asset_class": "equity_index", "refs": {"fx_home": "FX.close"}},
         {"asset_id": "FX", "asset_class": "equity_index"}]
    close = synth_daily(seed=1)
    rate = pd.Series(np.linspace(1.0, 2.5, len(close)), index=close.index)
    panel = pd.concat([to_panel("EQ", "close", close), to_panel("EQ", "policy_rate", rate),
                       to_panel("FX", "close", synth_daily(seed=4, s0=1100.0, vol=0.005))], ignore_index=True)
    return ScoringEngine(build_config(u, mini_profiles, scoring_cfg)), panel, close, rate


def test_trend_value_sign_and_missing_cash(trend_setup):
    eng, panel, close, rate = trend_setup
    res = eng.score(panel, as_of=T)
    tr = res.trend.loc["EQ"]
    t = pd.Timestamp(T)
    lag = close.index[close.index <= t - pd.DateOffset(months=12)][-1]
    w = close.index[(close.index > lag) & (close.index <= t)]
    cash = np.prod(1 + rate.shift(1)[w] / 100 / 252) - 1
    exp = close[t] / close[lag] - 1 - cash
    assert tr["value"] == pytest.approx(exp, rel=1e-9)
    assert tr["sign"] == int(np.sign(exp)) and tr["months"] == 12 and tr["reason"] == ""
    fx = res.trend.loc["FX"]
    assert fx["sign"] is None and np.isnan(fx["value"]) and fx["reason"] == "missing_field:policy_rate"
    d = res.to_dict()["assets"]
    assert {a["asset_id"]: a["trend"]["sign"] for a in d}["FX"] is None


def test_trend_pit_history_equals_cut_and_ignores_future_rows(trend_setup):
    eng, panel, close, rate = trend_setup
    full = eng.trend_history(panel, ["EQ"])["EQ"]
    cut = eng.trend_history(panel, ["EQ"], as_of=T)["EQ"]
    assert full.at[pd.Timestamp(T), "value"] == pytest.approx(cut.at[pd.Timestamp(T), "value"], rel=1e-12)
    fut = panel.copy()
    m = (fut["date"] > T) & (fut["asset_id"] == "EQ")
    fut.loc[m, "value"] = fut.loc[m, "value"] * 3.0   # 미래 가격·금리를 바꿔도 t 값 불변
    alt = eng.trend_history(fut, ["EQ"])["EQ"]
    pd.testing.assert_series_equal(full["value"][:T], alt["value"][:T])
    assert not np.allclose(full["value"]["2016":].dropna(), alt["value"]["2016":].dropna())


def test_trend_does_not_change_scores(trend_setup, scoring_cfg, mini_profiles):
    eng, panel, *_ = trend_setup
    sc = copy.deepcopy(scoring_cfg)
    sc.pop("trend")
    sc.pop("staged_entry")
    eng2 = ScoringEngine(build_config([{"asset_id": "EQ", "asset_class": "equity_index", "refs": {"fx_home": "FX.close"}},
                                       {"asset_id": "FX", "asset_class": "equity_index"}], mini_profiles, sc))
    a, b = eng.score(panel, as_of=T), eng2.score(panel, as_of=T)
    pd.testing.assert_frame_equal(a.blocks, b.blocks)
    pd.testing.assert_frame_equal(a.regime, b.regime)
    assert b.trend.at["EQ", "reason"] == "trend 설정 없음" and b.staged_entry.at["EQ", "reason"] == "staged_entry 설정 없음"
