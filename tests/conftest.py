"""테스트 공용 픽스처. 여기서 만드는 합성 데이터는 테스트 전용이다 — 결과 보고에 쓰지 않는다."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mtscore import build_config

ROOT = Path(__file__).resolve().parent.parent


def synth_daily(start="2010-01-01", end="2016-12-31", seed=0, s0=100.0, vol=0.01) -> pd.Series:
    """기하 랜덤워크 일별 시계열(테스트 전용)."""
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    return pd.Series(s0 * np.exp(np.cumsum(rng.normal(0, vol, len(idx)))), index=idx)


def to_panel(asset_id: str, field: str, s: pd.Series, lag_days: int = 0, source: str = "synthetic") -> pd.DataFrame:
    """시계열 → 4-1 스키마 행. lag_days 만큼 as_of 를 늦춘다(공표 지연)."""
    return pd.DataFrame({"date": s.index, "asset_id": asset_id, "field": field, "value": s.values,
                         "as_of": s.index + pd.to_timedelta(lag_days, unit="D"), "source": source})


def monthly(s: pd.Series) -> pd.Series:
    """월말 표본."""
    return s.groupby(s.index.to_period("M")).last().set_axis(s.groupby(s.index.to_period("M")).apply(lambda x: x.index[-1]))


@pytest.fixture
def mini_profiles() -> dict:
    """작은 equity 프로파일(블록마다 1~2개 지표)."""
    return {"equity_index": {"asset_class": "equity_index", "blocks": {
        "oversold": {"price": [
            {"name": "disparity_20", "indicator": "disparity", "direction": "-", "fields": ["close"],
             "params": {"window": 20}},
            {"name": "rsi_14", "indicator": "rsi", "direction": "-", "fields": ["close"], "params": {"window": 14}}],
            "fx": [{"name": "ccy_shock", "indicator": "shock_return", "direction": "+", "fields": ["fx_home"],
                    "params": {"window": 20}, "flags": ["currency"]}]},
        "valuation": {"multiples": [
            {"name": "pbr", "indicator": "level", "direction": "-", "fields": ["pbr"]}]},
        "fundamental": {"earnings": [
            {"name": "eps_chg_1m", "indicator": "pct_change_months", "direction": "+", "fields": ["fwd_eps_12m"],
             "params": {"months": 1}},
            {"name": "rev_ratio", "indicator": "revision_ratio", "direction": "+", "fields": ["up", "down"],
             "status": "na_until_found"}],
            "macro": [{"name": "ccy_trend", "indicator": "pct_change_months", "direction": "+", "fields": ["fx_home"],
                       "params": {"months": 3}, "flags": ["currency"]}]},
    }}}


@pytest.fixture
def scoring_cfg() -> dict:
    import yaml
    return yaml.safe_load((ROOT / "config" / "scoring.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def mini_universe() -> list[dict]:
    return [{"asset_id": "EQ", "asset_class": "equity_index", "refs": {"fx_home": "FX.close"}},
            {"asset_id": "FX", "asset_class": "equity_index"}]


@pytest.fixture
def mini_config(mini_universe, mini_profiles, scoring_cfg):
    return build_config(mini_universe, mini_profiles, scoring_cfg)


@pytest.fixture
def mini_panel() -> pd.DataFrame:
    """EQ: 일별 close, 월별 pbr·fwd_eps_12m(공표 5일 지연). FX: 일별 close. 2010~2016."""
    close = synth_daily(seed=1)
    pbr = monthly(synth_daily(seed=2, s0=1.0, vol=0.005))
    eps = monthly(synth_daily(seed=3, s0=50.0, vol=0.004))
    fx = synth_daily(seed=4, s0=1100.0, vol=0.005)
    return pd.concat([to_panel("EQ", "close", close), to_panel("EQ", "pbr", pbr, lag_days=5),
                      to_panel("EQ", "fwd_eps_12m", eps, lag_days=5), to_panel("FX", "close", fx)],
                     ignore_index=True)
