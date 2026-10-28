"""Phase 3 백테스트 — 합성 데이터 단위 테스트(테스트 전용, 결과 보고에 쓰지 않는다)."""
import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr

from conftest import synth_daily, to_panel
from mtscore import ScoringEngine, build_config
from mtscore.core import backtest as bt

H = [5, 21]


def test_forward_returns_hand_computed_and_start_after_t():
    idx = pd.bdate_range("2020-01-01", periods=10)
    lvl = pd.Series([100, 101, 103, 102, 105, 104, 106, 108, 107, 110.0], index=idx)
    ri = bt.return_index(bt.price_returns(lvl))
    f = bt.forward_returns(ri, [1, 3])
    assert f.at[idx[0], 1] == pytest.approx(101 / 100 - 1)       # 첫 수익은 t+1 의 것
    assert f.at[idx[2], 3] == pytest.approx(104 / 103 - 1)
    assert f[3].iloc[-3:].isna().all()                            # 끝의 h 행은 NaN
    # t+h 이후 값을 바꿔도 (t, t+h] 수익은 그대로
    lvl2 = lvl.copy()
    lvl2.iloc[6:] *= 3.0
    f2 = bt.forward_returns(bt.return_index(bt.price_returns(lvl2)), [1, 3])
    assert f2.at[idx[2], 3] == pytest.approx(f.at[idx[2], 3])


def test_forward_returns_missing_entry_or_exit_is_nan_and_gap_bridged():
    idx = pd.bdate_range("2020-01-01", periods=6)
    lvl = pd.Series([100, np.nan, 110, 121, np.nan, 133.1], index=idx)
    ri = bt.return_index(bt.price_returns(lvl))
    f = bt.forward_returns(ri, [2], valid=lvl.notna())
    assert f.at[idx[0], 2] == pytest.approx(0.10)     # 결측일을 건너 100 → 110
    assert np.isnan(f.at[idx[1], 2])                  # 진입일 결측
    assert np.isnan(f.at[idx[2], 2])                  # 청산일 결측


def test_duration_returns_step():
    idx = pd.bdate_range("2020-01-01", periods=4)
    y = pd.Series([3.0, 3.0, 3.5, 3.5], index=idx)
    r = bt.duration_returns(y, 8.5, 252)
    assert r.iloc[0] == 0.0
    assert r.iloc[1] == pytest.approx(3.0 / 100 / 252)
    assert r.iloc[2] == pytest.approx(-8.5 * 0.5 / 100 + 3.0 / 100 / 252)
    assert r.iloc[3] == pytest.approx(3.5 / 100 / 252)


def test_mae_hand_and_bounded_by_terminal():
    idx = pd.bdate_range("2020-01-01", periods=6)
    lvl = pd.Series([100, 95, 90, 98, 104, 101.0], index=idx)
    ri = bt.return_index(bt.price_returns(lvl))
    m = bt.forward_mae(ri, [3])
    f = bt.forward_returns(ri, [3])
    assert m.at[idx[0], 3] == pytest.approx(0.90 - 1)
    assert m.at[idx[2], 3] == pytest.approx(98 / 90 - 1)          # 역행 없음 → 최소 상승
    ok = f[3].notna()
    assert (m[3][ok] <= f[3][ok] + 1e-12).all()
    assert m[3].iloc[-3:].isna().all()


def test_event_cooldown():
    idx = pd.bdate_range("2020-01-01", periods=60)
    c = pd.Series(False, index=idx)
    c.iloc[[3, 4, 10, 30, 31, 52]] = True        # 진입: 3, 10, 30, 52
    ev = bt.event_dates(c, cooldown=20)
    assert list(ev) == [idx[3], idx[30], idx[52]]   # 10 은 3 뒤 7일 → 버림, 52 는 30 뒤 22일 → 채택


