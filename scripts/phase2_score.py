"""Phase 2 — 패널로 10개 자산 점수를 낸다(엔진 공개 API만 사용).

    .venv/bin/python scripts/phase2_score.py [기준일=2026-10-27]

산출(outputs/phase2/): coverage.csv · latest_indicators.csv · latest_scores.csv · score_history.csv.gz ·
result_<기준일>.json(docs/result_schema.md)
"""
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from mtscore import ScoringEngine, load_config  # noqa: E402

OUT = ROOT / "outputs" / "phase2"


def main(as_of="2026-10-27"):
    t0 = time.time()
    panel = pd.read_csv(ROOT / "data" / "processed" / "panel.csv.gz", parse_dates=["date", "as_of"])
    eng = ScoringEngine(load_config(ROOT / "config"))
    res = eng.score(panel, as_of=as_of)
    OUT.mkdir(parents=True, exist_ok=True)
    res.coverage.to_csv(OUT / "coverage.csv", index=False)
    res.contributions.to_csv(OUT / "latest_indicators.csv", index=False)
    latest = res.blocks.copy()
    latest.columns = [f"score_{c}" for c in latest.columns]
    latest = latest.join(res.bands.add_prefix("band_")).join(res.regime)
    latest.insert(0, "date", res.dates)
    latest.insert(1, "stale", res.stale)
    latest.index.name = "asset_id"
    latest.to_csv(OUT / "latest_scores.csv")
    rows = []
    for aid, h in res.history.items():
        b = h.blocks.copy()
        b.index.name = "date"
        b = b.reset_index().assign(asset_id=aid)
        rows.append(b)
    hist = pd.concat(rows, ignore_index=True)[["asset_id", "date", "oversold", "valuation", "fundamental"]]
    hist = hist.dropna(subset=["oversold", "valuation", "fundamental"], how="all")
    hist.round(4).to_csv(OUT / "score_history.csv.gz", index=False)
    (OUT / f"result_{as_of}.json").write_text(res.to_json(indent=1), encoding="utf-8")
    info = {"as_of": as_of, "score_seconds": round(time.time() - t0, 1), "history_rows": int(len(hist)),
            "history_first": {a: str(g["date"].min().date()) for a, g in hist.groupby("asset_id")}}
    (OUT / "score_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    pd.set_option("display.width", 250)
    print(latest.to_string())
    print(json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    main(*sys.argv[1:])
