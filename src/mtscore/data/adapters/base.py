"""어댑터 공통 인터페이스. 모든 어댑터 출력은 schema.validate_panel 을 통과해야 한다."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

import pandas as pd

from ..schema import validate_panel


class BaseAdapter(ABC):
    """데이터 공급 어댑터. 코어는 어댑터를 모른다 — 호스트나 수집 스크립트가 패널을 만들어 엔진에 넘긴다."""

    source_name: str = "base"

    @abstractmethod
    def _fetch(self, asset: str, fields: Iterable[str], start: str | None, end: str | None) -> pd.DataFrame:
        """원천에서 4-1 스키마 컬럼을 가진 DataFrame 을 만든다(검증 전)."""

    def fetch(self, asset: str, fields: Iterable[str], start: str | None = None, end: str | None = None) -> pd.DataFrame:
        """`asset` 의 `fields` 를 [start, end] 기준일 범위로 가져와 검증된 패널로 돌려준다."""
        df = self._fetch(asset, list(fields), start, end)
        if "source" not in df.columns or df["source"].isna().all():
            df = df.assign(source=self.source_name)
        return validate_panel(df)