def test_newey_west_lag0_is_iid_and_ic_matches_spearman():
    rng = np.random.default_rng(0)
    u = rng.normal(size=500)
    assert bt.newey_west_se(u, 0) == pytest.approx(u.std(ddof=0) / np.sqrt(len(u)))
    idx = pd.bdate_range("2015-01-01", periods=400)
    x = pd.Series(rng.normal(size=400), index=idx)
    y = 0.3 * x + pd.Series(rng.normal(size=400), index=idx)
    r = bt.spearman_ic(x, y, 1)
    assert r["ic"] == pytest.approx(spearmanr(x, y)[0], abs=1e-12)
    assert r["n"] == 400 and r["n_nonoverlap"] == 400
    r5 = bt.spearman_ic(x, y, 5)
    assert r5["n_nonoverlap"] == 80
    # 자기상관이 있으면 NW 표준오차가 커진다(t 감소)
    xs = x.rolling(20, min_periods=1).mean()
    ys = y.rolling(20, min_periods=1).mean()
    assert abs(bt.spearman_ic(xs, ys, 20)["t_nw"]) < abs(bt.spearman_ic(xs, ys, 1)["t_nw"])


def test_pooled_ic_single_asset_equals_ic():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2015-01-01", periods=300)
    x = pd.Series(rng.normal(size=300), index=idx)
    y = x + pd.Series(rng.normal(size=300), index=idx)
    assert bt.pooled_ic([(x, y)], 5)["ic"] == pytest.approx(bt.spearman_ic(x, y, 5)["ic"])


def test_ret_stats_warning():
    idx = pd.bdate_range("2020-01-01", periods=9)
    s = bt.ret_stats(pd.Series(np.linspace(-0.1, 0.1, 9), index=idx), None, 1)
    assert s["n"] == 9 and s["warning"] == "표본 부족"
    assert s["hit_rate"] == pytest.approx(4 / 9)


def test_trend_up_is_causal():
    s = synth_daily(end="2012-12-31", seed=5)
    a = bt.trend_up(s, 50)
    s2 = s.copy()
    s2.iloc[400:] *= 2.0
    b = bt.trend_up(s2, 50)
    pd.testing.assert_series_equal(a.iloc[:400], b.iloc[:400])
    assert a.iloc[:49].isna().all()


# ---- 엔진 수준 계약
def test_engine_backtest_no_lookahead(mini_config, mini_panel):
    eng = ScoringEngine(mini_config)
    res = eng.backtest(mini_panel, horizons=H, asset_ids=["EQ"], placebo=0)
    t = pd.Timestamp("2014-06-30")
    fr = res.forward["EQ"]
    close = mini_panel[(mini_panel.asset_id == "EQ") & (mini_panel.field == "close")].set_index("date")["value"]
    cal = res.history["EQ"].blocks.index
    i = cal.get_loc(t)
    assert fr.at[t, "fwd_21"] == pytest.approx(close[cal[i + 21]] / close[t] - 1)
    # as_of > t 인 행을 바꾸면: t 의 점수는 그대로, forward return 은 바뀐다
    p = mini_panel.copy()
    late = p["as_of"] > t
    p.loc[late, "value"] = p.loc[late, "value"] * 1.7
    res2 = eng.backtest(p, horizons=H, asset_ids=["EQ"], placebo=0)
    pd.testing.assert_series_equal(res.history["EQ"].blocks.loc[t], res2.history["EQ"].blocks.loc[t])
    assert res2.forward["EQ"].at[t, "fwd_21"] != pytest.approx(fr.at[t, "fwd_21"])
    # date > t+h 인 행을 바꾸면 fwd(t, h) 그대로
    p = mini_panel.copy()
    far = p["date"] > cal[i + 21]
    p.loc[far, "value"] = p.loc[far, "value"] * 1.7
    res3 = eng.backtest(p, horizons=H, asset_ids=["EQ"], placebo=0)
    assert res3.forward["EQ"].at[t, "fwd_21"] == pytest.approx(fr.at[t, "fwd_21"])


