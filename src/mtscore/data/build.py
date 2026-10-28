"""파생 필드 구성 — 어댑터가 받은 원시계열을 프로파일이 요구하는 field 로 만든다(순수 함수, 파일·네트워크 없음).

코어(src/mtscore/core)가 아니라 데이터 층에 둔다: 여기서 만든 값은 모두 4-1 패널 행(date, value, as_of)이 되어
validate_panel 을 통과한 뒤 엔진에 들어간다. 각 함수의 PIT 규칙과 가정은 docstring 에 적는다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---- 공통
def lagged_asof(left_dates: pd.DatetimeIndex, right: pd.DataFrame, lag_days: int = 0) -> pd.Series:
    """left_dates 각 날짜 t 에 대해 right(date, value, as_of) 중 as_of ≤ t − lag_days 인 가장 최근 기준일의 값.

    as_of 순서로 알려진 최신 관측을 쓴다(같은 as_of 면 기준일이 늦은 것). right 에 as_of 가 없으면 date 를 쓴다."""
    r = right.copy()
    if "as_of" not in r.columns:
        r["as_of"] = r["date"]
    r = r.sort_values(["as_of", "date"]).drop_duplicates("as_of", keep="last")
    # as_of 순으로 '그때까지 본 가장 늦은 기준일'의 값만 남긴다(늦게 온 옛 기준일 값이 최신을 덮지 않게)
    r["_max_date"] = r["date"].cummax()
    r = r[r["date"] == r["_max_date"]]
    keys = pd.DataFrame({"t": pd.DatetimeIndex(left_dates) - pd.Timedelta(days=lag_days)}).reset_index()
    m = pd.merge_asof(keys.sort_values("t"), r[["as_of", "value"]].rename(columns={"as_of": "t"}), on="t",
                      direction="backward")
    return pd.Series(m.sort_values("index")["value"].to_numpy(), index=pd.DatetimeIndex(left_dates))


def frame(dates, values, as_of=None) -> pd.DataFrame:
    d = pd.DataFrame({"date": pd.DatetimeIndex(dates), "value": np.asarray(values, dtype=float)})
    d["as_of"] = d["date"] if as_of is None else pd.DatetimeIndex(as_of)
    return d.dropna(subset=["value"]).reset_index(drop=True)


# ---- 금리·환율 파생
def yoy_from_level(cpi: pd.DataFrame) -> pd.DataFrame:
    """월별 물가지수(date=기준월 1일, value, as_of) → 전년동월비(%) (date, value, as_of). as_of 는 당월 공표일.
    가정: 최신 빈티지로 계산(공표 당시 값 아님)."""
    c = cpi.sort_values("date").set_index("date")
    prev = c["value"].reindex(c.index - pd.DateOffset(years=1)).to_numpy()
    yoy = (c["value"].to_numpy() / prev - 1.0) * 100.0
    return frame(c.index, yoy, c["as_of"])


def real_yield_proxy(nominal: pd.DataFrame, cpi: pd.DataFrame) -> pd.DataFrame:
    """실질금리 대리 = 명목(일별, %) − 그날까지 공표된 최신 CPI YoY(%). date = as_of = 명목 기준일.
    가정: 사후 물가(전년비)로 기대인플레이션을 대신한다(KTB10Y, Phase 0 결정)."""
    n = nominal.sort_values("date")
    yoy = yoy_from_level(cpi)
    known = lagged_asof(pd.DatetimeIndex(n["date"]), yoy)
    return frame(n["date"], n["value"].to_numpy() - known.to_numpy())


def rate_diff_cross_market(home: pd.DataFrame, foreign: pd.DataFrame, lag_days: int = 1) -> pd.DataFrame:
    """금리차 = 자국(일별) − 외국 금리. 외국(미국) 값은 기준일 t 에 대해 기준일 ≤ t − lag_days 의 최신값(시장 간 +1일 규칙:
    서울 마감 시점에는 그날 뉴욕 종가를 모른다). date = as_of = 자국 기준일. 외국 값이 5일 넘게 없으면 결측."""
    h = home.sort_values("date")
    f = foreign.sort_values("date")[["date", "value"]].copy()
    f["as_of"] = f["date"]
    known = lagged_asof(pd.DatetimeIndex(h["date"]), f, lag_days)
    fd = lagged_asof(pd.DatetimeIndex(h["date"]), f.assign(value=f["date"].astype("int64").astype(float)), lag_days)
    age = (pd.DatetimeIndex(h["date"]).astype("int64") - fd.to_numpy()) / 86400e9
    v = np.where(age <= 5 + lag_days, h["value"].to_numpy() - known.to_numpy(), np.nan)
    return frame(h["date"], v)


def rolling_sum_months(monthly: pd.DataFrame, n: int = 12) -> pd.DataFrame:
    """월별 흐름(date=기준월 1일, value, as_of) → 직전 n 개월 합. n 개월이 모두 있어야 값. as_of = 마지막 달의 as_of."""
    m = monthly.sort_values("date").set_index("date")
    full = m["value"].asfreq("MS")
    s = full.rolling(n, min_periods=n).sum().reindex(m.index)
    return frame(m.index, s.to_numpy(), m["as_of"])


# ---- 크레딧
UST_TENORS = {"US1YT=RR": 1, "US2YT=RR": 2, "US3YT=RR": 3, "US5YT=RR": 5, "US7YT=RR": 7, "US10YT=RR": 10,
              "US30YT=RR": 30}


def par_mod_duration(yield_pct: np.ndarray, tenor_years: np.ndarray) -> np.ndarray:
    """반기 이표 액면가 채권의 수정듀레이션(년) = (1 − (1 + y/2)^(−2T)) / y. y 는 연 수익률(소수)."""
    y = np.maximum(np.asarray(yield_pct, dtype=float) / 100.0, 1e-6)
    return (1.0 - (1.0 + y / 2.0) ** (-2.0 * np.asarray(tenor_years, dtype=float))) / y


def g_spread(yld: pd.Series, duration: pd.Series, curve: pd.DataFrame, max_age_bdays: int = 5,
             match: str = "duration") -> pd.Series:
    """G-스프레드(%p) = 지수 만기수익률 − 같은 듀레이션(match="duration") 또는 같은 만기(match="maturity") 국채 수익률.

    match="maturity": duration 자리에 지수 평균만기(년, iBoxx `AVG_LIFE`)를 넣고 그 만기의 커브 수익률을 선형 보간한다.
    사용자 결정 2026-10-28 A: US_IG·US_HY 모두 평균만기 매칭(ICE OAS 수준 상관 IG 0.94·HY 0.98).
    match="duration"(2026-10-26 구성안):

    curve: date × 만기(년) 열(%, 국채 기준일). 지수 기준일 t 에 커브를 max_age_bdays 까지 직전값으로 채운다.
    각 만기 국채를 액면가 채권으로 보고 수정듀레이션을 계산해(par_mod_duration) 지수 듀레이션에 해당하는 만기를 보간하고,
    그 만기의 수익률을 커브에서 선형 보간한다. 가정: 국채 = 액면가 반기 이표채, 만기 사이 선형 보간.
    커브 범위 밖 듀레이션은 끝 만기 값으로 고정한다.
    (만기 = 듀레이션으로 놓는 단순 근사는 IG 에서 ICE OAS 와 수준 상관 0.40 이었고, 이 방식은 0.77 — 2026-10-28 실측)"""
    if match not in ("duration", "maturity"):
        raise ValueError(f"match 는 duration | maturity ({match!r})")
    c = curve.sort_index().reindex(curve.index.union(yld.index)).ffill(limit=max_age_bdays).reindex(yld.index)
    tenors = np.array(sorted(c.columns), dtype=float)
    c = c[sorted(c.columns)]
    out = np.full(len(yld), np.nan)
    for i, (y, d) in enumerate(zip(yld.to_numpy(), duration.reindex(yld.index).to_numpy())):
        row = c.iloc[i].to_numpy(dtype=float)
        ok = ~np.isnan(row)
        if np.isnan(y) or np.isnan(d) or ok.sum() < 2:
            continue
        t_ok, r_ok = tenors[ok], row[ok]
        t_star = d if match == "maturity" else np.interp(d, par_mod_duration(r_ok, t_ok), t_ok)
        out[i] = y - np.interp(t_star, t_ok, r_ok)
    return pd.Series(out, index=yld.index)


# ---- 원자재 연속물
def c1c2_roll_signal(c1: pd.Series, c2: pd.Series) -> pd.Series:
    """c1/c2 관계로 본 교체 신호: t 의 c1 이 전일 c1 보다 전일 c2 에 더 가까우면 True.
    |c1_t − c2_{t−1}| < |c1_t − c1_{t−1}|. 커브가 평평하면 잡음으로도 참이 된다(2010~ WTI 에서 연 104회 — 단독 사용 불가,
    2026-10-28 실측). 그래서 교체일은 거래소 만기 규칙(cl_roll_dates)으로 정하고 이 신호는 검증에만 쓴다."""
    x = pd.concat({"c1": c1, "c2": c2}, axis=1).dropna()
    return ((x["c1"] - x["c2"].shift()).abs() < (x["c1"] - x["c1"].shift()).abs()).fillna(False)


def cl_roll_dates(trading_days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """NYMEX WTI(CL) 근월물 교체일 = 최종거래일 다음 거래일.

    최종거래일: 인도월 전월 25일의 3영업일 전. 25일이 영업일이 아니면 25일 직전 영업일의 3영업일 전(NYMEX 규정).
    영업일은 데이터의 거래일(trading_days)로 근사한다(가정: 휴장 달력 = 관측 거래일)."""
    td = pd.DatetimeIndex(sorted(set(pd.DatetimeIndex(trading_days).normalize())))
    out = []
    for m in pd.period_range(td.min(), td.max(), freq="M"):
        d25 = pd.Timestamp(m.year, m.month, 25)
        pos = int((td <= d25).sum()) - 1   # 25일(영업일이면) 또는 그 직전 영업일의 위치
        ltd_pos = pos - 3
        if ltd_pos < 0 or ltd_pos + 1 >= len(td):
            continue
        out.append(td[ltd_pos + 1])
    return pd.DatetimeIndex(out)


def back_adjust_ratio(c1: pd.Series, c2: pd.Series, rolls: pd.DatetimeIndex, early_days: int = 5) -> pd.DataFrame:
    """비율 백어저스트 연속물. 근월물 교체일 r 의 early_days 영업일(자기 관측일) 전에 다음 월물(그때의 c2)로 갈아탄다.

    갈아타는 날 s 의 수익률은 같은 월물끼리(c2_s / c2_{s−1}), 그 이전 가격은 c2_{s−1}/c1_{s−1} 배를 누적해 곱한다
    (마지막 값 = 실제 근월물 가격). early_days > 0 은 만기 직전 근월물 이상가(2020-04-20 CLc1 −37.63)를 피하려는 것이다.
    가정: 만기 5영업일 전 교체. 반환: date × {close(연속물), held(실제 보유 월물 가격), switch(교체일 여부)}.
    """
    x = pd.concat({"c1": c1, "c2": c2}, axis=1).dropna().sort_index()
    idx = x.index
    use_c2 = pd.Series(False, index=idx)
    switch = pd.Series(False, index=idx)
    for r in rolls:
        if r not in idx:
            continue
        pos = idx.get_loc(r)
        s = max(pos - early_days, 1)
        use_c2.iloc[s:pos] = True
        switch.iloc[s] = True
    held = np.where(use_c2, x["c2"], x["c1"])
    # 일별 수익률: 보유 월물이 같은 날은 held_t/held_{t−1}; 교체일 s 는 c2_s / c2_{s−1}(새 월물 자기 수익률)
    prev_same = np.where(switch, x["c2"].shift().to_numpy(), pd.Series(held, index=idx).shift().to_numpy())
    # early_days == 0 이면 교체일이 r 자신이고 c1_r 은 이미 새 월물: 전일 c2 와 비교
    ret = held / prev_same
    ret[0] = np.nan
    adj = np.empty(len(idx))
    adj[-1] = held[-1]
    for i in range(len(idx) - 1, 0, -1):
        adj[i - 1] = adj[i] / ret[i] if np.isfinite(ret[i]) and ret[i] != 0 else np.nan
    return pd.DataFrame({"close": adj, "held": held, "switch": switch.to_numpy()}, index=idx)


# ---- 바텀업 (현재 구성종목 — 생존편향, 가정)
def bottomup_rows(raw: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    """get_data 다필드 월별 원응답(Instrument, [F.date, F]×k) → 종목·표본월 행(ric, sample_date, month, <names>...).

    행은 표본 달마다 정렬돼 온다. EPS 반환 날짜는 '마지막 변경일'이라 다음 달에도 같은 날짜로 다른 값이 온다(NTM 혼합,
    2026-10-28 실측) → 값이 알려진 시점은 표본일이다. sample_date = 행의 모든 날짜 열 중 가장 늦은 날(보수적 PIT)."""
    d = raw.copy()
    cols = ["ric"]
    for n in names:
        cols += [f"{n}_date", n]
    d = d.iloc[:, :len(cols)]
    d.columns = cols
    dates = []
    for n in names:
        d[f"{n}_date"] = pd.to_datetime(d[f"{n}_date"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
        d[n] = pd.to_numeric(d[n], errors="coerce")
        dates.append(f"{n}_date")
    d["sample_date"] = d[dates].max(axis=1)
    d = d.dropna(subset=["sample_date"])
    d["month"] = d["sample_date"].dt.to_period("M")
    return d.drop_duplicates(["ric", "month"], keep="last")[["ric", "sample_date", "month"] + names].reset_index(drop=True)


def _pivot(rows: pd.DataFrame, col: str) -> pd.DataFrame:
    return rows.pivot(index="month", columns="ric", values=col).sort_index()


def eps_up_share(rows: pd.DataFrame) -> pd.DataFrame:
    """시총가중 상향 비중 = Σ_{EPS_m > EPS_{m−1}} 시총_{m−1} ÷ Σ_{EPS_m, EPS_{m−1}, 시총_{m−1} 모두 있음} 시총_{m−1} (0~1).

    가중치는 전월 표본일 시총(그달 표본일에 이미 알려짐). date = as_of = 그달 포함 종목 표본일의 최댓값.
    가정: NTM EPS 평균의 상승을 이익수정 확산으로 본다(수정 건수 필드 불가, Phase 0). 현재 구성종목 기준 — 생존편향."""
    eps, mcap, sd = _pivot(rows, "eps"), _pivot(rows, "mcap"), _pivot(rows, "sample_date")
    full = pd.period_range(eps.index.min(), eps.index.max(), freq="M")
    eps, mcap, sd = eps.reindex(full), mcap.reindex(full), sd.reindex(full)
    prev_eps, w = eps.shift(), mcap.shift()
    ok = eps.notna() & prev_eps.notna() & w.notna() & (w > 0)
    up = (eps > prev_eps) & ok
    den = w.where(ok).sum(axis=1, min_count=1)
    num = w.where(up).sum(axis=1, min_count=1).fillna(0.0)
    share = (num / den).where(den > 0)
    asof = sd.where(ok).max(axis=1)
    out = pd.DataFrame({"date": asof, "value": share, "n": ok.sum(axis=1)}).dropna(subset=["date", "value"])
    out["as_of"] = out["date"]
    return out.reset_index(drop=True)


def aggregate_multiples(rows: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """현재 구성종목 시총가중 지수 배수(KOSPI200 바텀업, 가정: 생존편향·구성 고정).

    - fwd_per = Σ시총 ÷ Σ(시총 × EPS_NTM ÷ 주가)  (적자 종목 포함한 합산 이익 기준)
    - pbr = Σ시총 ÷ Σ(시총 ÷ PBR_i)  (PBR > 0)
    - div_yield = Σ(시총 × DY_i) ÷ Σ시총  (%, DY 있는 종목)
    - fwd_eps_12m = 같은 종목 집합(전월·당월 모두 있음)의 합산 선행이익 증가율을 연쇄한 지수(첫 달 = 100).
      주식 수는 전월 표본일 값으로 고정(시총 ÷ 주가) — 증자·자사주가 아니라 EPS 변화만 반영한다. 수준은 임의 단위이고
      변화율 지표(fwd_eps_chg_*, revision_momentum, equity_eps_momentum)에만 쓴다.
    date = as_of = 그달 해당 종목 표본일의 최댓값. 반환: field → (date, value, as_of, n)."""
    eps, mcap, px, sd = (_pivot(rows, c) for c in ("eps", "mcap", "px", "sample_date"))
    full = pd.period_range(eps.index.min(), eps.index.max(), freq="M")
    eps, mcap, px, sd = eps.reindex(full), mcap.reindex(full), px.reindex(full), sd.reindex(full)
    out = {}

    def pack(val, mask, name):
        asof = sd.where(mask).max(axis=1)
        f = pd.DataFrame({"date": asof, "value": val, "n": mask.sum(axis=1)}).dropna(subset=["date", "value"])
        f["as_of"] = f["date"]
        out[name] = f.reset_index(drop=True)

    shares = mcap / px.where(px > 0)
    earn = eps * shares
    m = earn.notna() & mcap.notna()
    den = earn.where(m).sum(axis=1, min_count=1)
    pack((mcap.where(m).sum(axis=1, min_count=1) / den).where(den > 0), m, "fwd_per")
    if "pbr" in rows.columns:
        pbr = _pivot(rows, "pbr").reindex(full)
        m2 = mcap.notna() & (pbr > 0)
        pack(mcap.where(m2).sum(axis=1, min_count=1) / (mcap / pbr).where(m2).sum(axis=1, min_count=1), m2, "pbr")
    if "dy" in rows.columns:
        dy = _pivot(rows, "dy").reindex(full)
        m3 = mcap.notna() & dy.notna()
        pack((mcap * dy).where(m3).sum(axis=1, min_count=1) / mcap.where(m3).sum(axis=1, min_count=1), m3, "div_yield")
    sh_prev = shares.shift()
    m4 = eps.notna() & eps.shift().notna() & sh_prev.notna()
    num = (eps * sh_prev).where(m4).sum(axis=1, min_count=1)
    den4 = (eps.shift() * sh_prev).where(m4).sum(axis=1, min_count=1)
    g = (num / den4).where(den4 > 0)
    # 연쇄: 성장률이 없는 달(첫 달·공백)은 수준을 이어 가되(곱 1) 그달 값은 내지 않는다. 첫 달만 기준값 100 으로 낸다.
    level = 100.0 * g.fillna(1.0).cumprod()
    first = int(np.argmax(m4.any(axis=1).to_numpy())) - 1   # 첫 성장률 달의 전월 = 기준월
    emit = g.notna().to_numpy()
    if first >= 0:
        emit[first] = True
    mask = m4.copy()
    if first >= 0:
        mask.iloc[first] = m.iloc[first]
    pack(level.where(emit), mask, "fwd_eps_12m")
    return out


def breadth(closes: pd.DataFrame, ma_short: int = 20, ma_long: int = 200, low_window: int = 252) -> pd.DataFrame:
    """구성종목 일별 종가(date × ric, 수정주가) → 시장폭 필드(date × field). 현재 구성종목 기준 — 생존편향(가정).

    - breadth_above_ma20/ma200: 종가 > 이동평균(그 종목 관측 ma 개 이상)인 종목 비율(%)
    - breadth_new_low_52w: 종가 ≤ 직전 low_window 거래일(당일 포함) 최저가인 종목 비율(%, low_window 관측 이상)
    - breadth_adv / breadth_dec: 전일 대비 상승 / 하락 종목 수
    as_of = date(장 마감 뒤)."""
    c = closes.sort_index()
    out = {}
    for name, w in (("breadth_above_ma20", ma_short), ("breadth_above_ma200", ma_long)):
        ma = c.rolling(w, min_periods=w).mean()
        ok = ma.notna() & c.notna()
        out[name] = 100.0 * (c > ma).where(ok).sum(axis=1) / ok.sum(axis=1).replace(0, np.nan)
    lo = c.rolling(low_window, min_periods=low_window).min()
    ok = lo.notna() & c.notna()
    out["breadth_new_low_52w"] = 100.0 * (c <= lo).where(ok).sum(axis=1) / ok.sum(axis=1).replace(0, np.nan)
    ch = c.diff()
    okc = ch.notna()
    n = okc.sum(axis=1)
    out["breadth_adv"] = (ch > 0).where(okc).sum(axis=1).where(n > 0)
    out["breadth_dec"] = (ch < 0).where(okc).sum(axis=1).where(n > 0)
    return pd.DataFrame(out)


# ---- 금(COMEX GC) 연속물 — 사용자 결정 2026-10-28 B
GC_ACTIVE_MONTHS = (2, 4, 6, 8, 10, 12)   # G J M Q V Z


def _bday_calendar(trading_days: pd.DatetimeIndex, until: pd.Timestamp) -> pd.DatetimeIndex:
    """관측 거래일 + 관측 끝 이후는 평일(미래 만기 계산용). 가정: 휴장 달력 = 관측 거래일."""
    td = pd.DatetimeIndex(sorted(set(pd.DatetimeIndex(trading_days).normalize())))
    future = pd.bdate_range(td.max() + pd.Timedelta(days=1), until)
    return td.append(future)


def gc_c1_month(dates: pd.DatetimeIndex, cal: pd.DatetimeIndex) -> pd.Series:
    """Refinitiv `GCc1` 의 계약월 = 그달 계약의 최종거래일(그달 끝에서 3번째 영업일) 이전이면 그달, 이후면 다음 달.
    GCc1..c4 는 연속한 4개 달이다(COMEX 는 가까운 연속 월물을 상장). 근거: GCc1 = 'GOLD OCT26', EXPIR_DATE 2026-10-28
    (2026-10-28 조회), c1/c2 스프레드가 매달 이 규칙의 교체일에 튄다(검증: gc_roll_check)."""
    cal = pd.DatetimeIndex(cal)
    by_m = pd.Series(cal, index=cal.to_period("M")).groupby(level=0).apply(lambda s: s.iloc[-3] if len(s) >= 3 else s.iloc[0])
    out = []
    for t in pd.DatetimeIndex(dates):
        m = t.to_period("M")
        out.append(m if t <= by_m[m] else m + 1)
    return pd.Series(out, index=pd.DatetimeIndex(dates))


def gc_held_month(dates: pd.DatetimeIndex, cal: pd.DatetimeIndex, early_days: int = 5) -> pd.Series:
    """보유 활성월물: 활성월(G J M Q V Z) A 를 첫 통지일(FND = A 전월 마지막 영업일)의 early_days 영업일 전까지 들고,
    그날 다음 활성월로 갈아탄다(가정: 5영업일 전 — WTI 와 같은 간격)."""
    cal = pd.DatetimeIndex(cal)
    last_bd = pd.Series(cal, index=cal.to_period("M")).groupby(level=0).max()
    pos = {d: i for i, d in enumerate(cal)}
    switch = {}
    for m in last_bd.index:
        a = m + 1
        if a.month in GC_ACTIVE_MONTHS:
            fnd = last_bd[m]
            switch[a] = cal[max(pos[fnd] - early_days, 0)]
    actives = sorted(switch)
    out = []
    for t in pd.DatetimeIndex(dates):
        out.append(next(a for a in actives if t < switch[a]))
    return pd.Series(out, index=pd.DatetimeIndex(dates))


def continuous_from_nearbys(near: pd.DataFrame, c1_month: pd.Series, held: pd.Series) -> pd.DataFrame:
    """연속 월물 c1..cN(열 1..N)과 c1 계약월·보유 계약월로 같은 계약끼리의 수익률을 이어 붙인 비율 백어저스트 연속물.

    수익률_t = P_X(t) / P_X(t−1), X = t 의 보유 계약, P_X(s) = c_k(s), k = (X − c1월(s)) + 1. 마지막 값 = 보유 계약 실제 가격.
    보유 계약이 c1..cN 밖이면 그날 값은 NaN(가정 위반 표시)."""
    near = near.sort_index()
    idx = near.index
    c1m = c1_month.reindex(idx)
    hm = held.reindex(idx)

    def price(i, X):
        k = (X - c1m.iloc[i]).n + 1
        return near.iloc[i][k] if 1 <= k <= near.shape[1] else np.nan

    held_px = np.array([price(i, hm.iloc[i]) for i in range(len(idx))], dtype=float)
    ret = np.full(len(idx), np.nan)
    for i in range(1, len(idx)):
        ret[i] = held_px[i] / price(i - 1, hm.iloc[i])
    adj = np.full(len(idx), np.nan)
    adj[-1] = held_px[-1]
    for i in range(len(idx) - 1, 0, -1):
        adj[i - 1] = adj[i] / ret[i] if np.isfinite(ret[i]) and ret[i] > 0 else np.nan
    switch = (hm != hm.shift()).to_numpy()
    switch[0] = False
    return pd.DataFrame({"close": adj, "held": held_px, "held_month": hm.astype(str).to_numpy(), "switch": switch},
                        index=idx)


# ---- KOSPI200 이익 지표 민감도(사용자 결정 2026-10-28 C — Phase 3 비교용, 주 점수에 쓰지 않음)
def equal_weight_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """바텀업 행의 시총을 1 로 바꾼다 → aggregate_multiples·eps_up_share 가 동일가중이 된다.
    PER = 1/평균(EPS/주가), EPS 지수 = 종목당 같은 금액을 들고 있을 때의 이익 증가율, 상향 비중 = 종목 수 비중."""
    out = rows.copy()
    out["mcap"] = np.where(out["mcap"].notna(), 1.0, np.nan)
    return out


def exclude_rows(rows: pd.DataFrame, rics: list[str]) -> pd.DataFrame:
    """특정 종목(예: 삼성전자·SK하이닉스)을 뺀 바텀업 행."""
    return rows[~rows["ric"].isin(rics)].reset_index(drop=True)
