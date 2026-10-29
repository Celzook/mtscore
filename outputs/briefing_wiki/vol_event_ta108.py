import sys, numpy as np, pandas as pd
sys.path.insert(0, "/home/infomax/Desktop/Infomax/_project/기술적분석/20_engine")
from data import load_panel
P = load_panel(roll_adjust=True, drop_nonpos=True)
tr, ret, cls = P["tr"], P["ret"], P["uni"]["cls"]
sma = tr.rolling(20).mean(); sd = tr.rolling(20).std()
pctb = (tr - (sma - 2*sd)) / (4*sd)
rv = ret.rolling(20).std() * np.sqrt(252)
rvr = rv / rv.rolling(252, min_periods=252).mean()
sma200 = tr.rolling(200).mean()
H = [5, 21, 63]
fwd = {h: tr.shift(-h) / tr - 1 for h in H}
# 미래 경로: 21일 안 최저점(추가 하락), 미래 21일 실현변동성
fmin = pd.concat([tr.shift(-k) / tr - 1 for k in range(1, 22)]).groupby(level=0).min()
frv = ret[::-1].rolling(21).std()[::-1].shift(-1) * np.sqrt(252)
# 조건 없는 평균(자산별, 같은 기간) — 추세 효과 제거용
unc = {h: fwd[h].loc["2020-02-01":].mean() for h in H}
rows = []
for a in tr.columns:
    last = None
    s = pctb[a]
    for d in s.index[(s < 0).values]:
        if d < pd.Timestamp("2020-02-01") or pd.isna(rvr.at[d, a]) or pd.isna(fwd[63].at[d, a]):
            continue
        if last is not None and (tr.index.get_loc(d) - tr.index.get_loc(last)) < 20:
            continue
        last = d
        r = {"asset": a, "cls": cls[a], "date": d, "rvr": rvr.at[d, a], "rv": rv.at[d, a],
             "below200": tr.at[d, a] < sma200.at[d, a], "fmin21": fmin.at[d, a], "frv21": frv.at[d, a]}
        for h in H:
            r[f"r{h}"] = fwd[h].at[d, a]; r[f"x{h}"] = fwd[h].at[d, a] - unc[h][a]
        rows.append(r)
E = pd.DataFrame(rows)
E["vb"] = pd.cut(E["rvr"], [0, 1.0, 1.5, np.inf], labels=["낮음(<1)", "보통(1~1.5)", "높음(≥1.5)"])
E["month"] = E["date"].dt.to_period("M")
def summ(g):
    return pd.Series({"n": len(g), "월수": g["month"].nunique(),
        "21일 평균": g["r21"].mean(), "21일 초과": g["x21"].mean(), "63일 초과": g["x63"].mean(),
        "63일 승률": (g["r63"] > 0).mean(), "21일내 추가하락 평균": g["fmin21"].mean(),
        "추가하락>5% 비율": (g["fmin21"] < -0.05).mean(), "향후RV/현재RV": (g["frv21"] / g["rv"]).median()})
pd.set_option("display.width", 250); pd.set_option("display.float_format", lambda v: f"{v:.3f}")
print("이벤트:", len(E), "자산:", E.asset.nunique(), "기간", E.date.min().date(), E.date.max().date())
print("\n[1] 변동성비 구간별 (볼린저 하단 이탈, 20일 쿨다운)"); print(E.groupby("vb", observed=True).apply(summ).T)
print("\n[2] 변동성비 × 200일선 아래/위"); print(E.groupby(["below200", "vb"], observed=True).apply(summ).T)
print("\n[3] 자산군 × 변동성비 (63일 초과, n)")
print(E.groupby(["cls", "vb"], observed=True).agg(n=("x63", "size"), x63=("x63", "mean"), fmin=("fmin21", "mean")).unstack().round(3))
print("\n[4] 연도별 높음 vs 낮음 (63일 초과)")
E["yr"] = E.date.dt.year
print(E.groupby(["yr", "vb"], observed=True)["x63"].agg(["size", "mean"]).unstack().round(3))
# 월 클러스터 부트스트랩: 높음 − 낮음 63일 초과 차이
rng = np.random.default_rng(0); hi = E[E.vb == "높음(≥1.5)"]; lo = E[E.vb == "낮음(<1)"]
def boot(col):
    mh = hi.groupby("month")[col].apply(list); ml = lo.groupby("month")[col].apply(list); d = []
    for _ in range(4000):
        a = np.concatenate(mh.sample(len(mh), replace=True, random_state=rng.integers(1e9)).values)
        b = np.concatenate(ml.sample(len(ml), replace=True, random_state=rng.integers(1e9)).values)
        d.append(a.mean() - b.mean())
    d = np.array(d); return hi[col].mean() - lo[col].mean(), np.percentile(d, [2.5, 97.5])
for c in ["x21", "x63", "fmin21"]:
    print("\n[5] 높음−낮음", c, boot(c))
print("\n[6] RV 지속성: 현재 RV20 와 향후 21일 RV 의 순위상관", E[["rv", "frv21"]].corr("spearman").iloc[0, 1].round(3))
# [7] 고변동성 이벤트에서 변동성이 아직 오르는 중 vs 꺾인 뒤
rv5 = rv / rv.shift(5) - 1
E["rv_chg5"] = [rv5.at[d, a] for d, a in zip(E.date, E.asset)]
G = E[E.rvr >= 1.2].copy()
G["vstate"] = np.where(G.rv_chg5 > 0, "상승 중", "꺾임")
print("\n[7] 변동성비≥1.2 이벤트: 5일 RV 변화 방향별"); print(G.groupby("vstate").apply(summ).T)
