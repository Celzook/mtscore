"""Phase 4 단계 C — 장기 반전 짝 필드(data/build.py)·변형 설정(config/variants/phase4c.yaml)·엔진 불변성.

합성 데이터는 테스트 전용이다(결과 보고에 쓰지 않는다)."""
import copy
import sys

import numpy as np
import pandas as pd
import pytest
import yaml

from conftest import ROOT, synth_daily, to_panel
from mtscore import ScoringEngine, build_config
from mtscore.core.indicators.price import lag_months
from mtscore.core.transform import percentile_expanding
from mtscore.data import build as B

sys.path.insert(0, str(ROOT / "scripts"))
from phase4_c import variant_profiles  # noqa: E402

VARS = yaml.safe_load((ROOT / "config" / "variants" / "phase4c.yaml").read_text(encoding="utf-8"))


def test_lag_months_daily_matches_core_lag_months():
    s = synth_daily("2005-01-03", "2012-12-31", seed=7)
    got = B.lag_months_daily(s, 60)
    want = lag_months(s, 60)
    pd.testing.assert_series_equal(got, want, check_names=False, check_freq=False)
    assert got.first_valid_index() == pd.Timestamp("2010-01-04")   # 2005-01-04(월) ↔ 2010-01-04


def test_lag_months_daily_stale_gap_is_missing():
    s = synth_daily("2005-01-03", "2011-12-30", seed=8)
    s = s.drop(s.loc["2005-06-01":"2005-06-30"].index)              # 한 달 공백(5영업일 초과)
    lag = B.lag_months_daily(s, 60)
    assert lag.loc["2010-06-15":"2010-06-29"].isna().all()           # 공백 속 목표일 → 오래된 값을 되살리지 않는다
    assert lag.loc["2010-06-01"] == s.loc["2005-05-31"]              # 공백 첫날(목표 05-31 → 고른 관측도 05-31)
    assert np.isfinite(lag.loc["2010-07-01"])


def test_lag_months_exact_monthly_keeps_as_of():
    months = pd.date_range("2000-01-01", "2010-12-01", freq="MS")
    rows = pd.DataFrame({"date": months, "value": np.arange(len(months), dtype=float),
                         "as_of": months + pd.DateOffset(months=3)})
    rows = rows.drop(index=3)                                         # 2000-04 결측
    out = B.lag_months_exact(rows, 60).set_index("date")
    assert out.loc["2010-12-01", "value"] == rows.set_index("date").loc["2005-12-01", "value"]
    assert out.loc["2010-12-01", "as_of"] == pd.Timestamp("2011-03-01")
    assert pd.Timestamp("2005-04-01") not in out.index                # 짝(2000-04)이 없는 달은 행이 없다
    assert out.index.min() == pd.Timestamp("2005-01-01")


def test_ratio_minus_one_percentile_equals_log_diff_percentile():
    """FX 장기 반전을 비율 − 1 로 계산해도 로그 차분과 자기 역사 백분위가 같다(단조 변환)."""
    a = synth_daily("2010-01-01", "2015-12-31", seed=9)
    b = synth_daily("2010-01-01", "2015-12-31", seed=10)
    p1 = percentile_expanding(a / b - 1.0, 3)
    p2 = percentile_expanding(np.log(a) - np.log(b), 3)
    pd.testing.assert_series_equal(p1, p2)


def test_long_back_adjust_equals_short_on_overlap():
    """같은 교체 규칙이면 앞 구간을 더 붙여도 겹치는 구간의 연속물 값이 같다(마지막 값 기준 비율 백어저스트)."""
    c1 = synth_daily("2005-01-03", "2012-12-31", seed=11, s0=60)
    c2 = c1 * (1 + 0.01 * np.sin(np.arange(len(c1)) / 15))
    both = c1.index
    rolls = B.cl_roll_dates(both)
    long = B.back_adjust_ratio(c1, c2, rolls, early_days=5)["close"]
    cut = pd.Timestamp("2010-01-01")
    short = B.back_adjust_ratio(c1[c1.index >= cut], c2[c2.index >= cut], rolls[rolls >= cut], early_days=5)["close"]
    j = pd.concat({"l": long, "s": short}, axis=1).dropna()
    assert len(j) == len(short) and np.allclose(j["l"], j["s"], rtol=1e-12)


