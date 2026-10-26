"""Phase 0 — 무료 소스(FRED·ECOS·CFTC·naver·pykrx) 확보 가능성 실측.

    .venv/bin/python probes/probe_free.py

- FRED: 키 없이 fredgraph CSV 경로(FRED_API_KEY 가 있으면 API 경로도 시험)
- ECOS: ECOS_API_KEY 가 없으면 sample 키(1회 10건)로 존재·기간만 확인
결과: outputs/phase0/probe_free.json. 값은 저장하지 않는다.
"""
import ast
import io
import json
import os
import re
from pathlib import Path

import pandas as pd
import requests
import urllib3.util.connection as _uc

_uc.HAS_IPV6 = False  # 이 PC 에서 requests 의 IPv6 시도가 FRED 에서 read timeout 을 낸다(curl 은 즉시 200)

OUT = Path(__file__).resolve().parent.parent / "outputs" / "phase0" / "probe_free.json"
UA = {"User-Agent": "Mozilla/5.0"}
res = {}


def put(name, via, rows=0, first=None, last=None, err=None):
    res[name] = {"via": via, "rows": rows, "first": first, "last": last}
    if err:
        res[name]["errors"] = [str(err)[:200]]
    print(name, rows, first, last, err or "", flush=True)


# ---- FRED
FRED = {
    "UST10Y": "DGS10", "US_real10Y_TIPS": "DFII10", "US_BEI10Y": "T10YIE", "US_FedFunds": "DFF",
    "US_termprem_KimWright": "THREEFYTP10", "US_HY_OAS": "BAMLH0A0HYM2", "US_IG_OAS": "BAMLC0A0CM",
    "US_HY_yield": "BAMLH0A0HYM2EY", "VIX": "VIXCLS", "US_CPI": "CPIAUCSL", "US_crude_stocks_wk": "WCESTUS1",
    "KR_REER_BIS_broad": "RBKRBIS", "US_REER": "RBUSBIS", "KR_CPI": "KORCPIALLMINMEI",
    "KR_10Y_OECD": "IRLTLT01KRM156N", "US_STLFSI": "STLFSI4", "US_NFCI": "NFCI",
    "US_charge_off_proxy": "DRALACBN", "WTI_spot": "DCOILWTICO", "SP500_FRED": "SP500",
}
for n, sid in FRED.items():
    try:
        r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", headers={"User-Agent": "curl/8"}, timeout=40)  # 브라우저 UA("Mozilla/5.0")는 FRED 가 응답 없이 끊는다
        df = pd.read_csv(io.StringIO(r.text))
        df = df[pd.to_numeric(df.iloc[:, 1], errors="coerce").notna()]
        put(f"FRED_{n}", f"fredgraph {sid}", len(df), str(df.iloc[0, 0]), str(df.iloc[-1, 0]))
    except Exception as e:
        put(f"FRED_{n}", f"fredgraph {sid}", err=e)
fk = os.environ.get("FRED_API_KEY")
res["FRED_API_KEY_present"] = bool(fk)

# ---- ECOS (sample 키는 10건 제한 → 처음 10건과 마지막 10건만으로 기간 확인)
ek = os.environ.get("ECOS_API_KEY") or "sample"
res["ECOS_key"] = "env" if ek != "sample" else "sample"
ECOS = {  # 이름: (표, 주기, 시작, 끝, 항목)
    "KTB10Y_daily": ("817Y002", "D", "20100101", "20261023", "010210000"),
    "KTB3Y_daily": ("817Y002", "D", "20100101", "20261023", "010200000"),
    "KR_corpAAm3Y_daily": ("817Y002", "D", "20100101", "20261023", "010300000"),
    "KR_base_rate_daily": ("722Y001", "D", "20100101", "20261023", "0101000"),
    "USDKRW_daily": ("731Y001", "D", "20100101", "20261023", "0000001"),
    "KR_CPI_monthly": ("901Y009", "M", "201001", "202610", "0"),
    "KR_current_account_monthly": ("301Y013", "M", "201001", "202610", "000000"),
    "KR_REER_monthly": ("731Y005", "M", "201001", "202610", "0000003"),
    "KR_BEI_or_linker": ("817Y002", "D", "20100101", "20261023", "010230000"),
    "KR_export_monthly": ("901Y118", "M", "201001", "202610", "T002"),
}
for n, (tb, fq, s, e, it) in ECOS.items():
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{ek}/json/kr/1/10/{tb}/{fq}/{s}/{e}/{it}"
    try:
        j = requests.get(url, timeout=40).json()
        if "StatisticSearch" not in j:
            put(f"ECOS_{n}", f"{tb}/{fq}/{it}", err=j.get("RESULT", j))
            continue
        tot = j["StatisticSearch"]["list_total_count"]
        first = j["StatisticSearch"]["row"][0]
        jl = requests.get(url.replace("/1/10/", f"/{max(tot - 9, 1)}/{tot}/"), timeout=40).json()
        last = jl["StatisticSearch"]["row"][-1]
        put(f"ECOS_{n}", f"{tb}/{fq}/{it} {first.get('ITEM_NAME1')} [{first.get('UNIT_NAME')}]", tot,
            first["TIME"], last["TIME"])
    except Exception as e:
        put(f"ECOS_{n}", f"{tb}/{fq}/{it}", err=e)

