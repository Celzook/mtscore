"""Phase 2 — PIT 재현 점검: 과거 기준일로 잘라 계산한 점수 = 전체 이력의 그날 점수인지(score_history 는 소수 4자리 반올림).
그리고 패널의 as_of ≥ date 위반·미래 as_of 행이 없는지. 산출: outputs/phase2/pit_recompute_check.csv

    .venv/bin/python scripts/phase2_pit_check.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from mtscore import ScoringEngine, load_config  # noqa: E402

OUT = ROOT / "outputs" / "phase2"


def main(dates=("2020-03-23", "2024-08-05")):
    panel = pd.read_csv(ROOT / "data" / "processed" / "panel.csv.gz", parse_dates=["date", "as_of"])
    assert (panel["as_of"] >= panel["date"]).all()
    print("as_of 최댓값", panel["as_of"].max().date(), "date 최댓값", panel["date"].max().date())
    eng = ScoringEngine(load_config(ROOT / "config"))
    h = pd.read_csv(OUT / "score_history.csv.gz", parse_dates=["date"])
    rows = []
    for d in dates:
        r = eng.score(panel, as_of=d)
        for aid in r.blocks.index:
            t = r.dates[aid]
            hh = h[(h["asset_id"] == aid) & (h["date"] == t)]
            for b in ("oversold", "valuation", "fundamental"):
                a = r.blocks.at[aid, b]
                x = hh[b].iloc[0] if len(hh) else np.nan
                rows.append({"as_of": d, "asset_id": aid, "date": str(t.date()), "block": b, "cut": a, "history": x,
                             "absdiff": 0.0 if (np.isnan(a) and np.isnan(x)) else abs(a - x)})
    o = pd.DataFrame(rows)
    o.to_csv(OUT / "pit_recompute_check.csv", index=False)
    print(len(o), "건, 최대 차", o["absdiff"].max(), "NaN 불일치", int((o["cut"].isna() != o["history"].isna()).sum()))


if __name__ == "__main__":
    main()
