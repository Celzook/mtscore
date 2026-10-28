"""Phase 2 — 원천 대조 표본 점검(소스마다 3개 이상 값을 독립 경로와 비교). 산출: outputs/phase2/crosscheck.csv

    .venv/bin/python scripts/phase2_crosscheck.py
"""
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from phase2_build import END, RAW, RF, gd_concat, ts  # noqa: E402
from mtscore.data.adapters import ecos, fred  # noqa: E402
from mtscore.data.adapters.cftc import parse_records  # noqa: E402
from mtscore.data.adapters.krx import KrxIndexAdapter  # noqa: E402
from mtscore.data.adapters.refinitiv import parse_get_data  # noqa: E402

OUT = ROOT / "outputs" / "phase2"
ROWS = []
DATES = ["2026-09-15", "2026-10-07", "2026-10-23"]


def put(source_a, source_b, item, date, a, b, tol, note=""):
    diff = None if a is None or b is None or np.isnan(a) or np.isnan(b) else a - b
    ROWS.append({"item": item, "date": date, "source_a": source_a, "value_a": a, "source_b": source_b, "value_b": b,
                 "diff": diff, "tolerance": tol, "pass": diff is not None and abs(diff) <= tol, "note": note})


def at(df, d):
    s = df.set_index("date")["value"]
    s = s[s.index <= pd.Timestamp(d)]
    return (float(s.iloc[-1]), str(s.index[-1].date())) if len(s) else (np.nan, "")


def fredser(sid):
    p = fred.download(sid, RAW / "fred")
    return fred.parse_fredgraph(p.read_text(encoding="utf-8"), sid)


