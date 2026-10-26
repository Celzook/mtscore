"""수급 계열 계산 함수."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..registry import register


@register("flow_intensity", window=20, z_lookback=252)
def flow_intensity(net_flow: pd.Series, window: int, z_lookback: int) -> pd.Series:
    """window 일 누적 순매수의 z(직전 z_lookback 일 기준)."""
    s = net_flow.rolling(window, min_periods=window).sum()
    mu = s.rolling(z_lookback, min_periods=int(z_lookback * 0.8)).mean()
    sd = s.rolling(z_lookback, min_periods=int(z_lookback * 0.8)).std()
    return (s - mu) / sd.replace(0.0, np.nan)
