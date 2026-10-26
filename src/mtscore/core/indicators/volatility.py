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


@register("term_ratio", n_inputs=2)
def term_ratio(front: pd.Series, back: pd.Series) -> pd.Series:
    """근월 ÷ 원월 변동성지수(> 1 이면 기간구조 역전)."""
    return front / back


@register("shock_return", window=20)
def shock_return(x: pd.Series, window: int) -> pd.Series:
    """window 일 로그수익률(통화 급변 등). 부호 해석은 프로파일 direction 이 정한다."""
    return np.log(x).diff(window)
