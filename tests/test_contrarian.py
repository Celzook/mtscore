"""역발상 기술 지표(사용자 결정 2026-10-28) 회귀 테스트: bb_pctb·rv_ratio·level_rv_ratio, 하위블록 min 집계,
sub_block_agg 설정 검증, min 하위블록 기여도, 저장소 프로파일 로딩. 합성 데이터는 테스트 전용."""
import copy
import logging

import numpy as np
import pandas as pd
import pytest

from conftest import ROOT
from mtscore import ConfigError, ScoringEngine, build_config, load_config
from mtscore.core import indicators  # noqa: F401
from mtscore.core.registry import get_func
from mtscore.core.scoring import score_asset

T = "2015-06-30"
idx = pd.bdate_range("2020-01-01", periods=400)


def f(name, *s, **kw):
    spec = get_func(name)
    return spec.func(*s, **{**spec.defaults, **kw})


# ---- bb_pctb
def test_bb_pctb_hand_value_and_warmup():
    x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0], index=idx[:5])
    sd = np.sqrt(2.5)                                   # ddof=1: 표본분산 (4+1+0+1+4)/4
    out = f("bb_pctb", x, window=5, k=2.0)
    assert out.iloc[-1] == pytest.approx((5.0 - (3.0 - 2.0 * sd)) / (4.0 * sd))
    assert out.iloc[:-1].isna().all()                   # min_periods = window


def test_bb_pctb_band_edges_pin_ddof1():
    k = 19 / np.sqrt(20)        # 19개 동일값 + 이탈값 1개: ddof=1 이면 이탈값의 z = ±19/√20
    lo = pd.Series(np.r_[np.full(19, 10.0), 7.0], index=idx[:20])
    hi = pd.Series(np.r_[np.full(19, 10.0), 13.0], index=idx[:20])
    assert f("bb_pctb", lo, window=20, k=k).iloc[-1] == pytest.approx(0.0, abs=1e-12)   # 하단 밴드 = 0
    assert f("bb_pctb", hi, window=20, k=k).iloc[-1] == pytest.approx(1.0)              # 상단 밴드 = 1
    # ddof=0 이었다면 z = √19 이므로 k=√19 에서 0 이 됐을 것 — ddof=1 에서는 0 이 아니다
    assert f("bb_pctb", lo, window=20, k=np.sqrt(19)).iloc[-1] != pytest.approx(0.0, abs=1e-6)


def test_bb_pctb_at_ma_is_half_and_flat_is_nan():
    at_ma = pd.Series(np.r_[[9.0, 11.0] * 9, 10.0, 10.0], index=idx[:20])   # 평균 10, 마지막 값 10
    assert f("bb_pctb", at_ma, window=20, k=2.0).iloc[-1] == pytest.approx(0.5)
    flat = pd.Series(5.0, index=idx[:30])
    assert f("bb_pctb", flat, window=20, k=2.0).isna().all()                 # σ == 0 → NaN


def test_bb_pctb_works_on_level_series():
    """가산형: 수준 이동(음수 금리 포함)에 불변."""
    rng = np.random.default_rng(3)
    y = pd.Series(np.cumsum(rng.normal(0, 0.05, 300)), index=idx[:300])
    a, b = f("bb_pctb", y), f("bb_pctb", y - 5.0)
    pd.testing.assert_series_equal(a, b, rtol=1e-9)
    assert a.notna().sum() == 300 - 19


# ---- rv_ratio / level_rv_ratio
def test_rv_ratio_hand_value():
    rng = np.random.default_rng(7)
    x = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 40))), index=idx[:40])
    out = f("rv_ratio", x, window=5, lookback=10)        # min_periods: rv 4, 평균 8
    r = np.diff(np.log(x.to_numpy()))                    # r[j] = 날짜 j+1 의 로그수익률
    rv = {i: np.std(r[i - 5:i], ddof=1) * np.sqrt(252) for i in range(5, 40)}   # 날짜 i 의 rv(창 5)
    i = 39
    assert out.iloc[i] == pytest.approx(rv[i] / np.mean([rv[j] for j in range(i - 9, i + 1)]))


