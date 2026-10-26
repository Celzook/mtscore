"""공개 API — 호스트 프로젝트 진입점.

    from mtscore import ScoringEngine, load_config
    engine = ScoringEngine(load_config("config/"))
    result = engine.score(panel, as_of="2026-10-26")

코어는 파일·네트워크에 접근하지 않는다. 패널(4-1 스키마 long format)은 호출자가 공급한다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import AssetSpec, Config
from .core.scoring import BLOCKS, AssetScores, band, regime, score_asset
from .core.transform import pit_frame, to_calendar
from .data.schema import validate_panel

log = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"
ENGINE_VERSION = "0.1.0"
CALENDAR_FIELD_CANDIDATES = ("close", "yield", "spread")


@dataclass
class ScoreResult:
    """한 기준일의 스코어링 결과.

    Attributes:
        as_of: 요청 기준일(없으면 자산 기준일 중 가장 늦은 날).
        dates: asset_id → 실제 사용한 자산 달력일(요청 기준일 이전 마지막 거래일).
        stale: asset_id → 그 날이 요청일보다 daily_ffill_max_bdays 영업일 넘게 오래됐는지. True 면 블록 N/A.
        blocks: asset_id × block 점수(0~100, 클수록 매수 매력, N/A 는 NaN).
        bands: asset_id × block 구간 라벨.
        regime: asset_id 별 국면 라벨·표시 라벨(display)·부분판정 여부·블록 상태.
        contributions: 지표별 원시값·백분위·점수·블록 기여도(기준일 시점).
        coverage: 지표별 사용/제외와 사유. available = 기준일에 점수가 있었는지.
        history: asset_id → AssetScores(일별 전체 이력). to_json 에는 넣지 않는다.
    """

    as_of: pd.Timestamp
    dates: pd.Series
    stale: pd.Series
    blocks: pd.DataFrame
    bands: pd.DataFrame
    regime: pd.DataFrame
    contributions: pd.DataFrame
    coverage: pd.DataFrame
    history: dict = field(default_factory=dict, repr=False)

    @property
    def ranking(self) -> pd.DataFrame:
        """블록별 자산 간 순위(1 = 가장 높음). 블록 점수는 자산별 '자기 역사 대비' 백분위이므로
        이 순위는 '자기 역사 대비 극단성'의 비교이지 자산 간 기대수익 비교가 아니다."""
        return self.blocks.rank(ascending=False, method="min")

    def to_dict(self) -> dict:
        """JSON 직렬화용 dict(docs/result_schema.md). 결측은 None."""
        def clean(v):
            if v is None or v is pd.NaT or (np.isscalar(v) and not isinstance(v, str) and pd.isna(v)):
                return None
            if isinstance(v, (float, np.floating)):
                return round(float(v), 4)
            if isinstance(v, np.integer):
                return int(v)
            if isinstance(v, np.bool_):
                return bool(v)
            if isinstance(v, pd.Timestamp):
                return str(v.date())
            return v

        assets = []
        for aid in self.blocks.index:
            rg = self.regime.loc[aid]
            contrib = self.contributions[self.contributions["asset_id"] == aid].drop(columns="asset_id")
            cov = self.coverage[self.coverage["asset_id"] == aid].drop(columns="asset_id")
            assets.append({
                "asset_id": aid,
                "date": clean(self.dates.get(aid)),
                "stale": bool(self.stale.get(aid, False)),
                "blocks": {b: clean(self.blocks.at[aid, b]) for b in BLOCKS},
                "bands": {b: self.bands.at[aid, b] for b in BLOCKS},
                "regime": {"label": rg["label"], "display": rg["display"], "partial": bool(rg["partial"]),
                           "states": {k: rg[k] for k in ("o", "v", "f")}},
                "contributions": [{k: clean(v) for k, v in r.items()} for r in contrib.to_dict("records")],
                "coverage": [{k: clean(v) for k, v in r.items()} for r in cov.to_dict("records")],
            })
        return {"schema_version": SCHEMA_VERSION, "engine_version": ENGINE_VERSION, "as_of": str(self.as_of.date()),
                "note": "블록 점수는 자산별 자기 과거 분포 대비 백분위(0~100, 클수록 매수 매력)", "assets": assets}

    def to_json(self, **kw) -> str:
        """버전 포함 JSON 문자열. 스키마는 docs/result_schema.md."""
        return json.dumps(self.to_dict(), ensure_ascii=False, **kw)


class ScoringEngine:
    """설정(Config)과 패널로 블록 점수·국면을 산출한다."""

    def __init__(self, config: Config):
        """config: load_config/build_config 로 만든 검증된 설정."""
        self.config = config
        mcfg = config.scoring.get("missing", {}) or {}
        self.daily_ffill_max = int(mcfg.get("daily_ffill_max_bdays", 5))
        self.lowfreq_max_hold = int(mcfg.get("lowfreq_max_hold_bdays", 70))
        self.lowfreq_threshold = float(mcfg.get("lowfreq_threshold_days", 5))

    # ---- 내부: 달력·PIT 필드 구성
    def _calendar(self, panel: pd.DataFrame, asset: AssetSpec, cutoff: pd.Timestamp | None) -> pd.DatetimeIndex:
        """자산 달력 = 달력 필드(지정 또는 close·yield·spread 중 처음 있는 것)의 PIT 채택 관측 가용일.

        휴장일에 값을 복제하지 않기 위해서다(롤링 합·수익률 왜곡 방지). pit_frame 이 버리는 옛 기준일 수정치는
        달력일을 만들지 않는다. 빈도로 달력을 고르지 않는다 — 전체 이력의 빈도로 고르면 미래 행이 과거 달력을
        바꾼다(리뷰 a-calendar-lookahead). 달력 필드가 없으면 패널 전체 기간의 평일 달력."""
        own = panel[panel["asset_id"] == asset.asset_id]
        cands = [asset.calendar_field] if asset.calendar_field else list(CALENDAR_FIELD_CANDIDATES)
        for f in cands:
            rows = own[own["field"] == f]
            if len(rows):
                return pd.DatetimeIndex(pit_frame(rows).index)
        end = cutoff if cutoff is not None else panel["as_of"].max()
        return pd.bdate_range(panel["as_of"].min(), end)

    def _field_series(self, panel: pd.DataFrame, asset_id: str, fld: str, cal: pd.DatetimeIndex) -> pd.Series | None:
        rows = panel[(panel["asset_id"] == asset_id) & (panel["field"] == fld)]
        if rows.empty:
            return None
        return to_calendar(pit_frame(rows), cal, self.daily_ffill_max, self.lowfreq_max_hold, self.lowfreq_threshold,
                           label=f"{asset_id}.{fld}")

    def _asset_fields(self, panel: pd.DataFrame, asset: AssetSpec, cal: pd.DatetimeIndex) -> dict[str, pd.Series]:
        out = {}
        for fld in panel.loc[panel["asset_id"] == asset.asset_id, "field"].unique():
            s = self._field_series(panel, asset.asset_id, fld, cal)
            tr = asset.field_transforms.get(fld)
            if tr == "reciprocal":
                zeros = int((s == 0).sum())
                if zeros:
                    log.warning("%s.%s: reciprocal 변환에서 0 값 %d개를 NaN 으로 처리", asset.asset_id, fld, zeros)
                s = 1.0 / s.where(s != 0)
            elif tr == "negate":
                s = -s
            out[fld] = s
        for fld, (ra, rf) in asset.refs.items():
            if fld in out:
                log.warning("%s: refs.%s 가 자산 자체 field 를 덮어씀", asset.asset_id, fld)
            s = self._field_series(panel, ra, rf, cal)
            if s is not None:
                out[fld] = s
        return out

    # ---- 공개
    def score_history(self, panel: pd.DataFrame, asset_ids: list[str] | None = None,
                      as_of: str | pd.Timestamp | None = None) -> dict[str, AssetScores]:
        """자산별 일별 점수 이력(자산 달력 기준).

        as_of 를 주면 as_of 이후에 알려진 행(as_of 컬럼 > 기준일)을 먼저 버린다. as_of 를 주지 않아도 이력의 각
        날짜 값은 그날까지 알려진 정보만으로 계산된다(PIT) — 같은 날을 as_of 로 잘라 계산한 값과 같다.
        """
        p = validate_panel(panel)
        cutoff = pd.Timestamp(as_of).normalize() if as_of is not None else None
        if cutoff is not None:
            p = p[p["as_of"] <= cutoff]
        if p.empty:
            raise ValueError("기준일까지 알려진 패널 행이 없음")
        ids = asset_ids or [a.asset_id for a in self.config.universe]
        out = {}
        for aid in ids:
            asset = self.config.asset(aid)
            cal = self._calendar(p, asset, cutoff)
            defs, excluded, sub_w = self.config.indicator_defs(asset)
            fields = self._asset_fields(p, asset, cal)
            out[aid] = score_asset(defs, fields, cal, self.config.scoring, asset.asset_class, excluded, sub_w)
        return out

    def score(self, panel: pd.DataFrame, as_of: str | pd.Timestamp | None = None,
              asset_ids: list[str] | None = None) -> ScoreResult:
        """기준일(as_of, 없으면 각 자산의 마지막 가용일) 시점의 블록 점수·구간·국면·기여도·커버리지."""
        hist = self.score_history(panel, asset_ids, as_of)
        req = pd.Timestamp(as_of).normalize() if as_of is not None else None
        bands_cfg = self.config.scoring.get("bands", {}) or {}
        rg_cfg = self.config.scoring.get("regime", {}) or {}
        partial_label = rg_cfg.get("partial_label", "부분판정")
        dates, stale, blk_rows, band_rows, rg_rows, contrib, cov = {}, {}, {}, {}, {}, [], []
        for aid, h in hist.items():
            cal = h.blocks.index
            cal = cal if req is None else cal[cal <= req]
            if len(cal) == 0:
                raise ValueError(f"{aid}: 기준일 {req.date() if req is not None else '(마지막 가용일)'} 이전 달력일이 없음")
            t = cal[-1]
            dates[aid] = t
            lag = int(np.busday_count(t.date(), req.date())) if req is not None else 0
            is_stale = lag > self.daily_ffill_max
            stale[aid] = is_stale
            if is_stale:
                log.warning("%s: 마지막 자산 달력일 %s 가 기준일보다 %d영업일 이전 → 블록 N/A", aid, t.date(), lag)
            b = h.blocks.loc[t] if not is_stale else pd.Series(np.nan, index=list(BLOCKS))
            blk_rows[aid] = b
            band_rows[aid] = {k: band(b[k], bands_cfg) for k in BLOCKS}
            r = regime(b.to_dict(), rg_cfg)
            disp = None if r["label"] is None else (f"{r['label']} ({partial_label})" if r["partial"] else r["label"])
            rg_rows[aid] = {"label": r["label"], "display": disp, "partial": r["partial"], **r["states"]}
            rows_c = _contributions(aid, h, t)
            if is_stale:
                for r_ in rows_c:
                    r_.update(weight_in_block=0.0, contribution=np.nan)
            contrib.extend(rows_c)
            c = h.coverage.copy()
            c["available"] = [bool(u) and not is_stale and n in h.score.columns and not np.isnan(h.score.at[t, n])
                              for n, u in zip(c["indicator"], c["used"])]
            gone = c["used"].astype(bool) & ~c["available"].astype(bool)
            c.loc[gone, "reason"] = "unavailable_at_as_of"
            c.insert(0, "asset_id", aid)
            cov.append(c)
        return ScoreResult(
            as_of=req if req is not None else max(dates.values()),
            dates=pd.Series(dates),
            stale=pd.Series(stale, dtype=bool),
            blocks=pd.DataFrame(blk_rows).T[list(BLOCKS)].astype(float),
            bands=pd.DataFrame(band_rows).T[list(BLOCKS)],
            regime=pd.DataFrame(rg_rows).T[["label", "display", "partial", "o", "v", "f"]],
            contributions=pd.DataFrame(contrib, columns=["asset_id", "block", "sub_block", "indicator", "raw",
                                                         "percentile", "score", "weight_in_block", "contribution"]),
            coverage=pd.concat(cov, ignore_index=True) if cov else pd.DataFrame(),
            history=hist,
        )


def _contributions(aid: str, h: AssetScores, t: pd.Timestamp) -> list[dict]:
    """t 시점 지표별 블록 기여도. 기여도 합 = 블록 점수(가용 지표·하위블록만으로 가중치 재정규화).
    가용 가중치 합이 0 이면(모두 가중치 0) 그 블록 기여도는 NaN — scoring._weighted_mean 과 같은 규칙."""
    cov = h.coverage.set_index("indicator")
    rows = []
    for blk in BLOCKS:
        subs = [c for c in h.sub_blocks.columns if c[0] == blk]
        live_subs = [c for c in subs if not np.isnan(h.sub_blocks.at[t, c])]
        sw_tot = sum(h.weights[c] for c in live_subs)
        for c in subs:
            names = [n for n in h.score.columns if cov.at[n, "block"] == blk and cov.at[n, "sub_block"] == c[1]]
            live = [n for n in names if not np.isnan(h.score.at[t, n])]
            iw_tot = sum(h.weights[n] for n in live)
            for n in names:
                s = h.score.at[t, n]
                ok = n in live and c in live_subs and iw_tot > 0 and sw_tot > 0
                w = (h.weights[n] / iw_tot) * (h.weights[c] / sw_tot) if ok else 0.0
                rows.append({"asset_id": aid, "block": blk, "sub_block": c[1], "indicator": n,
                             "raw": h.raw.at[t, n], "percentile": h.percentile.at[t, n], "score": s,
                             "weight_in_block": w, "contribution": s * w if ok else np.nan})
    return rows
