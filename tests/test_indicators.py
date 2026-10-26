import numpy as np
import pandas as pd
import pytest

from mtscore.core import indicators  # noqa: F401
from mtscore.core.registry import get_func, register, registered

idx = pd.bdate_range("2020-01-01", periods=300)


def f(name, *s, **kw):
    spec = get_func(name)
    return spec.func(*s, **{**spec.defaults, **kw})


def test_disparity_known_value():
    x = pd.Series(np.r_[np.full(19, 10.0), 20.0], index=idx[:20])
    out = f("disparity", x, window=20)
    assert out.iloc[-1] == pytest.approx(20.0 / 10.5 - 1.0)
    assert out.iloc[:-1].isna().all()


def test_rsi_bounds_and_extremes():
    up = pd.Series(np.arange(1, 101, dtype=float), index=idx[:100])
    assert f("rsi", up, window=14).dropna().eq(100.0).all()
    flat = pd.Series(5.0, index=idx[:50])
    assert f("rsi", flat, window=14).dropna().eq(50.0).all()
    rng = np.random.default_rng(0)
    rw = pd.Series(100 + np.cumsum(rng.normal(size=300)), index=idx)
    r = f("rsi", rw, window=14).dropna()
    assert ((r >= 0) & (r <= 100)).all()


def test_erp_and_nonpositive_per():
    per = pd.Series([10.0, 20.0, -5.0], index=idx[:3])
    y = pd.Series([3.0, 3.0, 3.0], index=idx[:3])
    out = f("erp", per, y)
    assert out.iloc[0] == pytest.approx(7.0) and out.iloc[1] == pytest.approx(2.0)
    assert np.isnan(out.iloc[2])


def test_pct_change_months_uses_calendar_month():
    x = pd.Series(np.arange(1, 101, dtype=float), index=idx[:100])   # 2020-01-01 부터 영업일
    out = f("pct_change_months", x, months=1)
    assert out[:"2020-01-31"].isna().all()                           # 한 달 전 값이 아직 없음
    # 2020-03-02 의 한 달 전 = 2020-02-02(일) → 그 이전 마지막 값 = 2020-01-31
    assert out["2020-03-02"] == pytest.approx(x["2020-03-02"] / x["2020-01-31"] - 1.0)


def test_month_lag_on_held_monthly_field_hits_previous_release():
    """월별 값을 영업일에 유지한 시계열에서 1개월 변화는 항상 직전 공표치와 비교(고정 21영업일이면 어긋남)."""
    cal = pd.bdate_range("2020-01-01", "2021-12-31")
    rel = pd.date_range("2020-01-31", "2021-12-31", freq="BME")
    vals = pd.Series(np.arange(1, len(rel) + 1, dtype=float), index=rel)   # 매달 1씩 증가
    held = vals.reindex(cal).ffill()
    chg = f("diff_months", held, months=1).dropna()
    # 정의: 지금 알려진 값 − 한 달 전(t − 1개월)에 알려진 값 = (t − 1개월, t] 사이 공표 횟수
    expected = pd.Series([((rel > t - pd.DateOffset(months=1)) & (rel <= t)).sum() for t in chg.index],
                         index=chg.index, dtype=float)
    pd.testing.assert_series_equal(chg, expected, check_names=False)
    assert (chg == 1.0).mean() > 0.9


def test_revision_ratio():
    up = pd.Series([3.0, 0.0], index=idx[:2])
    dn = pd.Series([1.0, 0.0], index=idx[:2])
    out = f("revision_ratio", up, dn)
    assert out.iloc[0] == pytest.approx(0.5) and np.isnan(out.iloc[1])


def test_change_z_and_return_z_finite():
    rng = np.random.default_rng(1)
    x = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))), index=idx)
    for name in ("return_z", "change_z", "drawdown_over_rv"):
        out = f(name, x)
        assert np.isfinite(out.dropna()).all() and out.notna().sum() > 0


def test_registry_rejects_duplicate_name():
    with pytest.raises(ValueError, match="중복"):
        register("disparity")(lambda x: x)


def test_unknown_function_lists_registered():
    with pytest.raises(KeyError, match="등록되지 않은"):
        get_func("nope")
    assert "disparity" in registered()


def test_yoy_momentum_known_value():
    m = pd.date_range("2019-01-31", "2021-12-31", freq="BME")
    cpi = pd.Series(100.0, index=m)
    cpi["2020-01-31":] = 102.0          # 2020-01 부터 2% 높은 수준
    cpi["2021-01-31":] = 102.0          # 2021 전년비 0%
    held = cpi.reindex(pd.bdate_range(m[0], m[-1])).ffill()
    out = f("yoy_momentum", held, months=3)
    # 2020-06 말: YoY 2% (3개월 전 2020-03 도 2%) → 모멘텀 0
    assert out["2020-06-30"] == pytest.approx(0.0, abs=1e-9)
    # 2021-03 말: YoY 0%, 3개월 전(2020-12) YoY 2% → −2%p
    assert out["2021-03-31"] == pytest.approx(-2.0)


def test_spread_gap_change():
    i2 = pd.bdate_range("2020-01-01", "2020-12-31")
    hy = pd.Series(np.linspace(5.0, 4.0, len(i2)), index=i2)
    ig = pd.Series(1.0, index=i2)
    out = f("spread_gap_change", hy, ig, months=3).dropna()
    assert (out < 0).all()              # 차이 축소 → 음수(프로파일 direction '-' 로 매수 매력 ↑)