def test_rv_ratio_scale_invariant_and_constant_vol_is_one():
    rng = np.random.default_rng(8)
    x = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400))), index=idx)
    pd.testing.assert_series_equal(f("rv_ratio", x), f("rv_ratio", 3.0 * x), rtol=1e-9)
    alt = pd.Series(100 * np.exp(np.cumsum(np.tile([0.01, -0.01], 200))), index=idx)   # 실현변동성 일정
    r = f("rv_ratio", alt, window=20, lookback=60)
    assert r.iloc[100:].to_numpy() == pytest.approx(1.0)  # 창이 모두 꽉 찬 뒤(앞쪽은 min_periods 부분 창)


def test_level_rv_ratio_hand_value_and_vol_spike():
    rng = np.random.default_rng(9)
    y = pd.Series(np.cumsum(rng.normal(0, 0.05, 40)), index=idx[:40])
    out = f("level_rv_ratio", y, window=5, lookback=10)
    d = np.diff(y.to_numpy())
    vol = {i: np.std(d[i - 5:i], ddof=1) for i in range(5, 40)}
    i = 39
    assert out.iloc[i] == pytest.approx(vol[i] / np.mean([vol[j] for j in range(i - 9, i + 1)]))
    pd.testing.assert_series_equal(f("level_rv_ratio", y + 2.0, window=5, lookback=10), out, rtol=1e-9)
    steps = np.r_[np.tile([0.01, -0.01], 150), np.tile([0.04, -0.04], 50)]            # 마지막 100일 변동성 4배
    lvl = pd.Series(np.cumsum(steps), index=idx)
    r = f("level_rv_ratio", lvl, window=20, lookback=252)
    assert r.iloc[299] == pytest.approx(1.0, abs=1e-4) and r.iloc[-1] > 1.5   # 앞쪽 min_periods 부분 창 영향 ≤ 1e-4


# ---- 하위블록 min 집계 (mini_profiles 의 oversold.price = disparity_20, rsi_14)
def _min_cfg(mini_universe, mini_profiles, scoring_cfg, overrides=None):
    sc = copy.deepcopy(scoring_cfg)
    sc["sub_block_agg"] = {"oversold.price": "min"}
    u = copy.deepcopy(mini_universe)
    if overrides:
        u[0]["overrides"] = overrides
    return build_config(u, mini_profiles, sc)


def test_min_sub_block_is_rowwise_min(mini_universe, mini_profiles, scoring_cfg, mini_panel):
    h = ScoringEngine(_min_cfg(mini_universe, mini_profiles, scoring_cfg)).score_history(mini_panel, ["EQ"])["EQ"]
    sub = h.sub_blocks[("oversold", "price")]
    d20, r14 = h.score["disparity_20"], h.score["rsi_14"]
    both = d20.notna() & r14.notna()
    pd.testing.assert_series_equal(sub[both], np.minimum(d20, r14)[both], check_names=False)
    assert (sub[both] <= (d20 + r14)[both] / 2 + 1e-12).all()
    assert h.sub_block_agg[("oversold", "price")] == "min"


def _two_level_defs():
    from mtscore.core.registry import IndicatorDef
    return [IndicatorDef(name=n, indicator="level", block="oversold", sub_block="conf", fields=(fl,), direction=1)
            for n, fl in (("ia", "a"), ("ib", "b"))]


