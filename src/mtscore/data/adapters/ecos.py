"""한국은행 ECOS 어댑터 — StatisticSearch 를 10건씩 페이징한다.

- 키: 환경변수 `ECOS_API_KEY`, 없으면 `sample`(1회 10건 제한, 페이징으로 전량 수집 — ~/.claude/reference/bok-ecos/README.md).
  키 값은 로그·파일에 남기지 않는다(원자료 캐시는 행만 저장한다).
- 항목코드 함정(CLAUDE.md): `731Y005/0000003` 은 달러/유로, `817Y002/010230000` 은 국고채 30년.
- 원자료 캐시: raw_dir/<표>_<주기>_<항목>_<시작>_<끝>.csv. 값은 최신 수정치다(가정).

as_of 규칙(AS_OF_RULES, 가정):
- 901Y009(소비자물가, 월): date = 기준월 1일 → as_of = 다음 달 5일(한국 CPI 는 익월 초 공표, 사용자 결정 2026-10-28 기본값).
- 301Y013(국제수지, 월): date = 기준월 1일 → as_of = 2개월 뒤 10일(8월분이 10월 초 공표 — 약 1개월+ 지연, 가정).
- 일별(817Y002 금리·731Y001 환율): as_of = date.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from pandas.tseries.offsets import DateOffset

from .base import BaseAdapter

URL = "https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/{a}/{b}/{table}/{freq}/{start}/{end}/{item}"
PAGE = 10

AS_OF_RULES = {
    "901Y009": lambda d: d + DateOffset(months=1, days=4),
    "301Y013": lambda d: d + DateOffset(months=2, days=9),
    "817Y002": lambda d: d,
    "731Y001": lambda d: d,
    "722Y001": lambda d: d,
}


class EcosError(RuntimeError):
    """ECOS 가 RESULT 오류를 돌려줬을 때."""


def parse_rows(rows: list[dict], freq: str) -> pd.DataFrame:
    """StatisticSearch row 목록 → (date, value). 월별 TIME=YYYYMM → 그 달 1일, 일별 YYYYMMDD."""
    if not rows:
        return pd.DataFrame(columns=["date", "value"])
    d = pd.DataFrame(rows)
    fmt = {"M": "%Y%m", "D": "%Y%m%d"}[freq]
    out = pd.DataFrame({"date": pd.to_datetime(d["TIME"].astype(str), format=fmt),
                        "value": pd.to_numeric(d["DATA_VALUE"], errors="coerce")})
    return out.dropna().drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def _get(url: str, timeout: int = 40) -> dict:
    import time

    import requests

    for k in range(4):
        try:
            j = requests.get(url, timeout=timeout).json()
            break
        except requests.RequestException:
            if k == 3:
                raise
            time.sleep(5 * (k + 1))
    if "StatisticSearch" not in j:
        raise EcosError(str(j.get("RESULT", j))[:200])
    return j["StatisticSearch"]


def download(table: str, freq: str, start: str, end: str, item: str, raw_dir: Path, refresh: bool = False) -> Path:
    """전 구간을 10건씩 페이징해 raw_dir 에 CSV 로 저장한다(있으면 재사용)."""
    raw_dir = Path(raw_dir)
    p = raw_dir / f"{table}_{freq}_{item}_{start}_{end}.csv"
    if p.exists() and not refresh:
        return p
    key = os.environ.get("ECOS_API_KEY") or "sample"
    first = _get(URL.format(key=key, a=1, b=PAGE, table=table, freq=freq, start=start, end=end, item=item))
    total = int(first["list_total_count"])
    rows = list(first["row"])
    for a in range(PAGE + 1, total + 1, PAGE):
        rows += _get(URL.format(key=key, a=a, b=min(a + PAGE - 1, total), table=table, freq=freq, start=start,
                                end=end, item=item))["row"]
    if len(rows) != total:
        raise EcosError(f"{table}/{item}: 받은 행 {len(rows)} ≠ list_total_count {total}")
    raw_dir.mkdir(parents=True, exist_ok=True)
    cols = ["STAT_CODE", "ITEM_CODE1", "ITEM_NAME1", "UNIT_NAME", "TIME", "DATA_VALUE"]
    pd.DataFrame(rows)[[c for c in cols if c in rows[0]]].to_csv(p, index=False)
    return p


def read_raw(p: Path, freq: str) -> pd.DataFrame:
    d = pd.read_csv(p, dtype={"TIME": str})
    return parse_rows(d.to_dict("records"), freq)


class EcosAdapter(BaseAdapter):
    """mapping: {(asset_id, field): (table, freq, start, end, item)}. 캐시가 없으면 내려받는다."""

    source_name = "ecos"

    def __init__(self, mapping: dict, raw_dir: Path, download: bool = True):
        self.mapping = mapping
        self.raw_dir = Path(raw_dir)
        self.download = download

    def _fetch(self, asset, fields, start, end):
        parts = []
        for f in fields:
            spec = self.mapping.get((asset, f))
            if spec is None:
                continue
            table, freq, s, e, item = spec
            p = (download(table, freq, s, e, item, self.raw_dir) if self.download
                 else self.raw_dir / f"{table}_{freq}_{item}_{s}_{e}.csv")
            d = read_raw(p, freq)
            if start is not None:
                d = d[d["date"] >= pd.Timestamp(start)]
            if end is not None:
                d = d[d["date"] <= pd.Timestamp(end)]
            parts.append(pd.DataFrame({"date": d["date"], "asset_id": asset, "field": f, "value": d["value"],
                                       "as_of": AS_OF_RULES[table](pd.DatetimeIndex(d["date"])),
                                       "source": f"ecos:{table}/{item}"}))
        if not parts:
            return pd.DataFrame(columns=["date", "asset_id", "field", "value", "as_of", "source"])
        return pd.concat(parts, ignore_index=True)
