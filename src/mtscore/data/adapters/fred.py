"""FRED 어댑터 — 키 없이 fredgraph CSV 를 받는다(데이터 소스 함정: CLAUDE.md).

- `User-Agent: curl/8` 로 요청한다(브라우저 UA 는 응답 없이 끊긴다). requests 는 IPv4 강제(이 PC 에서 IPv6 시도가 timeout).
- 응답이 `<!DOCTYPE`/`<html` 로 시작하면 HTML(시리즈 중단·ID 오류)이므로 거부한다.
- 원자료는 `raw_dir/<SERIES>.csv` 에 캐시한다. 값은 최신 빈티지(수정치)다 — 공표 당시 값이 아니다(가정).

as_of 규칙(AS_OF_RULES, 달력일 기준. 확인하지 않은 것은 가정):
- 일별 시장값(VIXCLS·VXVCLS·DCOILWTICO·BAML*): as_of = date.
- H.15 계열(DGS10·DFII10·DFF): as_of = date + 1 미국 영업일(US_BDAY: 연방 공휴일·성금요일 제외, 다음 날 공표, 가정).
- THREEFYTP10·NFCI·CPIAUCSL: 패널에는 ALFRED 최초 공표값(as_of = 공표일)을 쓴다(사용자 결정 2026-10-28 E·F,
  alfred_download / first_releases). 아래 규칙은 최신 빈티지를 쓸 때의 근사(대조용)다.
- THREEFYTP10(Kim-Wright): as_of = date + 10일(근사).
- NFCI: date 는 주 마지막 금요일, 다음 수요일 공표 → as_of = date + 5일(근사).
- CPIAUCSL: date 는 기준월 1일 → as_of = 다음 달 1일 + 14일(근사).
- RBKRBIS(BIS REER): date 는 기준월 1일 → as_of = date + 3개월(약 3개월 지연, 가정).
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.tseries.holiday import GoodFriday, USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay, DateOffset, MonthBegin

from .base import BaseAdapter

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
# 미국 영업일: 연방 공휴일 + 성금요일(채권시장 휴장 근사, 가정). 정부 셧다운 공표 지연은 반영하지 못한다(가정).
_US_HOLIDAYS = USFederalHolidayCalendar().holidays("1990-01-01", "2030-12-31").union(
    GoodFriday.dates("1990-01-01", "2030-12-31"))
US_BDAY = CustomBusinessDay(holidays=_US_HOLIDAYS)
_US_HOL_D = _US_HOLIDAYS.values.astype("datetime64[D]")


def next_us_bday(d) -> pd.DatetimeIndex:
    """다음 미국 영업일(벡터화). 주말·공휴일 기준일은 직전 영업일로 당긴 뒤 하루 더한다(토요일 → 월요일)."""
    v = pd.DatetimeIndex(d).values.astype("datetime64[D]")
    return pd.DatetimeIndex(np.busday_offset(v, 1, roll="backward", holidays=_US_HOL_D))


def _same(d: pd.Series) -> pd.Series:
    return d


AS_OF_RULES = {
    "VIXCLS": _same, "VXVCLS": _same, "DCOILWTICO": _same, "BAMLH0A0HYM2": _same, "BAMLC0A0CM": _same,
    "DEXKOUS": next_us_bday, "DGS10": next_us_bday, "DFII10": next_us_bday, "DFF": next_us_bday,
    "THREEFYTP10": lambda d: d + pd.Timedelta(days=10),
    "NFCI": lambda d: d + pd.Timedelta(days=5),
    "CPIAUCSL": lambda d: d + MonthBegin(1) + pd.Timedelta(days=14),
    "RBKRBIS": lambda d: d + DateOffset(months=3),
}


class FredHtmlError(ValueError):
    """fredgraph 가 CSV 대신 HTML 을 돌려줬을 때."""


def parse_fredgraph(text: str, sid: str) -> pd.DataFrame:
    """fredgraph CSV 텍스트 → (date, value). '.' 결측은 버린다. HTML 이면 FredHtmlError."""
    head = text.lstrip()[:200].lower()
    if head.startswith("<!doctype") or head.startswith("<html"):
        raise FredHtmlError(f"{sid}: fredgraph 가 HTML 을 돌려줌(시리즈 중단 또는 ID 오류)")
    d = pd.read_csv(io.StringIO(text))
    d = d.iloc[:, :2]
    d.columns = ["date", "value"]
    d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    return d.dropna().reset_index(drop=True)


def as_of_for(sid: str, dates: pd.Series) -> pd.Series:
    if sid not in AS_OF_RULES:
        raise KeyError(f"{sid}: as_of 규칙 미정(AS_OF_RULES 에 추가할 것)")
    return pd.Series(AS_OF_RULES[sid](pd.DatetimeIndex(dates)), index=dates.index)


def download(sid: str, raw_dir: Path, refresh: bool = False, timeout: int = 60) -> Path:
    """fredgraph CSV 를 raw_dir/<sid>.csv 로 저장(있으면 재사용). HTML 이면 저장하지 않고 FredHtmlError."""
    import requests
    import urllib3.util.connection as uc

    raw_dir = Path(raw_dir)
    p = raw_dir / f"{sid}.csv"
    if p.exists() and not refresh:
        return p
    uc.HAS_IPV6 = False
    r = requests.get(URL.format(sid=sid), headers={"User-Agent": "curl/8"}, timeout=timeout)
    r.raise_for_status()
    parse_fredgraph(r.text, sid)   # 검증(HTML 거부)
    raw_dir.mkdir(parents=True, exist_ok=True)
    p.write_text(r.text, encoding="utf-8")
    return p


class FredAdapter(BaseAdapter):
    """mapping: {(asset_id, field): series_id}. 캐시가 없으면 내려받는다(download=False 면 캐시만 읽는다)."""

    source_name = "fred"

    def __init__(self, mapping: dict, raw_dir: Path, download: bool = True):
        self.mapping = mapping
        self.raw_dir = Path(raw_dir)
        self.download = download

    def _fetch(self, asset, fields, start, end):
        parts = []
        for f in fields:
            sid = self.mapping.get((asset, f))
            if sid is None:
                continue
            p = download(sid, self.raw_dir) if self.download else self.raw_dir / f"{sid}.csv"
            d = parse_fredgraph(p.read_text(encoding="utf-8"), sid)
            if start is not None:
                d = d[d["date"] >= pd.Timestamp(start)]
            if end is not None:
                d = d[d["date"] <= pd.Timestamp(end)]
            parts.append(pd.DataFrame({"date": d["date"], "asset_id": asset, "field": f, "value": d["value"],
                                       "as_of": as_of_for(sid, d["date"]), "source": f"fred:{sid}"}))
        if not parts:
            return pd.DataFrame(columns=["date", "asset_id", "field", "value", "as_of", "source"])
        return pd.concat(parts, ignore_index=True)


# ---- ALFRED(빈티지) — 키 없이 alfredgraph.csv?id=..&vintage_date=.. (2026-10-28 실측: 여러 빈티지를 열로 한 번에 받는다)
ALFRED_URL = "https://alfred.stlouisfed.org/graph/alfredgraph.csv"


def alfred_download(sid: str, start: str, end: str, raw_dir: Path, lookback_days: int, per_req: int = 12) -> list[Path]:
    """start~end 의 모든 평일을 빈티지 날짜로 받아 raw_dir/alfred/<sid>/<첫날>_<끝날>.csv 에 캐시한다(재개 가능).

    각 요청은 빈티지 per_req 개를 열로 받고(alfredgraph 는 한 요청에 12열까지만 준다 — 40개를 보내면 앞 12개만 온다, 2026-10-28 실측), 관측 구간은 (묶음 첫날 − lookback_days) 이후로 자른다.
    공표 지연이 lookback_days 보다 긴 관측은 놓친다 → first_releases 의 지연 분포로 확인한다."""
    import urllib3.util.connection as uc

    uc.HAS_IPV6 = False
    out_dir = Path(raw_dir) / "alfred" / sid
    out_dir.mkdir(parents=True, exist_ok=True)
    days = pd.bdate_range(start, end)
    paths = []
    for i in range(0, len(days), per_req):
        chunk = days[i:i + per_req]
        p = out_dir / f"{chunk[0]:%Y%m%d}_{chunk[-1]:%Y%m%d}.csv"
        paths.append(p)
        if p.exists():
            continue
        cosd = (chunk[0] - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        text = _alfred_get(sid, list(chunk), cosd)
        if text is None:   # 404: 묶음 안에 시리즈 첫 빈티지 이전 날짜가 있다 → 하루씩 받고 404 인 날은 빈티지 없음
            parts = [t for t in (_alfred_get(sid, [d], cosd) for d in chunk) if t is not None]
            frames = [pd.read_csv(io.StringIO(t)) for t in parts]
            text = (pd.concat([f.set_index(f.columns[0]) for f in frames], axis=1).reset_index().to_csv(index=False)
                    if frames else "observation_date\n")
        p.write_text(text, encoding="utf-8")
    return paths


def _alfred_get(sid: str, days: list, cosd: str) -> str | None:
    """빈티지 날짜 목록을 한 요청으로 받는다. 404(그 날짜에 빈티지 없음)면 None."""
    import time

    import requests

    n = len(days)
    params = {"id": ",".join([sid] * n), "vintage_date": ",".join(f"{d:%Y-%m-%d}" for d in days),
              "cosd": ",".join([cosd] * n)}
    for k in range(4):
        try:
            r = requests.get(ALFRED_URL, params=params, headers={"User-Agent": "curl/8"}, timeout=90)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            parse_fredgraph(r.text, sid)   # HTML 거부
            ncol = len(r.text.split("\n", 1)[0].split(",")) - 1
            if ncol != n:
                raise RuntimeError(f"ALFRED {sid}: 빈티지 {n}개 요청에 {ncol}열 응답")
            return r.text
        except Exception:  # noqa: BLE001
            if k == 3:
                raise
            time.sleep(5 * (k + 1))


def parse_alfred(text: str) -> pd.DataFrame:
    """alfredgraph 다빈티지 CSV → long (vintage, date, value). 열 이름 <SID>_<YYYYMMDD> 가 빈티지 날짜다."""
    head = text.lstrip()[:200].lower()
    if head.startswith("<!doctype") or head.startswith("<html"):
        raise FredHtmlError("alfredgraph 가 HTML 을 돌려줌")
    d = pd.read_csv(io.StringIO(text))
    d = d.rename(columns={d.columns[0]: "date"})
    if d.shape[1] < 2:
        return pd.DataFrame(columns=["vintage", "date", "value"])
    long = d.melt(id_vars="date", var_name="col", value_name="value")
    long["vintage"] = pd.to_datetime(long["col"].str.rsplit("_", n=1).str[-1], format="%Y%m%d")
    long["date"] = pd.to_datetime(long["date"]).dt.normalize()
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    return long.dropna(subset=["value"])[["vintage", "date", "value"]]


def first_releases(long: pd.DataFrame, max_lag_days: int | None = None) -> pd.DataFrame:
    """빈티지 long → 관측별 최초 공표값 (date, value, as_of = 최초로 그 관측이 나온 빈티지 날짜).

    첫 표본 빈티지에 이미 있던 과거 관측은 그때 처음 공표된 것이 아니다(실시간 값 없음). 그중 가장 최근 관측 하나만
    남기고 나머지는 버린다 — 수정치로 과거를 채우지 않는다(사용자 결정 2026-10-28 F). 그 이전 구간은 N/A.
    max_lag_days: 수집 창 길이(alfred_download 의 lookback_days). 이보다 늦은 '최초' 출현은 버린다."""
    x = long.sort_values(["date", "vintage"])
    fr = x.drop_duplicates("date", keep="first")
    if max_lag_days is not None:
        # 수집 창(lookback)보다 늦게 '처음' 나타난 관측은 공표가 아니라 창 밖 과거가 섞여 온 것이다(한 요청이 cosd 를
        # 무시하고 1947년부터 준 사례, 2026-10-28) → 버린다
        fr = fr[(fr["vintage"] - fr["date"]).dt.days <= max_lag_days]
    v0 = long["vintage"].min()
    backlog = fr[fr["vintage"] == v0]
    keep = fr[(fr["vintage"] != v0) | (fr["date"] == backlog["date"].max())]
    return pd.DataFrame({"date": keep["date"].values, "value": keep["value"].values,
                         "as_of": keep["vintage"].values}).sort_values("date").reset_index(drop=True)
