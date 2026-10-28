"""Phase 2 — 원자료(data/raw) → 검증된 4-1 패널(data/processed/panel.csv.gz) + 필드 지도(outputs/phase2/field_map.csv).

    .venv/bin/python scripts/phase2_build.py

네트워크를 쓰지 않는다(수집은 phase2_collect_*.py, 캐시가 없으면 FRED·ECOS·CFTC 어댑터가 받는다).
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from mtscore.data import build as B  # noqa: E402
from mtscore.data.adapters.cftc import CftcAdapter  # noqa: E402
from mtscore.data.adapters.ecos import EcosAdapter  # noqa: E402
from mtscore.data.adapters import fred as fred_mod  # noqa: E402
from mtscore.data.adapters.fred import FredAdapter  # noqa: E402
from mtscore.data.adapters.refinitiv import parse_get_data, parse_timeseries_single  # noqa: E402
from mtscore.data.schema import validate_panel  # noqa: E402

RAW = ROOT / "data" / "raw"
RF = RAW / "refinitiv"
OUT = ROOT / "outputs" / "phase2"
PROC = ROOT / "data" / "processed"
START, END = "2010-01-01", "2026-10-27"
WARM = "2008-01-01"
ALFRED_LOOKBACK = {"CPIAUCSL": 75, "NFCI": 60, "THREEFYTP10": 250}   # scripts/phase2_collect_alfred.py SPECS 와 같게   # 월별 변화·전년비 계산용 선행 구간(패널에는 START 이전 행도 넣는다 — 지표 워밍업)

FIELD_MAP = []   # (asset, field, source, as_of 규칙, 비고)
PARTS = []
INFO = {}


def add(asset, field, df, source, rule, note=""):
    """(date, value[, as_of]) → 패널 행 추가 + 필드 지도 기록."""
    d = df.copy()
    if "as_of" not in d.columns:
        d["as_of"] = d["date"]
    d = d[(d["date"] <= pd.Timestamp(END)) & (d["as_of"] <= pd.Timestamp(END))]   # 기준일까지 알려진 행만
    PARTS.append(pd.DataFrame({"date": d["date"], "asset_id": asset, "field": field, "value": d["value"],
                               "as_of": d["as_of"], "source": source}))
    FIELD_MAP.append({"asset_id": asset, "field": field, "source": source, "as_of_rule": rule, "note": note,
                      "rows": int(len(d)), "first": str(d["date"].min().date()) if len(d) else "",
                      "last": str(d["date"].max().date()) if len(d) else ""})


def safe(r):
    return r.replace("=", "_").replace(".", "_").replace("#", "_")


def ts(ric, section="ts"):
    """캐시된 get_timeseries 5년 구간들을 합친 (date, value). END 이후(장중 봉) 제거."""
    parts = []
    for p in sorted((RF / section).glob(f"{safe(ric)}__*.csv")):
        parts.append(parse_timeseries_single(pd.read_csv(p), ric, END))
    if not parts:
        return pd.DataFrame(columns=["date", "value"])
    d = pd.concat(parts).drop_duplicates("date", keep="last").sort_values("date")
    return d[["date", "value"]].reset_index(drop=True)


def gd_concat(pattern, section):
    return pd.concat([pd.read_csv(p) for p in sorted((RF / section).glob(pattern))], ignore_index=True)


def adapter_rows(adapter, mapping_keys):
    out = {}
    for asset, field in mapping_keys:
        out[(asset, field)] = adapter.fetch(asset, [field], WARM, END)
    return out


def _roll_offsets(c1, c2, rolls, sig):
    """규칙 교체일에서 k 거래일 어긋난 날의 c1/c2 신호 참 비율(전일 스프레드 0.5% 초과 달만). k=0 이 최대면 규칙이 맞다."""
    x = pd.concat({"c1": c1, "c2": c2}, axis=1).dropna()
    idx = x.index
    sp = ((x["c2"] - x["c1"]).abs() / x["c1"].abs()).shift()
    out = {}
    for k in range(-3, 4):
        pos = [idx.get_loc(d) + k for d in rolls if 0 <= idx.get_loc(d) + k < len(idx)]
        dd = idx[pos]
        big = (sp.reindex(dd) > 0.005).to_numpy()
        out[str(k)] = {"share_true": round(float(sig.reindex(dd)[big].mean()), 3), "n": int(big.sum())}
    return out


def _gold_roll_check(near, c1m, cont):
    """GCc1 계약월 규칙 검증: 규칙상 c1 교체일과 c2/c1 스프레드 급변일(상위 5%)이 겹치는 비율(±1일 비교)."""
    sp = (near[2] / near[1]).diff().abs()
    top = sp[sp > sp.quantile(0.95)].index
    rolls = c1m.index[(c1m != c1m.shift()).to_numpy()][1:]
    idx = near.index
    out = {"c1_rolls": int(len(rolls)), "active_switches": int(cont["switch"].sum()),
           "close_nan": int(cont["close"].isna().sum()),
           "cum_factor_first": float(cont["close"].iloc[0] / cont["held"].iloc[0])}
    for off in (-1, 0, 1):
        dd = idx[[idx.get_loc(d) + off for d in rolls if 0 <= idx.get_loc(d) + off < len(idx)]]
        out[f"share_in_top5pct_jump_k{off}"] = round(float(np.isin(dd, top).mean()), 3)
    return out


def _concentration(rows, rics):
    """기준 달(마지막) 두 종목(삼성 보통·우선, 하이닉스)의 시총·선행이익 비중."""
    last = rows[rows["month"] == rows["month"].max()].copy()
    last["earn"] = last["eps"] * last["mcap"] / last["px"]
    m = last.dropna(subset=["earn", "mcap"])
    sel = m["ric"].isin(rics)
    return {"month": str(last["month"].max()), "cap_share": round(float(m.loc[sel, "mcap"].sum() / m["mcap"].sum()), 4),
            "earn_share": round(float(m.loc[sel, "earn"].sum() / m["earn"].sum()), 4), "n": int(len(m))}


def main():
    t0 = time.time()
    # ---------------- Refinitiv 일별
    D = "date"
    k200 = ts(".KS200")
    add("KOSPI200", "close", k200, "refinitiv:.KS200", "as_of = date")
    add("KOSPI200", "close_tr", ts(".KS200TR"), "refinitiv:.KS200TR", "as_of = date", "2011-01~ (이전 구간 없음)")
    add("KOSPI200", "vol_index", ts(".KSVKOSPI"), "refinitiv:.KSVKOSPI", "as_of = date")
    usdkrw = ts("KRW=KFTC")
    add("USDKRW", "close", usdkrw, "refinitiv:KRW=KFTC", "as_of = date", "서울 마감. 엔진에서 reciprocal(원화 가격)")
    ktb10 = ts("KRTSY10Y=KQ")
    add("KTB10Y", "yield", ktb10, "refinitiv:KRTSY10Y=KQ", "as_of = date", "KOFIA 최종호가수익률(%)")
    add("KTB10Y", "policy_rate", ts("KRBASE=BOKK"), "refinitiv:KRBASE=BOKK", "as_of = date")
    ust10 = ts("US10YT=RR")
    add("UST10Y", "yield", ust10, "refinitiv:US10YT=RR", "as_of = date")
    # 금 연속물(사용자 결정 2026-10-28 B): 활성월 G J M Q V Z, 첫 통지일 5영업일 전 교체, 비율 백어저스트
    near = pd.DataFrame({k: ts(f"GCc{k}").set_index(D)["value"] for k in (1, 2, 3, 4)}).dropna()
    gcal = B._bday_calendar(near.index, near.index.max() + pd.DateOffset(months=8))
    c1m = B.gc_c1_month(near.index, gcal)
    held = B.gc_held_month(near.index, gcal, early_days=5)
    gcont = B.continuous_from_nearbys(near, c1m, held)
    INFO["gold_rolls"] = _gold_roll_check(near, c1m, gcont)
    gcont[["held_month", "switch"]][gcont["switch"]].to_csv(OUT / "gold_switch_dates.csv")
    add("GOLD", "close", gcont["close"].rename("value").reset_index().rename(columns={"index": D}).dropna(),
        "refinitiv:GCc1..GCc4 활성월 비율 백어저스트", "as_of = date",
        "활성월 G·J·M·Q·V·Z, 첫 통지일(인도월 전월 마지막 영업일) 5영업일 전 교체(가정). GCc1 계약월 = 그달 최종거래일"
        "(월말 3번째 영업일) 전이면 그달")
    g1 = near[1][near[1] > 0]
    add("GOLD", "close_c1_raw", g1.rename("value").reset_index(), "refinitiv:GCc1", "as_of = date",
        "원 근월물(실질가격용). 0 이하 값은 결측")

    # WTI 연속물(사용자 결정 2026-10-28: 비율 백어저스트)
    c1 = ts("CLc1").set_index(D)["value"]
    c2 = ts("CLc2").set_index(D)["value"]
    both = pd.concat({"c1": c1, "c2": c2}, axis=1).dropna().index
    rolls = B.cl_roll_dates(both)
    sig = B.c1c2_roll_signal(c1, c2)
    cont = B.back_adjust_ratio(c1, c2, rolls, early_days=5)
    INFO["wti_rolls"] = {"n": int(len(rolls)), "first": [str(x.date()) for x in rolls[:6]],
                         "c1c2_signal_by_offset": _roll_offsets(c1, c2, rolls, sig),
                         "last": [str(x.date()) for x in rolls[-6:]],
                         "per_year": round(len(rolls) / ((c1.index[-1] - c1.index[0]).days / 365.25), 2),
                         "min_adj_close": float(np.nanmin(cont["close"])),
                         "c1_min": float(c1.min()), "c1_min_date": str(c1.idxmin().date()),
                         "cum_factor_first": float(cont["close"].iloc[0] / c1.reindex(cont.index).iloc[0])}
    pd.DataFrame({"roll_date": rolls}).to_csv(OUT / "wti_roll_dates.csv", index=False)
    add("WTI", "close", cont["close"].rename("value").reset_index().rename(columns={"index": D}),
        "refinitiv:CLc1/CLc2 ratio back-adjusted", "as_of = date",
        "교체일 = NYMEX 최종거래일 규칙(관측 거래일 기준) 다음 날, 그 5영업일 전에 다음 월물로 갈아탐(가정). c1/c2 신호로 검증")
    c1_pos = c1[c1 > 0]   # 2020-04-20 −37.63: 0 이하 근월물 가격은 실질가격·커브 비율에 쓸 수 없다 → 결측(사용자 결정 2026-10-28)
    INFO["wti_spot_dropped"] = [str(d.date()) for d in c1.index[c1 <= 0]]
    add("WTI", "close_c1_raw", c1_pos.rename("value").reset_index(), "refinitiv:CLc1", "as_of = date",
        "원 근월물(실질가격·커브용). 0 이하 값(2020-04-20)은 결측")
    add("WTI", "close_c2", c2.rename("value").reset_index(), "refinitiv:CLc2", "as_of = date")
    inv = pd.read_csv(RAW / "lseg" / "eia" / "PS-ESPR-EIA.csv")
    inv = pd.DataFrame({D: pd.to_datetime(inv["Date"]).dt.normalize(),
                        "value": pd.to_numeric(inv["COMM_LAST"], errors="coerce")}).dropna()
    inv["as_of"] = inv[D] + pd.Timedelta(days=5)
    add("WTI", "inventory", inv, "lseg:PS-ESPR-EIA COMM_LAST", "as_of = 기준 금요일 + 5일(수요일 공표, 가정: 공휴일 지연 미반영)",
        "EIA 주간 미국 원유 재고(SPR 제외, 백만 배럴)")

    # KR 회사채 스프레드(%p)
    ktb3 = ts("KRTSY3Y=KQ").set_index(D)["value"]
    for fld, ric, note in (("spread", "KRGUCORP=KQ", "AA−(3년) − 국고3년"), ("spread_low_grade", "KRCORP=KQ", "BBB−(3년) − 국고3년")):
        s = (ts(ric).set_index(D)["value"] - ktb3).dropna()
        add("KR_CORP", fld, s.rename("value").reset_index(), f"refinitiv:{ric}−KRTSY3Y=KQ", "as_of = date", note)

    # ---------------- SPX (get_data)
    spx = parse_get_data(gd_concat("SPX_close__*.csv", "spx"))
    add("SP500", "close", spx[[D, "value"]], "refinitiv:.SPX TR.PriceClose Frq=D", "as_of = date",
        "휴장일 재반환 행은 반환 날짜로 중복 제거")
    a = B.bottomup_rows(pd.read_csv(RF / "spx" / "SPX_eps_ntm_aligned.csv"), ["eps", "px"])
    snap = parse_get_data(pd.read_csv(RF / "spx" / "SPX_eps_ntm_snap.csv"))
    eps = pd.concat([a.rename(columns={"sample_date": D, "eps": "value"})[[D, "value"]],
                     snap.assign(date=pd.Timestamp(END))[[D, "value"]]]).drop_duplicates(D, keep="last")
    add("SP500", "fwd_eps_12m", eps, "refinitiv:.SPX TR.EPSMean(Period=NTM) Frq=M + END 스냅숏",
        "as_of = 표본일(월말·스냅숏일) ≥ 반환 날짜", "반환 날짜는 마지막 변경일이라 다음 달에도 반복 → 표본일 사용(보수적)")
    pe = parse_get_data(pd.read_csv(RF / "spx" / "SPX_pe_fwd.csv"))
    pes = parse_get_data(pd.read_csv(RF / "spx" / "SPX_pe_fwd_snap.csv"))
    add("SP500", "fwd_per", pd.concat([pe, pes]).drop_duplicates(D, keep="last")[[D, "value"]],
        "refinitiv:.SPX TR.PtoEPSMeanEst Frq=M + END 스냅숏", "as_of = 반환 날짜(월말)")

    # ---------------- 바텀업
    us_rows = pd.concat([B.bottomup_rows(pd.read_csv(p), ["eps", "mcap"])
                         for p in sorted((RF / "bottomup_us").glob("us_*.csv"))]).drop_duplicates(["ric", "month"], keep="last")
    up = B.eps_up_share(us_rows)
    add("SP500", "eps_up_share", up, "refinitiv:SPY 보유종목 TR.EPSMean(NTM)·TR.CompanyMarketCap 바텀업",
        "as_of = 그달 표본일 최댓값", "현재 구성종목(생존편향, 가정). 가중치 = 전월 시총")
    INFO["sp500_bottomup"] = {"n_ric": int(us_rows["ric"].nunique()), "n_month_min": int(up["n"].min()),
                              "n_month_median": int(up["n"].median()), "n_last": int(up["n"].iloc[-1])}
    kr_rows = pd.concat([B.bottomup_rows(pd.read_csv(p), ["eps", "mcap", "px", "pbr", "dy"])
                         for p in sorted((RF / "bottomup_kr").glob("kr_*.csv"))]).drop_duplicates(["ric", "month"], keep="last")
    agg = B.aggregate_multiples(kr_rows)
    note_kr = "현재 KOSPI200 구성종목(KODEX200 보유) 바텀업 — 생존편향(가정, 사용자 결정 2026-10-28)"
    for fld in ("fwd_per", "pbr", "div_yield", "fwd_eps_12m"):
        add("KOSPI200", fld, agg[fld], f"refinitiv:KODEX200 보유종목 바텀업({fld})", "as_of = 그달 표본일 최댓값",
            note_kr + ("; 연쇄지수(첫 달 100)" if fld == "fwd_eps_12m" else ""))
    kup = B.eps_up_share(kr_rows)
    add("KOSPI200", "eps_up_share", kup, "refinitiv:KODEX200 보유종목 바텀업", "as_of = 그달 표본일 최댓값", note_kr)
    # 민감도 필드(사용자 결정 2026-10-28 C — Phase 3 비교용, 프로파일에 없어 점수에 쓰지 않음)
    ex2 = ["005930.KS", "005935.KS", "000660.KS"]
    for tag, rr, desc in (("ew", B.equal_weight_rows(kr_rows), "동일가중"),
                          ("ex2", B.exclude_rows(kr_rows, ex2), "삼성전자(보통·우선)·SK하이닉스 제외 시총가중")):
        a2 = B.aggregate_multiples(rr)
        for fld in ("fwd_per", "fwd_eps_12m"):
            add("KOSPI200", f"{fld}_{tag}", a2[fld], f"refinitiv:KODEX200 바텀업 {desc}", "as_of = 그달 표본일 최댓값",
                "민감도(점수 미사용). " + note_kr)
        add("KOSPI200", f"eps_up_share_{tag}", B.eps_up_share(rr), f"refinitiv:KODEX200 바텀업 {desc}",
            "as_of = 그달 표본일 최댓값", "민감도(점수 미사용). " + note_kr)
    INFO["kospi200_concentration"] = _concentration(kr_rows, ["005930.KS", "005935.KS", "000660.KS"])
    INFO["kospi200_bottomup"] = {k: {"n_min": int(v["n"].min()), "n_median": int(v["n"].median()),
                                     "n_last": int(v["n"].iloc[-1]), "first": str(v["date"].min().date())}
                                 for k, v in {**agg, "eps_up_share": kup}.items()}

    # 시장폭(현재 구성종목 일봉)
    hold = pd.read_csv(RF / "holdings" / "kodex200.csv").dropna(subset=["Holding RIC"])
    closes = {}
    for r in hold["Holding RIC"]:
        d = ts(r, "kr_daily")
        if len(d):
            closes[r] = d.set_index(D)["value"]
    cl = pd.DataFrame(closes)
    cl = cl.reindex(cl.index.intersection(pd.DatetimeIndex(k200[D])))   # KOSPI200 거래일만
    br = B.breadth(cl)
    for fld in br.columns:
        add("KOSPI200", fld, br[fld].rename("value").reset_index().rename(columns={"index": D}).dropna(),
            "refinitiv:KODEX200 보유종목 일봉 get_timeseries CLOSE", "as_of = date",
            "현재 구성종목 기준 — 생존편향(가정)")
    INFO["kospi200_breadth"] = {"n_ric": int(cl.shape[1]), "n_2010": int(cl.loc["2010"].notna().any().sum()),
                                "n_last": int(cl.iloc[-1].notna().sum())}

    # ---------------- iBoxx (lseg)
    ust_curve = pd.DataFrame({ten: ts(r).set_index(D)["value"] for r, ten in B.UST_TENORS.items()})
    for aid, ric in (("US_HY", "IBLUS0004"), ("US_IG", "IBLUS0005")):
        ib = pd.concat([pd.read_csv(p) for p in sorted((RAW / "lseg" / "iboxx").glob(f"{ric}__*.csv"))])
        ib["Date"] = pd.to_datetime(ib["Date"]).dt.normalize()
        ib = ib.drop_duplicates("Date", keep="last").set_index("Date").sort_index()
        ib = ib[ib.index <= pd.Timestamp(END)]
        gs = B.g_spread(ib["YLDTOMAT"], ib["AVG_LIFE"], ust_curve, match="maturity").dropna()
        add(aid, "spread", gs.rename("value").reset_index().rename(columns={"Date": D}),
            f"lseg:.{ric} YLDTOMAT − UST 커브(1·2·3·5·7·10·30년 =RR) 평균만기(AVG_LIFE) 매칭", "as_of = date",
            "G-스프레드(%p). 사용자 결정 2026-10-28 A(가정: 만기 사이 선형 보간)")
        gd_ = B.g_spread(ib["YLDTOMAT"], ib["MOD_DURTN"], ust_curve, match="duration").dropna()
        add(aid, "spread_dur_matched", gd_.rename("value").reset_index().rename(columns={"Date": D}),
            f"lseg:.{ric} YLDTOMAT − 같은 수정듀레이션 액면 국채", "as_of = date", "비교용(점수에 쓰지 않음)")
        lvl = ib["TRDPRC_1"].dropna()
        add(aid, "index_level", lvl.rename("value").reset_index().rename(columns={"Date": D}),
            f"lseg:.{ric} TRDPRC_1", "as_of = date", "총수익지수(TRTN_PRICE 와 동일 — Phase 2 확인)")
        both = ib[["TRDPRC_1", "TRTN_PRICE"]].dropna()
        INFO[f"{aid}_tr_check"] = {"rows_both": int(len(both)),
                                   "max_abs_diff": float((both["TRDPRC_1"] - both["TRTN_PRICE"]).abs().max())}

    # ---------------- FRED
    fred_map = {("SP500", "vol_index"): "VIXCLS", ("SP500", "vol_index_3m"): "VXVCLS",
                ("UST10Y", "real_yield"): "DFII10", ("UST10Y", "policy_rate"): "DFF",
                ("USDKRW", "reer"): "RBKRBIS"}
    from mtscore.data.adapters.fred import AS_OF_RULES  # noqa: F401
    rules = {"VIXCLS": "as_of = date", "VXVCLS": "as_of = date", "DFII10": "as_of = 다음 미국 영업일(가정)",
             "DFF": "as_of = 다음 미국 영업일", "RBKRBIS": "as_of = 기준월 1일 + 3개월(가정)"}
    fa = FredAdapter(fred_map, RAW / "fred")
    for (aid, fld), sid in fred_map.items():
        p = fa.fetch(aid, [fld], WARM, END)
        add(aid, fld, p[[D, "value", "as_of"]], f"fred:{sid}", rules[sid], "최신 빈티지(수정치) — 가정")
    # ALFRED 최초 공표값(사용자 결정 2026-10-28 E·F): 값 = 처음 나온 빈티지의 값, as_of = 그 빈티지 날짜(공표일)
    for sid, targets in (("CPIAUCSL", [("UST10Y", "cpi"), ("GOLD", "cpi"), ("WTI", "cpi")]),
                         ("NFCI", [("UST10Y", "nfci")]), ("THREEFYTP10", [("UST10Y", "term_premium")])):
        files = sorted((RAW / "fred" / "alfred" / sid).glob("*.csv"))
        long = pd.concat([fred_mod.parse_alfred(p.read_text(encoding="utf-8")) for p in files], ignore_index=True)
        fr = fred_mod.first_releases(long, max_lag_days=ALFRED_LOOKBACK[sid])
        lag = (fr["as_of"] - fr["date"]).dt.days
        INFO[f"alfred_{sid}"] = {"vintage_first": str(long["vintage"].min().date()),
                                 "vintage_last": str(long["vintage"].max().date()), "n_obs": int(len(fr)),
                                 "first_obs": str(fr["date"].min().date()), "last_obs": str(fr["date"].max().date()),
                                 "lag_days_median": float(lag.median()), "lag_days_max": int(lag.max()),
                                 "lag_days_p95": float(lag.quantile(0.95))}
        for aid, fld in targets:
            add(aid, fld, fr, f"alfred:{sid} 최초 공표값", "as_of = ALFRED 최초 공표 빈티지 날짜(실측)",
                f"실시간 값(수정치 미사용). 첫 빈티지 {long['vintage'].min().date()} 이전은 N/A")

    # ---------------- ECOS
    ea = EcosAdapter({("KTB10Y", "cpi"): ("901Y009", "M", "200801", "202610", "0"),
                      ("USDKRW", "ca"): ("301Y013", "M", "200801", "202610", "000000")}, RAW / "ecos")
    kr_cpi = ea.fetch("KTB10Y", ["cpi"], WARM, END)
    add("KTB10Y", "cpi", kr_cpi[[D, "value", "as_of"]], "ecos:901Y009/0", "as_of = 다음 달 5일(익월 초 공표, 사용자 결정)",
        "소비자물가 총지수(2020=100)")
    ca = ea.fetch("USDKRW", ["ca"], WARM, END)
    ca12 = B.rolling_sum_months(ca[[D, "value", "as_of"]], 12)
    add("USDKRW", "current_account_12m", ca12, "ecos:301Y013/000000 12개월 합",
        "as_of = 기준월 + 2개월 10일(가정)", "경상수지(백만달러) 최근 12개월 합")
    # 파생: KTB 실질금리 대리, 금리차
    ry = B.real_yield_proxy(ktb10, kr_cpi[[D, "value", "as_of"]])
    add("KTB10Y", "real_yield", ry, "파생: KRTSY10Y=KQ − ECOS CPI YoY(그날까지 공표분)", "as_of = date",
        "대리지표(가정: 사후 물가로 기대인플레이션 대신)")
    rd = B.rate_diff_cross_market(ktb10, ust10, lag_days=1)
    add("USDKRW", "rate_diff", rd, "파생: KRTSY10Y=KQ − US10YT=RR(t−1일 이전 최신)", "as_of = date",
        "시장 간 +1일 규칙(서울 마감 시점의 최신 뉴욕 종가)")

    # ---------------- CFTC
    ca_ = CftcAdapter({("GOLD", "cot_net"): "088691", ("WTI", "cot_net"): "067651", ("UST10Y", "cot_net"): "043602"},
                      RAW / "cftc")
    for aid, code in (("GOLD", "088691"), ("WTI", "067651"), ("UST10Y", "043602")):
        p = ca_.fetch(aid, ["cot_net"], WARM, END)
        add(aid, "cot_net", p[[D, "value", "as_of"]], f"cftc:6dca-aqww/{code}", "as_of = 화요일 + 3일(금요일 공표)",
            "비상업 롱 − 숏(계약). 공휴일 주 지연 미반영(가정)")

    panel = validate_panel(pd.concat(PARTS, ignore_index=True))
    PROC.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PROC / "panel.csv.gz", index=False)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(FIELD_MAP).to_csv(OUT / "field_map.csv", index=False)
    INFO["panel_rows"] = int(len(panel))
    INFO["build_seconds"] = round(time.time() - t0, 1)
    (OUT / "build_info.json").write_text(json.dumps(INFO, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(INFO, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
