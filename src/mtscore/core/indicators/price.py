"""가격·수준 계열 계산 함수. 입력은 영업일 달력에 정렬된 시계열(결측 허용)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..registry import register

BDAYS_PER_YEAR = 252


def _realized_vol(x: pd.Series, window: int) -> pd.Series:
    r = np.log(x).diff()
    return r.rolling(window, min_periods=int(window * 0.8)).std() * np.sqrt(BDAYS_PER_YEAR)


@register("level")
def level(x: pd.Series) -> pd.Series:
    """수준 그대로(백분위는 transform 에서)."""
    return x.astype(float)


@register("disparity", window=20)
def disparity(x: pd.Series, window: int) -> pd.Series:
    """이격도: x / 이동평균(window) − 1."""
    ma = x.rolling(window, min_periods=window).mean()
    return x / ma - 1.0


@register("level_disparity", window=60)
def level_disparity(x: pd.Series, window: int) -> pd.Series:
    """수준 이격: x − 이동평균(window). 금리·스프레드처럼 비율이 무의미한 수준 변수용."""
    return x - x.rolling(window, min_periods=window).mean()


@register("drawdown_over_rv", lookback=252, rv_window=60)
def drawdown_over_rv(x: pd.Series, lookback: int, rv_window: int) -> pd.Series:
    """lookback 고점 대비 낙폭(음수) ÷ 연율화 실현변동성(rv_window)."""
    peak = x.rolling(lookback, min_periods=int(lookback * 0.8)).max()
    dd = x / peak - 1.0
    return dd / _realized_vol(x, rv_window)


@register("return_z", window=20, z_lookback=252)
def return_z(x: pd.Series, window: int, z_lookback: int) -> pd.Series:
    """window 일 로그수익률의 z(직전 z_lookback 일 분포 기준, 현재값 포함 rolling)."""
    r = np.log(x).diff(window)
    mu = r.rolling(z_lookback, min_periods=int(z_lookback * 0.8)).mean()
    sd = r.rolling(z_lookback, min_periods=int(z_lookback * 0.8)).std()
    return (r - mu) / sd.replace(0.0, np.nan)


@register("change_z", window=20, z_lookback=252)
def change_z(x: pd.Series, window: int, z_lookback: int) -> pd.Series:
    """window 일 수준 변화(차분)의 z. 금리·스프레드용."""
    d = x.diff(window)
    mu = d.rolling(z_lookback, min_periods=int(z_lookback * 0.8)).mean()
    sd = d.rolling(z_lookback, min_periods=int(z_lookback * 0.8)).std()
    return (d - mu) / sd.replace(0.0, np.nan)


@register("rsi", window=14)
def rsi(x: pd.Series, window: int) -> pd.Series:
    """Wilder RSI(0~100). 변화가 0 인 구간(상승·하락 모두 0)은 50."""
    d = x.diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    au = up.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    ad = dn.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    tot = au + ad
    out = 100.0 * au / tot
    return out.where(tot > 0, 50.0).where(au.notna())


def lag_months(x: pd.Series, months: int) -> pd.Series:
    """t 시점에 't − months 달력월' 시점의 값(그날 이전 마지막 달력일의 값, 결측이면 결측).

    고정 영업일 shift 와 달리 월 길이(20~23 영업일)에 흔들리지 않는다. x 는 to_calendar 결과이므로 그 시점에
    유지 한도를 넘긴 값은 이미 결측 — 오래된 값을 되살리지 않는다. t 이전 값만 쓰므로 PIT.
    정의상 '지금 알려진 값 vs n개월 전에 알려진 값' 비교다. 공표일이 매달 흔들리는 월별 필드는 드물게(약 4%)
    직전 공표가 아니라 그 전 공표와 비교된다(가정: 이 정의를 그대로 쓴다)."""
    target = x.index - pd.DateOffset(months=months)
    pos = x.index.searchsorted(target, side="right") - 1
    vals = np.where(pos >= 0, x.to_numpy(dtype=float)[np.clip(pos, 0, None)], np.nan)
    return pd.Series(vals, index=x.index)


@register("pct_change_months", months=3)
def pct_change_months(x: pd.Series, months: int) -> pd.Series:
    """months 달력월 변화율: x_t / (t − months 시점에 알려진 x) − 1."""
    return x / lag_months(x, months) - 1.0


@register("diff_months", months=3)
def diff_months(x: pd.Series, months: int) -> pd.Series:
    """months 달력월 수준 차분(금리차 등)."""
    return x - lag_months(x, months)


@register("gap_to_long_mean", lookback_years=10)
def gap_to_long_mean(x: pd.Series, lookback_years: int) -> pd.Series:
    """log(x / 과거 lookback_years 년 평균). 최소 절반 기간 이상 쌓인 뒤부터."""
    w = lookback_years * BDAYS_PER_YEAR
    return np.log(x / x.rolling(w, min_periods=w // 2).mean())


@register("ratio_minus_one", n_inputs=2)
def ratio_minus_one(a: pd.Series, b: pd.Series) -> pd.Series:
    """a / b − 1 (예: 선물 커브 c1/c2 − 1 = 백워데이션)."""
    return a / b - 1.0


@register("spread", n_inputs=2)
def spread(a: pd.Series, b: pd.Series) -> pd.Series:
    """a − b (예: 금리 − 기준금리)."""
    return a - b


@register("ratio", n_inputs=2)
def ratio(a: pd.Series, b: pd.Series) -> pd.Series:
    """a / b (예: 실질가격 = 명목가격 / CPI)."""
    return a / b
