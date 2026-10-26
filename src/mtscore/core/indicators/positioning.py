"""포지셔닝 계열 계산 함수(CFTC COT 등 주별 데이터)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..registry import register


@register("positioning_z", lookback=756)
def positioning_z(net: pd.Series, lookback: int) -> pd.Series:
    """순포지션의 z(직전 lookback 영업일, 기본 3년). 주별 값은 공표일 기준으로 일별 유지된 상태로 들어온다."""
    mu = net.rolling(lookback, min_periods=lookback // 2).mean()
    sd = net.rolling(lookback, min_periods=lookback // 2).std()
    return (net - mu) / sd.replace(0.0, np.nan)
