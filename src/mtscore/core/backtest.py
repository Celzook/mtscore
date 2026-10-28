"""백테스트 — forward return·통계. 순수 함수(파일·네트워크 없음).

무(無)미래참조 규칙
- 점수는 t 시점에 알 수 있던 값(as_of ≤ t)만으로 계산된 이력(ScoringEngine.score_history)을 받는다.
- forward return 은 t 종가 이후 구간 (t, t+h] 의 수익이다. 첫 일별 수익은 t+1 의 것이다.
- h 는 자산 달력(점수 색인)의 위치 이동(영업일 수)이다. 달력일 오프셋이 아니다. 끝의 h 행은 NaN.
- 분위 경계·순위(IC)는 전체 표본으로 정한다(분석 단계의 사후 집계이며 점수 계산에는 쓰지 않는다).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from .scoring import regime


# ---- 일별 수익률 · 수익 지수
def price_returns(level: pd.Series) -> pd.Series:
    """가격·총수익 지수 수준 → 일별 단순수익률. 결측일의 변화는 다음 관측일에 몰아 준다(결측일 = 0)."""
    s = level.dropna().astype(float)
    r = s / s.shift(1) - 1.0
    return r.reindex(level.index).fillna(0.0)


def duration_returns(y: pd.Series, duration: float, carry_days: float = 252.0) -> pd.Series:
    """금리(%) 수준 → 일별 근사 수익률 −D×Δy/100 + y_{t−1}/100/carry_days.

    가정: 수정듀레이션 D 고정, 볼록성·롤다운 무시, 캐리 = 직전일 금리의 일할(연 carry_days 일).
    스프레드(%p)를 넣으면 같은 듀레이션 국채 대비 초과수익 근사가 된다."""
    s = y.dropna().astype(float)
    r = -float(duration) * s.diff() / 100.0 + s.shift(1) / 100.0 / float(carry_days)
    return r.reindex(y.index).fillna(0.0)


def return_index(daily: pd.Series) -> pd.Series:
    """일별 수익률 → 누적 수익 지수(첫날 1). 일별 수익률은 복리로 쌓는다."""
    return (1.0 + daily.fillna(0.0)).cumprod()


def forward_returns(index: pd.Series, horizons, valid: pd.Series | None = None) -> pd.DataFrame:
    """h 영업일 forward return: index[t+h] / index[t] − 1 (구간 (t, t+h]).

    valid: 수익 원천 값이 실제로 있던 날(진입·청산일 모두 valid 여야 값이 있다). 없으면 전부 valid."""
    v = pd.Series(True, index=index.index) if valid is None else valid.reindex(index.index).fillna(False).astype(bool)
    out = {}
    for h in horizons:
        h = int(h)
        f = index.shift(-h) / index - 1.0
        ok = v & v.shift(-h, fill_value=False)
        out[h] = f.where(ok)
    return pd.DataFrame(out, index=index.index)


def forward_mae(index: pd.Series, horizons, valid: pd.Series | None = None) -> pd.DataFrame:
    """최대 역행폭(MAE): min_{1≤k≤h} index[t+k]/index[t] − 1 (0 이상이면 0 으로 자르지 않는다)."""
    v = pd.Series(True, index=index.index) if valid is None else valid.reindex(index.index).fillna(False).astype(bool)
    nxt = index.shift(-1)
    out = {}
    for h in horizons:
        h = int(h)
        mn = nxt[::-1].rolling(h, min_periods=h).min()[::-1]   # min(index[t+1..t+h])
        ok = v & v.shift(-h, fill_value=False)
        out[h] = (mn / index - 1.0).where(ok)
    return pd.DataFrame(out, index=index.index)


def trend_up(index: pd.Series, window: int = 200) -> pd.Series:
    """추세 게이트: 수익 지수 ≥ 그 window 일 단순이동평균(현재 포함, 과거만 사용). 워밍업 중은 NaN."""
    ma = index.rolling(int(window), min_periods=int(window)).mean()
    return (index >= ma).where(ma.notna())


# ---- 통계
def newey_west_se(u: np.ndarray, lag: int) -> float:
    """평균의 Newey-West(Bartlett 가중) 표준오차. lag 0 이면 iid 표준오차(분산 ddof=0)."""
    u = np.asarray(u, dtype=float)
    n = len(u)
    if n < 2:
        return np.nan
    e = u - u.mean()
    s = e @ e / n
    for k in range(1, min(int(lag), n - 1) + 1):
        s += 2.0 * (1.0 - k / (lag + 1.0)) * (e[k:] @ e[:-k]) / n
    return float(np.sqrt(max(s, 0.0) / n))


def rank_products(x: pd.Series, y: pd.Series) -> pd.Series:
    """표준화 순위 곱 u_t = z(rank x)·z(rank y) (ddof=0). 평균 = Spearman 상관. x·y 둘 다 있는 날만."""
    d = pd.concat([x, y], axis=1, keys=["x", "y"]).dropna()
    if len(d) < 3:
        return pd.Series(dtype=float)
    rx, ry = d["x"].rank(), d["y"].rank()
    sx, sy = rx.std(ddof=0), ry.std(ddof=0)
    if sx == 0 or sy == 0:
        return pd.Series(np.nan, index=d.index)
    return ((rx - rx.mean()) / sx) * ((ry - ry.mean()) / sy)


def spearman_ic(score: pd.Series, fwd: pd.Series, horizon: int) -> dict:
    """Spearman IC 와 Newey-West t(lag = horizon − 1), 그리고 겹치지 않는 표본(h 행마다 1개) 강건성 점검.

    Returns: ic, t_nw, n, ic_nonoverlap, t_nonoverlap, n_nonoverlap."""
    u = rank_products(score, fwd)
    n = int(u.notna().sum())
    ic = float(u.mean()) if n else np.nan
    se = newey_west_se(u.dropna().to_numpy(), max(int(horizon) - 1, 0)) if n >= 3 else np.nan
    t = ic / se if se and np.isfinite(se) and se > 0 else np.nan
    d = pd.concat([score, fwd], axis=1).dropna()
    sub = d.iloc[::max(int(horizon), 1)]
    m = len(sub)
    ic2 = float(sub.iloc[:, 0].rank().corr(sub.iloc[:, 1].rank())) if m >= 3 else np.nan
    t2 = ic2 * np.sqrt((m - 2) / (1 - ic2 ** 2)) if m >= 3 and np.isfinite(ic2) and abs(ic2) < 1 else np.nan
    return {"ic": ic, "t_nw": t, "n": n, "ic_nonoverlap": ic2, "t_nonoverlap": t2, "n_nonoverlap": m}


def pooled_ic(pairs: list[tuple[pd.Series, pd.Series]], horizon: int) -> dict:
    """자산군 풀링 IC: 자산마다 표준화 순위 곱을 만든 뒤 날짜별 평균 → 그 날짜 시계열의 평균과 NW t.

    순위는 자산 안에서 매긴다(자산 간 수익률 규모 차이를 지운다)."""
    us = [rank_products(s, f) for s, f in pairs]
    us = [u for u in us if len(u)]
    if not us:
        return {"ic": np.nan, "t_nw": np.nan, "n": 0, "n_dates": 0, "n_assets": 0}
    m = pd.concat(us, axis=1).mean(axis=1).dropna()
    se = newey_west_se(m.to_numpy(), max(int(horizon) - 1, 0))
    ic = float(m.mean())
    return {"ic": ic, "t_nw": ic / se if se and se > 0 else np.nan, "n": int(sum(u.notna().sum() for u in us)),
            "n_dates": int(len(m)), "n_assets": len(us)}


def ret_stats(fwd: pd.Series, mae: pd.Series | None, horizon: int, min_n: int = 10) -> dict:
    """forward return 묶음 통계: n·평균·중앙값·승률(>0)·평균 MAE·겹침 보정 표본 수(n/h)·경고."""
    f = fwd.dropna()
    n = len(f)
    out = {"n": n, "mean": f.mean() if n else np.nan, "median": f.median() if n else np.nan,
           "hit_rate": (f > 0).mean() if n else np.nan,
           "mae_mean": mae.reindex(f.index).mean() if (mae is not None and n) else np.nan,
           "n_indep_approx": n / max(int(horizon), 1)}
    out["warning"] = "표본 부족" if n < min_n else ("독립 표본 부족(중첩)" if out["n_indep_approx"] < min_n else "")
    return out


def quantile_labels(score: pd.Series, q: int = 5) -> pd.Series:
    """전체 표본 분위(1 = 최저, q = 최고). 경계가 겹치면 줄인다(duplicates=drop)."""
    s = score.dropna()
    if s.empty:
        return pd.Series(dtype=float, index=score.index)
    lab = pd.qcut(s, q, labels=False, duplicates="drop") + 1
    return lab.reindex(score.index)


def band_masks(score: pd.Series, bands: dict) -> dict[str, pd.Series]:
    """극단 구간 마스크: ≥extreme, ≥alert, ≤contra_alert, ≤contra_extreme, 그리고 전체(all)."""
    ok = score.notna()
    e, a = bands.get("extreme", 90), bands.get("alert", 75)
    ca, ce = bands.get("contra_alert", 25), bands.get("contra_extreme", 10)
    return {"all": ok, f">={e:g}": score >= e, f">={a:g}": score >= a, f"<={ca:g}": score <= ca, f"<={ce:g}": score <= ce}


def event_dates(cond: pd.Series, cooldown: int) -> pd.DatetimeIndex:
    """이벤트 = 조건이 거짓→참으로 바뀐 날(진입일). 직전 이벤트 뒤 cooldown 영업일(위치) 안의 진입은 버린다."""
    c = cond.fillna(False).astype(bool).to_numpy()
    prev = np.r_[False, c[:-1]]
    entries = np.flatnonzero(c & ~prev)
    keep, last = [], -10 ** 9
    for i in entries:
        if i - last > cooldown:
            keep.append(i)
            last = i
    return cond.index[keep]


def regime_labels(blocks: pd.DataFrame, regime_cfg: dict) -> pd.DataFrame:
    """일별 국면 라벨(core.scoring.regime 그대로). 블록이 모두 NaN 인 날은 label None."""
    rows = []
    for t, b in blocks.iterrows():
        r = regime(b.to_dict(), regime_cfg)
        rows.append({"date": t, "label": r["label"], "partial": r["partial"], **r["states"]})
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame(columns=["label", "partial", "o", "v", "f"])


# ---- 플라시보(순환 이동)·다중검정
def _zrank(v: np.ndarray) -> np.ndarray:
    """표준화 순위(평균 순위로 동률 처리, ddof=0)."""
    r = rankdata(v)
    sd = r.std()
    return (r - r.mean()) / sd if sd > 0 else np.full(len(r), np.nan)


def shift_draws(n: int, n_shifts: int, seed: int, margin: int = 252) -> np.ndarray:
    """순환 이동 크기 표본: [margin, n − margin) 정수 n_shifts 개(고정 시드). 범위가 없으면 빈 배열."""
    if n - margin <= margin or n_shifts <= 0:
        return np.array([], dtype=int)
    return np.random.default_rng(seed).integers(margin, n - margin, n_shifts)


def placebo_ic(score: pd.Series, fwds: dict, shifts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """순환 이동 플라시보. 점수를 점수가 있는 날들 위에서 k 칸 굴려(np.roll) forward return 과의 관계를 끊되
    점수의 자기상관 구조는 유지한다. Returns (obs[h], P[shift, h]) — IC 정의는 rank_products 평균과 같다."""
    s = score.dropna()
    hs = list(fwds)
    obs = np.full(len(hs), np.nan)
    P = np.full((len(shifts), len(hs)), np.nan)
    vals = s.to_numpy()
    for j, h in enumerate(hs):
        f = fwds[h].reindex(s.index)
        ok = f.notna().to_numpy()
        if ok.sum() < 3:
            continue
        zy = _zrank(f.to_numpy()[ok])
        obs[j] = np.mean(_zrank(vals[ok]) * zy)
        for i, k in enumerate(shifts):
            P[i, j] = np.mean(_zrank(np.roll(vals, int(k))[ok]) * zy)
    return obs, P


def pooled_placebo_ic(pairs: list[tuple[pd.Series, dict]], shifts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """풀링 플라시보: 모든 자산에 같은 이동 k 를 적용하고 pooled_ic 와 같은 방식(날짜별 평균 순위곱의 평균)으로 집계."""
    hs = list(pairs[0][1])
    union = pd.DatetimeIndex(sorted(set().union(*[set(sc.dropna().index) for sc, _ in pairs])))
    prep = {h: [] for h in hs}   # 기간별 (점수값, 유효 마스크, 표준화 순위 y, union 위치)
    for score, fwds in pairs:
        s = score.dropna()
        for h in hs:
            f = fwds[h].reindex(s.index)
            ok = f.notna().to_numpy()
            if ok.sum() >= 3:
                prep[h].append((s.to_numpy(), ok, _zrank(f.to_numpy()[ok]), union.get_indexer(s.index[ok])))

    def stat(k):
        out = []
        for h in hs:
            if not prep[h]:
                out.append(np.nan)
                continue
            tot = np.zeros(len(union))
            cnt = np.zeros(len(union))
            for vals, ok, zy, pos in prep[h]:
                np.add.at(tot, pos, _zrank(np.roll(vals, int(k))[ok]) * zy)
                np.add.at(cnt, pos, 1.0)
            m = cnt > 0
            out.append(float(np.mean(tot[m] / cnt[m])))
        return np.array(out)

    return stat(0), np.array([stat(k) for k in shifts]).reshape(len(shifts), len(hs))


def placebo_p(obs, P) -> np.ndarray:
    """양측 플라시보 p = (#|P| ≥ |obs| + 1) / (N + 1), 열(기간)마다."""
    P = np.atleast_2d(P)
    obs = np.atleast_1d(obs)
    if P.shape[0] == 0:
        return np.full(len(obs), np.nan)
    return ((np.abs(P) >= np.abs(obs)).sum(axis=0) + 1) / (P.shape[0] + 1)


def bh_fdr(p) -> np.ndarray:
    """Benjamini-Hochberg q 값(NaN 은 그대로 두고 나머지로 계산)."""
    p = np.asarray(p, dtype=float)
    q = np.full(len(p), np.nan)
    ok = ~np.isnan(p)
    m = int(ok.sum())
    if m == 0:
        return q
    pv = p[ok]
    o = np.argsort(pv)
    adj = pv[o] * m / np.arange(1, m + 1)
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    out = np.empty(m)
    out[o] = np.minimum(adj, 1.0)
    q[ok] = out
    return q
