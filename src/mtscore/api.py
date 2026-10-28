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
from .core import backtest as bt
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


@dataclass
class BacktestResult:
    """engine.backtest 산출물. 모든 통계 행에 n 이 있고, n < min_n 이면 warning = '표본 부족'.

    Attributes:
        horizons: forward return 기간(자산 달력 영업일).
        forward: asset_id → DataFrame[fwd_h…, mae_h…, trend_up](자산 달력 색인).
        quantiles: 자산 × 블록 × h × 분위(1~q) 통계.
        bands: 자산 × 블록 × h × 구간(all·≥90·≥75·≤25·≤10) 통계.
        events: 자산 × 블록 × 구간 × h 이벤트 통계(쿨다운 적용, 무조건 평균 대비 초과).
        event_list: 이벤트 날짜·점수·forward return 목록.
        ic: 자산 × 블록 × h × 기간(full·first_half·second_half) Spearman IC·NW t·겹치지 않는 표본 점검.
            플라시보를 켜면 full 행에 p_placebo(순환 이동 양측 p)·placebo_sd·nw_se·se_ratio(= placebo_sd/nw_se)·
            p_nw(정규 근사 양측)·q_placebo·q_nw(전 자산×블록×기간 BH-FDR)가 붙는다.
        ic_cells: 자산 × 블록 셀 단위(기간 평균 IC) 플라시보 p 와 셀 간 BH-FDR q(플라시보를 켰을 때).
        regimes: 자산 × 국면 라벨 × h 통계.
        pooled_ic · pooled_bands: 자산군 풀링 결과.
        regime_daily: asset_id → 일별 국면 라벨.
        history: asset_id → AssetScores(점수 이력).
        return_rule: asset_id → 수익률 규칙 설명(가정 표기).
    """

    horizons: list
    forward: dict
    quantiles: pd.DataFrame
    bands: pd.DataFrame
    events: pd.DataFrame
    event_list: pd.DataFrame
    ic: pd.DataFrame
    regimes: pd.DataFrame
    pooled_ic: pd.DataFrame
    pooled_bands: pd.DataFrame
    regime_daily: dict = field(default_factory=dict, repr=False)
    history: dict = field(default_factory=dict, repr=False)
    return_rule: dict = field(default_factory=dict)
    ic_cells: pd.DataFrame = field(default_factory=pd.DataFrame)


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


    # ---- 백테스트
    def return_index(self, panel: pd.DataFrame, asset: AssetSpec,
                     cal: pd.DatetimeIndex | None = None) -> tuple[pd.Series, pd.Series, str]:
        """자산 달력 위 수익 지수·유효일 마스크·규칙 설명. return_field 별 규칙(가정 포함):

        - duration_approx: −D×Δy/100 + y_{t−1}/100/carry_days 일별 근사(meta duration, 금리 필드
          meta return_yield_field 기본 'yield'). 스프레드 필드면 같은 듀레이션 국채 대비 초과수익 근사.
        - 그 밖: 그 필드(field_transforms 적용 후, 예 USDKRW 역수 = 원화 가격)의 수준 비율."""
        p = validate_panel(panel)
        cal = self._calendar(p, asset, None) if cal is None else cal
        bcfg = self.config.scoring.get("backtest", {}) or {}
        rf = asset.return_field
        if rf == "duration_approx":
            yf = asset.meta.get("return_yield_field", "yield")
            dur = asset.meta.get("duration")
            if dur is None:
                raise ValueError(f"{asset.asset_id}: return_field duration_approx 인데 duration 이 없음")
            y = self._field_series(p, asset.asset_id, yf, cal)
            if y is None:
                raise ValueError(f"{asset.asset_id}: 수익률용 금리 필드 {yf} 없음")
            carry = float(bcfg.get("carry_days_per_year", 252))
            daily = bt.duration_returns(y, float(dur), carry)
            rule = f"−{dur}×Δ{yf}/100 + {yf}/100/{carry:g} 일별 근사(가정: 듀레이션 고정, 볼록성 무시)"
            valid = y.notna()
        else:
            s = self._field_series(p, asset.asset_id, rf, cal)
            if s is None:
                raise ValueError(f"{asset.asset_id}: return_field {rf} 없음")
            tr = asset.field_transforms.get(rf)
            if tr == "reciprocal":
                s = 1.0 / s.where(s != 0)
            elif tr == "negate":
                raise ValueError(f"{asset.asset_id}: negate 변환된 return_field 는 수익률로 쓸 수 없음")
            daily = bt.price_returns(s)
            rule = f"{rf}{'(역수)' if tr == 'reciprocal' else ''} 수준 비율"
            valid = s.notna()
        idx = bt.return_index(daily).where(valid.cummax())
        return idx, valid, rule

    def backtest(self, panel: pd.DataFrame, horizons=None, asset_ids: list[str] | None = None,
                 history: dict | None = None, placebo: int | None = None) -> BacktestResult:
        """점수 이력 × forward return 통계. 튜닝하지 않는다(임계값·분위·쿨다운은 scoring.yaml).

        horizons 기본값 scoring.yaml backtest.horizons. history 를 주면 점수를 다시 계산하지 않는다.
        placebo: 순환 이동 플라시보 횟수(None 이면 backtest.placebo_shifts, 없으면 0 = 끔). 이동 크기는
        [252, n − 252) 에서 고정 시드(backtest.placebo_seed + 셀 순번)로 뽑는다. 풀링은 모든 자산에 같은 이동."""
        p = validate_panel(panel)
        bcfg = self.config.scoring.get("backtest", {}) or {}
        horizons = [int(h) for h in (horizons or bcfg.get("horizons", [21, 63, 126, 252]))]
        cooldown = int(bcfg.get("event_cooldown_bdays", 20))
        min_n = int(bcfg.get("min_n_warning", 10))
        q = int(bcfg.get("quantiles", 5))
        gate_w = int(bcfg.get("trend_gate_window", 200))
        n_pl = int(bcfg.get("placebo_shifts", 0) if placebo is None else placebo)
        seed = int(bcfg.get("placebo_seed", 0))
        pl_rows, cell_no = [], 0
        bands_cfg = self.config.scoring.get("bands", {}) or {}
        rg_cfg = self.config.scoring.get("regime", {}) or {}
        hist = history if history is not None else self.score_history(p, asset_ids)
        ids = asset_ids or list(hist)
        fwd, rules, rdaily = {}, {}, {}
        qrows, brows, erows, elist, icrows, rgrows = [], [], [], [], [], []
        for aid in ids:
            asset = self.config.asset(aid)
            h = hist[aid]
            cal = h.blocks.index
            idx, valid, rules[aid] = self.return_index(p, asset, cal)
            F = bt.forward_returns(idx, horizons, valid)
            M = bt.forward_mae(idx, horizons, valid)
            fr = pd.concat([F.add_prefix("fwd_"), M.add_prefix("mae_")], axis=1)
            fr["trend_up"] = bt.trend_up(idx, gate_w)
            fwd[aid] = fr
            rd = bt.regime_labels(h.blocks, rg_cfg)
            rdaily[aid] = rd
            for blk in BLOCKS:
                sc = h.blocks[blk]
                if sc.notna().sum() == 0:
                    continue
                ql = bt.quantile_labels(sc, q)
                masks = bt.band_masks(sc, bands_cfg)
                dates = sc.dropna().index
                mid = dates[len(dates) // 2]
                periods = {"full": sc.notna(), "first_half": sc.notna() & (sc.index < mid),
                           "second_half": sc.notna() & (sc.index >= mid)}
                for hz in horizons:
                    f, m = F[hz], M[hz]
                    for k in sorted(ql.dropna().unique()):
                        sel = ql == k
                        qrows.append({"asset_id": aid, "block": blk, "horizon": hz, "quantile": int(k),
                                      "score_lo": sc[sel].min(), "score_hi": sc[sel].max(),
                                      **bt.ret_stats(f[sel], m, hz, min_n)})
                    for lab, mk in masks.items():
                        brows.append({"asset_id": aid, "block": blk, "horizon": hz, "band": lab,
                                      **bt.ret_stats(f[mk], m, hz, min_n)})
                    for per, mk in periods.items():
                        r = bt.spearman_ic(sc[mk], f[mk], hz)
                        icrows.append({"asset_id": aid, "block": blk, "horizon": hz, "period": per,
                                       "start": sc[mk].first_valid_index(), "end": sc[mk].last_valid_index(),
                                       **r, "warning": "표본 부족" if r["n_nonoverlap"] < min_n else ""})
                if n_pl > 0:
                    shifts = bt.shift_draws(int(sc.notna().sum()), n_pl, seed + cell_no)
                    obs, P = bt.placebo_ic(sc, {hz: F[hz] for hz in horizons}, shifts)
                    ph = bt.placebo_p(obs, P)
                    pc = bt.placebo_p(np.nanmean(obs), np.nanmean(P, axis=1)[:, None])[0] if len(P) else np.nan
                    pl_rows.append({"asset_id": aid, "block": blk, "mean_ic": float(np.nanmean(obs)), "p_cell": pc,
                                    "n_shifts": len(shifts),
                                    **{f"p_{hz}": ph[j] for j, hz in enumerate(horizons)},
                                    **{f"sd_{hz}": (np.nanstd(P[:, j]) if len(P) else np.nan)
                                       for j, hz in enumerate(horizons)}})
                cell_no += 1
                for lab, mk in masks.items():
                    if lab == "all":
                        continue
                    ev = bt.event_dates(mk, cooldown)
                    for t in ev:
                        elist.append({"asset_id": aid, "block": blk, "band": lab, "date": t, "score": sc[t],
                                      **{f"fwd_{hz}": F.at[t, hz] for hz in horizons},
                                      **{f"mae_{hz}": M.at[t, hz] for hz in horizons}})
                    for hz in horizons:
                        st = bt.ret_stats(F[hz].reindex(ev), M[hz], hz, min_n)
                        st["n_indep_approx"] = np.nan
                        st["warning"] = "표본 부족" if st["n"] < min_n else ""
                        base = F[hz][sc.notna()].mean()
                        erows.append({"asset_id": aid, "block": blk, "band": lab, "horizon": hz, **st,
                                      "uncond_mean": base, "excess_mean": st["mean"] - base})
            lab = rd["label"].where(rd["label"].notna())
            for hz in horizons:
                for name in lab.dropna().unique():
                    sel = lab == name
                    rgrows.append({"asset_id": aid, "regime": name, "horizon": hz,
                                   "share_days": sel.sum() / lab.notna().sum(),
                                   **bt.ret_stats(F[hz][sel], M[hz], hz, min_n)})
        pic, pband = self._pooled(ids, hist, fwd, horizons, bands_cfg, min_n, n_pl, seed)
        ic_df, cells = pd.DataFrame(icrows), pd.DataFrame(pl_rows)
        if len(cells):
            from scipy.stats import norm
            cells["q_cell"] = bt.bh_fdr(cells["p_cell"])
            long = cells.melt(id_vars=["asset_id", "block"], value_vars=[f"p_{h}" for h in horizons],
                              var_name="h", value_name="p_placebo")
            long["horizon"] = long["h"].str[2:].astype(int)
            sd = cells.melt(id_vars=["asset_id", "block"], value_vars=[f"sd_{h}" for h in horizons],
                            var_name="h", value_name="placebo_sd")
            sd["horizon"] = sd["h"].str[3:].astype(int)
            ic_df = ic_df.merge(long.drop(columns="h"), on=["asset_id", "block", "horizon"], how="left")
            ic_df = ic_df.merge(sd.drop(columns="h"), on=["asset_id", "block", "horizon"], how="left")
            full = ic_df["period"] == "full"
            ic_df.loc[~full, ["p_placebo", "placebo_sd"]] = np.nan
            ic_df["nw_se"] = (ic_df["ic"] / ic_df["t_nw"]).where(full)
            ic_df["se_ratio"] = ic_df["placebo_sd"] / ic_df["nw_se"]
            ic_df["p_nw"] = pd.Series(2 * norm.sf(ic_df["t_nw"].abs()), index=ic_df.index).where(full)
            ic_df["q_placebo"] = np.nan
            ic_df["q_nw"] = np.nan
            ic_df.loc[full, "q_placebo"] = bt.bh_fdr(ic_df.loc[full, "p_placebo"])
            ic_df.loc[full, "q_nw"] = bt.bh_fdr(ic_df.loc[full, "p_nw"])
        return BacktestResult(horizons=horizons, forward=fwd, quantiles=pd.DataFrame(qrows), bands=pd.DataFrame(brows),
                              events=pd.DataFrame(erows), event_list=pd.DataFrame(elist), ic=ic_df,
                              regimes=pd.DataFrame(rgrows), pooled_ic=pic, pooled_bands=pband,
                              regime_daily=rdaily, history=hist, return_rule=rules, ic_cells=cells)

    def _pooled(self, ids, hist, fwd, horizons, bands_cfg, min_n, n_pl=0, seed=0):
        """자산군 풀링: IC 는 자산 안 순위 곱의 날짜 평균(NW t), 구간 통계는 자산 행을 그대로 합친다.
        n_pl > 0 이면 모든 자산에 같은 이동을 주는 순환 플라시보 p·sd 를 붙인다(이동 범위는 가장 짧은 자산 기준)."""
        classes = {}
        for aid in ids:
            classes.setdefault(self.config.asset(aid).asset_class, []).append(aid)
        classes["ALL"] = list(ids)
        icr, br = [], []
        for ci, (cls, members) in enumerate(classes.items()):
            for bi, blk in enumerate(BLOCKS):
                pl = {}
                if n_pl > 0:
                    nmin = min(int(hist[a].blocks[blk].notna().sum()) for a in members)
                    shifts = bt.shift_draws(nmin, n_pl, seed + 1000 + 10 * ci + bi)
                    pp = [(hist[a].blocks[blk], {hz: fwd[a][f"fwd_{hz}"] for hz in horizons}) for a in members]
                    obs, P = bt.pooled_placebo_ic(pp, shifts)
                    ph = bt.placebo_p(obs, P)
                    pl = {hz: (ph[j], np.nanstd(P[:, j]) if len(P) else np.nan) for j, hz in enumerate(horizons)}
                for hz in horizons:
                    pairs = [(hist[a].blocks[blk], fwd[a][f"fwd_{hz}"]) for a in members]
                    row = {"asset_class": cls, "assets": ",".join(members), "block": blk, "horizon": hz,
                           **bt.pooled_ic(pairs, hz)}
                    if pl:
                        row["p_placebo"], row["placebo_sd"] = pl[hz]
                        row["se_ratio"] = pl[hz][1] / (row["ic"] / row["t_nw"]) if row["t_nw"] else np.nan
                    icr.append(row)
                    allm = {}
                    for a in members:
                        sc = hist[a].blocks[blk]
                        for lab, mk in bt.band_masks(sc, bands_cfg).items():
                            allm.setdefault(lab, []).append((fwd[a][f"fwd_{hz}"][mk], fwd[a][f"mae_{hz}"]))
                    for lab, lst in allm.items():
                        f = pd.concat([x for x, _ in lst], ignore_index=True)
                        m = pd.concat([y.reindex(x.index) for x, y in lst], ignore_index=True)
                        br.append({"asset_class": cls, "block": blk, "horizon": hz, "band": lab,
                                   **bt.ret_stats(f, m, hz, min_n)})
        return pd.DataFrame(icr), pd.DataFrame(br)


def _contributions(aid: str, h: AssetScores, t: pd.Timestamp) -> list[dict]:
    """t 시점 지표별 블록 기여도. 기여도 합 = 블록 점수(가용 지표·하위블록만으로 가중치 재정규화).
    가용 가중치 합이 0 이면(모두 가중치 0) 그 블록 기여도는 NaN — scoring._weighted_mean 과 같은 규칙.

    min 하위블록(sub_block_agg)은 하위블록 값 = 최솟값 지표의 점수이므로, 그 지표(구속 지표, 동점이면 정의 순서상
    첫 지표)가 하위블록 비중 전체를 갖고 나머지 지표는 비중 0·기여도 0 이다. 하위블록이 그날 NaN 이면(시작한 지표
    하나라도 결측, scoring._min_joint) 모든 지표가 비중 0·기여도 NaN. 이렇게 해도 블록 기여도 합 = 블록 점수가 유지된다."""
    cov = h.coverage.set_index("indicator")
    rows = []
    for blk in BLOCKS:
        subs = [c for c in h.sub_blocks.columns if c[0] == blk]
        live_subs = [c for c in subs if not np.isnan(h.sub_blocks.at[t, c])]
        sw_tot = sum(h.weights[c] for c in live_subs)
        for c in subs:
            names = [n for n in h.score.columns if cov.at[n, "block"] == blk and cov.at[n, "sub_block"] == c[1]]
            live = [n for n in names if not np.isnan(h.score.at[t, n])]
            is_min = h.sub_block_agg.get(c, "mean") == "min"
            binding = min(live, key=lambda n: h.score.at[t, n]) if is_min and live else None
            iw_tot = sum(h.weights[n] for n in live)
            for n in names:
                s = h.score.at[t, n]
                if is_min:
                    ok = c in live_subs and sw_tot > 0
                    w = h.weights[c] / sw_tot if ok and n == binding else 0.0
                    rows.append({"asset_id": aid, "block": blk, "sub_block": c[1], "indicator": n,
                                 "raw": h.raw.at[t, n], "percentile": h.percentile.at[t, n], "score": s,
                                 "weight_in_block": w, "contribution": s * w if ok else np.nan})
                    continue
                ok = n in live and c in live_subs and iw_tot > 0 and sw_tot > 0
                w = (h.weights[n] / iw_tot) * (h.weights[c] / sw_tot) if ok else 0.0
                rows.append({"asset_id": aid, "block": blk, "sub_block": c[1], "indicator": n,
                             "raw": h.raw.at[t, n], "percentile": h.percentile.at[t, n], "score": s,
                             "weight_in_block": w, "contribution": s * w if ok else np.nan})
    return rows