def test_min_nan_rule_and_warmup_survivor_direct():
    """시작한 지표가 그날 결측이면 NaN, 아직 시작 전(워밍업)인 지표는 빼고 남은 지표 점수."""
    cal = pd.bdate_range("2010-01-01", "2016-12-30")
    rng = np.random.default_rng(11)
    a = pd.Series(rng.normal(size=len(cal)), index=cal)
    b = pd.Series(rng.normal(size=len(cal)), index=cal)
    b[:"2010-06-30"] = np.nan                            # b 는 늦게 시작 → 점수도 반년 늦게
    b["2015-03-02":"2015-03-31"] = np.nan                # 시작 후 결측 구간
    sc = {"sub_block_agg": {"oversold.conf": "min"}}
    h = score_asset(_two_level_defs(), {"a": a, "b": b}, cal, sc, "equity_index")
    sub, sa, sb = h.sub_blocks[("oversold", "conf")], h.score["ia"], h.score["ib"]
    warm = sa.notna() & ~sb.notna().cummax()             # b 시작 전
    assert warm.sum() > 50
    pd.testing.assert_series_equal(sub[warm], sa[warm], check_names=False)
    gap = cal[(cal >= "2015-03-02") & (cal <= "2015-03-31")]
    assert sub[gap].isna().all() and sa[gap].notna().all()          # 공동 조건: 하나라도 결측이면 NaN
    both = sa.notna() & sb.notna()
    pd.testing.assert_series_equal(sub[both], np.minimum(sa, sb)[both], check_names=False)
    assert np.isnan(h.blocks.loc[gap, "oversold"]).all()            # 유일한 하위블록 → 블록도 N/A


def test_min_history_equals_cut_during_warmup_gap(mini_universe, mini_profiles, scoring_cfg, mini_panel):
    """두 지표 워밍업 차이 구간의 날: 이력값 = 그날로 잘라 계산한 값(전체 이력 coverage 로 NaN 을 정하면 깨진다)."""
    cfg = _min_cfg(mini_universe, mini_profiles, scoring_cfg)
    h = ScoringEngine(cfg).score_history(mini_panel, ["EQ"])["EQ"]
    one = h.score["disparity_20"].isna() ^ h.score["rsi_14"].isna()
    days = h.score.index[one.to_numpy() & h.score["rsi_14"].notna().to_numpy()]
    assert len(days) > 0, "두 지표의 워밍업이 달라야 검사가 의미 있다"
    for t in (days[0], days[-1]):
        cut = ScoringEngine(cfg).score_history(mini_panel, ["EQ"], as_of=t)["EQ"]
        assert h.sub_blocks.at[t, ("oversold", "price")] == pytest.approx(cut.sub_blocks.at[t, ("oversold", "price")])
        assert h.sub_blocks.at[t, ("oversold", "price")] == pytest.approx(h.score.at[t, "rsi_14"])


def test_min_sub_block_single_survivor(mini_universe, mini_profiles, scoring_cfg, mini_panel):
    cfg = _min_cfg(mini_universe, mini_profiles, scoring_cfg, {"exclude": ["disparity_20"]})
    h = ScoringEngine(cfg).score_history(mini_panel, ["EQ"])["EQ"]
    pd.testing.assert_series_equal(h.sub_blocks[("oversold", "price")], h.score["rsi_14"], check_names=False)


def test_min_weight_override_rejected(mini_universe, mini_profiles, scoring_cfg):
    """min 하위블록 지표 가중치는 무시되므로 overrides.weights 로 지정하면 ConfigError(exclude 안내)."""
    for w in ({"rsi_14": 5}, {"disparity_20": 0}):
        with pytest.raises(ConfigError, match="overrides.exclude"):
            _min_cfg(mini_universe, mini_profiles, scoring_cfg, {"weights": w})
    _min_cfg(mini_universe, mini_profiles, scoring_cfg, {"weights": {"oversold.price": 2, "pbr": 3}})  # 하위블록·mean 지표는 허용


