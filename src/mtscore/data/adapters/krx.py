"""KRX 어댑터 — KRX Open API(data-dbg.krx.co.kr, 헤더 `AUTH_KEY`).

키: `~/.config/krx_key`(40자 AUTH_KEY, 2026-10-28 확인) 또는 환경변수 `KRX_AUTH_KEY`. 값은 로그·파일에 남기지 않는다.
이 키로 되는 것(2026-10-28 실측, data/raw/krx/probe_openapi.json): `idx/kospi_dd_trd`·`idx/krx_dd_trd`(지수 일별 종가·시총),
`sto/stk_bydd_trd`(종목 일별 시세·시총·상장주식수), `sto/stk_isu_base_info`, `etp/etf_bydd_trd`. `idx/drvprod_dd_trd` 는 401.
mtscore 가 필요한 지수 PER·PBR·배당수익률, 투자자별 순매수, 과거 구성종목은 이 API 응답에 없다 → 그 필드는 N/A
(pykrx 는 KRX_ID/KRX_PW 로그인이 필요하고 계정이 없다). 여기서는 교차검증용 지수 종가만 읽는다.
as_of = date(장 마감 뒤).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from .base import BaseAdapter

BASE = "https://data-dbg.krx.co.kr/svc/apis/"
KEY_FILE = Path.home() / ".config" / "krx_key"


def _key() -> str:
    k = os.environ.get("KRX_AUTH_KEY")
    return k.strip() if k else KEY_FILE.read_text().strip()


def download_day(endpoint: str, bas_dd: str, raw_dir: Path, refresh: bool = False) -> Path:
    import requests

    raw_dir = Path(raw_dir)
    p = raw_dir / f"{endpoint.replace('/', '_')}_{bas_dd}.json"
    if p.exists() and not refresh:
        return p
    r = requests.get(BASE + endpoint, params={"basDd": bas_dd}, headers={"AUTH_KEY": _key()}, timeout=30)
    r.raise_for_status()
    j = r.json()
    if "OutBlock_1" not in j:
        raise RuntimeError(f"KRX {endpoint} {bas_dd}: {str(j)[:200]}")
    raw_dir.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
    return p


def parse_index_day(j: dict, index_name: str = "코스피 200") -> pd.DataFrame:
    """kospi_dd_trd 응답 → (date, close, mktcap) 한 행(없으면 빈 프레임)."""
    rows = [r for r in j.get("OutBlock_1", []) if r.get("IDX_NM") == index_name]
    if not rows:
        return pd.DataFrame(columns=["date", "close", "mktcap"])
    r = rows[0]
    return pd.DataFrame({"date": [pd.to_datetime(r["BAS_DD"], format="%Y%m%d")],
                         "close": [float(str(r["CLSPRC_IDX"]).replace(",", ""))],
                         "mktcap": [float(str(r["MKTCAP"]).replace(",", ""))]})


class KrxIndexAdapter(BaseAdapter):
    """(asset_id, "close") → KRX 지수 종가. dates 를 하루씩 받는다(교차검증용 표본)."""

    source_name = "krx_openapi"

    def __init__(self, dates: list[str], raw_dir: Path, index_name: str = "코스피 200", download: bool = True):
        self.dates = dates
        self.raw_dir = Path(raw_dir)
        self.index_name = index_name
        self.download = download

    def _fetch(self, asset, fields, start, end):
        if "close" not in fields:
            return pd.DataFrame(columns=["date", "asset_id", "field", "value", "as_of", "source"])
        parts = []
        for d in self.dates:
            bas = pd.Timestamp(d).strftime("%Y%m%d")
            p = (download_day("idx/kospi_dd_trd", bas, self.raw_dir) if self.download
                 else self.raw_dir / f"idx_kospi_dd_trd_{bas}.json")
            parts.append(parse_index_day(json.loads(p.read_text(encoding="utf-8")), self.index_name))
        d = pd.concat(parts, ignore_index=True)
        return pd.DataFrame({"date": d["date"], "asset_id": asset, "field": "close", "value": d["close"],
                             "as_of": d["date"], "source": "krx_openapi:idx/kospi_dd_trd"})
