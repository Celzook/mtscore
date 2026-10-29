"""변동성·심리 계열 계산 함수."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..registry import register
from .price import _realized_vol, bb_pctb


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


OVERSOLD_SIDES = ("lower", "upper")


def _if_oversold(x: pd.Series, vol: pd.Series, bb_window: int, bb_k: float, oversold_side: str, pctb_edge: float,
                 neutral: float) -> pd.Series:
    """vol 을 같은 입력 x 의 볼린저 %b(bb_pctb, ddof=1)가 과매도 쪽 밴드 밖인 날에만 쓰고, 그 밖의 날은 neutral.

    oversold_side: lower = %b < pctb_edge(가격형, 하단 이탈) / upper = %b > pctb_edge(수준형 금리·스프레드, 상단 이탈).
    %b 나 vol 이 NaN 이면 NaN. 조건은 원 지표 %b 로만 건다(블록 점수로 걸면 순환 참조)."""
    if oversold_side not in OVERSOLD_SIDES:
        raise ValueError(f"oversold_side 는 {OVERSOLD_SIDES} 중 하나 ({oversold_side!r})")
    pb = bb_pctb(x, bb_window, bb_k)
    cond = pb < pctb_edge if oversold_side == "lower" else pb > pctb_edge
    return vol.where(cond, float(neutral)).where(pb.notna() & vol.notna())


@register("rv_ratio_if_oversold", window=20, lookback=252, bb_window=20, bb_k=2.0, oversold_side="lower",
          pctb_edge=0.0, neutral=1.0)
def rv_ratio_if_oversold(x: pd.Series, window: int, lookback: int, bb_window: int, bb_k: float, oversold_side: str,
                         pctb_edge: float, neutral: float) -> pd.Series:
    """조건부 변동성비(사용자 결정 2026-10-29, 사전 등록 B1): 과매도 쪽 밴드 밖인 날만 rv_ratio, 그 밖은 neutral(1.0).
    기본값(lower, 0)은 가격형 정의다. 프로파일은 oversold_side·pctb_edge 를 params 로 명시한다(자산별 하드코딩 없음).
    알려진 부작용: 과매도인데 변동성이 낮은(rv_ratio < 1) 날은 과매도가 아닌 날(1.0)보다 낮게 순위가 매겨진다."""
    return _if_oversold(x, rv_ratio(x, window, lookback), bb_window, bb_k, oversold_side, pctb_edge, neutral)


@register("level_rv_ratio_if_oversold", window=20, lookback=252, bb_window=20, bb_k=2.0, oversold_side="upper",
          pctb_edge=1.0, neutral=1.0)
def level_rv_ratio_if_oversold(x: pd.Series, window: int, lookback: int, bb_window: int, bb_k: float,
                               oversold_side: str, pctb_edge: float, neutral: float) -> pd.Series:
    """level_rv_ratio 의 조건부판(금리·스프레드). 기본값(upper, 1)은 수준형 정의다. 규칙은 rv_ratio_if_oversold 와 같다."""
    return _if_oversold(x, level_rv_ratio(x, window, lookback), bb_window, bb_k, oversold_side, pctb_edge, neutral)


@register("term_ratio", n_inputs=2)
def term_ratio(front: pd.Series, back: pd.Series) -> pd.Series:
    """근월 ÷ 원월 변동성지수(> 1 이면 기간구조 역전)."""
    return front / back


@register("shock_return", window=20)
def shock_return(x: pd.Series, window: int) -> pd.Series:
    """window 일 로그수익률(통화 급변 등). 부호 해석은 프로파일 direction 이 정한다."""
    return np.log(x).diff(window)