def test_min_item_weight_rejected(mini_universe, mini_profiles, scoring_cfg):
    """프로파일 항목이나 overrides.add 항목에 weight 를 직접 적어도 min 하위블록이면 ConfigError."""
    prof = copy.deepcopy(mini_profiles)
    prof["equity_index"]["blocks"]["oversold"]["price"][1]["weight"] = 0
    with pytest.raises(ConfigError, match="overrides.exclude"):
        _min_cfg(mini_universe, prof, scoring_cfg)
    item = {"name": "rsi_2x", "indicator": "rsi", "direction": "-", "fields": ["close"], "params": {"window": 2}}
    with pytest.raises(ConfigError, match="overrides.exclude"):
        _min_cfg(mini_universe, mini_profiles, scoring_cfg, {"add": {"oversold.price": [{**item, "weight": 3}]}})
    _min_cfg(mini_universe, mini_profiles, scoring_cfg, {"add": {"oversold.price": [item]}})   # weight 없으면 허용
    prof = copy.deepcopy(mini_profiles)
    prof["equity_index"]["blocks"]["valuation"]["multiples"][0]["weight"] = 2
    _min_cfg(mini_universe, prof, scoring_cfg)                                              # mean 하위블록은 허용


def test_min_ignores_indicator_weights_in_core():
    """build_config 를 거치지 않은 IndicatorDef.weight 도 min 집계에는 영향이 없다."""
    from dataclasses import replace
    cal = pd.bdate_range("2010-01-01", "2014-12-31")
    rng = np.random.default_rng(12)
    flds = {"a": pd.Series(rng.normal(size=len(cal)), index=cal), "b": pd.Series(rng.normal(size=len(cal)), index=cal)}
    sc = {"sub_block_agg": {"oversold.conf": "min"}}
    base = score_asset(_two_level_defs(), flds, cal, sc, "equity_index")
    heavy = score_asset([replace(d, weight=9.0 if d.name == "ia" else 0.0) for d in _two_level_defs()], flds, cal, sc,
                        "equity_index")
    pd.testing.assert_frame_equal(base.sub_blocks, heavy.sub_blocks)


def test_default_agg_is_weighted_mean(mini_config, mini_panel):
    h = ScoringEngine(mini_config).score_history(mini_panel, ["EQ"])["EQ"]
    both = h.score["disparity_20"].notna() & h.score["rsi_14"].notna()
    expected = ((h.score["disparity_20"] + h.score["rsi_14"]) / 2)[both]
    pd.testing.assert_series_equal(h.sub_blocks[("oversold", "price")][both], expected, check_names=False)
    assert h.sub_block_agg[("oversold", "price")] == "mean"


def test_min_contributions_binding_indicator(mini_universe, mini_profiles, scoring_cfg, mini_panel):
    res = ScoringEngine(_min_cfg(mini_universe, mini_profiles, scoring_cfg)).score(mini_panel, as_of=T)
    c = res.contributions[res.contributions.asset_id == "EQ"].set_index("indicator")
    d20, r14 = c.at["disparity_20", "score"], c.at["rsi_14", "score"]
    bind, other = ("disparity_20", "rsi_14") if d20 <= r14 else ("rsi_14", "disparity_20")
    n_live_subs = 2                                       # oversold: price, fx
    assert c.at[bind, "weight_in_block"] == pytest.approx(1 / n_live_subs)
    assert c.at[bind, "contribution"] == pytest.approx(min(d20, r14) / n_live_subs)
    assert c.at[other, "weight_in_block"] == 0.0 and c.at[other, "contribution"] == 0.0
    for blk, g in c.groupby("block"):
        assert g["contribution"].sum(min_count=1) == pytest.approx(res.blocks.at["EQ", blk])
    h = res.history["EQ"]
    assert h.sub_blocks.at[pd.Timestamp(T), ("oversold", "price")] == pytest.approx(min(d20, r14))


