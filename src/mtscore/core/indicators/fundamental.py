"""펀더멘털 계열 계산 함수."""
from __future__ import annotations

import pandas as pd

from ..registry import register
from .price import lag_months


@register("revision_momentum", months=1)
def revision_momentum(fwd_eps: pd.Series, months: int) -> pd.Series:
    """수정 모멘텀: months 달력월 변화율의 months 달력월 차분(변화율이 가속되는지)."""
    chg = fwd_eps / lag_months(fwd_eps, months) - 1.0
    return chg - lag_months(chg, months)


@register("revision_ratio", n_inputs=2)
def revision_ratio(up: pd.Series, down: pd.Series) -> pd.Series:
    """이익수정비율 = (상향 − 하향) / (상향 + 하향)."""
    tot = (up + down).where(lambda s: s > 0)
    return (up - down) / tot


@register("yoy_momentum", months=3)
def yoy_momentum(level: pd.Series, months: int) -> pd.Series:
    """전년비(YoY) 의 months 개월 변화(%p). 물가지수 등 수준 시계열을 받는다(물가 모멘텀)."""
    yoy = (level / lag_months(level, 12) - 1.0) * 100.0
    return yoy - lag_months(yoy, months)


@register("spread_gap_change", n_inputs=2, months=3)
def spread_gap_change(low_grade: pd.Series, high_grade: pd.Series, months: int) -> pd.Series:
    """하위등급 − 상위등급 스프레드 차이의 months 개월 변화(신용 사이클). 확대 = 악화."""
    gap = low_grade - high_grade
    return gap - lag_months(gap, months)
