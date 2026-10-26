import numpy as np
import pandas as pd
import pytest

from mtscore.core.transform import (apply_direction, hold_limits, percentile_expanding, percentile_rolling,
                                    pit_frame, pit_series, to_calendar)


def rows(spec):
    return pd.DataFrame(spec, columns=["date", "as_of", "value"]).assign(
        date=lambda d: pd.to_datetime(d["date"]), as_of=lambda d: pd.to_datetime(d["as_of"]))


def frame(dates, values, refs=None):
    idx = pd.to_datetime(dates)
    return pd.DataFrame({"value": values, "ref": pd.to_datetime(refs) if refs is not None else idx}, index=idx)


def test_pit_series_uses_latest_reference_and_revision():
    r = rows([("2024-01-31", "2024-02-05", 1.0),   # 1월치 첫 공표
              ("2024-01-31", "2024-02-20", 1.1),   # 1월치 수정
              ("2024-02-29", "2024-03-05", 2.0)])
    s = pit_series(r)
    assert s[pd.Timestamp("2024-02-05")] == 1.0
    assert s[pd.Timestamp("2024-02-20")] == 1.1
    assert s[pd.Timestamp("2024-03-05")] == 2.0


def test_late_revision_of_old_reference_does_not_override_newer():
    r = rows([("2024-01-31", "2024-02-05", 1.0),
              ("2024-02-29", "2024-03-05", 2.0),
              ("2024-01-31", "2024-03-10", 9.9)])   # 옛 기준일의 늦은 수정
    s = pit_series(r)
    assert pd.Timestamp("2024-03-10") not in s.index
    assert s.iloc[-1] == 2.0


def test_pit_frame_keeps_reference_date():
    f = pit_frame(rows([("2024-01-31", "2024-02-05", 1.0), ("2024-02-29", "2024-03-05", 2.0)]))
    assert list(f["ref"]) == list(pd.to_datetime(["2024-01-31", "2024-02-29"]))


def test_to_calendar_daily_ffill_limit():
    cal = pd.bdate_range("2024-01-01", "2024-02-29")
    days = list(pd.bdate_range("2024-01-01", "2024-01-05")) + [pd.Timestamp("2024-01-22")]
    out = to_calendar(frame(days, [1.0, 1.0, 1.0, 1.0, 1.0, 2.0]), cal, daily_ffill_max=5, lowfreq_max_hold=70)
    assert out["2024-01-12"] == 1.0          # 1/5 관측 후 5번째 달력일까지 유지
    assert np.isnan(out["2024-01-15"])       # 6번째부터 결측
    assert out["2024-01-22"] == 2.0


def test_to_calendar_lowfreq_hold_weekend_release_and_expiry():
    cal = pd.bdate_range("2024-01-01", "2024-06-28")
    # 월별 기준일 두 번 공표, 두 번째는 토요일
    f = frame(["2023-12-08", "2024-01-06"], [4.0, 5.0], refs=["2023-11-30", "2023-12-31"])
    out = to_calendar(f, cal, daily_ffill_max=5, lowfreq_max_hold=70)
    assert out["2024-01-05"] == 4.0          # 달력 시작 전 공표 → 달력 첫날로
    assert out["2024-01-08"] == 5.0          # 토요일 공표 → 다음 영업일
    held = out["2024-01-08":].dropna()
    assert len(held) == 71                   # 관측일 + 70 달력일까지 유지
    assert np.isnan(out.iloc[-1])            # 70일 넘으면 결측(중단 시리즈 방지)


def test_hold_limits_causal():
    ref = pd.Series(pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-01", "2024-03-04", "2024-03-05"]))
    lim = hold_limits(ref, 5, 70, 5.0)
    assert lim[0] == 70 and lim[1] == 70     # 첫 관측·월 간격 → 저빈도
    assert lim[2] == 70                      # 간격 [29, 1] 중앙값 15 → 아직 저빈도
    assert lim[4] == 5                       # 간격 [29, 1, 3, 1] 중앙값 2 → 일별
    ref2 = pd.concat([ref, pd.Series(pd.to_datetime(["2024-06-30", "2024-09-30"]))], ignore_index=True)
    assert (hold_limits(ref2, 5, 70, 5.0)[:5] == lim).all()   # 미래 관측이 과거 한도를 바꾸지 않음


def test_percentile_expanding_warmup_and_monotone():
    idx = pd.bdate_range("2010-01-01", "2014-12-31")
    x = pd.Series(np.arange(len(idx), dtype=float), index=idx)
    p = percentile_expanding(x, min_history_years=3)
    assert p[:"2012-12-31"].isna().all()
    first = p.first_valid_index()
    assert first >= pd.Timestamp("2013-01-01")
    n = idx.get_loc(first) + 1
    assert p[first] == pytest.approx(100 * (n - 0.5) / n)   # 현재값이 최대: mid-rank
    assert (p.dropna() > 99.9).all()


def test_percentile_expanding_ties_and_nan():
    idx = pd.bdate_range("2010-01-01", "2013-06-30")
    x = pd.Series(1.0, index=idx)
    x.iloc[5] = np.nan
    p = percentile_expanding(x, min_history_years=3)
    assert p.dropna().eq(50.0).all()
    assert np.isnan(p.iloc[5])


def test_percentile_uses_only_past():
    idx = pd.bdate_range("2010-01-01", "2014-12-31")
    x = pd.Series(np.random.default_rng(0).normal(size=len(idx)), index=idx)
    t = pd.Timestamp("2013-06-28")
    assert percentile_expanding(x)[t] == percentile_expanding(x[:t])[t]
    assert percentile_rolling(x, 2, 3)[t] == percentile_rolling(x[:t], 2, 3)[t]


def test_percentile_rolling_window_differs_from_expanding():
    idx = pd.bdate_range("2010-01-01", "2016-12-31")
    x = pd.Series(np.arange(len(idx), dtype=float), index=idx)
    x[:"2011-12-31"] = -1000.0                # 오래된 극단값: 2년 창 밖으로 빠진다
    x["2016-06-01":] = x["2014-05-01"]        # 최근 값: 2년 창(2014-06~) 안에서는 최소, 전체 역사에서는 중간
    p_roll = percentile_rolling(x, window_years=2, min_history_years=3)
    p_exp = percentile_expanding(x, min_history_years=3)
    assert p_roll["2016-06-01"] < 2.0
    assert p_exp["2016-06-01"] > 30.0
    assert p_roll[:"2012-12-31"].isna().all()


def test_percentile_fractional_years():
    idx = pd.bdate_range("2010-01-01", "2013-12-31")
    x = pd.Series(np.arange(len(idx), dtype=float), index=idx)
    p = percentile_expanding(x, min_history_years=1.5)
    assert p.first_valid_index() >= pd.Timestamp("2011-07-01")
    assert percentile_rolling(x, window_years=0.5, min_history_years=1.5).notna().any()


def test_apply_direction():
    p = pd.Series([10.0, 90.0])
    assert apply_direction(p, 1).tolist() == [10.0, 90.0]
    assert apply_direction(p, -1).tolist() == [90.0, 10.0]
    with pytest.raises(ValueError):
        apply_direction(p, 0)
