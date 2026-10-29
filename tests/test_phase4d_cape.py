"""Phase 4 D-1 CAPE 분모(data/shiller.py) — as_of 지연·120개월 요구·결측 처리·PIT(테스트 전용 합성 데이터)."""
import numpy as np
import pandas as pd
import pytest

from mtscore.data import shiller as SH


def _shiller(months, e):
    return pd.DataFrame({"month": pd.DatetimeIndex(months), "E": e})


def _cpi(months, vals, lag_days=15):
    m = pd.DatetimeIndex(months)
    return pd.DataFrame({"date": m, "value": np.asarray(vals, float),
                         "as_of": m + pd.DateOffset(months=1, days=lag_days - 1)})   # 다음 달 lag_days 일 공표


def test_e_pit_as_of_is_first_day_of_month_plus_4():
    e = SH.e_pit(_shiller(["2020-02-01", "2020-03-01"], [1.0, np.nan]))
    assert list(e["date"]) == [pd.Timestamp("2020-02-01")]          # E 없는 달은 버린다
    assert e["as_of"].iloc[0] == pd.Timestamp("2020-06-01")


def test_last_e_month_is_month_minus_4():
    months = pd.date_range("2018-01-01", "2020-12-01", freq="MS")
    e = SH.e_pit(_shiller(months, np.arange(len(months), dtype=float) + 1))
    for t in ("2020-05-31", "2020-06-01", "2020-09-15"):
        t = pd.Timestamp(t)
        last = e[e["as_of"] <= t]["date"].max()
        assert (t.year * 12 + t.month) - (last.year * 12 + last.month) == 4


def test_requires_full_window():
    months = pd.date_range("2000-01-01", "2010-12-01", freq="MS")   # 132개월
    e = SH.e_pit(_shiller(months, np.ones(len(months))))
    cpi = _cpi(months, np.full(len(months), 100.0))
    out = SH.real_e10(e, cpi, window=120)
    first = out["date"].min()
    # 120번째 E 월 = 2009-12 → as_of 2010-04-01 이 첫 값. 그 전(119개월)은 값이 없다
    assert first == pd.Timestamp("2010-04-01")
    assert out["value"].eq(1.0).all() and (out["as_of"] == out["date"]).all()
    assert SH.real_e10(e[e["date"] < "2009-12-01"], cpi, window=120).empty


def test_value_is_cpi_ref_times_mean_real_e_and_respects_cpi_as_of():
    months = pd.date_range("2020-01-01", "2020-06-01", freq="MS")
    e = SH.e_pit(_shiller(months, [10.0, 20.0, 30.0, 40.0, 50.0, 60.0]))
    cpi = _cpi(months, [100.0, 110.0, 120.0, 130.0, 140.0, 150.0])
    out = SH.real_e10(e, cpi, window=3).set_index("date")["value"]
    # 2020-07-01: 알려진 E = 2020-01~03, 알려진 CPI 최신 = 2020-05(6월 15일 공표) → 기준 140
    exp = 140.0 * np.mean([10 / 100, 20 / 110, 30 / 120])
    assert out[pd.Timestamp("2020-07-01")] == pytest.approx(exp)
    # 2020-07-15: 2020-06 CPI(150) 공표 → 기준만 바뀐다(E 창 그대로)
    assert out[pd.Timestamp("2020-07-15")] == pytest.approx(150.0 * np.mean([10 / 100, 20 / 110, 30 / 120]))
    # CAPE = 종가 / 분모 는 기준 CPI 로 가격을 실질화한 Shiller 식과 같다: (P/CPI_ref) / 평균(E/CPI)
    p = 3000.0
    assert p / out[pd.Timestamp("2020-07-15")] == pytest.approx((p / 150.0) / np.mean([10 / 100, 20 / 110, 30 / 120]))


def test_missing_month_gives_no_value_and_skip_missing_sensitivity():
    months = pd.date_range("2020-01-01", "2020-12-01", freq="MS")
    e = SH.e_pit(_shiller(months, np.arange(1, 13, dtype=float)))
    cpi = _cpi(months, np.full(12, 100.0))
    cpi = cpi[cpi["date"] != pd.Timestamp("2020-05-01")]             # 공표되지 않은 달(예: CPIAUCSL 2025-10)
    out = SH.real_e10(e, cpi, window=3)
    # E 창(3개월)에 2020-05 가 들어가는 사건일(E 2020-05~07 → as_of 2020-09-01~11-01)에는 값이 없다
    bad = out[(out["date"] >= "2020-09-01") & (out["date"] < "2020-12-01")]
    assert bad.empty
    assert pd.Timestamp("2020-12-01") in set(out["date"])            # 창이 빠진 달을 지나면 다시 값이 난다
    s = SH.real_e10(e, cpi, window=3, skip_missing=True).set_index("date")
    # 민감도: 2020-09-01(E 마지막 월 05, 그 달 CPI 없음) 창 = 2020-02·03·04 → 달력 4개월, 값을 만들어 넣지 않는다
    assert s.at[pd.Timestamp("2020-09-01"), "span_months"] == 4
    assert s.at[pd.Timestamp("2020-09-01"), "value"] == pytest.approx(np.mean([2.0, 3.0, 4.0]))
    # 2020-10-01(E 마지막 월 06) 창 = 03·04·06
    assert s.at[pd.Timestamp("2020-10-01"), "value"] == pytest.approx(np.mean([3.0, 4.0, 6.0]))


def test_nan_e_inside_window_gives_no_value():
    months = pd.date_range("2020-01-01", "2020-06-01", freq="MS")
    e = SH.e_pit(_shiller(months, [1.0, 2.0, np.nan, 4.0, 5.0, 6.0]))
    out = SH.real_e10(e, _cpi(months, np.full(6, 100.0)), window=3)
    # E 창에 2020-03 이 들어가는 동안(E 마지막 월 2020-04·05 → as_of 2020-08-01·09-01)은 값이 없다
    assert not set(out["date"]) & {pd.Timestamp("2020-08-01"), pd.Timestamp("2020-09-01")}
    assert out.set_index("date").at[pd.Timestamp("2020-10-01"), "value"] == pytest.approx(5.0)


def test_pit_future_rows_do_not_change_past():
    months = pd.date_range("2019-01-01", "2020-12-01", freq="MS")
    rng = np.random.default_rng(0)
    e = SH.e_pit(_shiller(months, rng.uniform(5, 10, len(months))))
    cpi = _cpi(months, np.linspace(100, 120, len(months)))
    full = SH.real_e10(e, cpi, window=6).set_index("date")["value"]
    cut = pd.Timestamp("2020-06-20")
    part = SH.real_e10(e[e["as_of"] <= cut], cpi[cpi["as_of"] <= cut], window=6).set_index("date")["value"]
    pd.testing.assert_series_equal(full[full.index <= cut], part)
