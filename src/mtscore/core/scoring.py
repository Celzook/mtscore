"""지표 → 백분위 점수 → 하위블록·블록 점수 → 구간·국면. 순수 함수(파일·네트워크 없음)."""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .registry import IndicatorDef
from .transform import apply_direction, percentile_expanding, percentile_rolling

log = logging.getLogger(__name__)

BLOCKS = ("oversold", "valuation", "fundamental")
BLOCK_KEY = {"oversold": "o", "valuation": "v", "fundamental": "f"}
SUB_BLOCK_AGGS = ("mean", "min")   # 하위블록 집계: mean = 지표 가중평균(기본), min = 행별 최솟값(퍼지 AND)


@dataclass
class AssetScores:
    """한 자산의 일별 산출물."""

    raw: pd.DataFrame            # 지표 원시값 (date × indicator)
    percentile: pd.DataFrame     # 방향 반영 전 백분위
    score: pd.DataFrame          # 방향 반영 점수(클수록 매수 매력)
    sub_blocks: pd.DataFrame     # (block, sub_block) MultiIndex 컬럼
    blocks: pd.DataFrame         # date × block
    coverage: pd.DataFrame       # indicator 별 used/excluded·사유
    weights: dict                # indicator → 가중치, (block, sub_block) → 가중치
    sub_block_agg: dict = field(default_factory=dict)   # (block, sub_block) → mean | min


def currency_variant_excluded(d: IndicatorDef, variant: str) -> bool:
    """통화 이중반영 변형: oversold_only 면 fundamental 의 통화 지표를, fundamental_only 면 oversold 의 통화 지표를 뺀다."""
    if "currency" not in d.flags or variant == "both":
        return False
    if variant == "oversold_only":
        return d.block == "fundamental"
    if variant == "fundamental_only":
        return d.block == "oversold"
    raise ValueError(f"currency_variant 값 오류: {variant}")


def _weighted_mean(frame: pd.DataFrame, w: pd.Series) -> pd.Series:
    """행별 NaN 을 건너뛴 가중평균. 모든 값이 NaN 이면 NaN."""
    vals = frame.to_numpy(dtype=float)
    ww = np.broadcast_to(w.reindex(frame.columns).to_numpy(dtype=float), vals.shape)
    mask = ~np.isnan(vals)
    num = np.where(mask, vals * ww, 0.0).sum(axis=1)
    den = np.where(mask, ww, 0.0).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(den > 0, num / den, np.nan)
    return pd.Series(out, index=frame.index)


def _min_joint(frame: pd.DataFrame) -> pd.Series:
    """min 하위블록의 행별 최솟값. 그날까지 점수가 한 번이라도 나온(시작한) 지표가 그날 하나라도 NaN 이면 NaN —
    공동 조건은 모두 있어야 판정한다. 아직 시작하지 않은 지표(워밍업 중)는 빼고 본다: 시작한 지표가 하나뿐이면
    그 지표 점수, 하나도 없으면 NaN.

    '시작 여부'를 전체 이력의 coverage used 가 아니라 그날까지의 관측으로 정하는 것은 인과성 때문이다. 전체 이력으로
    정하면 워밍업이 늦은 지표가 나중에 점수를 내는지(미래)에 따라 과거 행이 NaN 이 되어, 이력값과 그날로 잘라 계산한
    값이 달라진다(잘라 계산하면 그 지표는 insufficient_history 로 빠지고 남은 지표 하나가 하위블록이 된다)."""
    started = frame.notna().cummax()
    gap = (started & frame.isna()).any(axis=1)
    return frame.min(axis=1, skipna=True).where(~gap)


