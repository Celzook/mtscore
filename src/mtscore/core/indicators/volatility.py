"""변동성·심리 계열 계산 함수."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..registry import register
from .price import _realized_vol


@register("vol_over_rv", n_inputs=2, rv_window=20)
def vol_over_rv(vol_index: pd.Series, close: pd.Series, rv_window: int) -> pd.Series:
    """내재변동성지수(%) ÷ 기초자산 실현변동성(%)."""
    rv = _realized_vol(close, rv_window) * 100.0
    return vol_index / rv.replace(0.0, np.nan)


@register("rv_ratio", window=20, lookback=252)
def rv_ratio(x: pd.Series, window: int, lookback: int) -> pd.Series:
    """실현변동성(window, 로그수익률) ÷ 그 실현변동성의 현재값 포함 lookback 일 평균(rolling,
    min_periods 0.8·lookback). > 1 이면 평소보다 변동성이 높다. 평균이 0 이면 NaN."""
    rv = _realized_vol(x, window)
    return rv / rv.rolling(lookback, min_periods=int(lookback * 0.8)).mean().replace(0.0, np.nan)


@register("level_rv_ratio", window=20, lookback=252)
def level_rv_ratio(x: pd.Series, window: int, lookback: int) -> pd.Series:
    """rv_ratio 의 수준 변수판(금리·스프레드): 1차 차분의 rolling(window) 표준편차 ÷ 그 현재값 포함 lookback 일 평균.
    disparity / level_disparity 짝과 같은 관계. 연율화 계수는 비율에서 상쇄되므로 곱하지 않는다."""
    vol = x.diff().rolling(window, min_periods=int(window * 0.8)).std()
    return vol / vol.rolling(lookback, min_periods=int(lookback * 0.8)).mean().replace(0.0, np.nan)


@register("term_ratio", n_inputs=2)
def term_ratio(front: pd.Series, back: pd.Series) -> pd.Series:
    """근월 ÷ 원월 변동성지수(> 1 이면 기간구조 역전)."""
    return front / back


@register("shock_return", window=20)
def shock_return(x: pd.Series, window: int) -> pd.Series:
    """window 일 로그수익률(통화 급변 등). 부호 해석은 프로파일 direction 이 정한다."""
    return np.log(x).diff(window)
