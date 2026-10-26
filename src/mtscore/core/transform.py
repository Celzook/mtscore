"""Point-in-time 정렬, 결측 처리, 백분위 변환, 방향 반전.

PIT 규칙
- 한 필드의 행들(date=기준일, as_of=알려진 날)로 "그날 알 수 있던 최신값" 시계열을 만든다.
  가용일 t 의 값 = as_of ≤ t 인 행 중 가장 최근 기준일의 (그 기준일에 대한) 최신 vintage.
  옛 기준일의 늦은 수정(revision)은 더 새로운 기준일 값을 덮어쓰지 않는다.
- 이 시계열은 가용일(as_of) 기준으로 색인되므로, 이후의 변화율·차분·백분위도 모두 그 시점 정보만 쓴다.
- 값을 얼마나 오래 유지할지(일별 5영업일 / 저빈도 다음 공표까지)도 그 관측 시점까지의 기준일 간격만으로
  정한다(인과적 판정). 전체 이력으로 빈도를 판정하면 미래 행이 과거 유지 기간을 바꾼다.
"""
from __future__ import annotations

import bisect
import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def pit_frame(rows: pd.DataFrame) -> pd.DataFrame:
    """한 (asset, field) 의 패널 행들 → 가용일(as_of) 색인 DataFrame[value, ref].

    ref 는 그 값의 기준일(date). validate_panel 을 통과한 행(date, as_of, value)을 받는다.
    """
    if rows.empty:
        return pd.DataFrame(columns=["value", "ref"], dtype=float)
    d = rows[["date", "as_of", "value"]].sort_values(["as_of", "date"], kind="mergesort")
    d = d[d["date"] >= d["date"].cummax()]  # 지금까지 본 가장 새로운 기준일(또는 그 수정치)만
    g = d.groupby("as_of").last()
    out = pd.DataFrame({"value": g["value"].astype(float), "ref": g["date"]})
    out.index.name = None
    return out


def pit_series(rows: pd.DataFrame) -> pd.Series:
    """pit_frame 의 값 열만(가용일 색인 최신값 시계열)."""
    return pit_frame(rows)["value"]


def hold_limits(ref: pd.Series, daily_ffill_max: int, lowfreq_max_hold: int, threshold_days: float) -> np.ndarray:
    """관측마다 유지 한도(영업일). 그 관측까지의 기준일 간격(0 = 같은 기준일 수정치는 제외) 확장 중앙값이
    threshold_days(달력일)를 넘으면 저빈도로 보고 lowfreq_max_hold, 아니면 daily_ffill_max.
    첫 관측(간격 정보 없음)은 저빈도로 본다. 과거 정보만 쓰므로 PIT."""
    gaps = ref.diff().dt.days
    gaps = gaps.where(gaps > 0)
    med = gaps.expanding().median()
    low = med.isna() | (med > threshold_days)
    return np.where(low.to_numpy(), lowfreq_max_hold, daily_ffill_max)