def score_asset(defs: list[IndicatorDef], fields: dict[str, pd.Series], calendar: pd.DatetimeIndex,
                scoring_cfg: dict, asset_class: str, excluded: dict[str, str] | None = None,
                sub_block_weights: dict[str, float] | None = None) -> AssetScores:
    """한 자산의 지표를 계산하고 블록 점수까지 만든다.

    Args:
        defs: 이 자산에 적용할 지표 정의(프로파일 + overrides 반영 후).
        fields: field 이름 → 달력에 정렬된 PIT 시계열.
        calendar: 영업일 달력.
        scoring_cfg: scoring.yaml 내용.
        asset_class: 자산군(지표의 asset_classes 제한 확인용).
        excluded: 지표 이름 → 사전 제외 사유(override 등).
        sub_block_weights: "block.sub_block" → 가중치 override.

    하위블록 집계는 scoring_cfg["sub_block_agg"]("block.sub_block" → mean | min, 없으면 mean)가 정한다.
    - mean: 행별 NaN 을 건너뛴 지표 가중평균(가용 지표로 재정규화).
    - min: 행별 최솟값(퍼지 AND — 조건이 동시에 성립할 때만 점수가 높다). 지표 가중치는 쓰지 않는다(최솟값은
      가중할 수 없음) — 빼려면 overrides.exclude 를 쓴다. 결측 규칙은 _min_joint 참고.
    블록 집계(하위블록 → 블록)는 언제나 가중평균이다.
    """
    excluded = dict(excluded or {})
    pcfg = scoring_cfg.get("percentile", {})
    method = pcfg.get("method", "expanding")
    min_years = float(pcfg.get("min_history_years", 3))
    roll_years = float(pcfg.get("rolling_years", 10))
    variant = scoring_cfg.get("currency_variant", "both")
    agg_cfg = dict(scoring_cfg.get("sub_block_agg") or {})
    bad = {k: v for k, v in agg_cfg.items() if v not in SUB_BLOCK_AGGS}
    if bad:
        raise ValueError(f"sub_block_agg 값 오류: {bad} (허용 {SUB_BLOCK_AGGS})")

    raw, pct, sc, cov = {}, {}, {}, []
    used: list[IndicatorDef] = []
    for d in defs:
        reason = excluded.get(d.name)
        if reason is None and d.status != "active":
            reason = f"status:{d.status}"
        if reason is None and d.asset_classes and asset_class not in d.asset_classes:
            reason = f"asset_class:{asset_class} 미적용"
        if reason is None and currency_variant_excluded(d, variant):
            reason = f"currency_variant:{variant}"
        if reason is None:
            miss = [f for f in d.fields if f not in fields or fields[f].notna().sum() == 0]
            if miss:
                reason = "missing_field:" + ",".join(miss)
        if reason is None:
            r = d.compute([fields[f] for f in d.fields]).reindex(calendar)
            n_inf = int(np.isinf(r.to_numpy(dtype=float)).sum())
            if n_inf:
                log.info("%s: 비유한값 %d개를 NaN 으로 처리", d.name, n_inf)
                r = r.replace([np.inf, -np.inf], np.nan)
            p = (percentile_expanding(r, min_years) if method == "expanding"
                 else percentile_rolling(r, roll_years, min_years))
            if p.notna().sum() == 0:
                reason = "insufficient_history"
            else:
                raw[d.name], pct[d.name] = r, p
                sc[d.name] = apply_direction(p, d.direction)
                used.append(d)
        cov.append({"indicator": d.name, "block": d.block, "sub_block": d.sub_block, "function": d.indicator,
                    "fields": ",".join(d.fields), "direction": "+" if d.direction == 1 else "-",
                    "used": reason is None, "reason": reason or "",
                    "first_score_date": (sc[d.name].first_valid_index() if reason is None else None)})
        if reason:
            log.info("지표 제외 %s: %s", d.name, reason)

    raw_df = pd.DataFrame(raw, index=calendar)
    pct_df = pd.DataFrame(pct, index=calendar)
    sc_df = pd.DataFrame(sc, index=calendar)
    ind_w = pd.Series({d.name: d.weight for d in used}, dtype=float)
    sbw = dict(sub_block_weights or {})

    sub_cols, sub_series, sub_w, sub_agg = [], [], {}, {}
    for blk in BLOCKS:
        for sb in dict.fromkeys(d.sub_block for d in used if d.block == blk):
            names = [d.name for d in used if d.block == blk and d.sub_block == sb]
            agg = agg_cfg.get(f"{blk}.{sb}", "mean")
            sub_cols.append((blk, sb))
            sub_series.append(_min_joint(sc_df[names]) if agg == "min"
                              else _weighted_mean(sc_df[names], ind_w[names]))
            sub_w[(blk, sb)] = float(sbw.get(f"{blk}.{sb}", 1.0))
            sub_agg[(blk, sb)] = agg
    if sub_cols:
        sub_df = pd.concat(sub_series, axis=1)
        sub_df.columns = pd.MultiIndex.from_tuples(sub_cols, names=["block", "sub_block"])
    else:
        sub_df = pd.DataFrame(index=calendar, columns=pd.MultiIndex.from_tuples([], names=["block", "sub_block"]))

    blocks = {}
    for blk in BLOCKS:
        cols = [c for c in sub_cols if c[0] == blk]
        if cols:
            blocks[blk] = _weighted_mean(sub_df[cols], pd.Series({c: sub_w[c] for c in cols}))
        else:
            blocks[blk] = pd.Series(np.nan, index=calendar)
    blk_df = pd.DataFrame(blocks, index=calendar)[list(BLOCKS)]
    weights = {**{d.name: d.weight for d in used}, **sub_w}
    return AssetScores(raw_df, pct_df, sc_df, sub_df, blk_df, pd.DataFrame(cov), weights, sub_agg)