def test_engine_backtest_tables_carry_n(mini_config, mini_panel):
    res = ScoringEngine(mini_config).backtest(mini_panel, horizons=H, asset_ids=["EQ"], placebo=0)
    for df in (res.quantiles, res.bands, res.events, res.ic, res.regimes, res.pooled_bands):
        assert "n" in df.columns and len(df)
    assert set(res.bands["band"]) == {"all", ">=90", ">=75", "<=25", "<=10"}
    assert (res.events.loc[res.events["n"] < 10, "warning"] == "표본 부족").all()
    full = res.ic[res.ic.period == "full"]
    assert set(full["block"]) <= {"oversold", "valuation", "fundamental"}
    assert len(res.event_list) == res.events.groupby(["block", "band"])["n"].max().sum()


def test_engine_return_rules(mini_profiles, scoring_cfg):
    """역수 변환(원화 매수 관점)과 duration_approx(금리 필드) 수익률 규칙."""
    uni = [{"asset_id": "FXR", "asset_class": "equity_index", "field_transforms": {"close": "reciprocal"}},
           {"asset_id": "BND", "asset_class": "equity_index", "return_field": "duration_approx", "duration": 5.0,
            "return_yield_field": "yld"}]
    cfg = build_config(uni, mini_profiles, scoring_cfg)
    px = synth_daily(end="2011-12-31", seed=7, s0=1100.0)
    yl = synth_daily(end="2011-12-31", seed=8, s0=3.0, vol=0.01)
    panel = pd.concat([to_panel("FXR", "close", px), to_panel("BND", "close", px), to_panel("BND", "yld", yl)],
                      ignore_index=True)
    eng = ScoringEngine(cfg)
    idx, valid, rule = eng.return_index(panel, cfg.asset("FXR"))
    t0, t1 = px.index[10], px.index[31]
    assert idx[t1] / idx[t0] - 1 == pytest.approx(px[t0] / px[t1] - 1)
    assert "역수" in rule
    idx, valid, rule = eng.return_index(panel, cfg.asset("BND"))
    d = bt.duration_returns(yl, 5.0, 252)
    assert idx[t1] / idx[t0] - 1 == pytest.approx(np.prod(1 + d.loc[t0:t1].iloc[1:]) - 1)


def test_bh_fdr_known_values():
    q = bt.bh_fdr([0.01, 0.04, 0.03, np.nan, 0.5])
    assert q[0] == pytest.approx(0.04) and q[2] == pytest.approx(0.04 * 4 / 3) and q[1] == pytest.approx(0.04 * 4 / 3)
    assert np.isnan(q[3]) and q[4] == pytest.approx(0.5)


def test_placebo_signal_vs_null():
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2010-01-01", periods=1500)
    x = pd.Series(rng.normal(size=1500), index=idx).rolling(40, min_periods=1).mean()
    noise = pd.Series(rng.normal(size=1500), index=idx)
    good = {5: (0.5 * x + 0.1 * noise)}
    shifts = bt.shift_draws(1500, 300, 0)
    assert ((shifts >= 252) & (shifts < 1500 - 252)).all()
    o, P = bt.placebo_ic(x, good, shifts)
    assert o[0] == pytest.approx(bt.spearman_ic(x, good[5], 5)["ic"])
    assert bt.placebo_p(o, P)[0] < 0.01
    o0, P0 = bt.placebo_ic(x, {5: noise}, shifts)
    assert bt.placebo_p(o0, P0)[0] > 0.01
    po, PP = bt.pooled_placebo_ic([(x, good)], shifts[:20])
    assert po[0] == pytest.approx(o[0]) and PP.shape == (20, 1)


def test_engine_backtest_placebo_columns(mini_config, mini_panel):
    res = ScoringEngine(mini_config).backtest(mini_panel, horizons=H, asset_ids=["EQ"], placebo=30)
    full = res.ic[res.ic.period == "full"]
    assert full["p_placebo"].between(0, 1).all() and full["q_placebo"].notna().all()
    assert res.ic.loc[res.ic.period != "full", "p_placebo"].isna().all()
    assert set(res.ic_cells["block"]) == set(full["block"]) and "q_cell" in res.ic_cells
    assert "p_placebo" in res.pooled_ic