def to_calendar(frame: pd.DataFrame, calendar: pd.DatetimeIndex, daily_ffill_max: int = 5,
                lowfreq_max_hold: int = 70, threshold_days: float = 5.0, label: str = "") -> pd.Series:
    """pit_frame 결과를 달력에 올린다.

    - 달력 밖의 가용일(주말·휴장일 공표)은 다음 달력일로 넘긴다. 같은 달력일에 여러 관측이면 마지막 것.
    - 각 관측은 hold_limits 가 정한 달력일 수까지만 유지하고, 넘으면 결측(결측 유지 일수는 DEBUG 로그).
    """
    if frame.empty or len(calendar) == 0:
        return pd.Series(np.nan, index=calendar, dtype=float)
    limits = hold_limits(frame["ref"], daily_ffill_max, lowfreq_max_hold, threshold_days).astype(float)
    pos = calendar.searchsorted(frame.index, side="left")
    # 달력 시작 전에 공표된 관측: 공표일부터 달력 첫날까지 지난 영업일만큼 유지 한도를 깎는다
    pre = frame.index < calendar[0]
    if pre.any():
        elapsed = np.busday_count(frame.index[pre].values.astype("datetime64[D]"),
                                  np.datetime64(calendar[0].date(), "D"))
        limits[pre] = limits[pre] - elapsed
    ok = (pos < len(calendar)) & (limits >= 0)
    obs = pd.DataFrame({"pos": pos[ok], "value": frame["value"].to_numpy()[ok], "limit": limits[ok]})
    obs = obs.groupby("pos").last()
    n = len(calendar)
    val = np.full(n, np.nan)
    lim = np.full(n, -1.0)
    src = np.full(n, -1.0)
    val[obs.index] = obs["value"].to_numpy()
    lim[obs.index] = obs["limit"].to_numpy()
    src[obs.index] = obs.index
    last = pd.Series(src).replace(-1.0, np.nan).ffill().to_numpy()
    v_ff = pd.Series(val).ffill().to_numpy()   # 관측일의 NaN 값은 생기지 않음(validate_panel 이 제거)
    l_ff = pd.Series(lim).replace(-1.0, np.nan).ffill().to_numpy()
    age = np.arange(n) - last
    keep = ~np.isnan(last) & (age <= l_ff)
    out = np.where(keep, v_ff, np.nan)
    expired = int((~keep & ~np.isnan(last)).sum())
    if expired:
        log.debug("%s: 유지 한도 초과로 결측 처리한 날 %d일", label, expired)
    return pd.Series(out, index=calendar)


def _years_offset(years: float) -> pd.DateOffset:
    """소수 연수도 받도록 월 단위 오프셋으로 바꾼다."""
    return pd.DateOffset(months=int(round(float(years) * 12)))


def percentile_expanding(x: pd.Series, min_history_years: float = 3.0) -> pd.Series:
    """자기 과거(현재 포함) 분포 내 백분위(0~100). 동률은 절반 반영(mid-rank).

    첫 유효 관측일로부터 min_history_years 년이 지나기 전은 NaN(워밍업). NaN 관측은 분포에 넣지 않는다.
    """
    out = np.full(len(x), np.nan)
    vals = x.to_numpy(dtype=float)
    valid_idx = np.flatnonzero(~np.isnan(vals))
    if len(valid_idx) == 0:
        return pd.Series(out, index=x.index)
    start = x.index[valid_idx[0]] + _years_offset(min_history_years)
    hist: list[float] = []
    for i in valid_idx:
        v = vals[i]
        bisect.insort(hist, v)
        if x.index[i] < start:
            continue
        lo = bisect.bisect_left(hist, v)
        hi = bisect.bisect_right(hist, v)
        out[i] = 100.0 * (lo + 0.5 * (hi - lo)) / len(hist)
    return pd.Series(out, index=x.index)


def percentile_rolling(x: pd.Series, window_years: float = 10.0, min_history_years: float = 3.0) -> pd.Series:
    """직전 window_years 년(현재 포함) 분포 내 백분위. 워밍업 규칙은 expanding 과 같다."""
    out = np.full(len(x), np.nan)
    vals = x.to_numpy(dtype=float)
    idx = x.index
    valid = ~np.isnan(vals)
    if not valid.any():
        return pd.Series(out, index=idx)
    first = idx[np.flatnonzero(valid)[0]]
    start = first + _years_offset(min_history_years)
    win_off = _years_offset(window_years)
    lo_ptr = 0
    for i in np.flatnonzero(valid):
        t = idx[i]
        if t < start:
            continue
        w0 = t - win_off
        while idx[lo_ptr] <= w0:
            lo_ptr += 1
        win = vals[lo_ptr:i + 1]
        win = win[~np.isnan(win)]
        v = vals[i]
        out[i] = 100.0 * ((win < v).sum() + 0.5 * (win == v).sum()) / len(win)
    return pd.Series(out, index=idx)


def apply_direction(pct: pd.Series, direction: int) -> pd.Series:
    """방향 반전: (+) 그대로, (−) 100 − 백분위. 결과는 '클수록 매수 매력'."""
    if direction not in (1, -1):
        raise ValueError(f"direction 은 +1/-1: {direction}")
    return pct if direction == 1 else 100.0 - pct
