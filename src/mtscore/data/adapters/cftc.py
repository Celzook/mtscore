"""CFTC COT 어댑터 — Socrata `6dca-aqww`(Legacy, Futures Only) 공개 API. 키 없음.

cot_net = 비상업(noncommercial) 롱 − 숏 계약 수.
as_of 규칙: date = 보고 기준 화요일 → as_of = date + 3일(금요일 공표). 공휴일 주의 월요일 공표 지연은 반영하지 않는다(가정).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .base import BaseAdapter

URL = ("https://publicreporting.cftc.gov/resource/6dca-aqww.json?cftc_contract_market_code={code}"
       "&$select=report_date_as_yyyy_mm_dd,cftc_contract_market_code,market_and_exchange_names,"
       "noncomm_positions_long_all,noncomm_positions_short_all&$order=report_date_as_yyyy_mm_dd&$limit=50000"
       "&$where=report_date_as_yyyy_mm_dd>='{start}'")
CODES = {"gold": "088691", "wti": "067651", "ust10y": "043602"}
AS_OF_LAG_DAYS = 3


def parse_records(records: list[dict]) -> pd.DataFrame:
    """Socrata 레코드 → (date, value=비상업 순포지션)."""
    if not records:
        return pd.DataFrame(columns=["date", "value"])
    d = pd.DataFrame(records)
    out = pd.DataFrame({
        "date": pd.to_datetime(d["report_date_as_yyyy_mm_dd"].str[:10]),
        "value": pd.to_numeric(d["noncomm_positions_long_all"]) - pd.to_numeric(d["noncomm_positions_short_all"]),
    })
    return out.dropna().drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def download(code: str, raw_dir: Path, start: str = "2008-01-01", refresh: bool = False) -> Path:
    import requests

    raw_dir = Path(raw_dir)
    p = raw_dir / f"cot_{code}.json"
    if p.exists() and not refresh:
        return p
    j = requests.get(URL.format(code=code, start=start), timeout=60).json()
    if not isinstance(j, list):
        raise RuntimeError(f"CFTC {code}: {str(j)[:200]}")
    raw_dir.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    return p


class CftcAdapter(BaseAdapter):
    """mapping: {(asset_id, "cot_net"): 계약 코드}."""

    source_name = "cftc"

    def __init__(self, mapping: dict, raw_dir: Path, download: bool = True):
        self.mapping = mapping
        self.raw_dir = Path(raw_dir)
        self.download = download

    def _fetch(self, asset, fields, start, end):
        parts = []
        for f in fields:
            code = self.mapping.get((asset, f))
            if code is None:
                continue
            p = download(code, self.raw_dir) if self.download else self.raw_dir / f"cot_{code}.json"
            d = parse_records(json.loads(p.read_text(encoding="utf-8")))
            if start is not None:
                d = d[d["date"] >= pd.Timestamp(start)]
            if end is not None:
                d = d[d["date"] <= pd.Timestamp(end)]
            parts.append(pd.DataFrame({"date": d["date"], "asset_id": asset, "field": f, "value": d["value"],
                                       "as_of": d["date"] + pd.Timedelta(days=AS_OF_LAG_DAYS),
                                       "source": f"cftc:6dca-aqww/{code}"}))
        if not parts:
            return pd.DataFrame(columns=["date", "asset_id", "field", "value", "as_of", "source"])
        return pd.concat(parts, ignore_index=True)
