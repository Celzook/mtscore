"""Phase 2 — Refinitiv 원자료 수집(WSL 에서 실행, 워커는 Windows python.exe). 재개 가능: 받은 파일은 건너뛴다.

    .venv/bin/python scripts/phase2_collect_refinitiv.py holdings ts spx bottomup_us bottomup_kr iboxx eia   # 약 10분
    .venv/bin/python scripts/phase2_collect_refinitiv.py kr_daily                          # 길다(종목 201 × 4구간)

원자료: data/raw/refinitiv/<section>/<id>.csv (gitignore). 키는 워커 stdin 으로만 넘긴다.
END 는 마지막 완결 거래일(장중 미완성 봉 방지 — 오늘 행을 받지 않는다).
"""
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from mtscore.data.adapters.refinitiv import LSEG_PYTHON, LSEG_WORKER, run_jobs  # noqa: E402

RAW = ROOT / "data" / "raw" / "refinitiv"
LOG = RAW / "worker.log"
START, END = "2010-01-01", "2026-10-27"
CHUNKS = [("2010-01-01", "2014-12-31"), ("2015-01-01", "2019-12-31"), ("2020-01-01", "2024-12-31"),
          ("2025-01-01", END)]
M = {"SDate": START, "EDate": END, "Frq": "M"}
TS_RICS = [".KS200", ".KS200TR", ".KSVKOSPI", "KRW=KFTC", "KRTSY10Y=KQ", "KRTSY3Y=KQ", "KRGUCORP=KQ", "KRCORP=KQ",
           "KRBASE=BOKK", "US1YT=RR", "US2YT=RR", "US3YT=RR", "US5YT=RR", "US7YT=RR", "US10YT=RR", "US30YT=RR",
           "GCc1", "GCc2", "GCc3", "GCc4", "CLc1", "CLc2"]   # US20YT=RR 은 2020 재발행 전 데이터 없음 → 커브 보간에서 제외


def safe(r):
    return r.replace("=", "_").replace(".", "_").replace("#", "_")


def holdings(name):
    d = pd.read_csv(RAW / "holdings" / f"{name}.csv")
    d.columns = ["inst", "ric", "w"]
    d = d.dropna(subset=["ric"])
    d = d[d["ric"].astype(str).str.strip() != ""]
    return list(dict.fromkeys(d["ric"]))


def ts_jobs(rics):
    return [{"id": f"{safe(r)}__{s[:4]}", "kind": "ts", "rics": [r], "fields": ["CLOSE"], "start": s, "end": e}
            for r in rics for s, e in CHUNKS]


