"""KOSPI200 바텀업 CAPE(Phase 4 D-2) — 민감도 필드 `cape_bu` 전용 순수 함수. 점수(프로파일)에는 쓰지 않는다.

정의(사전 등록 docs/prereg_2026-10-29.md §D-2, 구성 선택은 가정):
- 종목 집합: 현재 KODEX200 보유종목 중 결산일이 `max_first_year`(2003) 이하인 연간 지배주주 순이익이 있는 종목(고정).
  가정: 생존편향(현재 구성종목만).
- CAPE_t = Σ_i 시총_i,t ÷ Σ_i E10_i,t. i 는 t 에 시총이 있고 10개 연도 창이 성립하는 집합 종목(분자·분모 같은 종목).
- E10_i,t = t 에 알려진 최근 `window`개 연간 실질 지배주주 순이익의 평균.
  실질 = 순이익 × CPI_t ÷ CPI_FY. CPI_FY = 결산월까지 12개월 평균, CPI_t = t 에 공표된 최신값(ECOS as_of 규칙).
- 가용일(PIT) = max(결산일 + `lag_days`(90, 사업보고서 법정 기한, 가정), 공시일).
  공시일 = Refinitiv 원 공표일(결산일 + `ann_cap_days` 이내일 때만), 없으면 I/B/E/S 실적 반환 날짜(같은 상한), 둘 다 없으면 결산일 + 90일.
- 창 요건: 연간 보고 `window`개가 모두 있어야 한다. 결산일 변경(3월→12월 등)으로 빠진 전환기는 건너뛰므로
  가장 오래된 결산일과 최신 결산일의 차가 `max_span_days`(3960일 ≈ 10년 10개월) 이내여야 한다
  (가정: 빠진 전환기 1개 + 결산월 이동 9개월까지 허용, 예 2012-03 → 2014-12 는 10년 9개월).
  최신 결산일이 t 보다 `stale_days` 넘게 오래되면 그 종목은 t 에 빠진다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ROW_COLS = ["ric", "pe", "ni", "ann", "ibes_date"]


def _ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce", utc=True).dt.tz_localize(None)


def parse_fiscal(ni_raw: pd.DataFrame, eps_raw: pd.DataFrame | None = None) -> pd.DataFrame:
    """Refinitiv 원응답 → 연간 행(ric, pe, ni, ann, ibes_date).

    ni_raw 열: Instrument, Period End Date, Original Announcement Date Time, NI after Minority Interest[, NI after Tax].
    eps_raw 열: Instrument, Period End Date, Date(I/B/E/S 실적 반환 날짜), EPS Actual.
    ni = 지배주주 순이익만 쓴다(총 순이익으로 대체하지 않는다). 결측 행은 버린다."""
    d = ni_raw.iloc[:, :4].copy()
    d.columns = ["ric", "pe", "ann", "ni"]
    d["pe"] = _ts(d["pe"]).dt.normalize()
    d["ann"] = _ts(d["ann"])
    d["ni"] = pd.to_numeric(d["ni"], errors="coerce")
    d = d.dropna(subset=["pe", "ni"]).drop_duplicates(["ric", "pe"], keep="first")
    if eps_raw is not None and len(eps_raw):
        e = eps_raw.iloc[:, :3].copy()
        e.columns = ["ric", "pe", "ibes_date"]
        e["pe"] = _ts(e["pe"]).dt.normalize()
        e["ibes_date"] = _ts(e["ibes_date"])
        e = e.dropna(subset=["pe"]).drop_duplicates(["ric", "pe"], keep="first")
        d = d.merge(e, on=["ric", "pe"], how="left")
    else:
        d["ibes_date"] = pd.NaT
    return d[ROW_COLS].sort_values(["ric", "pe"]).reset_index(drop=True)


def fixed_set(fiscal: pd.DataFrame, max_first_year: int = 2003) -> list[str]:
    """첫 연간 지배주주 순이익의 결산 연도 ≤ max_first_year 인 종목(고정 집합)."""
    first = fiscal.groupby("ric")["pe"].min()
    return sorted(first[first.dt.year <= max_first_year].index)


def available_date(fiscal: pd.DataFrame, lag_days: int = 90, ann_cap_days: int = 365) -> pd.DataFrame:
    """가용일 열(avail)과 쓰인 공시일 출처(avail_src: ann·ibes·lag_only)를 붙인다."""
    d = fiscal.copy()
    cap = pd.Timedelta(days=ann_cap_days)
    ok_ann = d["ann"].notna() & (d["ann"] - d["pe"] <= cap) & (d["ann"] >= d["pe"])
    ok_ibes = d["ibes_date"].notna() & (d["ibes_date"] - d["pe"] <= cap) & (d["ibes_date"] >= d["pe"])
    # 공시 시각(UTC)이 있으므로 그다음 날부터 쓴다(보수적: 한국 시각 다음 날 새벽 공시도 막는다)
    filing = (d["ann"].where(ok_ann, d["ibes_date"].where(ok_ibes)) + pd.Timedelta(days=1)).dt.normalize()
    d["avail_src"] = np.where(ok_ann, "ann", np.where(ok_ibes, "ibes", "lag_only"))
    floor = d["pe"] + pd.Timedelta(days=lag_days)
    d["avail"] = filing.where(filing > floor, floor)   # 공시일 결측(NaT 비교 거짓)이면 결산일 + lag_days
    return d


def cpi_fy_avg(cpi: pd.DataFrame, pe: pd.Timestamp, asof: pd.Timestamp) -> float:
    """결산월까지 12개월 CPI 평균(그 12개월이 모두 asof 까지 공표돼 있어야 한다, 아니면 NaN). cpi: date(월 1일)·value·as_of."""
    end = pe.to_period("M").to_timestamp()
    months = pd.date_range(end - pd.DateOffset(months=11), end, freq="MS")
    c = cpi[cpi["date"].isin(months) & (cpi["as_of"] <= asof)]
    return float(c["value"].mean()) if len(c) == 12 else np.nan


def member_e10(rows: pd.DataFrame, cpi: pd.DataFrame, asof: pd.Timestamp, cpi_now: float, window: int = 10,
               max_span_days: int = 3960, stale_days: int = 730) -> float:
    """한 종목의 asof 시점 E10(실질, CPI_now 기준 원화). 창이 성립하지 않으면 NaN. rows 는 available_date 결과의 한 종목분."""
    r = rows[rows["avail"] <= asof].sort_values("pe").tail(window)
    if len(r) < window:
        return np.nan
    if (r["pe"].iloc[-1] - r["pe"].iloc[0]).days > max_span_days or (asof - r["pe"].iloc[-1]).days > stale_days:
        return np.nan
    defl = np.array([cpi_fy_avg(cpi, p, asof) for p in r["pe"]])
    if not np.isfinite(defl).all():
        return np.nan
    return float(np.mean(r["ni"].to_numpy() * cpi_now / defl))


def cape_bottomup(fiscal: pd.DataFrame, mcap: pd.DataFrame, cpi: pd.DataFrame, members: list[str], window: int = 10,
                  lag_days: int = 90, ann_cap_days: int = 365, max_span_days: int = 3960,
                  stale_days: int = 730, min_share: float = 0.9) -> pd.DataFrame:
    """월별 바텀업 CAPE.

    mcap: ric·date(표본일, 월말)·mcap. 월마다 표본일 = 그달 집합 종목 표본일의 최댓값 = as_of.
    min_share: 창이 성립한 종목의 시총이 그달 시총 있는 집합 종목 시총의 이 비율 미만이면 값은 NaN(가정: 고정 집합의
    대부분이 들어올 때만 집합 CAPE 로 본다 — 초기 몇 개 종목만의 값 방지).
    cpi: date·value·as_of. Returns 열 date·value·as_of·n_listed(시총 있는 집합 종목)·n_used·mcap_share_used(시총 기준
    사용 비중)·pe_ratio_trailing(같은 종목의 Σ시총 ÷ Σ최근 연간 명목 순이익, 크기 점검용)."""
    fa = available_date(fiscal[fiscal["ric"].isin(members)], lag_days, ann_cap_days)
    by_ric = {r: g for r, g in fa.groupby("ric")}
    m = mcap[mcap["ric"].isin(members)].dropna(subset=["mcap"]).copy()
    m["month"] = m["date"].dt.to_period("M")
    out = []
    for month, g in m.groupby("month"):
        asof = g["date"].max()
        known = cpi[cpi["as_of"] <= asof]
        if known.empty:
            continue
        cpi_now = float(known.sort_values("date")["value"].iloc[-1])
        num = den = mc_all = last_ni = 0.0
        n_used = 0
        for ric, mc in zip(g["ric"], g["mcap"]):
            mc_all += mc
            rows = by_ric.get(ric)
            if rows is None:
                continue
            e10 = member_e10(rows, cpi, asof, cpi_now, window, max_span_days, stale_days)
            if not np.isfinite(e10):
                continue
            num += mc
            den += e10
            last_ni += float(rows[rows["avail"] <= asof].sort_values("pe")["ni"].iloc[-1])
            n_used += 1
        share = num / mc_all if mc_all else np.nan
        ok = n_used > 0 and den > 0 and share >= min_share
        out.append({"date": asof, "value": num / den if ok else np.nan, "as_of": asof,
                    "n_listed": int(len(g)), "n_used": n_used, "mcap_share_used": share,
                    "pe_ratio_trailing": num / last_ni if n_used and last_ni > 0 else np.nan})
    return pd.DataFrame(out)