def main():
    # 1) UST10Y: Refinitiv US10YT=RR vs FRED DGS10 (같은 기준일)
    a, b = ts("US10YT=RR"), fredser("DGS10")
    for d in DATES:
        put("refinitiv:US10YT=RR", "fred:DGS10", "UST10Y yield %", d, at(a, d)[0], at(b, d)[0], 0.03,
            "Refinitiv 는 뉴욕 마감 호가, H.15 는 정오 무렵 매수호가 기반 → 수 bp 차 허용")
    # 2) KTB10Y·KTB3Y·AA−3Y: Refinitiv =KQ vs ECOS 817Y002
    for ric, item, code in (("KRTSY10Y=KQ", "KTB10Y yield %", "010210000"), ("KRTSY3Y=KQ", "KTB3Y yield %", "010200000"),
                            ("KRGUCORP=KQ", "회사채 AA− 3Y %", "010300000")):
        a = ts(ric)
        b = ecos.read_raw(ecos.download("817Y002", "D", "20260901", "20261027", code, RAW / "ecos"), "D")
        for d in DATES:
            put(f"refinitiv:{ric}", f"ecos:817Y002/{code}", item, d, at(a, d)[0], at(b, d)[0], 0.005,
                "둘 다 KOFIA 최종호가수익률")
    # 3) USDKRW: KRW=KFTC vs ECOS 731Y001(매매기준율) · FRED DEXKOUS(뉴욕 정오)
    a = ts("KRW=KFTC")
    b = ecos.read_raw(ecos.download("731Y001", "D", "20260901", "20261027", "0000001", RAW / "ecos"), "D")
    c = fredser("DEXKOUS")
    for d in DATES:
        put("refinitiv:KRW=KFTC", "ecos:731Y001/0000001", "USDKRW", d, at(a, d)[0], at(b, d)[0], 10.0,
            "서울 마감 종가 vs 매매기준율(전일 시장평균환율) — 정의가 달라 수 원 차 허용")
        put("refinitiv:KRW=KFTC", "fred:DEXKOUS", "USDKRW", d, at(a, d)[0], at(c, d)[0], 15.0, "서울 마감 vs 뉴욕 정오")
    # 4) KOSPI200: Refinitiv .KS200 vs KRX Open API
    a = ts(".KS200")
    kx = KrxIndexAdapter(DATES, RAW / "krx").fetch("KOSPI200", ["close"])
    for d in DATES:
        put("refinitiv:.KS200", "krx_openapi:kospi_dd_trd", "KOSPI200 close", d, at(a, d)[0],
            float(kx.loc[kx["date"] == pd.Timestamp(d), "value"].iloc[0]), 0.01)
    # 4b) 바텀업 구성종목 시총 합 vs KRX 지수 시가총액(현재 구성종목 목록 점검)
    snap = pd.concat([pd.read_csv(p) for p in sorted((RF / "bottomup_kr").glob("kr_snap_*.csv"))])
    mc = pd.to_numeric(snap.iloc[:, 4], errors="coerce").sum()
    j = json.loads((RAW / "krx" / "idx_kospi_dd_trd_20261023.json").read_text(encoding="utf-8"))
    from mtscore.data.adapters.krx import download_day, parse_index_day
    j27 = json.loads(download_day("idx/kospi_dd_trd", "20261027", RAW / "krx").read_text(encoding="utf-8"))
    k27 = parse_index_day(j27)
    put("refinitiv:KODEX200 보유 201종목 TR.CompanyMarketCap 합", "krx_openapi:코스피 200 MKTCAP", "KOSPI200 시가총액(조원)",
        END, mc / 1e12, float(k27["mktcap"].iloc[0]) / 1e12, float(k27["mktcap"].iloc[0]) / 1e12 * 0.05,
        "구성종목 목록 완전성 점검(우선주·시총 정의 차 5% 허용)")
    del j
    # 5) WTI: CLc1 vs FRED DCOILWTICO(현물 Cushing)
    a, b = ts("CLc1"), fredser("DCOILWTICO")
    for d in ["2025-03-14", "2025-06-13", "2025-09-15", "2026-09-15", "2026-10-07", "2026-10-20"]:
        put("refinitiv:CLc1", "fred:DCOILWTICO", "WTI $/bbl", d, at(a, d)[0], at(b, d)[0], 1.5,
            "근월 선물 vs EIA 현물(Cushing). 2025 |차| 중앙 0.69, 2026 급한 백워데이션 구간에서 최대 7.2 — 정의 차(현물 vs 근월물)")
    # 5b) EIA 원유 재고: PS-ESPR-EIA 주간 변화(백만 배럴) vs Refinitiv 경제지표 USOILC=ECI(주간 변화, 배럴)
    lv = pd.read_csv(RAW / "lseg" / "eia" / "PS-ESPR-EIA.csv")
    lv = pd.Series(pd.to_numeric(lv["COMM_LAST"], errors="coerce").to_numpy(), index=pd.to_datetime(lv["Date"])).diff()
    ch = pd.read_csv(RAW / "lseg" / "eia" / "USOILC_ECI.csv")
    ch = pd.Series(pd.to_numeric(ch["VALUE"], errors="coerce").to_numpy() / 1e6, index=pd.to_datetime(ch["Date"]))
    for d in ch.dropna().index[-3:]:
        put("lseg:PS-ESPR-EIA 주간 변화(백만 배럴)", "lseg:USOILC=ECI(백만 배럴)", "EIA 원유 재고 주간 변화", str(d.date()),
            float(lv.get(d, np.nan)), float(ch[d]), 0.05, "같은 EIA 원천의 다른 Refinitiv 계열(수준 vs 변화)")
    # 6) S&P500: .SPX vs FRED SP500
    a = parse_get_data(gd_concat("SPX_close__*.csv", "spx"))[["date", "value"]]
    b = fredser("SP500")
    for d in DATES:
        put("refinitiv:.SPX", "fred:SP500", "S&P500 close", d, at(a, d)[0], at(b, d)[0], 0.5)
    # 7) CFTC: Socrata vs CFTC 연간 파일(deacot2026.zip, Legacy Futures Only)
    import requests
    p = RAW / "cftc" / "deacot2026.zip"
    if not p.exists():
        r = requests.get("https://www.cftc.gov/files/dea/history/deacot2026.zip", timeout=120,
                         headers={"User-Agent": "curl/8"})
        r.raise_for_status()
        p.write_bytes(r.content)
    z = zipfile.ZipFile(p)
    t = pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), low_memory=False)
    t.columns = [c.strip() for c in t.columns]
    code_col = [c for c in t.columns if "CFTC Contract Market Code" in c][0]
    date_col = [c for c in t.columns if "As of Date in Form YYYY-MM-DD" in c][0]
    for name, code in (("gold", "088691"), ("wti", "067651"), ("ust10y", "043602")):
        soc = parse_records(json.loads((RAW / "cftc" / f"cot_{code}.json").read_text(encoding="utf-8")))
        tt = t[t[code_col].astype(str).str.strip() == code].copy()
        tt["date"] = pd.to_datetime(tt[date_col])
        tt["value"] = tt["Noncommercial Positions-Long (All)"] - tt["Noncommercial Positions-Short (All)"]
        for d in sorted(tt["date"])[-3:][:1] + sorted(tt["date"])[-1:]:
            put("cftc:socrata 6dca-aqww", "cftc:deacot2026.zip", f"COT {name} 비상업 순포지션", str(d.date()),
                at(soc, d)[0], float(tt.loc[tt["date"] == d, "value"].iloc[0]), 0.0)
    # 8) iBoxx G-스프레드 vs FRED ICE OAS(2023-10~): 상관(수준·주간 변화)
    panel = pd.read_csv(ROOT / "data" / "processed" / "panel.csv.gz", parse_dates=["date", "as_of"])
    for aid, sid, fld in (("US_HY", "BAMLH0A0HYM2", "spread"), ("US_IG", "BAMLC0A0CM", "spread"),
                          ("US_HY", "BAMLH0A0HYM2", "spread_dur_matched"), ("US_IG", "BAMLC0A0CM", "spread_dur_matched")):
        g = panel[(panel.asset_id == aid) & (panel.field == fld)].set_index("date")["value"]
        o = fredser(sid).set_index("date")["value"]
        x = pd.concat({"g": g, "o": o}, axis=1).dropna()
        w = x.resample("W-FRI").last().diff().dropna()
        ROWS.append({"item": f"{aid} {fld} vs ICE OAS 상관", "date": f"{x.index.min().date()}~{x.index.max().date()}",
                     "source_a": f"lseg:iBoxx {fld}(spread=평균만기 매칭, spread_dur_matched=듀레이션 매칭)", "value_a": round(float(x["g"].corr(x["o"])), 3),
                     "source_b": f"fred:{sid}", "value_b": round(float(w["g"].corr(w["o"])), 3),
                     "diff": round(float((x["g"] - x["o"]).mean()), 3), "tolerance": None,
                     "pass": bool(x["g"].corr(x["o"]) > 0.8 and w["g"].corr(w["o"]) > 0.6),
                     "note": "value_a=수준 상관, value_b=주간 변화 상관, diff=평균 수준 차(%p). 판정 기준 수준>0.8·변화>0.6"})
        for d in (DATES[1:] if fld == "spread" else []):
            put("lseg:iBoxx G-spread", f"fred:{sid}", f"{aid} spread %p", d, at(g.rename("value").reset_index(), d)[0],
                at(o.rename("value").reset_index(), d)[0], 1.0, "G-스프레드 vs OAS(정의 차, 참고)")
    # 9) CPI: ECOS 901Y009 vs FRED KORCPIALLMINMEI(OECD) — 전년비로 비교(기준연도 차)
    e = ecos.read_raw(next((RAW / "ecos").glob("901Y009_M_0_*.csv")), "M").set_index("date")["value"]
    try:
        o = fredser("KORCPIALLMINMEI").set_index("date")["value"]
        ey, oy = (e / e.shift(12) - 1) * 100, (o / o.shift(12) - 1) * 100
        common = ey.dropna().index.intersection(oy.dropna().index)[-3:]
        for d in common:
            put("ecos:901Y009 YoY%", "fred:KORCPIALLMINMEI YoY%", "한국 CPI 전년비 %", str(d.date()), float(ey[d]),
                float(oy[d]), 0.15)
    except Exception as ex:  # noqa: BLE001
        ROWS.append({"item": "한국 CPI", "note": f"FRED KORCPIALLMINMEI 실패: {str(ex)[:120]}", "pass": False})
    # 10) US CPI: FRED CPIAUCSL MoM vs Refinitiv USCPI=ECI 는 미수집 → FRED CPIAUCSL 과 CPILFESL 은 정의가 달라 생략
    out = pd.DataFrame(ROWS)
    out.to_csv(OUT / "crosscheck.csv", index=False)
    pd.set_option("display.width", 250)
    print(out[["item", "date", "value_a", "value_b", "diff", "pass"]].to_string())
    print("pass", int(out["pass"].sum()), "/", len(out))


if __name__ == "__main__":
    main()
