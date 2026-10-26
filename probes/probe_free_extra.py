"""Phase 0 보완 probe — 1차 검증에서 근거가 없던 항목을 실제 호출로 확인.

    .venv/bin/python probes/probe_free_extra.py

대상: FRED BAA10Y·AAA10Y, CFTC KRW 계약 검색, naver 투자자 수급 HTTP 상태, pykrx 투자자 수급 함수.
결과: outputs/phase0/probe_free_extra.json + 콘솔(→ probe_free_extra_run.txt). 값은 저장하지 않는다.
"""
import io
import json
import re
from pathlib import Path

import pandas as pd
import requests

OUT = Path(__file__).resolve().parent.parent / "outputs" / "phase0" / "probe_free_extra.json"
res = {}


def put(name, **kw):
    res[name] = kw
    print(name, json.dumps(kw, ensure_ascii=False), flush=True)


for sid in ["BAA10Y", "AAA10Y"]:
    r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", headers={"User-Agent": "curl/8"},
                     timeout=40)
    if r.text.lstrip().startswith("<"):
        put(f"FRED_{sid}", status=r.status_code, rows=0, note="HTML 반환")
        continue
    df = pd.read_csv(io.StringIO(r.text))
    df = df[pd.to_numeric(df.iloc[:, 1], errors="coerce").notna()]
    put(f"FRED_{sid}", status=r.status_code, rows=len(df), first=str(df.iloc[0, 0]), last=str(df.iloc[-1, 0]))

# CFTC: KRW 가 들어간 계약명 검색(legacy futures-only, 2010 이후)
u = ("https://publicreporting.cftc.gov/resource/6dca-aqww.json?$select=market_and_exchange_names,"
     "cftc_contract_market_code,max(report_date_as_yyyy_mm_dd)&$group=market_and_exchange_names,cftc_contract_market_code"
     "&$where=upper(market_and_exchange_names) like '%25KOREAN%25' OR upper(market_and_exchange_names) like '%25KRW%25'")
try:
    j = requests.get(u, timeout=60).json()
    put("CFTC_KRW_search", status="ok", contracts=j)
except Exception as e:
    put("CFTC_KRW_search", status="error", error=str(e)[:200])

# naver 투자자 수급(일별) — 상태 코드·날짜 매치 수
for q in ["bizdate=20100105&sosok=01&page=1", "bizdate=20261023&sosok=01&page=1", ""]:
    try:
        r = requests.get(f"https://finance.naver.com/sise/investorDealTrendDay.naver?{q}",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.encoding = "euc-kr"
        put(f"NAVER_investorDealTrendDay[{q or 'noparam'}]", status=r.status_code, bytes=len(r.text),
            date_matches=len(re.findall(r"\d{2}\.\d{2}\.\d{2}", r.text)))
    except Exception as e:
        put(f"NAVER_investorDealTrendDay[{q}]", status="error", error=str(e)[:200])

# pykrx 투자자별 거래대금(KOSPI) — 로그인 없이 되는지
try:
    from pykrx import stock
    df = stock.get_market_trading_value_by_date("20240102", "20240131", "KOSPI")
    put("PYKRX_investor_value_KOSPI", rows=len(df))
except Exception as e:
    put("PYKRX_investor_value_KOSPI", status="error", error=str(e)[:200])

OUT.parent.mkdir(parents=True, exist_ok=True)
json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", OUT)