def test_min_contributions_when_sub_block_nan(mini_universe, mini_profiles, scoring_cfg, mini_panel):
    """기준일에 min 하위블록(oversold.fx = ccy_shock + disparity_5)의 지표 하나가 끊기면 하위블록 NaN →
    두 지표 모두 비중 0·기여도 NaN, 블록은 price 하위블록만으로 재정규화되고 기여도 합 = 블록."""
    sc = {**copy.deepcopy(scoring_cfg), "sub_block_agg": {"oversold.fx": "min"}}
    u = copy.deepcopy(mini_universe)
    u[0]["overrides"] = {"add": {"oversold.fx": [
        {"name": "disparity_5", "indicator": "disparity", "direction": "-", "fields": ["close"], "params": {"window": 5}}]}}
    cfg = build_config(u, mini_profiles, sc)
    p = mini_panel[~((mini_panel.asset_id == "FX") & (pd.to_datetime(mini_panel.date) > "2015-03-31"))]
    res = ScoringEngine(cfg).score(p, as_of=T)
    c = res.contributions[res.contributions.asset_id == "EQ"].set_index("indicator")
    assert np.isnan(c.at["ccy_shock", "score"]) and not np.isnan(c.at["disparity_5", "score"])
    for n in ("ccy_shock", "disparity_5"):
        assert c.at[n, "weight_in_block"] == 0.0 and np.isnan(c.at[n, "contribution"])
    g = c[c.block == "oversold"]
    assert res.blocks.at["EQ", "oversold"] == pytest.approx((c.at["disparity_20", "score"] + c.at["rsi_14", "score"]) / 2)
    assert g["contribution"].sum(min_count=1) == pytest.approx(res.blocks.at["EQ", "oversold"])


# ---- sub_block_agg 설정 검증
@pytest.mark.parametrize("agg,msg", [({"oversold.price": "max"}, "값 오류"), ({"price": "min"}, "block.sub_block"),
                                     ({"oversell.price": "min"}, "block.sub_block"), ({"oversold.": "min"}, "block.sub_block"),
                                     ({"oversold.price.x": "min"}, "block.sub_block"),
                                     ({"oversold.price ": "min"}, "block.sub_block"),
                                     ({" oversold.price": "min"}, "block.sub_block"),
                                     (["oversold.price"], "매핑")])
def test_sub_block_agg_rejected(mini_universe, mini_profiles, scoring_cfg, agg, msg):
    sc = {**copy.deepcopy(scoring_cfg), "sub_block_agg": agg}
    with pytest.raises(ConfigError, match=msg):
        build_config(mini_universe, mini_profiles, sc)


def test_sub_block_agg_unknown_sub_block_warns(mini_universe, mini_profiles, scoring_cfg, caplog):
    """scoring.yaml 은 자산군 공유 — 이 설정의 프로파일에 없는 하위블록 키는 오류가 아니라 경고."""
    sc = {**copy.deepcopy(scoring_cfg), "sub_block_agg": {"oversold.confluenc": "min"}}
    with caplog.at_level(logging.WARNING, logger="mtscore.config"):
        build_config(mini_universe, mini_profiles, sc)
    assert any("oversold.confluenc" in r.getMessage() for r in caplog.records)


def _repo_dicts():
    import yaml
    load = lambda p: yaml.safe_load(p.read_text(encoding="utf-8"))   # noqa: E731
    profiles = {d["asset_class"]: d for d in map(load, sorted((ROOT / "config" / "profiles").glob("*.yaml")))}
    return load(ROOT / "config" / "universe.yaml"), profiles, load(ROOT / "config" / "scoring.yaml")


