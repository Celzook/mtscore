"""S&P500 CAPE 분모(10년 평균 실질 이익) — Shiller 이익 + ALFRED CPI 최초 공표값 (사전 등록 D-1, 2026-10-29).

데이터 층의 파생 필드다. 결과는 4-1 패널 행(date, value, as_of)이 되어 validate_panel 을 통과한 뒤 엔진에 들어가고,
지표 `cape` 는 기존 계산 함수 `ratio`(close ÷ 이 필드)로 만든다.

정의(docs/prereg_2026-10-29.md §D-1)
- CAPE_t = .SPX 일별 종가_t ÷ 120개월 평균 실질 이익
- 실질 이익_m = Shiller as-reported E_m × (CPI_기준 ÷ CPI_m), CPI 는 ALFRED CPIAUCSL 최초 공표값(as_of = 공표일)
- PIT: t 에 쓰는 E 의 마지막 월 = t 의 달 − 4개월 → E_m 의 as_of = (m + 4개월) 1일
- CPI_기준 = t 에 알려진 최신 CPI(as_of ≤ t 인 최초 공표값 중 기준월이 가장 늦은 것).
  Shiller 의 CAPE 는 가격·이익을 같은 기준 CPI 로 실질화하므로 기준 CPI 가 약분된다(P_t/CPI_t ÷ 평균(E_m/CPI_m)).
  여기서 분자는 명목 종가이므로 분모에 CPI_기준을 곱해야 같은 식이 된다 — 즉 '가격을 t 에 알려진 최신 CPI 로
  실질화'한 것과 같다. 기준 CPI 를 t 마다 다르게 고르면 수준이 바뀌므로 CPI_기준 은 반드시 t 의 최신 공표값 하나로 고정한다.
- 120개월이 모두 있어야 값을 낸다(E·CPI 중 하나라도 없으면 그 시점은 값 없음). 채우지 않는다.

가정
- Shiller E 이력은 최근 몇 달만 수정된다(2023-09판·2026-10판 대조: 2023.04~06 만 −0.03~−0.09%, 빈티지 2개).
  최신판 하나의 값을 과거 시점에도 쓴다 — 4개월 규칙 밖의 수정은 반영하지 못한다.
- Shiller 의 최근 몇 달 E 는 분기 이익을 월로 보간한 값이다(Shiller 원자료 설명).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

E_LAG_MONTHS = 4      # 사전 등록 D-1: t 에 쓰는 E 의 마지막 월 = t 의 달 − 4
WINDOW_MONTHS = 120   # 10년


def parse_shiller_csv(path) -> pd.DataFrame:
    """scripts/phase4d_shiller_to_csv.py 가 만든 CSV → DataFrame(month, P, D, E, CPI, CAPE). 빈 칸은 NaN 그대로."""
    d = pd.read_csv(path)
    d["month"] = pd.to_datetime(d["month"])
    return d


def e_pit(shiller: pd.DataFrame, lag_months: int = E_LAG_MONTHS) -> pd.DataFrame:
    """월별 E → (date = 기준월 1일, value = E, as_of = 기준월 + lag_months 의 1일). E 가 없는 달은 버린다."""
    d = shiller.dropna(subset=["E"]).sort_values("month")
    return pd.DataFrame({"date": d["month"].values, "value": d["E"].astype(float).values,
                         "as_of": (d["month"] + pd.DateOffset(months=lag_months)).values}).reset_index(drop=True)


def real_e10(e: pd.DataFrame, cpi: pd.DataFrame, window: int = WINDOW_MONTHS, skip_missing: bool = False) -> pd.DataFrame:
    """CAPE 분모 = CPI_기준 × mean_{최근 window 개월}(E_m / CPI_m), 사건일(E·CPI 의 as_of)마다 한 행.

    e:   (date = 기준월 1일, value, as_of) — e_pit 결과
    cpi: (date = 기준월 1일, value, as_of) — 최초 공표값(ALFRED first_releases)
    반환: (date = as_of = 사건일, value). 사건일 t 에 as_of ≤ t 인 행만 쓴다.
      - E 창: 알려진 E 중 기준월이 가장 늦은 달부터 거꾸로 window 개월(달이 비면 값 없음)
      - CPI_m: 창의 각 달 m 의 CPI 중 as_of ≤ t 인 것(없으면 값 없음)
      - CPI_기준: as_of ≤ t 인 CPI 중 기준월이 가장 늦은 것의 값
    skip_missing: 민감도 전용(사전 등록 정의 아님). 참이면 창을 '달력 120개월' 대신 'E·CPI 가 모두 있는 최근 120개월'로
      잡는다(빠진 달은 건너뛰고 더 과거 달로 채운다 — 값을 만들어 넣지는 않는다). 반환에 창의 달력 길이(span_months)를 붙인다.
    """
    e = e.dropna(subset=["value"]).sort_values(["as_of", "date"])
    c = cpi.dropna(subset=["value"]).sort_values(["as_of", "date"])
    events = pd.DatetimeIndex(sorted(set(e["as_of"]) | set(c["as_of"])))
    rows = []
    for t in events:
        ek = e[e["as_of"] <= t].drop_duplicates("date", keep="last").set_index("date")["value"]
        ck = c[c["as_of"] <= t].drop_duplicates("date", keep="last").set_index("date")["value"]
        if ek.empty or ck.empty:
            continue
        last = ek.index.max()
        if skip_missing:
            both = pd.concat([ek, ck], axis=1, keys=["e", "c"]).loc[:last].dropna().tail(window)
            if len(both) < window:
                continue
            ev, cv = both["e"], both["c"]
            span = (last.year - both.index[0].year) * 12 + last.month - both.index[0].month + 1
        else:
            months = pd.date_range(end=last, periods=window, freq="MS")
            ev = ek.reindex(months)
            cv = ck.reindex(months)
            if ev.isna().any() or cv.isna().any():
                continue
            span = window
        ref = float(ck.loc[ck.index.max()])
        rows.append((t, ref * float(np.mean(ev.to_numpy() / cv.to_numpy())), span))
    out = pd.DataFrame(rows, columns=["date", "value", "span_months"])
    out["as_of"] = out["date"]
    return out if skip_missing else out.drop(columns="span_months")
