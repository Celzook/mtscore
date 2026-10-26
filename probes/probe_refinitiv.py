"""Phase 0 — Refinitiv 확보 가능성 실측. python.exe 로 실행(WSL 셸, mtscore 폴더에서):

    cat ~/.claude/reference/refinitiv-workspace/.appkey | python.exe probes/probe_refinitiv.py

결과: outputs/phase0/probe_refinitiv.json (항목별 행 수·시작·끝·오류). 값 자체는 저장하지 않는다.
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
START, END = "2010-01-01", "2026-10-23"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs", "phase0", "probe_refinitiv.json")
res = {}


def ts(name, ric, field="CLOSE", interval="daily"):
    parts, errs = [], []
    for y in range(2010, 2027, 5):
        s, e = f"{y}-01-01", min(END, f"{y + 4}-12-31")
        for k in range(3):
            try:
                d = ek.get_timeseries([ric], fields=[field], start_date=s, end_date=e, interval=interval)
                parts.append(d.iloc[:, 0])
                break
            except Exception as ex:
                if "No data" in str(ex) or k == 2:
                    errs.append(f"{s}: {str(ex)[:160]}")
                    break
                time.sleep(2)
    if parts:
        x = pd.concat(parts).sort_index()
        x = x[~x.index.duplicated()].dropna()
        res[name] = {"via": f"get_timeseries {ric} {field}", "rows": len(x),
                     "first": str(x.index[0].date()) if len(x) else None,
                     "last": str(x.index[-1].date()) if len(x) else None, "errors": errs[:2]}
    else:
        res[name] = {"via": f"get_timeseries {ric} {field}", "rows": 0, "errors": errs[:2]}
    print(name, res[name]["rows"], res[name].get("first"), res[name].get("last"), flush=True)


def gd(name, rics, fields, params):
    try:
        _gd(name, rics, fields, params)
    except Exception as ex:
        res[name] = {"via": f"get_data {rics[:3]} {fields}", "rows": 0, "errors": [str(ex)[:200]]}
        print(name, "EXC", str(ex)[:160], flush=True)


def _gd(name, rics, fields, params):
    for k in range(3):
        try:
            d, err = ek.get_data(rics, fields, params)
            break
        except Exception as ex:
            d, err = None, str(ex)
            time.sleep(2)
    info = {"via": f"get_data {rics[:3]} {fields} {params}"}
    if d is None:
        info.update(rows=0, errors=[str(err)[:200]])
    else:
        val_cols = [c for c in d.columns[1:] if "date" not in str(c).lower()]
        dd = d.dropna(subset=val_cols, how="all") if val_cols else d
        dd = dd[dd[val_cols].apply(lambda r: r.astype(str).str.strip().ne("").any(), axis=1)] if val_cols else dd
        dcol = [c for c in d.columns if str(c).lower() == "date" or str(c).lower().endswith(".date")]
        info.update(rows=int(len(dd)), columns=list(map(str, d.columns)))
        if dcol and len(dd):
            ds = pd.to_datetime(dd[dcol[0]], errors="coerce").dropna()
            if len(ds):
                info.update(first=str(ds.min().date()), last=str(ds.max().date()))
        if err:
            info["errors"] = [str(e.get("message", e))[:160] for e in err][:3]
    res[name] = info
    print(name, info.get("rows"), info.get("first"), info.get("last"), info.get("errors", ""), flush=True)


M = {"SDate": START, "EDate": END, "Frq": "M"}
# 가격·변동성·환율·금리·원자재 — 1차 실행(outputs/phase0/probe_refinitiv_run1.txt)에서 확인 완료.
# 다시 돌리려면 PROBE_PRICES=1
if os.environ.get("PROBE_PRICES") == "1":
  for n, r in [("KS200_close", ".KS200"), ("KS200TR_close", ".KS200TR"), ("VKOSPI", ".KSVKOSPI"),
               ("USDKRW_KFTC", "KRW=KFTC"), ("USDKRW_NY", "KRW="), ("KTB10Y_KQ", "KRTSY10Y=KQ"),
               ("KTB3Y_KQ", "KRTSY3Y=KQ"), ("KRCORP_AAm3Y_KQ", "KRGUCORP=KQ"), ("KR_base_rate", "KRBASE=BOKK"),
               ("UST10Y", "US10YT=RR"), ("GOLD_c1", "GCc1"), ("GOLD_c2", "GCc2"), ("WTI_c1", "CLc1"),
               ("WTI_c2", "CLc2"), ("K200_fut_c1", "KSc1"), ("DXY", ".DXY")]:
      ts(n, r)
  gd("SPX_close_daily", [".SPX"], ["TR.PriceClose.date", "TR.PriceClose"], {"SDate": START, "EDate": END, "Frq": "D"})
  gd("VIX_close_daily", [".VIX"], ["TR.PriceClose.date", "TR.PriceClose"], {"SDate": "2026-09-01", "EDate": END, "Frq": "D"})
# S&P500 컨센서스·밸류에이션
gd("SPX_EPS_NTM", [".SPX"], ["TR.EPSMean.date", "TR.EPSMean"], dict(M, Period="NTM"))
for f in ["TR.NumEstRevisingUp", "TR.NumEstRevisingDown", "TR.EPSNumUpRevisions", "TR.EPSNumDownRevisions",
          "TR.NumberOfUpRevisions", "TR.EPSNumIncEstimates", "TR.EPSMeanChg", "TR.EPSNumUp", "TR.EPSNumDown",
          "TR.EPSMeanPctChg", "TR.PriceToBVPerShare", "TR.DividendYield", "TR.PtoEPSMeanEst", "TR.IndexDividendYield"]:
    gd(f"SPX_{f}", [".SPX"], [f + ".date", f], dict(M, Period="NTM") if "EPS" in f or "Revising" in f else M)
# KOSPI200 바텀업 (대표 종목) + 과거 구성 가능성
for f, p in [("TR.EPSMean", "NTM"), ("TR.NumEstRevisingUp", "NTM"), ("TR.NumEstRevisingDown", "NTM"),
             ("TR.CompanyMarketCap", None), ("TR.PriceToBVPerShare", None), ("TR.DividendYield", None),
             ("TR.BVPSMean", "FY1"), ("TR.DPSMean", "FY1")]:
    gd(f"005930_{f}", ["005930.KS"], [f + ".date", f], dict(M, Period=p) if p else M)
gd("KS200_constituents_hist", [".KS200"], ["TR.IndexConstituentRIC"], {"SDate": "2015-01-01"})
gd("KODEX200_holdings_now", ["069500.KS"], ["TR.FundHoldingRIC", "TR.FundPercentageOfFundAssets"], {"EndNum": 300})
# 포지셔닝 (COT 가 Refinitiv 에 있는지)
for n, r in [("COT_gold", "1GC-NCL-NET=COT"), ("COT_gold_alt", "GC-NCL-NET=COT")]:
    ts(n, r, field="CLOSE", interval="weekly")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", OUT)
