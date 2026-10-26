"""Phase 0 보완 probe — KOSPI200 바텀업 실현 가능성(상위 구성종목 전체 커버리지)과 종목 일봉.

    cat ~/.claude/reference/refinitiv-workspace/.appkey | python.exe probes/probe_refinitiv_extra.py

- KODEX200(069500.KS) 현재 보유종목 중 누적 비중 85% 까지의 종목에 대해
  TR.EPSMean(NTM)·TR.PriceToBVPerShare·TR.DividendYield·TR.CompanyMarketCap 월별 2010~ 의 종목별 첫 관측월.
- 상위 5종목 get_timeseries CLOSE 일봉 커버리지(시장폭 대안 경로).
결과: outputs/phase0/probe_refinitiv_extra.json. 값은 저장하지 않는다.
"""
import json
import os
import sys
import time

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")
key = sys.stdin.readline().strip()

import pandas as pd  # noqa: E402

_orig = pd.to_numeric


def _compat(arg, errors="raise", **kw):
    if errors == "ignore":
        try:
            return _orig(arg, errors="raise", **kw)
        except (ValueError, TypeError):
            return arg
    return _orig(arg, errors=errors, **kw)


pd.to_numeric = _compat
import eikon as ek  # noqa: E402

ek.set_app_key(key)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs", "phase0", "probe_refinitiv_extra.json")
res = {}


def gd(rics, fields, params):
    for k in range(3):
        try:
            return ek.get_data(rics, fields, params)
        except Exception as ex:
            if k == 2:
                raise
            time.sleep(2)


h, _ = gd(["069500.KS"], ["TR.FundHoldingRIC", "TR.FundPercentageOfFundAssets"], {"EndNum": 300})
h.columns = ["inst", "ric", "w"]
h = h[h["ric"].astype(str).str.strip() != ""].copy()
h["w"] = pd.to_numeric(h["w"], errors="coerce")
h = h.dropna(subset=["w"]).sort_values("w", ascending=False)
h["cum"] = h["w"].cumsum()
top = h[h["cum"].shift(fill_value=0) < 85]
rics = list(dict.fromkeys(top["ric"]))
res["holdings"] = {"n_total": int(len(h)), "n_to_85pct": len(rics), "weight_covered": round(float(top["w"].sum()), 2)}
print("holdings", res["holdings"], flush=True)

M = {"SDate": "2010-01-01", "EDate": "2026-10-23", "Frq": "M"}
for f, p in [("TR.EPSMean", "NTM"), ("TR.PriceToBVPerShare", None), ("TR.DividendYield", None),
             ("TR.CompanyMarketCap", None)]:
    firsts, nrows = {}, {}
    for i in range(0, len(rics), 10):
        chunk = rics[i:i + 10]
        try:
            d, err = gd(chunk, [f + ".date", f], dict(M, Period=p) if p else M)
        except Exception as ex:
            print(f, chunk[0], "EXC", str(ex)[:120], flush=True)
            continue
        d.columns = ["ric", "date", "v"]
        d["v"] = pd.to_numeric(d["v"], errors="coerce")
        d["date"] = pd.to_datetime(d["date"], errors="coerce")
        d = d.dropna(subset=["v", "date"])
        for r_, g in d.groupby("ric"):
            firsts[r_] = str(g["date"].min().date())
            nrows[r_] = int(len(g))
    got = [r for r in rics if r in firsts]
    fs = pd.to_datetime(pd.Series([firsts[r] for r in got])) if got else pd.Series(dtype="datetime64[ns]")
    w = top.set_index("ric")["w"]
    res[f] = {"n_with_data": len(got), "n_requested": len(rics),
              "weight_with_data": round(float(w.reindex(got).sum()), 2),
              "weight_with_data_since_2011": round(float(w.reindex([r for r in got if firsts[r] <= "2011-01-31"]).sum()), 2),
              "first_obs_min": str(fs.min().date()) if len(fs) else None,
              "first_obs_median": str(fs.median().date()) if len(fs) else None,
              "missing": [r for r in rics if r not in firsts]}
    print(f, {k: v for k, v in res[f].items() if k != "missing"}, "missing:", res[f]["missing"][:10], flush=True)

for r_ in rics[:5]:
    try:
        d = ek.get_timeseries([r_], fields=["CLOSE"], start_date="2010-01-01", end_date="2014-12-31", interval="daily")
        d2 = ek.get_timeseries([r_], fields=["CLOSE"], start_date="2022-01-01", end_date="2026-10-23", interval="daily")
        res[f"daily_{r_}"] = {"rows_2010_14": int(len(d)), "rows_2022_26": int(len(d2)),
                              "first": str(d.index.min().date()) if len(d) else None}
    except Exception as ex:
        res[f"daily_{r_}"] = {"error": str(ex)[:160]}
    print(f"daily_{r_}", res[f"daily_{r_}"], flush=True)

json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", OUT)
