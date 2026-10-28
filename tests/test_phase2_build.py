"""Phase 2 파생 필드(data/build.py) — PIT 규칙과 계산을 작은 합성 입력으로 확인한다(테스트 전용 합성 데이터)."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mtscore.data import build as B

FX = Path(__file__).parent / "fixtures" / "phase2"


def _df(dates, vals, as_of=None):
    d = pd.DataFrame({"date": pd.to_datetime(dates), "value": vals})
    if as_of is not None:
        d["as_of"] = pd.to_datetime(as_of)
    return d


def test_lagged_asof_uses_only_known_values():
    right = _df(["2020-01-01", "2020-02-01"], [1.0, 2.0], ["2020-02-05", "2020-03-05"])
    s = B.lagged_asof(pd.to_datetime(["2020-02-04", "2020-02-05", "2020-03-04", "2020-03-05"]), right)
    assert np.isnan(s.iloc[0]) and list(s.iloc[1:]) == [1.0, 1.0, 2.0]


def test_lagged_asof_ignores_late_old_revision():
    # 옛 기준일 값이 늦게 와도(as_of 늦음) 더 최근 기준일 값을 덮지 않는다
    right = _df(["2020-02-01", "2020-01-01"], [2.0, 9.0], ["2020-03-01", "2020-03-10"])
    s = B.lagged_asof(pd.to_datetime(["2020-03-15"]), right)
    assert s.iloc[0] == 2.0


def test_real_yield_proxy_respects_cpi_publication():
    months = pd.date_range("2018-01-01", "2020-02-01", freq="MS")
    cpi = _df(months, np.linspace(100, 113, len(months)), months + pd.DateOffset(months=1, days=4))
    nom = _df(["2020-02-04", "2020-02-06"], [3.0, 3.0])
    ry = B.real_yield_proxy(nom, cpi)
    c = cpi.set_index("date")["value"]
    # 2020-02-04 에 알려진 최신 CPI 는 2019-12(1월 5일 공표), 2020-02-06 에는 2020-01(2월 5일 공표)
    assert ry["value"].iloc[0] == pytest.approx(3.0 - (c["2019-12-01"] / c["2018-12-01"] - 1) * 100)
    assert ry["value"].iloc[1] == pytest.approx(3.0 - (c["2020-01-01"] / c["2019-01-01"] - 1) * 100)
    assert (ry["as_of"] == ry["date"]).all()


def test_rate_diff_uses_prior_us_close():
    home = _df(["2020-03-03", "2020-03-04"], [2.0, 2.0])
    us = _df(["2020-03-02", "2020-03-03", "2020-03-04"], [1.0, 1.5, 9.0])
    rd = B.rate_diff_cross_market(home, us, lag_days=1)
    assert list(rd["value"]) == [1.0, 0.5]     # 같은 날 뉴욕 종가(1.5·9.0)는 쓰지 않는다


def test_rate_diff_stale_foreign_is_missing():
    home = _df(["2020-03-20"], [2.0])
    us = _df(["2020-03-02"], [1.0])
    assert B.rate_diff_cross_market(home, us).empty


def test_rolling_sum_months_needs_full_window():
    months = pd.date_range("2020-01-01", periods=13, freq="MS")
    m = _df(months, np.ones(13), months + pd.DateOffset(months=2))
    m = m.drop(index=5)   # 6월 결측
    s = B.rolling_sum_months(m, 12)
    assert s.empty or s["date"].min() > pd.Timestamp("2021-01-01")


def test_g_spread_flat_curve_and_duration_matching():
    idx = pd.to_datetime(["2020-01-02", "2020-01-03"])
    curve = pd.DataFrame({1: [2.0, 1.0], 10: [2.0, 3.0], 30: [2.0, 4.0]}, index=idx)
    y = pd.Series([5.0, 5.0], index=idx)
    d = pd.Series([7.0, 7.0], index=idx)
    g = B.g_spread(y, d, curve)
    assert g.iloc[0] == pytest.approx(3.0)           # 평평한 커브: 만기와 무관
    # 기울어진 커브: 듀레이션 7 의 액면 국채 만기는 7년보다 길다 → 만기=듀레이션 근사보다 높은 수익률을 뺀다
    naive = 5.0 - np.interp(7.0, [1, 10, 30], [1.0, 3.0, 4.0])
    assert g.iloc[1] < naive


def test_par_mod_duration_monotone():
    d = B.par_mod_duration(np.array([4.0, 4.0, 4.0]), np.array([2.0, 10.0, 30.0]))
    assert d[0] < 2.0 and d[1] < 10.0 and np.all(np.diff(d) > 0)


def test_cl_roll_dates_april_2020():
    td = pd.bdate_range("2020-04-01", "2020-04-30").drop(pd.Timestamp("2020-04-10"))   # 성금요일 휴장
    r = B.cl_roll_dates(td)
    assert pd.Timestamp("2020-04-22") in r      # 5월물 최종거래일 2020-04-21(25일 토요일 → 24일의 3영업일 전)


def test_back_adjust_ratio_returns_and_last_value():
    idx = pd.bdate_range("2020-01-01", periods=10)
    c1 = pd.Series([10, 10.5, 10.2, 10.4, 10.1, 12, 12.2, 12.1, 12.5, 12.4], index=idx, dtype=float)
    c2 = pd.Series([11, 11.4, 11.3, 11.5, 11.9, 13, 13.1, 13.0, 13.3, 13.2], index=idx, dtype=float)
    roll = pd.DatetimeIndex([idx[5]])
    out = B.back_adjust_ratio(c1, c2, roll, early_days=2)
    assert out["close"].iloc[-1] == pytest.approx(12.4)
    r = out["close"].pct_change()
    assert r.iloc[2] == pytest.approx(10.2 / 10.5 - 1)          # 교체 전: 근월물 수익률
    assert r.iloc[3] == pytest.approx(11.5 / 11.3 - 1)          # 교체일(5−2=3): 새 월물 자기 수익률
    assert r.iloc[5] == pytest.approx(12.0 / 11.9 - 1)          # 원래 교체일: 같은 월물(전일 c2 → 당일 c1)
    assert r.iloc[7] == pytest.approx(12.1 / 12.2 - 1)
    assert out["switch"].sum() == 1


def test_back_adjust_avoids_negative_expiry_print():
    idx = pd.bdate_range("2020-04-13", periods=8)
    c1 = pd.Series([22, 20, 19, 18, -37.6, 10, 13.8, 16.5], index=idx)
    c2 = pd.Series([27, 26, 25.5, 25, 20.4, 11.6, 20.7, 21.4], index=idx)
    out = B.back_adjust_ratio(c1, c2, pd.DatetimeIndex([idx[6]]), early_days=5)
    assert (out["close"] > 0).all()


def test_bottomup_rows_sample_date_is_row_max():
    raw = pd.read_csv(FX / "refinitiv" / "bottomup_us.csv")
    rows = B.bottomup_rows(raw, ["eps", "mcap"])
    first = rows[rows["ric"] == "NVDA.OQ"].iloc[0]
    assert first["sample_date"] == pd.Timestamp("2010-01-29")   # EPS 반환일 01-26 이 아니라 표본일(월말)
    assert rows.groupby("ric").size().to_dict() == {"AAPL.OQ": 4, "NVDA.OQ": 4}


def _rows(spec):
    out = []
    for ric, month, eps, mcap, px in spec:
        p = pd.Period(month, "M")
        out.append({"ric": ric, "sample_date": p.end_time.normalize(), "month": p, "eps": eps, "mcap": mcap, "px": px})
    return pd.DataFrame(out)


def test_eps_up_share_uses_prior_month_weights():
    rows = _rows([("A", "2020-01", 1.0, 100, 10), ("B", "2020-01", 1.0, 300, 10),
                  ("A", "2020-02", 1.1, 900, 10), ("B", "2020-02", 0.9, 100, 10)])
    s = B.eps_up_share(rows)
    assert len(s) == 1 and s["value"].iloc[0] == pytest.approx(100 / 400)   # 1월 시총 가중
    assert s["date"].iloc[0] == pd.Timestamp("2020-02-29")


def test_aggregate_multiples_simple():
    rows = _rows([("A", "2020-01", 1.0, 100, 10), ("B", "2020-01", 2.0, 100, 20),
                  ("A", "2020-02", 1.1, 110, 11), ("B", "2020-02", 2.0, 100, 20)])
    agg = B.aggregate_multiples(rows)
    # 1월: 이익 = 1×10주 + 2×5주 = 20, 시총 200 → PER 10
    assert agg["fwd_per"]["value"].iloc[0] == pytest.approx(10.0)
    # 2월 EPS 지수: 전월 주식 수 고정 (1.1×10 + 2×5)/(1×10 + 2×5) = 1.05
    e = agg["fwd_eps_12m"].set_index("date")["value"]
    assert e.iloc[0] == pytest.approx(100.0) and e.iloc[1] == pytest.approx(105.0)


def test_breadth_counts():
    idx = pd.bdate_range("2020-01-01", periods=25)
    up = pd.Series(np.arange(25, dtype=float) + 1, index=idx)
    down = pd.Series(100 - np.arange(25, dtype=float), index=idx)
    b = B.breadth(pd.DataFrame({"U": up, "D": down}), ma_short=20, ma_long=200, low_window=20)
    last = b.iloc[-1]
    assert last["breadth_above_ma20"] == pytest.approx(50.0)
    assert last["breadth_adv"] == 1 and last["breadth_dec"] == 1
    assert last["breadth_new_low_52w"] == pytest.approx(50.0)
    assert np.isnan(last["breadth_above_ma200"])


def test_g_spread_maturity_matching():
    idx = pd.to_datetime(["2020-01-03"])
    curve = pd.DataFrame({1: [1.0], 10: [3.0], 30: [4.0]}, index=idx)
    g = B.g_spread(pd.Series([5.0], index=idx), pd.Series([12.0], index=idx), curve, match="maturity")
    assert g.iloc[0] == pytest.approx(5.0 - (3.0 + 2 / 20 * 1.0))
    with pytest.raises(ValueError):
        B.g_spread(pd.Series([5.0], index=idx), pd.Series([12.0], index=idx), curve, match="x")


def test_gc_contract_months_and_switch():
    cal = pd.bdate_range("2026-09-01", "2027-03-31")
    d = pd.to_datetime(["2026-10-27", "2026-10-28", "2026-10-29", "2026-11-20", "2026-11-23"])
    c1 = B.gc_c1_month(d, cal)
    # 2026-10 최종거래일 = 10-28(월말 3번째 영업일) → 10-29 부터 c1 은 11월물
    assert [str(x) for x in c1] == ["2026-10", "2026-10", "2026-11", "2026-11", "2026-11"]
    h = B.gc_held_month(d, cal, early_days=5)
    # 12월물 첫 통지일 = 11-30, 5영업일 전 = 11-23 에 2월물로 교체
    assert [str(x) for x in h] == ["2026-12", "2026-12", "2026-12", "2026-12", "2027-02"]


def test_continuous_from_nearbys_same_contract_returns():
    idx = pd.to_datetime(["2026-11-19", "2026-11-20", "2026-11-23", "2026-11-24"])
    near = pd.DataFrame({1: [100, 101, 102, 103], 2: [110, 111, 112, 113], 3: [120, 121, 123, 124],
                         4: [130, 131, 132, 133]}, index=idx, dtype=float)
    c1m = pd.Series([pd.Period("2026-11")] * 4, index=idx)
    held = pd.Series([pd.Period("2026-12")] * 2 + [pd.Period("2027-02")] * 2, index=idx)
    out = B.continuous_from_nearbys(near, c1m, held)
    r = out["close"].pct_change()
    assert r.iloc[1] == pytest.approx(111 / 110 - 1)     # 12월물 = c2
    assert r.iloc[2] == pytest.approx(132 / 131 - 1)     # 교체일: 2월물 = c1(11월) 기준 c4, 같은 계약끼리
    assert out["close"].iloc[-1] == pytest.approx(out["held"].iloc[-1])
    assert out["switch"].sum() == 1


def test_equal_weight_and_exclude_rows():
    rows = _rows([("A", "2020-01", 1.0, 100, 10), ("B", "2020-01", 1.0, 300, 10),
                  ("A", "2020-02", 1.1, 900, 10), ("B", "2020-02", 0.9, 100, 10)])
    assert B.eps_up_share(B.equal_weight_rows(rows))["value"].iloc[0] == pytest.approx(0.5)
    assert B.eps_up_share(B.exclude_rows(rows, ["B"]))["value"].iloc[0] == pytest.approx(1.0)
