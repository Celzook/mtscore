"""Phase 4 C0 — 장기 반전 지표용 장기 필드 패널(data/processed/phase4c_long_panel.csv.gz).

    .venv/bin/python scripts/phase4c_build.py

네트워크를 쓰지 않는다(수집은 scripts/phase4c_collect.py). 2005~2009 원자료(data/raw/phase4c_long/)와 Phase 2 원자료
(data/raw/refinitiv/ts, 2010~)를 읽기만 하고, Phase 2 와 같은 빌더 함수(data/build.py)로 연속물을 만든다.
기존 패널(panel.csv.gz)은 읽기만 한다(2010~ 구간이 Phase 2 close 와 같은지 대조).

필드(새 이름 — 기존 지표 입력과 분리, 사전 등록 C1):
  GOLD·WTI  close_long, close_long_m60     연속물(Phase 2 와 같은 규칙)과 그 60 달력월 전 값
  USDKRW    reer_long,  reer_long_m60      FRED RBKRBIS(as_of = 기준월 + 3개월, Phase 2 와 같은 가정)
  KTB10Y·UST10Y yield_long, yield_long_m60 KRTSY10Y=KQ / US10YT=RR
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from mtscore.data import build as B  # noqa: E402
from mtscore.data.adapters.fred import FredAdapter  # noqa: E402
from mtscore.data.adapters.refinitiv import parse_timeseries_single  # noqa: E402
from mtscore.data.schema import validate_panel  # noqa: E402
from phase2_build import _gold_roll_check, _roll_offsets  # noqa: E402  (Phase 2 검증 함수 재사용)

RAW_LONG = ROOT / "data" / "raw" / "phase4c_long"
RF_TS = ROOT / "data" / "raw" / "refinitiv" / "ts"
PROC = ROOT / "data" / "processed"
OUT = ROOT / "outputs" / "phase4"
START, END = "2005-01-01", "2026-10-27"   # END = Phase 2 와 같은 마지막 완결 거래일
PRE_END = pd.Timestamp("2009-12-31")
VARIANTS = yaml.safe_load((ROOT / "config" / "variants" / "phase4c.yaml").read_text(encoding="utf-8"))
MONTHS = int(VARIANTS["long_months"])
SFX = f"_m{MONTHS}"

PARTS, COVER, INFO = [], [], {}


def safe(r):
    return r.replace("=", "_").replace(".", "_").replace("#", "_")


def ts_long(ric):
    """2005~2009(phase4c_long) + 2010~(Phase 2) get_timeseries CLOSE → Series(date 색인). END 이후 제거."""
    files = sorted((RAW_LONG / "refinitiv").glob(f"{safe(ric)}__*.csv")) + sorted(RF_TS.glob(f"{safe(ric)}__*.csv"))
    d = pd.concat([parse_timeseries_single(pd.read_csv(p), ric, END) for p in files])
    d = d.drop_duplicates("date", keep="last").sort_values("date")
    return d.set_index("date")["value"]


def add(asset, field, s, source, as_of=None, note=""):
    s = s.dropna()
    d = pd.DataFrame({"date": s.index, "asset_id": asset, "field": field, "value": s.to_numpy(dtype=float),
                      "as_of": s.index if as_of is None else as_of.reindex(s.index).to_numpy(), "source": source})
    PARTS.append(d)
    COVER.append({"asset_id": asset, "field": field, "source": source, "rows": len(d),
                  "first": str(s.index.min().date()) if len(s) else "", "last": str(s.index.max().date()) if len(s) else "",
                  "note": note})


def add_daily_pair(asset, base, s, source, note=""):
    s = s[s.index >= pd.Timestamp(START)]
    add(asset, f"{base}_long", s, source, note=note)
    add(asset, f"{base}_long{SFX}", B.lag_months_daily(s, MONTHS), source + f" ({MONTHS} 달력월 전 값)",
        note=f"t − {MONTHS}개월 이전 마지막 관측(5영업일 넘게 오래되면 결측)")


def overlap_check(asset, long_close, panel):
    """2010~ 구간에서 장기 연속물이 Phase 2 close 와 같은지(같은 규칙·같은 기준점이면 부동소수 잡음만)."""
    p = panel[(panel.asset_id == asset) & (panel.field == "close")].set_index("date")["value"]
    j = pd.concat({"long": long_close, "p2": p}, axis=1).dropna()
    rel = (j["long"] / j["p2"] - 1).abs()
    only_p2 = p.index.difference(long_close.dropna().index)
    return {"n_overlap": int(len(j)), "max_rel_diff": float(rel.max()), "p2_dates_missing_in_long": int(len(only_p2))}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    panel = pd.read_csv(PROC / "panel.csv.gz", parse_dates=["date", "as_of"])

    # ---- 금: 활성월 비율 백어저스트(Phase 2 결정 B 와 같은 함수·같은 인자)
    raw = {k: ts_long(f"GCc{k}") for k in (1, 2, 3, 4)}
    near = pd.DataFrame(raw).dropna()
    INFO["gold_raw_first"] = {f"GCc{k}": str(v.index.min().date()) for k, v in raw.items()}
    INFO["gold_days_dropped_any_c_missing_pre2010"] = int(
        (pd.DataFrame(raw).loc[:PRE_END].isna().any(axis=1)).sum())
    gcal = B._bday_calendar(near.index, near.index.max() + pd.DateOffset(months=8))
    c1m = B.gc_c1_month(near.index, gcal)
    held = B.gc_held_month(near.index, gcal, early_days=5)
    gcont = B.continuous_from_nearbys(near, c1m, held)
    pre = near.index <= PRE_END
    INFO["gold_roll_check_2005_2009"] = _gold_roll_check(near[pre], c1m[pre], gcont[pre])
    INFO["gold_roll_check_2010_on"] = _gold_roll_check(near[~pre], c1m[~pre], gcont[~pre])
    INFO["gold_overlap_vs_phase2_close"] = overlap_check("GOLD", gcont["close"], panel)
    add_daily_pair("GOLD", "close", gcont["close"], "refinitiv:GCc1..GCc4 활성월 비율 백어저스트(2005~)",
                   "Phase 2 와 같은 규칙(gc_c1_month·gc_held_month(5)·continuous_from_nearbys)")

    # ---- WTI: NYMEX 규칙 교체일, 5영업일 전 교체, 비율 백어저스트(Phase 2 와 같은 함수·같은 인자)
    c1, c2 = ts_long("CLc1"), ts_long("CLc2")
    both = pd.concat({"c1": c1, "c2": c2}, axis=1).dropna().index
    rolls = B.cl_roll_dates(both)
    sig = B.c1c2_roll_signal(c1, c2)
    cont = B.back_adjust_ratio(c1, c2, rolls, early_days=5)
    INFO["wti_raw_first"] = {"CLc1": str(c1.index.min().date()), "CLc2": str(c2.index.min().date())}
    INFO["wti_roll_offsets_2005_2009"] = _roll_offsets(c1, c2, rolls[rolls <= PRE_END], sig)
    INFO["wti_roll_offsets_2010_on"] = _roll_offsets(c1, c2, rolls[rolls > PRE_END], sig)
    INFO["wti_c1_nonpositive"] = [str(d.date()) for d in c1.index[c1 <= 0]]
    INFO["wti_min_adj_close"] = float(np.nanmin(cont["close"]))
    INFO["wti_overlap_vs_phase2_close"] = overlap_check("WTI", cont["close"], panel)
    add_daily_pair("WTI", "close", cont["close"], "refinitiv:CLc1/CLc2 ratio back-adjusted(2005~)",
                   "Phase 2 와 같은 규칙(cl_roll_dates·back_adjust_ratio(5))")

    # ---- 금리
    for aid, ric in (("KTB10Y", "KRTSY10Y=KQ"), ("UST10Y", "US10YT=RR")):
        y = ts_long(ric)
        p = panel[(panel.asset_id == aid) & (panel.field == "yield")].set_index("date")["value"]
        j = pd.concat({"long": y, "p2": p}, axis=1).dropna()
        INFO[f"{aid}_yield_overlap_vs_phase2"] = {"n_overlap": int(len(j)),
                                                  "max_abs_diff": float((j["long"] - j["p2"]).abs().max())}
        INFO[f"{aid}_raw_first"] = str(y.index.min().date())
        add_daily_pair(aid, "yield", y, f"refinitiv:{ric}(2005~)")

    # ---- REER(FRED RBKRBIS, Phase 2 와 같은 어댑터·as_of 규칙)
    fa = FredAdapter({("USDKRW", "reer_long"): "RBKRBIS"}, RAW_LONG / "fred", download=False)
    full = fa.fetch("USDKRW", ["reer_long"], None, END)
    INFO["reer_raw_first"] = str(full["date"].min().date())
    full = full[full["as_of"] <= pd.Timestamp(END)][["date", "value", "as_of"]]
    r = full[full["date"] >= pd.Timestamp(START)]
    s = r.set_index("date")
    add("USDKRW", "reer_long", s["value"], "fred:RBKRBIS(2005~)", as_of=s["as_of"],
        note="as_of = 기준월 1일 + 3개월(가정, Phase 2 와 같음). 최신 빈티지(수정치) — 가정")
    # 60개월 전 값은 1994~ 전체 계열에서 찾는다(받을 수 있는 만큼 — 달력 첫날 2010-01 에 알려진 2009-10 기준월도 짝이 있게)
    lag = B.lag_months_exact(full, MONTHS)
    lag = lag[lag["date"] >= pd.Timestamp(START)].set_index("date")
    add("USDKRW", f"reer_long{SFX}", lag["value"], f"fred:RBKRBIS ({MONTHS}개월 전 기준월 값)", as_of=lag["as_of"],
        note=f"같은 date·as_of 에 기준월 − {MONTHS}개월 값(가정: 공표 시차 고정)")
    p = panel[(panel.asset_id == "USDKRW") & (panel.field == "reer")].set_index("date")["value"]
    j = pd.concat({"long": s["value"], "p2": p}, axis=1).dropna()
    INFO["reer_overlap_vs_phase2"] = {"n_overlap": int(len(j)), "max_abs_diff": float((j["long"] - j["p2"]).abs().max())}

    out = validate_panel(pd.concat(PARTS, ignore_index=True))
    out.to_csv(PROC / "phase4c_long_panel.csv.gz", index=False)
    cov = pd.DataFrame(COVER)
    cov.to_csv(OUT / "phase4c_coverage_fields.csv", index=False)
    INFO["panel_rows"] = int(len(out))
    INFO["long_months"] = MONTHS
    (OUT / "phase4c_build_info.json").write_text(json.dumps(INFO, ensure_ascii=False, indent=1), encoding="utf-8")
    print(cov.to_string(index=False))
    print(json.dumps(INFO, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
