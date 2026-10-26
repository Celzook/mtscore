"""Phase 1 리뷰(4개 관점 + 반박 검증)에서 확인된 결함·테스트 공백에 대한 회귀 테스트. 합성 데이터는 테스트 전용."""
import copy

import numpy as np
import pandas as pd
import pytest

from conftest import synth_daily, to_panel
from mtscore import ConfigError, SchemaError, ScoringEngine, build_config, validate_panel
from mtscore.core.registry import registered
from mtscore.core.scoring import band
from mtscore.data.adapters import CsvAdapter

T = "2015-06-30"


# ---- PIT: 모든 계산 함수의 인과성(미래 값을 바꿔도 과거 출력 불변)
@pytest.mark.parametrize("name", sorted(registered()))
def test_every_registered_function_is_causal(name):
    spec = registered()[name]
    idx = pd.bdate_range("2000-01-03", periods=4000)   # 10년 창(min_periods 1260) 함수도 컷 이전에 값이 나오게
    rng = np.random.default_rng(sum(map(ord, name)))
    ins = [pd.Series(50 * np.exp(np.cumsum(rng.normal(0, 0.01, len(idx)))), index=idx) for _ in range(spec.n_inputs)]
    base = spec.func(*ins, **spec.defaults)
    cut = 3000
    assert base.iloc[:cut + 1].notna().sum() > 100, "컷 이전 출력이 비어 있으면 인과성 검사가 무의미"
    alt_ins = []
    for s in ins:
        a = s.copy()
        a.iloc[cut + 1:] = a.iloc[cut + 1:] * 3.7 + 1.0
        alt_ins.append(a)
    alt = spec.func(*alt_ins, **spec.defaults)
    pd.testing.assert_series_equal(base.iloc[:cut + 1], alt.iloc[:cut + 1], check_names=False)


def test_history_equals_cut_when_field_frequency_changes(mini_config, mini_panel):
    """pbr 이 기준일 이후에 일별로 바뀌어도(미래 행) 기준일 이력값은 잘라 계산한 값과 같다(리뷰 pit-1)."""
    fut = pd.bdate_range("2015-07-01", "2016-12-30")
    extra = to_panel("EQ", "pbr", pd.Series(1.0, index=fut))
    p = pd.concat([mini_panel, extra], ignore_index=True)
    eng = ScoringEngine(mini_config)
    full = eng.score_history(p)["EQ"].blocks.loc[T]
    cut = eng.score(p, as_of=T).blocks.loc["EQ"]
    pd.testing.assert_series_equal(full, cut, check_names=False)
    assert not np.isnan(cut["valuation"])


def test_history_equals_cut_on_every_month_end(mini_config, mini_panel):
    eng = ScoringEngine(mini_config)
    full = eng.score_history(mini_panel)["EQ"].blocks
    for t in pd.date_range("2013-06-30", "2016-06-30", freq="6BME"):
        cut = eng.score(mini_panel, as_of=t).blocks.loc["EQ"]
        pd.testing.assert_series_equal(full.loc[t], cut, check_names=False)


# ---- refs 가 실제로 참조 자산의 값을 쓰는지
def test_ref_field_values_come_from_referenced_asset(mini_config, mini_panel):
    res = ScoringEngine(mini_config).score(mini_panel, as_of=T)
    raw = res.contributions.set_index(["asset_id", "indicator"]).at[("EQ", "ccy_shock"), "raw"]
    fx = mini_panel[(mini_panel.asset_id == "FX") & (mini_panel.field == "close")].set_index("date")["value"]
    fx.index = pd.to_datetime(fx.index)
    expected = np.log(fx).diff(20).loc[T]
    assert raw == pytest.approx(expected)