def band(score: float, bands: dict) -> str | None:
    """점수 구간: 극단(≥90)·경계(≥75)·중립·반대경계(≤25)·반대극단(≤10). NaN 은 None."""
    if score is None or (isinstance(score, float) and np.isnan(score)):
        return None
    if score >= bands.get("extreme", 90):
        return "극단"
    if score >= bands.get("alert", 75):
        return "경계"
    if score <= bands.get("contra_extreme", 10):
        return "반대극단"
    if score <= bands.get("contra_alert", 25):
        return "반대경계"
    return "중립"


def regime(block_scores: dict[str, float], regime_cfg: dict) -> dict:
    """블록 점수 → 국면 라벨.

    - 블록 ≥ threshold 면 high, 아니면 low. NaN 블록은 N/A.
    - 전 블록 가용: 매트릭스를 위에서부터 보고 처음 맞는 행(null = 무관).
    - N/A 블록이 있으면 N/A 블록에 high·low 를 모두 넣어 본 전체 판정 라벨이 하나로 모이면 그 라벨,
      아니면 축약 라벨. 둘 다 partial=True.
    Returns: {"label", "partial", "states"}  states 는 {"o": "high"/"low"/None, ...}
    """
    thr = float(regime_cfg.get("threshold", 50))
    states = {}
    for blk in BLOCKS:
        v = block_scores.get(blk)
        states[BLOCK_KEY[blk]] = None if v is None or np.isnan(v) else ("high" if v >= thr else "low")
    matrix = regime_cfg.get("matrix", [])

    def full_label(st: dict) -> str | None:
        for row in matrix:
            if all(row.get(k) in (None, s) for k, s in st.items()):
                return row["label"]
        return None

    avail = {k: s for k, s in states.items() if s is not None}
    if not avail:
        return {"label": None, "partial": True, "states": states}
    missing = [k for k, s in states.items() if s is None]
    if not missing:
        return {"label": full_label(states), "partial": False, "states": states}
    labels = []
    for combo in itertools.product(("high", "low"), repeat=len(missing)):
        labels.append(full_label({**avail, **dict(zip(missing, combo))}))
    labels = list(dict.fromkeys(labels))
    if len(labels) == 1 and labels[0] is not None:
        label = labels[0]
    else:
        abbr = {"high": "高", "low": "低"}
        label = "축약:" + "·".join(f"{k.upper()}{abbr[s]}" for k, s in states.items() if s is not None)
    return {"label": label, "partial": True, "states": states}


def staged_entry_flag(oversold: float, vol_ratio: float, oversold_min: float, vol_ratio_min: float) -> bool | None:
    """분할 진입 표시(사전 등록 B2): 과매도 블록 점수 ≥ oversold_min 이고 변동성비(원시값) ≥ vol_ratio_min.
    둘 중 하나라도 결측이면 None(판정 불가). 점수·국면에는 영향이 없다(표시 전용)."""
    if oversold is None or vol_ratio is None or np.isnan(oversold) or np.isnan(vol_ratio):
        return None
    return bool(oversold >= oversold_min and vol_ratio >= vol_ratio_min)