def test_unknown_agg_key_is_error_on_full_load(tmp_path):
    """전 프로파일을 읽는 load_config 경로: 오타 키는 ConfigError."""
    import shutil
    import yaml
    shutil.copytree(ROOT / "config", tmp_path / "config")
    sc_path = tmp_path / "config" / "scoring.yaml"
    sc = yaml.safe_load(sc_path.read_text(encoding="utf-8"))
    sc["sub_block_agg"] = {"oversold.confluenc": "min"}
    sc_path.write_text(yaml.safe_dump(sc, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigError, match="oversold.confluenc"):
        load_config(tmp_path / "config")
    u, profiles, sc0 = _repo_dicts()
    with pytest.raises(ConfigError, match="oversold.confluenc"):
        build_config(u, profiles, {**sc0, "sub_block_agg": {"oversold.confluenc": "min"}}, strict_agg_keys=True)
    build_config(u, profiles, sc0, strict_agg_keys=True)   # 저장소 설정 자체는 strict 통과


def test_score_asset_rejects_bad_agg_directly():
    with pytest.raises(ValueError, match="sub_block_agg"):
        score_asset([], {}, idx[:5], {"sub_block_agg": {"oversold.x": "median"}}, "equity_index")


# ---- 저장소 설정
def test_repo_profiles_load_with_confluence_and_volatility():
    cfg = load_config(ROOT / "config")
    assert cfg.scoring["sub_block_agg"] == {"oversold.confluence": "min"}
    for cls in ("equity_index", "fx", "commodity", "rates", "credit"):
        ov = cfg.profiles[cls]["blocks"]["oversold"]
        names = {it["name"] for it in ov["confluence"]}
        assert names == {"bb_pctb_20", "rsi_14"}, cls
        assert all(it["name"] != "rsi_14" for it in ov.get("price", [])), cls
    for cls, name in (("fx", "rv_ratio_20"), ("commodity", "rv_ratio_20"), ("rates", "level_rv_ratio_20"),
                      ("credit", "level_rv_ratio_20")):
        assert [it["name"] for it in cfg.profiles[cls]["blocks"]["oversold"]["volatility"]] == [name]
    eq = cfg.profiles["equity_index"]["blocks"]["oversold"]
    assert "rv_ratio_20" in {it["name"] for it in eq["vol_sentiment"]}
    inst = next(it for it in eq["flows"] if it["name"] == "inst_net_buy_intensity")
    assert inst["status"] == "na_until_found" and inst["direction"] == "-" and inst["fields"] == ["inst_net_buy"]
    # 지표 정의 고정: indicator·direction·fields·params (방향 반전·함수 교체·파라미터 변경 뮤턴트를 잡는다)
    fld = {"equity_index": "close", "fx": "close", "commodity": "close", "rates": "yield", "credit": "spread"}
    sign = {"equity_index": "-", "fx": "-", "commodity": "-", "rates": "+", "credit": "+"}
    vol_sb = {"equity_index": "vol_sentiment", "fx": "volatility", "commodity": "volatility", "rates": "volatility",
              "credit": "volatility"}
    for cls in fld:
        ov = cfg.profiles[cls]["blocks"]["oversold"]
        items = {it["name"]: it for sb in ov.values() for it in sb}
        assert {k: items["bb_pctb_20"][k] for k in ("indicator", "direction", "fields", "params")} == {
            "indicator": "bb_pctb", "direction": sign[cls], "fields": [fld[cls]], "params": {"window": 20, "k": 2}}, cls
        assert {k: items["rsi_14"][k] for k in ("indicator", "direction", "fields", "params")} == {
            "indicator": "rsi", "direction": sign[cls], "fields": [fld[cls]], "params": {"window": 14}}, cls
        rv_name, rv_func = (("level_rv_ratio_20", "level_rv_ratio") if cls in ("rates", "credit")
                            else ("rv_ratio_20", "rv_ratio"))
        assert rv_name in {it["name"] for it in ov[vol_sb[cls]]}, cls
        assert {k: items[rv_name][k] for k in ("indicator", "direction", "fields", "params")} == {
            "indicator": rv_func, "direction": "+", "fields": [fld[cls]], "params": {"window": 20}}, cls
        assert not ({"rv_ratio_20", "level_rv_ratio_20"} - {rv_name}) & set(items), cls   # 다른 짝이 섞이지 않음
    for a in cfg.universe:                               # overrides 가 새 구성에서도 검증을 통과
        defs, excluded, _ = cfg.indicator_defs(a)
        d = {x.name: x for x in defs}
        assert d["rsi_14"].sub_block == "confluence" and d["bb_pctb_20"].sub_block == "confluence"
        if a.asset_id == "SP500":
            assert "inst_net_buy_intensity" in excluded    # SP500 은 flows 전체 제외