# ---- 부분 가용(일부 지표·하위블록 결측) 상태에서 재정규화와 기여도 합
def test_partial_availability_renormalizes_and_contributions_sum(mini_config, mini_panel):
    p = mini_panel[~((mini_panel.asset_id == "FX") & (pd.to_datetime(mini_panel.date) > "2015-03-31"))]
    res = ScoringEngine(mini_config).score(p, as_of=T)
    c = res.contributions[res.contributions.asset_id == "EQ"].set_index("indicator")
    assert np.isnan(c.at["ccy_shock", "score"])                  # FX 끊김 → oversold.fx 하위블록 결측
    d20, r14 = c.at["disparity_20", "score"], c.at["rsi_14", "score"]
    assert res.blocks.at["EQ", "oversold"] == pytest.approx((d20 + r14) / 2)   # price 하위블록만으로 재정규화
    for blk, g in c.groupby("block"):
        assert g["contribution"].sum(min_count=1) == pytest.approx(res.blocks.at["EQ", blk])
    cov = res.coverage.set_index(["asset_id", "indicator"])
    assert cov.at[("EQ", "ccy_shock"), "reason"] == "unavailable_at_as_of"   # 리뷰 spec-1
    assert not bool(cov.at[("EQ", "ccy_shock"), "available"])


def test_zero_weight_block_is_nan_not_error(mini_universe, mini_profiles, scoring_cfg, mini_panel):
    u = copy.deepcopy(mini_universe)
    u[0]["overrides"] = {"weights": {"valuation.multiples": 0}}
    res = ScoringEngine(build_config(u, mini_profiles, scoring_cfg)).score(mini_panel, as_of=T)
    assert np.isnan(res.blocks.at["EQ", "valuation"])
    c = res.contributions[(res.contributions.asset_id == "EQ") & (res.contributions.block == "valuation")]
    assert c["contribution"].isna().all()


# ---- overrides
def test_exclude_bare_sub_block_and_add(mini_universe, mini_profiles, scoring_cfg, mini_panel):
    u = copy.deepcopy(mini_universe)
    u[0]["overrides"] = {"exclude": ["price"], "add": {"oversold.extra": [
        {"name": "disparity_5", "indicator": "disparity", "direction": "-", "fields": ["close"], "params": {"window": 5}}]}}
    res = ScoringEngine(build_config(u, mini_profiles, scoring_cfg)).score(mini_panel, as_of=T)
    cov = res.coverage.set_index(["asset_id", "indicator"])
    assert cov.at[("EQ", "disparity_20"), "reason"] == "override_exclude:price"
    assert cov.at[("EQ", "rsi_14"), "reason"] == "override_exclude:price"
    assert bool(cov.at[("EQ", "disparity_5"), "used"])
    assert ("FX", "disparity_5") not in cov.index                       # add 는 그 자산에만


@pytest.mark.parametrize("ov,msg", [({"weights": {"no_such": 2}}, "weights"), ({"params": {"no_such": {}}}, "params"),
                                    ({"weights": {"rsi_14": -1}}, "0 이상"), ({"bogus": 1}, "알 수 없는 키")])
def test_override_typos_rejected(mini_universe, mini_profiles, scoring_cfg, ov, msg):
    u = copy.deepcopy(mini_universe)
    u[0]["overrides"] = ov
    with pytest.raises(ConfigError, match=msg):
        build_config(u, mini_profiles, scoring_cfg)


# ---- scoring.yaml 검증
@pytest.mark.parametrize("patch,msg", [
    ({"percentile": {"method": "expandin"}}, "percentile.method"),
    ({"currency_variant": "oversold"}, "currency_variant"),
    ({"bands": {"extreme": 70, "alert": 75}}, "bands"),
    ({"regime": {"threshold": 50, "matrix": [{"oversold": "high", "label": "x"}]}}, "regime.matrix"),
    ({"regime": {"threshold": 50, "matrix": [{"o": "High", "label": "x"}]}}, "regime.matrix"),
])
def test_scoring_config_validation(mini_universe, mini_profiles, scoring_cfg, patch, msg):
    sc = {**copy.deepcopy(scoring_cfg), **patch}
    with pytest.raises(ConfigError, match=msg):
        build_config(mini_universe, mini_profiles, sc)


