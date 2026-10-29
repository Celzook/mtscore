import sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/infomax/Desktop/Infomax/_project/mtscore/src")
from mtscore.core.indicators.price import bb_pctb
from mtscore.core.indicators.volatility import rv_ratio, level_rv_ratio
D = "/home/infomax/Desktop/Infomax/_project/mtscore/data/processed/"
pan = pd.read_csv(D + "panel.csv.gz", parse_dates=["date"])
fr = pd.read_csv(D + "phase3_forward_returns.csv.gz", parse_dates=["date"])
SPEC = {  # asset: (field, 과매도 방향: '-' 는 %b<0, '+' 는 %b>1, 변동성 함수)
 "KOSPI200": ("close", "-", rv_ratio), "SP500": ("close", "-", rv_ratio), "USDKRW": ("close", "-", rv_ratio),
 "GOLD": ("close", "-", rv_ratio), "WTI": ("close", "-", rv_ratio),
 "KTB10Y": ("yield", "+", level_rv_ratio), "UST10Y": ("yield", "+", level_rv_ratio),
 "US_HY": ("spread", "+", level_rv_ratio), "US_IG": ("spread", "+", level_rv_ratio), "KR_CORP": ("spread", "+", level_rv_ratio)}
rows = []
for a, (fld, dirn, vf) in SPEC.items():
    x = pan[(pan.asset_id == a) & (pan.field == fld)].drop_duplicates("date", keep="last").set_index("date")["value"].sort_index()
    if a == "USDKRW": x = 1.0 / x   # universe.yaml field_transforms: reciprocal (원화 가격)
    pb = bb_pctb(x, 20, 2); vr = vf(x, 20, 252)
    f = fr[fr.asset_id == a].set_index("date")
    unc = {h: f[f"fwd_{h}"].mean() for h in (21, 63)}
    hit = (pb < 0) if dirn == "-" else (pb > 1)
    last = None
    for d in hit[hit].index:
        if d not in f.index or pd.isna(vr.get(d)) or pd.isna(f.at[d, "fwd_63"]): continue
        if last is not None and len(x.loc[last:d]) - 1 < 20: continue
        last = d
        rows.append({"asset": a, "date": d, "vr": vr[d], "r21": f.at[d, "fwd_21"], "r63": f.at[d, "fwd_63"],
                     "x21": f.at[d, "fwd_21"] - unc[21], "x63": f.at[d, "fwd_63"] - unc[63], "mae21": f.at[d, "mae_21"],
                     "trend_up": f.at[d, "trend_up"]})
    print(a, fld, "첫값", x.index[0].date(), "마지막", x.index[-1].date(), "샘플값", round(x.iloc[-1], 4))
E = pd.DataFrame(rows)
E["vb"] = pd.cut(E.vr, [0, 1.0, 1.5, np.inf], labels=["낮음(<1)", "보통(1~1.5)", "높음(≥1.5)"])
E["month"] = E.date.dt.to_period("M")
def summ(g):
    return pd.Series({"n": len(g), "월수": g.month.nunique(), "21일 초과": g.x21.mean(), "63일 초과": g.x63.mean(),
        "63일 승률": (g.r63 > 0).mean(), "21일 MAE 평균": g.mae21.mean(), "MAE<−5% 비율": (g.mae21 < -0.05).mean()})
pd.set_option("display.width", 250); pd.set_option("display.float_format", lambda v: f"{v:.3f}")
print("\n이벤트", len(E), E.date.min().date(), E.date.max().date())
print("\n[A] 변동성비 구간별 (10개 자산 합산)"); print(E.groupby("vb", observed=True).apply(summ).T)
print("\n[B] 자산별 (n, 63일 초과, MAE)"); print(E.groupby(["asset", "vb"], observed=True).agg(n=("x63", "size"), x63=("x63", "mean"), mae=("mae21", "mean")).unstack().round(3))
print("\n[C] 주가지수·원자재만 (가격형)"); print(E[E.asset.isin(["KOSPI200","SP500","GOLD","WTI","USDKRW"])].groupby("vb", observed=True).apply(summ).T)
print("\n[D] 금리·크레딧 (수준형)"); print(E[~E.asset.isin(["KOSPI200","SP500","GOLD","WTI","USDKRW"])].groupby("vb", observed=True).apply(summ).T)
rng = np.random.default_rng(0); hi = E[E.vb == "높음(≥1.5)"]; lo = E[E.vb == "낮음(<1)"]
def boot(col):
    mh = hi.groupby("month")[col].apply(list); ml = lo.groupby("month")[col].apply(list); d = []
    for _ in range(4000):
        a = np.concatenate(mh.sample(len(mh), replace=True, random_state=rng.integers(1e9)).values)
        b = np.concatenate(ml.sample(len(ml), replace=True, random_state=rng.integers(1e9)).values)
        d.append(np.nanmean(a) - np.nanmean(b))
    return round(hi[col].mean() - lo[col].mean(), 4), np.percentile(d, [2.5, 97.5]).round(4)