def section(name):
    if name == "holdings":
        return [{"id": "kodex200", "kind": "gd", "rics": ["069500.KS"],
                 "fields": ["TR.FundHoldingRIC", "TR.FundPercentageOfFundAssets"], "params": {"EndNum": 1000}},
                {"id": "spy", "kind": "gd", "rics": ["SPY"],
                 "fields": ["TR.FundHoldingRIC", "TR.FundPercentageOfFundAssets"], "params": {"EndNum": 2000}}]
    if name == "ts":
        return ts_jobs(TS_RICS)
    if name == "spx":
        jobs = [{"id": f"SPX_close__{s[:4]}", "kind": "gd", "rics": [".SPX"],
                 "fields": ["TR.PriceClose.date", "TR.PriceClose"], "params": {"SDate": s, "EDate": e, "Frq": "D"}}
                for s, e in CHUNKS]
        # EPS 반환 날짜는 '마지막 변경일'이라 달이 바뀌어도 같은 날짜가 다른 값으로 온다(NTM 혼합). 표본일(월말)을
        # 알기 위해 같은 요청에 TR.PriceClose 를 붙인다 — 행이 표본 달마다 정렬돼 온다(2026-10-28 실측).
        jobs += [{"id": "SPX_eps_ntm_aligned", "kind": "gd", "rics": [".SPX"],
                  "fields": ["TR.EPSMean.date", "TR.EPSMean", "TR.PriceClose.date", "TR.PriceClose"],
                  "params": dict(M, Period="NTM")},
                 {"id": "SPX_pe_fwd", "kind": "gd", "rics": [".SPX"],
                  "fields": ["TR.PtoEPSMeanEst.date", "TR.PtoEPSMeanEst"], "params": dict(M, Period="NTM")},
                 {"id": "SPX_eps_ntm_snap", "kind": "gd", "rics": [".SPX"], "fields": ["TR.EPSMean.date", "TR.EPSMean"],
                  "params": {"SDate": END, "Period": "NTM"}},
                 {"id": "SPX_pe_fwd_snap", "kind": "gd", "rics": [".SPX"],
                  "fields": ["TR.PtoEPSMeanEst.date", "TR.PtoEPSMeanEst"], "params": {"SDate": END, "Period": "NTM"}}]
        return jobs
    if name in ("bottomup_us", "bottomup_kr"):
        rics = holdings("spy" if name == "bottomup_us" else "kodex200")
        tag = "us" if name == "bottomup_us" else "kr"
        fields = ["TR.EPSMean.date", "TR.EPSMean", "TR.CompanyMarketCap.date", "TR.CompanyMarketCap"]
        if tag == "kr":
            fields += ["TR.PriceClose.date", "TR.PriceClose", "TR.PriceToBVPerShare.date", "TR.PriceToBVPerShare",
                       "TR.DividendYield.date", "TR.DividendYield"]
        jobs = []
        for i in range(0, len(rics), 50):
            b = rics[i:i + 50]
            jobs.append({"id": f"{tag}_m_{i:04d}", "kind": "gd", "rics": b, "fields": fields,
                         "params": dict(M, Period="NTM")})
            jobs.append({"id": f"{tag}_snap_{i:04d}", "kind": "gd", "rics": b, "fields": fields,
                         "params": {"SDate": END, "Period": "NTM"}})
        return jobs
    if name == "kr_daily":
        return ts_jobs(holdings("kodex200"))
    if name == "iboxx":   # lseg-data get_history(전 필드) — lsegvenv python.exe
        return [{"id": f"{r.strip('.')}__{s[:4]}", "kind": "hist", "ric": r, "fields": None, "start": s, "end": e}
                for r in (".IBLUS0004", ".IBLUS0005") for s, e in (("2009-12-28", "2017-12-31"), ("2018-01-01", END))]
    if name == "eia":     # EIA 주간 원유 재고(SPR 제외, 백만 배럴) — lseg 검색으로 찾은 RIC(2026-10-28)
        return [{"id": "PS-ESPR-EIA", "kind": "hist", "ric": "PS-ESPR-EIA", "fields": ["COMM_LAST"],
                 "start": "2008-01-01", "end": END},
                {"id": "USOILC_ECI", "kind": "hist", "ric": "USOILC=ECI", "fields": None,   # 대조용: 주간 변화(배럴)
                 "start": "2026-01-01", "end": END}]
    raise SystemExit(f"unknown section {name}")


if __name__ == "__main__":
    for sec in sys.argv[1:]:
        t = time.time()
        jobs = section(sec)
        if sec in ("iboxx", "eia"):
            r = run_jobs(jobs, ROOT / "data" / "raw" / "lseg" / sec, python=LSEG_PYTHON, worker=LSEG_WORKER,
                         log_file=ROOT / "data" / "raw" / "lseg" / "worker.log")
        else:
            r = run_jobs(jobs, RAW / sec, log_file=LOG)
        print(f"{sec}: jobs={len(jobs)} ok={len(r['ok'])} err={len(r['err'])} {time.time() - t:.0f}s", flush=True)
        for k, v in list(r["err"].items())[:10]:
            print("  ERR", k, v[:160], flush=True)