def test_rolling_method_changes_scores(mini_universe, mini_profiles, scoring_cfg, mini_panel):
    exp = ScoringEngine(build_config(mini_universe, mini_profiles, scoring_cfg)).score(mini_panel, as_of="2016-12-30")
    sc = {**scoring_cfg, "percentile": {"method": "rolling", "min_history_years": 3, "rolling_years": 4}}
    rol = ScoringEngine(build_config(mini_universe, mini_profiles, sc)).score(mini_panel, as_of="2016-12-30")
    ce = exp.contributions.set_index(["asset_id", "indicator"])["percentile"]
    cr = rol.contributions.set_index(["asset_id", "indicator"])["percentile"]
    assert (ce - cr).abs().max() > 0.1


# ---- 구간·표시 라벨
@pytest.mark.parametrize("score,label", [(90, "극단"), (89.99, "경계"), (75, "경계"), (74.9, "중립"), (25.1, "중립"),
                                         (25, "반대경계"), (10.1, "반대경계"), (10, "반대극단"), (0, "반대극단")])
def test_band_thresholds(score, label):
    assert band(score, {"extreme": 90, "alert": 75, "contra_alert": 25, "contra_extreme": 10}) == label


def test_band_nan_is_none():
    assert band(float("nan"), {}) is None


def test_partial_display_label(mini_config, mini_panel):
    res = ScoringEngine(mini_config).score(mini_panel[mini_panel.field != "pbr"], as_of=T)
    rg = res.regime.loc["EQ"]
    assert rg["partial"] and rg["display"].endswith("(부분판정)") and rg["display"].startswith(rg["label"])
    full = ScoringEngine(mini_config).score(mini_panel, as_of=T).regime.loc["EQ"]
    assert full["display"] == full["label"]


# ---- 스키마·CSV
def test_bad_as_of_rejected():
    df = pd.DataFrame({"date": ["2024-01-02"], "asset_id": ["A"], "field": ["close"], "value": [1.0],
                       "as_of": ["garbage"]})
    with pytest.raises(SchemaError, match="as_of"):
        validate_panel(df)


@pytest.mark.parametrize("col", ["asset_id", "field"])
def test_empty_ids_rejected(col):
    df = pd.DataFrame({"date": ["2024-01-02"], "asset_id": ["A"], "field": ["close"], "value": [1.0]})
    df[col] = "  "
    with pytest.raises(SchemaError, match=col):
        validate_panel(df)


def test_csv_adapter_filters_asset_field_and_end(tmp_path):
    pd.DataFrame({"date": ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-03", "2024-01-03"],
                  "asset_id": ["A", "A", "A", "B", "A"], "field": ["close", "close", "close", "close", "pbr"],
                  "value": [1, 2, 3, 9, 7]}).to_csv(tmp_path / "x.csv", index=False)
    out = CsvAdapter(tmp_path).fetch("A", ["close"], start="2024-01-03", end="2024-01-03")
    assert out["value"].tolist() == [2.0]


def test_csv_adapter_bad_date_with_range_is_rejected(tmp_path):
    pd.DataFrame({"date": ["2024-01-02", "nope"], "asset_id": ["A", "A"], "field": ["close", "close"],
                  "value": [1, 2]}).to_csv(tmp_path / "x.csv", index=False)
    with pytest.raises(SchemaError, match="date"):
        CsvAdapter(tmp_path).fetch("A", ["close"], start="2024-01-01")


# ---- 변환·달력
def test_negate_transform(scoring_cfg, mini_profiles):
    u = [{"asset_id": "A", "asset_class": "equity_index", "field_transforms": {"pbr": "negate"}},
         {"asset_id": "B", "asset_class": "equity_index"}]
    cfg = build_config(u, mini_profiles, scoring_cfg)
    close = synth_daily(seed=11)
    pbr = synth_daily(seed=12, s0=1.0)
    panel = pd.concat([to_panel("A", "close", close), to_panel("A", "pbr", pbr),
                       to_panel("B", "close", close), to_panel("B", "pbr", -pbr)], ignore_index=True)
    c = ScoringEngine(cfg).score(panel, as_of=T).contributions.set_index(["asset_id", "indicator"])
    assert c.at[("A", "pbr"), "score"] == pytest.approx(c.at[("B", "pbr"), "score"])