for c in ["x21", "x63", "mae21"]: print("[E] 높음−낮음", c, boot(c))
print("\n[F] 임계값 민감도: 변동성비 ≥ c vs < 1 (63일 초과, MAE<−5% 비율, n·월)")
for c in (1.25, 1.5, 1.75, 2.0):
    h = E[E.vr >= c]; l = E[E.vr < 1]
    print(c, "n", len(h), "월", h.month.nunique(), "x63 %.3f vs %.3f" % (h.x63.mean(), l.x63.mean()),
          "MAE5 %.2f vs %.2f" % ((h.mae21 < -.05).mean(), (l.mae21 < -.05).mean()))
print("\n[G] 전·후반 (2010-2017 / 2018-2026), 높음(≥1.5) vs 낮음")
for nm, m in (("전반", E.date < "2018-01-01"), ("후반", E.date >= "2018-01-01")):
    s = E[m]; h = s[s.vr >= 1.5]; l = s[s.vr < 1]
    print(nm, "높음 n", len(h), "x63 %.3f" % h.x63.mean(), "MAE5 %.2f" % (h.mae21 < -.05).mean(), "| 낮음 n", len(l), "x63 %.3f" % l.x63.mean(), "MAE5 %.2f" % (l.mae21 < -.05).mean())
print("\n[H] 높음(≥1.5) 자산 빼고 보기: KOSPI200·WTI 제외")
s = E[~E.asset.isin(["KOSPI200", "WTI"])]; print("높음 n", (s.vr >= 1.5).sum(), "x63 %.3f" % s[s.vr >= 1.5].x63.mean(), "낮음 x63 %.3f" % s[s.vr < 1].x63.mean())
# [I] 대조군: 과매도가 아닌 날(%b 가 과매도 쪽 밴드 밖이 아님)도 같은 방식(20일 간격)으로 표본을 뽑아 변동성비별로 본다
rows = []
for a, (fld, dirn, vf) in SPEC.items():
    x = pan[(pan.asset_id == a) & (pan.field == fld)].drop_duplicates("date", keep="last").set_index("date")["value"].sort_index()
    if a == "USDKRW": x = 1.0 / x
    pb = bb_pctb(x, 20, 2); vr = vf(x, 20, 252)
    f = fr[fr.asset_id == a].set_index("date")
    unc63 = f["fwd_63"].mean()
    ok = (pb >= 0) if dirn == "-" else (pb <= 1)
    last = None
    for d in ok[ok].index:
        if d not in f.index or pd.isna(vr.get(d)) or pd.isna(f.at[d, "fwd_63"]): continue
        if last is not None and len(x.loc[last:d]) - 1 < 20: continue
        last = d
        rows.append({"asset": a, "date": d, "vr": vr[d], "x63": f.at[d, "fwd_63"] - unc63, "mae21": f.at[d, "mae_21"]})
C = pd.DataFrame(rows)
C["vb"] = pd.cut(C.vr, [0, 1.0, 1.5, np.inf], labels=["낮음(<1)", "보통(1~1.5)", "높음(≥1.5)"])
print("\n[I] 대조군(과매도 아님, 20일 간격) 변동성비별: n, 63일 초과, MAE<−5% 비율")
print(C.groupby("vb", observed=True).agg(n=("x63", "size"), x63=("x63", "mean"), mae5=("mae21", lambda s: (s < -.05).mean())).round(3))
pc = ["KOSPI200", "SP500", "GOLD", "WTI", "USDKRW"]
print("가격형만"); print(C[C.asset.isin(pc)].groupby("vb", observed=True).agg(n=("x63", "size"), x63=("x63", "mean")).round(3))
print("KOSPI200·WTI 만"); print(C[C.asset.isin(["KOSPI200", "WTI"])].groupby("vb", observed=True).agg(n=("x63", "size"), x63=("x63", "mean")).round(3))
