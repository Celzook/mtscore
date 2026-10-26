"""CSV 어댑터 — 모든 자산의 최종 대체 경로. 4-1 스키마 그대로인 CSV 파일(들)을 읽는다."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from .base import BaseAdapter


class CsvAdapter(BaseAdapter):
    """`root` 아래 `*.csv`(또는 지정 파일들)를 읽는다. 파일마다 4-1 스키마 컬럼을 가져야 한다."""

    source_name = "csv"

    def __init__(self, root: str | Path, pattern: str = "*.csv"):
        """root: CSV 파일 또는 디렉터리. pattern: 디렉터리일 때 읽을 파일 패턴(TEMPLATE.csv 는 제외)."""
        self.root = Path(root)
        self.pattern = pattern

    def _files(self) -> list[Path]:
        if self.root.is_file():
            return [self.root]
        return sorted(p for p in self.root.glob(self.pattern) if p.name.upper() != "TEMPLATE.CSV")

    def _fetch(self, asset: str, fields: Iterable[str], start: str | None, end: str | None) -> pd.DataFrame:
        fields = set(fields)
        parts = []
        for p in self._files():
            d = pd.read_csv(p, dtype={"asset_id": str, "field": str, "source": str})
            d = d[(d["asset_id"] == asset) & (d["field"].isin(fields))]
            if len(d):
                parts.append(d)
        if not parts:
            return pd.DataFrame(columns=["date", "asset_id", "field", "value", "as_of", "source"])
        d = pd.concat(parts, ignore_index=True)
        dates = pd.to_datetime(d["date"], errors="coerce")
        keep = pd.Series(True, index=d.index)
        if start is not None:
            keep &= dates >= pd.Timestamp(start)
        if end is not None:
            keep &= dates <= pd.Timestamp(end)
        keep |= dates.isna()  # 날짜 파싱 실패 행은 버리지 않고 validate_panel 에서 SchemaError 로 거부
        return d[keep]