def test_asset_calendar_skips_holidays(mini_config, mini_panel):
    """자산 달력은 자기 close 가 있는 날만 — 휴장일에 값을 복제하지 않는다(리뷰 numeric-1)."""
    hol = pd.Timestamp("2014-05-05")
    p = mini_panel[~((mini_panel.asset_id == "EQ") & (pd.to_datetime(mini_panel.date) == hol))]
    h = ScoringEngine(mini_config).score_history(p, asset_ids=["EQ"])["EQ"]
    assert hol not in h.blocks.index
    assert pd.Timestamp("2014-05-06") in h.blocks.index


def test_first_score_date_reported(mini_config, mini_panel):
    cov = ScoringEngine(mini_config).score(mini_panel, as_of=T).coverage.set_index(["asset_id", "indicator"])
    d = cov.at[("EQ", "disparity_20"), "first_score_date"]
    assert pd.Timestamp("2013-01-01") <= pd.Timestamp(d) <= pd.Timestamp("2013-03-01")


def test_empty_calendar_gives_clear_error(mini_config):
    """달력 필드가 없는 자산(EQ)은 평일 달력을 쓰는데, 패널이 주말뿐이면 달력이 비어 명확한 오류."""
    panel = pd.DataFrame({"date": ["2024-01-06"], "asset_id": ["FX"], "field": ["close"], "value": [1.0]})
    with pytest.raises(ValueError, match="이전 달력일이 없음"):
        ScoringEngine(mini_config).score(panel, as_of="2024-01-07", asset_ids=["EQ"])


# ---- 2차 검증(수정 검증 워크플로)에서 확인된 항목
def test_calendar_choice_is_causal_when_price_frequency_changes(mini_config, mini_panel):
    """close 가 주별이다가 나중에 일별이 돼도, 이력의 t 값 = t 로 자른 값(리뷰 a-calendar-lookahead)."""
    close = synth_daily(seed=21)
    weekly = close[:"2013-12-31"][close[:"2013-12-31"].index.dayofweek == 4]
    eq_close = pd.concat([weekly, close["2014-01-01":]])
    p = pd.concat([mini_panel[~((mini_panel.asset_id == "EQ") & (mini_panel.field == "close"))],
                   to_panel("EQ", "close", eq_close)], ignore_index=True)
    eng = ScoringEngine(mini_config)
    full = eng.score_history(p, asset_ids=["EQ"])["EQ"].blocks
    for t in ["2013-06-28", "2013-12-27", "2014-06-30"]:
        cut = eng.score(p, as_of=t, asset_ids=["EQ"]).blocks.loc["EQ"]
        pd.testing.assert_series_equal(full.loc[t], cut, check_names=False)


def test_rejected_revisions_do_not_create_calendar_days(mini_config, mini_panel):
    sat = pd.Timestamp("2014-03-08")
    rev = pd.DataFrame({"date": [pd.Timestamp("2014-03-03")], "asset_id": ["EQ"], "field": ["close"], "value": [1.0],
                        "as_of": [sat], "source": ["rev"]})
    h = ScoringEngine(mini_config).score_history(pd.concat([mini_panel, rev], ignore_index=True), asset_ids=["EQ"])
    assert sat not in h["EQ"].blocks.index


def test_month_lag_does_not_resurrect_expired_values():
    from mtscore.core.indicators.price import lag_months
    idx = pd.bdate_range("2011-01-03", "2015-12-31")
    x = pd.Series(np.nan, index=idx)
    x[:"2011-12-30"] = 10.0                 # 2011년 값 이후 3년 결측(유지 한도 초과로 이미 NaN)
    x["2015-01-02":] = 20.0
    assert np.isnan(lag_months(x, 1)["2015-01-30"])


