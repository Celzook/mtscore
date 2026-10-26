"""입력 패널 데이터 계약(long format)과 검증.

컬럼: date, asset_id, field, value, as_of, source
- as_of: 값이 알려진 시점. 비어 있으면 date 로 채운다.
- as_of < date 는 거부한다(기준일보다 먼저 알려진 값은 계약 위반 — 예측치는 별도 field 로 넣을 것).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

PANEL_COLUMNS = ["date", "asset_id", "field", "value", "as_of", "source"]
REQUIRED_COLUMNS = ["date", "asset_id", "field", "value"]


class SchemaError(ValueError):
    """패널이 데이터 계약을 어겼을 때."""


def validate_panel(df: pd.DataFrame) -> pd.DataFrame:
    """패널을 검증하고 정규화한 복사본을 돌려준다.

    정규화: date·as_of 를 Timestamp(날짜 단위)로, value 를 float 로, as_of 결측은 date 로, source 결측은 "".
    비유한값(inf)은 NaN 으로 바꾸고 로그를 남긴다. NaN value 행은 제거하고 로그를 남긴다.

    Raises:
        SchemaError: 필수 컬럼 누락, 날짜·숫자 변환 실패, as_of < date, 같은 (date, asset_id, field, as_of) 중복.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(f"필수 컬럼 누락: {missing}")
    out = df.copy()
    if "as_of" not in out.columns:
        out["as_of"] = pd.NaT
    if "source" not in out.columns:
        out["source"] = ""
    out = out[PANEL_COLUMNS]

    for c in ("date", "as_of"):
        conv = pd.to_datetime(out[c], errors="coerce")
        bad = conv.isna() & out[c].notna()
        if bad.any():
            raise SchemaError(f"{c} 날짜 변환 실패 {int(bad.sum())}행 (예: {out.loc[bad, c].iloc[0]!r})")
        out[c] = conv.dt.normalize()
    if out["date"].isna().any():
        raise SchemaError(f"date 결측 {int(out['date'].isna().sum())}행")
    n_fill = int(out["as_of"].isna().sum())
    if n_fill:
        log.info("as_of 결측 %d행을 date 로 채움(공표 지연이 있는 필드라면 as_of 를 직접 넣을 것)", n_fill)
    out["as_of"] = out["as_of"].fillna(out["date"])

    val = pd.to_numeric(out["value"], errors="coerce")
    bad = val.isna() & out["value"].notna()
    if bad.any():
        raise SchemaError(f"value 숫자 변환 실패 {int(bad.sum())}행 (예: {out.loc[bad, 'value'].iloc[0]!r})")
    val = val.astype(float)
    inf = ~np.isfinite(val) & val.notna()
    if inf.any():
        log.warning("비유한값(inf) %d행을 NaN 으로 처리", int(inf.sum()))
        val[inf] = np.nan
    out["value"] = val
    nan_rows = out["value"].isna()
    if nan_rows.any():
        log.info("value 결측 %d행 제거", int(nan_rows.sum()))
        out = out[~nan_rows]

    for c in ("asset_id", "field"):
        if out[c].isna().any() or (out[c].astype(str).str.strip() == "").any():
            raise SchemaError(f"{c} 결측·빈 문자열")
        out[c] = out[c].astype(str)
    out["source"] = out["source"].fillna("").astype(str)

    early = out["as_of"] < out["date"]
    if early.any():
        r = out[early].iloc[0]
        raise SchemaError(f"as_of < date {int(early.sum())}행 (예: {r['asset_id']}/{r['field']} date={r['date'].date()} "
                          f"as_of={r['as_of'].date()})")
    dup = out.duplicated(["date", "asset_id", "field", "as_of"], keep=False)
    if dup.any():
        r = out[dup].iloc[0]
        raise SchemaError(f"(date, asset_id, field, as_of) 중복 {int(dup.sum())}행 (예: {r['asset_id']}/{r['field']} "
                          f"{r['date'].date()})")
    return out.sort_values(["asset_id", "field", "date", "as_of"]).reset_index(drop=True)
