"""시장폭 계열 계산 함수. 구성종목 집계(비율·상승/하락 종목 수)는 어댑터가 field 로 공급한다."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..registry import register


@register("adr", n_inputs=2, window=20)
def adr(advancers: pd.Series, decliners: pd.Series, window: int) -> pd.Series:
    """등락비율: window 일 상승 종목 수 합 ÷ 하락 종목 수 합."""
    a = advancers.rolling(window, min_periods=window).sum()
    d = decliners.rolling(window, min_periods=window).sum()
    return a / d.replace(0.0, np.nan)