def test_stale_asset_is_na_not_ranked(mini_config, mini_panel):
    p = mini_panel[~((mini_panel.asset_id == "FX") & (pd.to_datetime(mini_panel.date) > "2014-03-31"))]
    res = ScoringEngine(mini_config).score(p, as_of="2016-06-30")
    assert bool(res.stale["FX"]) and not bool(res.stale["EQ"])
    assert res.blocks.loc["FX"].isna().all() and res.regime.at["FX", "label"] is None
    assert res.ranking.loc["FX"].isna().all()
    cov = res.coverage.set_index(["asset_id", "indicator"])
    assert cov.at[("FX", "disparity_20"), "reason"] == "unavailable_at_as_of"
    import json
    assert {a["asset_id"]: a["stale"] for a in json.loads(res.to_json())["assets"]}["FX"] is True


def test_prestart_observation_hold_counts_from_publication():
    cal = pd.bdate_range("2010-01-01", "2010-12-31")
    f = pd.DataFrame({"value": [1.0, 2.0], "ref": pd.to_datetime(["2009-05-31", "2009-06-30"])},
                     index=pd.to_datetime(["2009-06-01", "2009-06-30"]))
    out = to_calendar_(f, cal)
    assert out.isna().all()                 # 2009-06-30 공표값은 2010-01 시작 시점에 이미 70영업일 초과
    f2 = pd.DataFrame({"value": [3.0], "ref": pd.to_datetime(["2009-11-30"])}, index=pd.to_datetime(["2009-12-15"]))
    out2 = to_calendar_(f2, cal)
    held = out2.dropna()
    assert held.index[0] == cal[0] and len(held) == 70 - int(np.busday_count("2009-12-15", "2010-01-01")) + 1


def to_calendar_(f, cal):
    from mtscore.core.transform import to_calendar
    return to_calendar(f, cal, daily_ffill_max=5, lowfreq_max_hold=70)


def test_engine_respects_lowfreq_hold_config(mini_universe, mini_profiles, scoring_cfg, mini_panel):
    p = mini_panel[~((mini_panel.field == "pbr") & (pd.to_datetime(mini_panel.date) > "2015-03-31"))]
    sc = copy.deepcopy(scoring_cfg)
    sc["missing"]["lowfreq_max_hold_bdays"] = 10
    short = ScoringEngine(build_config(mini_universe, mini_profiles, sc)).score(p, as_of="2015-04-30")
    long_ = ScoringEngine(build_config(mini_universe, mini_profiles, scoring_cfg)).score(p, as_of="2015-04-30")
    assert np.isnan(short.blocks.at["EQ", "valuation"])        # 3월말치(4/5 공표) 10영업일 후 만료
    assert not np.isnan(long_.blocks.at["EQ", "valuation"])    # 70영업일이면 유지


@pytest.mark.parametrize("ov,msg", [({"params": {"disparity_20": 30}}, "params"),
                                    ({"add": {"oversold.x": {"name": "a"}}}, "add"),
                                    ({"add": ["x"]}, "add"),
                                    ({"weights": {"rsi_14": float("inf")}}, "유한값"),
                                    ({"exclude": "price"}, "exclude")])
def test_override_shape_errors_are_config_errors(mini_universe, mini_profiles, scoring_cfg, ov, msg):
    u = copy.deepcopy(mini_universe)
    u[0]["overrides"] = ov
    with pytest.raises(ConfigError, match=msg):
        build_config(u, mini_profiles, scoring_cfg)


@pytest.mark.parametrize("patch,msg", [({"bands": {"extrem": 90}}, "bands"), ({"weights": {}}, "알 수 없는 키"),
                                       ({"missing": {"daily_ffill_max_bdays": float("inf")}}, "유한값"),
                                       ({"regime": {"threshold": 50, "matrix": {"a": 1}}}, "regime.matrix")])
def test_scoring_unknown_keys_and_shapes(mini_universe, mini_profiles, scoring_cfg, patch, msg):
    sc = copy.deepcopy(scoring_cfg)
    for k, v in patch.items():
        sc[k] = {**(sc.get(k) or {}), **v} if isinstance(v, dict) and k in ("bands", "missing") else v
    with pytest.raises(ConfigError, match=msg):
        build_config(mini_universe, mini_profiles, sc)
