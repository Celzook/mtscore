"""Phase 4 E (TREND) — KR_CORP 추세 표시의 현금 차감 면제(결정 4) 전후 점검.

    .venv/bin/python scripts/phase4e_trend_check.py

1) 점수 불변: score_history 가 outputs/phase2/score_history.csv.gz 와 정확히 같다(phase2_score.py 와 같은 절차).
2) result JSON: Phase 2 결과에서 trend(basis 추가)·schema_version 만 다르다.
3) KR_CORP 추세: 이전(현금 차감) vs 이후(면제) 양(+)인 날 비율·값 차이. 다른 자산은 phase4b_trend_coverage.csv 와 동일.
산출: outputs/phase4/phase4e_trend_kr_corp.csv · phase4e_trend_check.json
"""
import dataclasses
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from mtscore import ScoringEngine, load_config  # noqa: E402

OUT = ROOT / "outputs" / "phase4"
AS_OF = "2026-10-27"


def share(v: pd.Series) -> float:
    return float((v > 0).sum() / v.notna().sum())


def main():
    panel = pd.read_csv(ROOT / "data" / "processed" / "panel.csv.gz", parse_dates=["date", "as_of"])
    cfg = load_config(ROOT / "config")
    eng = ScoringEngine(cfg)
    res = eng.score(panel, as_of=AS_OF)

    rows = []
    for aid, h in res.history.items():
        b = h.blocks.copy()
        b.index.name = "date"
        rows.append(b.reset_index().assign(asset_id=aid))
    hist = pd.concat(rows, ignore_index=True)[["asset_id", "date", "oversold", "valuation", "fundamental"]]
    hist = hist.dropna(subset=["oversold", "valuation", "fundamental"], how="all").round(4).reset_index(drop=True)
    p2 = pd.read_csv(OUT.parent / "phase2" / "score_history.csv.gz", parse_dates=["date"])
    pd.testing.assert_frame_equal(hist, p2, check_exact=True, check_dtype=False)   # 다르면 여기서 중단
    print(f"[1] score_history {len(hist):,}행 Phase 2 와 정확히 동일")

    j_new = res.to_dict()
    j_old = json.loads((OUT.parent / "phase2" / f"result_{AS_OF}.json").read_text(encoding="utf-8"))
    for a in j_new["assets"]:
        a.pop("trend")
    for a in j_old["assets"]:
        a.pop("staged_entry", None)
        a.pop("trend", None)
    for a in j_new["assets"]:
        a.pop("staged_entry")
    v_new, v_old = j_new.pop("schema_version"), j_old.pop("schema_version")
    assert j_new == j_old, "result JSON(trend·staged_entry·버전 제외)이 Phase 2 와 다름"
    print(f"[2] result JSON(trend·staged_entry·schema_version 제외) Phase 2 와 동일 ({v_old} -> {v_new})")

    after = eng.trend_history(panel)
    # 이전 동작 = KR_CORP 도 현금을 뺀다(면제 해제)
    uni_before = [dataclasses.replace(a, trend_cash="subtract") if a.asset_id == "KR_CORP" else a for a in cfg.universe]
    eng_b = ScoringEngine(dataclasses.replace(cfg, universe=uni_before))
    before = eng_b.trend_history(panel, ["KR_CORP"])
    cov = pd.read_csv(OUT / "phase4b_trend_coverage.csv").set_index("asset_id")
    others = {}
    for aid, fr in after.items():
        if aid == "KR_CORP":
            continue
        s = share(fr["value"])
        assert abs(s - cov.at[aid, "share_pos"]) < 1e-12 and int(fr["value"].notna().sum()) == cov.at[aid, "n_days"], aid
        others[aid] = round(s, 4)
    print(f"[3a] KR_CORP 외 9개 자산 share_pos·n_days 가 phase4b_trend_coverage.csv 와 동일")

    vb, va = before["KR_CORP"]["value"], after["KR_CORP"]["value"]
    assert abs(share(vb) - cov.at["KR_CORP", "share_pos"]) < 1e-12   # 이전 재계산이 기존 산출과 일치
    d = pd.DataFrame({"value_before_cash_subtracted": vb, "value_after_no_cash": va}).dropna()
    d["diff"] = d["value_after_no_cash"] - d["value_before_cash_subtracted"]
    d["sign_before"] = np.sign(d["value_before_cash_subtracted"]).astype(int)
    d["sign_after"] = np.sign(d["value_after_no_cash"]).astype(int)
    d.index.name = "date"
    d.to_csv(OUT / "phase4e_trend_kr_corp.csv", float_format="%.6f")
    flip = int((d["sign_before"] != d["sign_after"]).sum())
    info = {
        "as_of": AS_OF, "n_days": int(len(d)), "first_value_date": str(d.index.min().date()),
        "share_pos_before": round(share(vb), 4), "share_pos_after": round(share(va), 4),
        "sign_flip_days": flip, "sign_flip_share": round(flip / len(d), 4),
        "mean_diff": round(float(d["diff"].mean()), 4), "min_diff": round(float(d["diff"].min()), 4),
        "max_diff": round(float(d["diff"].max()), 4),
        "latest_before": round(float(vb.dropna().iloc[-1]), 4), "latest_after": round(float(va.dropna().iloc[-1]), 4),
        "latest_trend_json": next(a["trend"] for a in res.to_dict()["assets"] if a["asset_id"] == "KR_CORP"),
        "other_assets_share_pos": others,
    }
    (OUT / "phase4e_trend_check.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[3b]", json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    main()