def test_variant_yaml_builds_on_real_config():
    uni = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text(encoding="utf-8"))
    sc = yaml.safe_load((ROOT / "config" / "scoring.yaml").read_text(encoding="utf-8"))
    profs = {}
    for p in sorted((ROOT / "config" / "profiles").glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        profs[d["asset_class"]] = d
    assert VARS["long_months"] == 60
    for v, want in (("C1", {"GOLD": ("valuation", "real_price"), "WTI": ("valuation", "real_price"),
                            "USDKRW": ("valuation", "reer"), "KTB10Y": ("valuation", "level"),
                            "UST10Y": ("valuation", "level")}),
                    ("C2", {"USDKRW": ("fundamental", "macro")})):
        cfg = build_config(copy.deepcopy(uni), variant_profiles(profs, v), copy.deepcopy(sc))
        name = "long_reversal_60m" if v == "C1" else "rate_diff_level"
        for aid, (blk, sb) in want.items():
            defs, _, _ = cfg.indicator_defs(cfg.asset(aid))
            d = next(x for x in defs if x.name == name)
            assert (d.block, d.sub_block) == (blk, sb)
    # 원본 프로파일은 바뀌지 않는다(변형은 사본에만)
    assert all(x["name"] != "long_reversal_60m" for x in profs["commodity"]["blocks"]["valuation"]["real_price"])


def test_engine_long_fields_feed_only_new_indicator(scoring_cfg):
    """장기 필드(2005~)와 변형 지표를 넣어도 기존 지표 점수는 그대로이고, 새 지표는 자산 달력 첫날(2010)부터 값이 있다."""
    prof = {"commodity": {"asset_class": "commodity", "blocks": {
        "oversold": {"price": [{"name": "disparity_60", "indicator": "disparity", "direction": "-",
                                "fields": ["close"], "params": {"window": 60}}]},
        "valuation": {"real_price": [{"name": "level_close", "indicator": "level", "direction": "-",
                                      "fields": ["close"]}]},
        "fundamental": {"curve": [{"name": "chg_3m", "indicator": "pct_change_months", "direction": "+",
                                   "fields": ["close"], "params": {"months": 3}}]}}}}
    uni = [{"asset_id": "CMD", "asset_class": "commodity"}]
    long = synth_daily("2005-01-03", "2016-12-30", seed=12)
    close = long[long.index >= "2010-01-01"]
    base_panel = to_panel("CMD", "close", close)
    longp = pd.concat([to_panel("CMD", "close_long", long),
                       to_panel("CMD", "close_long_m60", B.lag_months_daily(long, 60).dropna())], ignore_index=True)
    var = copy.deepcopy(prof)
    var["commodity"]["blocks"]["valuation"]["real_price"].extend(
        copy.deepcopy(VARS["variants"]["C1"]["commodity"]["valuation.real_price"]))
    h0 = ScoringEngine(build_config(uni, prof, scoring_cfg)).score_history(base_panel)["CMD"]
    h0l = ScoringEngine(build_config(uni, prof, scoring_cfg)).score_history(
        pd.concat([base_panel, longp], ignore_index=True))["CMD"]
    h1 = ScoringEngine(build_config(uni, var, scoring_cfg)).score_history(
        pd.concat([base_panel, longp], ignore_index=True))["CMD"]
    pd.testing.assert_frame_equal(h0.blocks, h0l.blocks)               # 장기 필드만 추가: 점수 불변
    pd.testing.assert_frame_equal(h0.score, h1.score[h0.score.columns])
    pd.testing.assert_frame_equal(h0.blocks[["oversold", "fundamental"]], h1.blocks[["oversold", "fundamental"]])
    raw = h1.raw["long_reversal_60m"]
    assert raw.first_valid_index() == pd.Timestamp("2010-01-04")       # 2015 가 아니라 달력 첫날부터
    t = pd.Timestamp("2014-03-14")
    prev = long[long.index <= t - pd.DateOffset(months=60)].iloc[-1]
    assert raw.loc[t] == pytest.approx(long.loc[t] / prev - 1.0)
    assert h1.score["long_reversal_60m"].first_valid_index() < pd.Timestamp("2013-02-01")
    assert not h0.blocks["valuation"].equals(h1.blocks["valuation"])