# ---- CFTC COT (Socrata 공개 API, legacy futures-only)
for n, code in [("COT_gold", "088691"), ("COT_wti", "067651"), ("COT_UST10Y", "043602"), ("COT_KRW", None),
                ("COT_SP500_emini", "13874A")]:
    if code is None:
        put(n, "CFTC: KRW 계약 없음(CME KRW 선물 상장 폐지)", err="no contract code")
        continue
    try:
        u = ("https://publicreporting.cftc.gov/resource/6dca-aqww.json?"
             f"cftc_contract_market_code={code}&$select=report_date_as_yyyy_mm_dd&$order=report_date_as_yyyy_mm_dd&$limit=5000"
             "&$where=report_date_as_yyyy_mm_dd>='2010-01-01'")
        j = requests.get(u, timeout=60).json()
        d = [x["report_date_as_yyyy_mm_dd"][:10] for x in j]
        put(n, f"CFTC legacy {code}", len(d), d[0] if d else None, d[-1] if d else None)
    except Exception as e:
        put(n, f"CFTC legacy {code}", err=e)

# ---- naver: KPI200 일봉, 투자자 수급
try:
    r = requests.get("https://api.finance.naver.com/siseJson.naver?symbol=KPI200&requestType=1&startTime=20100101"
                     "&endTime=20261023&timeframe=day", headers=UA, timeout=60)
    rows = ast.literal_eval(r.text.strip())[1:]
    put("NAVER_KPI200_daily", "siseJson KPI200", len(rows), rows[0][0], rows[-1][0])
except Exception as e:
    put("NAVER_KPI200_daily", "siseJson KPI200", err=e)
try:
    r = requests.get("https://finance.naver.com/sise/investorDealTrendDay.naver?bizdate=20100105&sosok=01&page=1",
                     headers=UA, timeout=30)
    r.encoding = "euc-kr"
    dates = re.findall(r"\d{2}\.\d{2}\.\d{2}", r.text)
    put("NAVER_investor_flow_KOSPI_2010", "investorDealTrendDay bizdate=20100105", len(dates),
        dates[-1] if dates else None, dates[0] if dates else None)
except Exception as e:
    put("NAVER_investor_flow_KOSPI_2010", "investorDealTrendDay", err=e)

# ---- pykrx (KRX 로그인 필요 여부)
res["KRX_ID_present"] = bool(os.environ.get("KRX_ID"))
try:
    from pykrx import stock
    df = stock.get_index_fundamental("20240101", "20240131", "1028")
    put("PYKRX_K200_fundamental", "get_index_fundamental 1028", len(df),
        str(df.index[0].date()) if len(df) else None, str(df.index[-1].date()) if len(df) else None)
except Exception as e:
    put("PYKRX_K200_fundamental", "get_index_fundamental 1028", err=e)
try:
    from pykrx import stock
    t = stock.get_index_portfolio_deposit_file("1028", "20150102")
    put("PYKRX_K200_constituents_2015", "get_index_portfolio_deposit_file 1028 20150102", len(t))
except Exception as e:
    put("PYKRX_K200_constituents_2015", "get_index_portfolio_deposit_file", err=e)

OUT.parent.mkdir(parents=True, exist_ok=True)
json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", OUT)
