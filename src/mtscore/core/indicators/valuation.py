"""밸류에이션 계열 계산 함수."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..registry import register
from .price import BDAYS_PER_YEAR


@register("erp", n_inputs=2)
def erp(fwd_per: pd.Series, local_yield_pct: pd.Series) -> pd.Series:
    """주식위험프리미엄(%p) = 100 / Fwd PER − 10년 국채(%). PER ≤ 0 은 NaN."""
    ey = 100.0 / fwd_per.where(fwd_per > 0)
    return ey - local_yield_pct


@register("real_price_gap", n_inputs=2, lookback_years=10)
def real_price_gap(price: pd.Series, cpi: pd.Series, lookback_years: int) -> pd.Series:
    """물가 디플레이트 실질가격의 log(현재 / 과거 lookback_years 년 평균)."""
    real = price / cpi
    w = lookback_years * BDAYS_PER_YEAR
    return np.log(real / real.rolling(w, min_periods=w // 2).mean())
