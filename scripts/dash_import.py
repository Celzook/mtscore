"""Stock_Dashboard 가격 이력을 mtscore 패널 형식으로 옮긴다(대시보드 2단계 ①: 과매도 블록만, 2026-10-29 사용자 결정).

    .venv/bin/python scripts/dash_import.py [대시보드 폴더]

입력(읽기만): <대시보드>/data/history/equity_daily.csv(티커 열), yf_daily.csv(키 열) — 둘 다 Refinitiv 종가.
출력: data/processed/panel_dash.csv.gz (date, asset_id, field=close, value, as_of=date, source)
자산과 원천 열의 대응은 config/dash_assets.yaml 에 있다(자산 추가 = 그 파일과 universe.yaml 에 한 줄씩).
"""
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DASH = ROOT.parent.parent / "_public" / "_equity_manage" / "Stock_Dashboard"
OUT = ROOT / "data" / "processed" / "panel_dash.csv.gz"


def main(dash=None):
    dash = Path(dash) if dash else DEFAULT_DASH
    spec = yaml.safe_load((ROOT / "config" / "dash_assets.yaml").read_text(encoding="utf-8"))
    rows = []
    for fname, assets in spec["files"].items():
        df = pd.read_csv(dash / "data" / "history" / fname, index_col=0, parse_dates=True)
        for aid, col in assets.items():
            if col not in df:
                raise KeyError(f"{fname} 에 열 {col} 없음 ({aid})")
            s = pd.to_numeric(df[col], errors="coerce").dropna()
            s = s[s > 0]
            if aid in spec.get("start", {}):
                s = s[s.index >= pd.Timestamp(str(spec["start"][aid]))]
            rows.append(pd.DataFrame({"date": s.index, "asset_id": aid, "field": "close", "value": s.values,
                                      "as_of": s.index, "source": f"Stock_Dashboard {fname}:{col} (Refinitiv 종가)"}))
    out = pd.concat(rows, ignore_index=True).sort_values(["asset_id", "date"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, date_format="%Y-%m-%d")
    print(out.groupby("asset_id")["date"].agg(["min", "max", "count"]).to_string())


if __name__ == "__main__":
    main(*sys.argv[1:])
