"""공개 API 시연 — 합성 데이터(테스트·시연 전용, 결과 해석·보고 금지).

    .venv/bin/python examples/demo_synthetic.py

저장소 config/ 를 그대로 읽고, 유니버스 중 KOSPI200·USDKRW·KTB10Y·KR_CORP 네 자산에만 합성 패널을 만들어 넣는다.
나머지 자산은 데이터가 없어 coverage 에 missing_field 로 나온다 — 이 동작 자체가 시연 대상이다.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from mtscore import ScoringEngine, load_config

ROOT = Path(__file__).resolve().parent.parent
rng = np.random.default_rng(42)
idx = pd.bdate_range("2010-01-04", "2016-12-30")


def walk(s0, vol):
    return pd.Series(s0 * np.exp(np.cumsum(rng.normal(0, vol, len(idx)))), index=idx)


def rows(aid, field, s, lag=0):
    return pd.DataFrame({"date": s.index, "asset_id": aid, "field": field, "value": s.values,
                         "as_of": s.index + pd.to_timedelta(lag, unit="D"), "source": "SYNTHETIC"})


def month_end(s):
    return s.groupby(s.index.to_period("M")).tail(1)


k200 = walk(250, 0.012)
panel = pd.concat([
    rows("KOSPI200", "close", k200),
    rows("KOSPI200", "vol_index", walk(18, 0.03)),
    rows("KOSPI200", "pbr", month_end(walk(1.0, 0.006)), lag=3),
    rows("KOSPI200", "fwd_per", month_end(walk(10, 0.006)), lag=3),
    rows("KOSPI200", "fwd_eps_12m", month_end(walk(25, 0.004)), lag=3),
    rows("USDKRW", "close", walk(1150, 0.005)),
    rows("KTB10Y", "yield", walk(3.0, 0.01)),
    rows("KR_CORP", "spread", walk(0.8, 0.01)),
], ignore_index=True)

engine = ScoringEngine(load_config(ROOT / "config"))
res = engine.score(panel, as_of="2016-06-30", asset_ids=["KOSPI200", "USDKRW", "KTB10Y", "KR_CORP"])
pd.set_option("display.width", 160)
print("as_of:", res.as_of.date())
print("\n[blocks]\n", res.blocks.round(1))
print("\n[regime]\n", res.regime)
print("\n[coverage: KOSPI200 제외 지표]\n",
      res.coverage[(res.coverage.asset_id == "KOSPI200") & (~res.coverage.used)][["indicator", "reason"]].to_string(index=False))
print("\n[contributions: KOSPI200 oversold]\n",
      res.contributions[(res.contributions.asset_id == "KOSPI200") & (res.contributions.block == "oversold")]
      .dropna(subset=["contribution"])[["indicator", "raw", "percentile", "score", "weight_in_block"]].round(3).to_string(index=False))
print("\n[json head]", res.to_json()[:300], "...")
