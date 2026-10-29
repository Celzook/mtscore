"""Phase 4 E — 채택 조건 충족 후보 3개(C1·C2·D1)를 반영했을 때 현재 점수·국면이 얼마나 바뀌는지(영향 평가, 판정 아님).

    PYTHONPATH=src .venv/bin/python scripts/phase4_impact.py

사용자 결정 1(2026-10-29, 보류)을 정하기 위한 계산이다. 설정 파일(config/*)은 바꾸지 않는다 — 변형은 메모리 안 설정 사본이다
(phase4_c.py·phase4_d.py 와 같은 방식). 점수 로직·사전 등록 판정은 건드리지 않는다.

후보
- C1 원자재 장기 반전(valuation.real_price, config/variants/phase4c.yaml). **원자재(GOLD·WTI)에만 적용**한다.
  같은 변형 파일의 fx·rates 가지는 사전 등록 판정에서 기각이라(phase4c_verdict.csv) 쓰지 않는다.
- C2 FX 금리차 수준(fundamental.macro, USDKRW).
- D1 S&P500 CAPE(valuation.multiples, SP500) — **빠진 달 건너뛰기 정의**(사용자 결정 3: E·CPI 가 모두 있는 최근 120개월).
  data/processed/phase4d_cape_e10.csv 는 달력 120개월(엄격) 정의라 2026-01-13 에서 끝난다 → 같은 코드(SH.real_e10
  skip_missing=True)로 메모리에서 다시 만든다.

입력: data/processed/panel.csv.gz + phase4c_long_panel.csv.gz(장기 필드) + Shiller/ALFRED(phase4_d 와 같은 원천).
산출(outputs/phase4/): phase4e_impact.csv(긴 형식), phase4e_impact_report.md, phase4e_run_log.txt, phase4e_cape_e10_skipmissing.csv

가정(검증 전, 보고서에도 같은 표기)
1. 새 지표는 변형 파일·phase4_d 가 정한 기존 하위블록에 지표 가중치 1(기본)로 들어간다 — 하위블록 안 동일 가중.
2. 이력 비교는 as_of=2026-10-27 로 자른 패널 하나로 만든 일별 이력(PIT)이다. 비교 구간 2013-01-01~2026-10-27.
3. '국면 라벨이 바뀐 날' 은 세 블록이 모두 점수가 있는 날(두 설정 모두)만 센다. N/A 블록이 있는 날은 별도로 센다.
4. 국면 임계값 50 은 결정 5(유지)를 그대로 쓴다.
"""
import copy
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from mtscore import ScoringEngine, load_config  # noqa: E402
from mtscore.core.scoring import BLOCKS, regime  # noqa: E402
from mtscore.data import shiller as SH  # noqa: E402
from mtscore.data.schema import validate_panel  # noqa: E402
from phase3_backtest import engine, raw_cfg  # noqa: E402
import phase4_d as P4D  # noqa: E402  (cpi_first_release·with_cape·상수 재사용; main 은 실행되지 않는다)

OUT = ROOT / "outputs" / "phase4"
PROC = ROOT / "data" / "processed"
AS_OF = "2026-10-27"
HIST_FROM = "2013-01-01"
THR_KEY = "threshold"
VARS = yaml.safe_load((ROOT / "config" / "variants" / "phase4c.yaml").read_text(encoding="utf-8"))

# 후보별 적용 자산·새 지표 이름. C1 은 원자재만(사전 등록 판정 채택 범위).
CANDS = {"C1": {"assets": ["GOLD", "WTI"], "indicator": {"GOLD": "long_reversal_60m", "WTI": "long_reversal_60m"},
                "block": "valuation", "label": "원자재 장기 반전(60개월)"},
         "C2": {"assets": ["USDKRW"], "indicator": {"USDKRW": "rate_diff_level"}, "block": "fundamental",
                "label": "환율 금리차 수준"},
         "D1": {"assets": ["SP500"], "indicator": {"SP500": "cape"}, "block": "valuation", "label": "S&P500 CAPE"}}
ARMS = ["base", "C1", "C2", "D1", "all3"]
AFFECTED = {a: c for c, v in CANDS.items() for a in v["assets"]}
BLOCK_KO = {"oversold": "과매도", "valuation": "밸류에이션", "fundamental": "펀더멘털"}


def add_variant(profs, variant, classes):
    """phase4_c.variant_profiles 와 같은 방식이되 적용 자산군을 제한한다(C1 → commodity 만)."""
    p = copy.deepcopy(profs)
    for cls, adds in VARS["variants"][variant].items():
        if cls not in classes:
            continue
        for key, items in adds.items():
            blk, sb = key.split(".")
            p[cls]["blocks"][blk][sb].extend(copy.deepcopy(items))
    return p


def arm_config(uni, profs, arm):
    use_c1, use_c2, use_d1 = arm in ("C1", "all3"), arm in ("C2", "all3"), arm in ("D1", "all3")
    p = copy.deepcopy(profs)
    if use_c1:
        p = add_variant(p, "C1", {"commodity"})
    if use_c2:
        p = add_variant(p, "C2", {"fx"})
    return (P4D.with_cape(uni) if use_d1 else copy.deepcopy(uni)), p


def hist_frame(hist):
    rows = []
    for a, h in hist.items():
        b = h.blocks.copy()
        b.index.name = "date"
        rows.append(b.reset_index().assign(asset_id=a))
    return pd.concat(rows, ignore_index=True)[["asset_id", "date", *BLOCKS]]


def same(x, y):
    """NaN 을 같은 값으로 보는 완전 일치."""
    return bool(((x == y) | (x.isna() & y.isna())).all().all())


def count_diff(a, b, cols):
    m = a.merge(b, on=["asset_id", "date"], how="outer", suffixes=("", "_ref"), indicator=True)
    out = {"rows": len(a), "rows_ref": len(b), "only_new": int((m["_merge"] == "left_only").sum()),
           "only_ref": int((m["_merge"] == "right_only").sum())}
    for c in cols:
        x, y = m[c], m[c + "_ref"]
        out[f"mismatch_{c}"] = int((~((x == y) | (x.isna() & y.isna()))).sum())
    return out


def state_label_fn(rg_cfg):
    """블록 점수 3개 → 국면 라벨(core.scoring.regime 그대로, 상태 조합별 캐시)."""
    thr = float(rg_cfg.get(THR_KEY, 50))
    cache = {}

    def f(o, v, fu):
        key = tuple("N" if np.isnan(x) else ("H" if x >= thr else "L") for x in (o, v, fu))
        if key not in cache:
            rep = {"H": 100.0, "L": 0.0, "N": np.nan}
            cache[key] = regime(dict(zip(BLOCKS, (rep[k] for k in key))), rg_cfg)["label"]
        return cache[key]
    return f


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    log = []

    def note(msg):
        print(msg, flush=True)
        log.append(str(msg))

    rows = []   # 긴 형식: section, asset_id, arm, item, value_num, value_text

    def add(section, asset, arm, item, num=None, text=None):
        rows.append({"section": section, "asset_id": asset, "arm": arm, "item": item,
                     "value_num": num, "value_text": text})

    # ---- 패널: Phase 2 + 장기 필드 + (건너뛰기 정의) CAPE 분모
    panel = pd.read_csv(PROC / "panel.csv.gz", parse_dates=["date", "as_of"])
    longp = pd.read_csv(PROC / "phase4c_long_panel.csv.gz", parse_dates=["date", "as_of"])
    sh = SH.parse_shiller_csv(P4D.SHILLER_CSV)
    cpi, cinfo = P4D.cpi_first_release(panel)
    e10s = SH.real_e10(SH.e_pit(sh), cpi, skip_missing=True)
    e10s = e10s[e10s.date <= pd.Timestamp(AS_OF)].reset_index(drop=True)
    e10_rows = e10s.drop(columns="span_months").assign(
        asset_id=P4D.ASSET, field="cape_e10",
        source="phase4e: 빠진 달 건너뛴 120개월(사용자 결정 3, SH.real_e10 skip_missing=True)")
    e10_rows[["date", "asset_id", "field", "value", "as_of", "source"]].to_csv(
        OUT / "phase4e_cape_e10_skipmissing.csv", index=False)
    full = validate_panel(pd.concat([panel, longp, e10_rows[["date", "asset_id", "field", "value", "as_of", "source"]]],
                                    ignore_index=True))
    note(f"패널 {len(panel):,}행 + 장기 필드 {len(longp):,}행 + cape_e10(건너뛰기) {len(e10s)}행 "
         f"({e10s.date.min().date()}~{e10s.date.max().date()}, 창 최대 {int(e10s.span_months.max())}개월)")
    note(f"  CPI 최초 공표값 빠진 달: {cinfo['combined_missing_months']}")

    uni, profs, sc = raw_cfg()
    rg_cfg = sc["regime"]
    ids = [a["asset_id"] for a in uni]
    label_of = state_label_fn(rg_cfg)

    # ---- 점수: 5개 설정(base·C1·C2·D1·all3) 전 자산
    res = {}
    for arm in ARMS:
        u, p = arm_config(uni, profs, arm)
        t = time.time()
        res[arm] = engine(u, p, sc).score(full, as_of=AS_OF)
        note(f"[점수] {arm} {time.time() - t:.1f}초")
    H = {arm: {a: r.history[a] for a in ids} for arm, r in res.items()}

    # ---- 3. 정합성 단언
    ref2 = pd.read_csv(ROOT / "outputs" / "phase2" / "score_history.csv.gz", parse_dates=["date"])
    eng_default = ScoringEngine(load_config(ROOT / "config"))
    sanity = {}
    for name, hist in (("default(load_config)", eng_default.score_history(full, as_of=AS_OF)),
                       ("base(raw_cfg 사본)", H["base"])):
        h = hist_frame(hist).dropna(subset=list(BLOCKS), how="all").round(4)
        d = count_diff(h, ref2, list(BLOCKS))
        sanity[name] = d
        note(f"[재현] {name} vs outputs/phase2/score_history.csv.gz(round 4): 행 {d['rows']}/{d['rows_ref']}, "
             f"불일치 {d['mismatch_oversold']}/{d['mismatch_valuation']}/{d['mismatch_fundamental']}, "
             f"한쪽에만 {d['only_new']}/{d['only_ref']}")
        assert d["rows"] == d["rows_ref"] and d["only_new"] == 0 and d["only_ref"] == 0, f"{name}: 행 집합 불일치 {d}"
        assert all(d[f"mismatch_{b}"] == 0 for b in BLOCKS), f"{name}: 기본 설정이 Phase 2 점수를 재현하지 못함 {d}"
        add("sanity", None, name, "reproduce_phase2_mismatch_total", sum(d[f"mismatch_{b}"] for b in BLOCKS))

    for arm in ARMS[1:]:
        cands = [c for c in CANDS if arm in (c, "all3")]
        touched = {a: [CANDS[c]["block"] for c in cands if a in CANDS[c]["assets"]] for a in ids}
        for a in ids:
            hb, ha = H["base"][a], H[arm][a]
            for blk in BLOCKS:
                if blk in touched.get(a, []):
                    continue
                assert same(hb.blocks[[blk]], ha.blocks[[blk]]), f"{arm} {a}: 영향 없어야 할 블록 {blk} 이 바뀜"
            common = [c for c in hb.score.columns if c in ha.score.columns]
            assert same(hb.score[common], ha.score[common]), f"{arm} {a}: 기존 지표 점수가 바뀜"
            if not touched[a]:
                assert same(hb.blocks, ha.blocks) and list(hb.score.columns) == list(ha.score.columns), \
                    f"{arm} {a}: 영향 없는 자산이 바뀜"
        n_un = sum(1 for a in ids if not touched[a])
        note(f"[불변] {arm}: 영향 없는 자산 {n_un}개 블록·지표 점수 완전 동일, 영향 자산의 다른 블록·기존 지표 점수 동일")
        add("sanity", None, arm, "unaffected_assets_identical", 1.0)
    # all3 의 영향 자산 블록 = 그 후보 단독과 완전 동일(후보 간 상호작용 없음)
    for c, v in CANDS.items():
        for a in v["assets"]:
            assert same(H["all3"][a].blocks, H[c][a].blocks), f"all3 {a} 이 {c} 단독과 다름"
    note("[불변] all3 의 영향 자산 이력 = 해당 후보 단독 이력(후보 간 상호작용 없음)")

    # ---- 1. 최근 기준일 스냅숏
    for arm in ARMS[1:]:   # 분할 진입 표시(과매도 블록 기반)·추세 표시는 후보와 무관해야 한다
        assert res[arm].staged_entry.astype(str).equals(res["base"].staged_entry.astype(str)), f"{arm}: 분할 진입 표시가 바뀜"
        assert res[arm].trend.astype(str).equals(res["base"].trend.astype(str)), f"{arm}: 추세 표시가 바뀜"
    note("[불변] 분할 진입 표시·추세 표시: 모든 설정에서 현재와 동일")
    for arm in ARMS:
        r = res[arm]
        assert (r.dates == pd.Timestamp(AS_OF)).all(), f"{arm}: 자산 기준일이 {AS_OF} 가 아님 {r.dates.to_dict()}"
        assert not r.stale.any()
        for a in ids:
            for blk in BLOCKS:
                add("snapshot", a, arm, blk, float(r.blocks.at[a, blk]))
            add("snapshot", a, arm, "regime_label", None, r.regime.at[a, "label"])
            add("snapshot", a, arm, "regime_display", None, r.regime.at[a, "display"])
        # 라벨은 이력에서 직접 다시 계산해도 같아야 한다
        for a in ids:
            b = H[arm][a].blocks.loc[pd.Timestamp(AS_OF)]
            assert label_of(*[b[k] for k in BLOCKS]) == r.regime.at[a, "label"], f"{arm} {a}: 라벨 재계산 불일치"
    ctb = res["all3"].contributions
    snap_new = {}
    for c, v in CANDS.items():
        for a in v["assets"]:
            n = v["indicator"][a]
            blk = v["block"]
            for arm in (c, "all3"):
                cc = res[arm].contributions
                row = cc[(cc.asset_id == a) & (cc.indicator == n)]
                assert len(row) == 1, f"{arm} {a} {n}: 기여도 행 {len(row)}개"
                row = row.iloc[0]
                for k in ("raw", "percentile", "score", "weight_in_block", "contribution"):
                    add("new_indicator", a, arm, f"{n}.{k}", float(row[k]))
                if arm == "all3":
                    snap_new[a] = {k: float(row[k]) for k in ("raw", "percentile", "score", "weight_in_block", "contribution")}
            # 같은 블록 기존 지표 점수·하위블록 구성(변화 원인 설명용)
            cb = res["all3"].contributions
            for r_ in cb[(cb.asset_id == a) & (cb.block == blk) & (cb.indicator != n)].itertuples():
                add("block_members", a, "all3", f"{r_.indicator}.score", float(r_.score))
                add("block_members", a, "all3", f"{r_.indicator}.weight_in_block", float(r_.weight_in_block))
            add("block_members", a, "all3", f"{n}.weight_in_block", snap_new[a]["weight_in_block"])
    # 지표 가중치 1 · 하위블록 동일 가중 확인용(가정 1): 새 지표가 속한 하위블록과 형제 지표 수
    cov = res["all3"].coverage
    for c, v in CANDS.items():
        for a in v["assets"]:
            n = v["indicator"][a]
            sb = cov[(cov.asset_id == a) & (cov.indicator == n)].iloc[0]
            sibs = cov[(cov.asset_id == a) & (cov.block == sb["block"]) & (cov.sub_block == sb["sub_block"]) & cov.used]
            add("block_members", a, "all3", f"{n}.sub_block", None, f"{sb['block']}.{sb['sub_block']}")
            add("block_members", a, "all3", f"{n}.sub_block_n_indicators", float(len(sibs)))
            add("block_members", a, "all3", f"{n}.first_score_date", None, str(pd.Timestamp(sb["first_score_date"]).date()))

    # ---- 2. 이력(2013-01-01~): 국면 라벨 변화·전이표·50선 교차
    hist_stats = []
    for a, c in AFFECTED.items():
        blk = CANDS[c]["block"]
        hb, hv = H["base"][a].blocks, H[c][a].blocks
        idx = hb.index[(hb.index >= pd.Timestamp(HIST_FROM)) & (hb.index <= pd.Timestamp(AS_OF))]
        hb, hv = hb.loc[idx], hv.loc[idx]
        lb = pd.Series([label_of(*r) for r in hb[list(BLOCKS)].to_numpy()], index=idx)
        lv = pd.Series([label_of(*r) for r in hv[list(BLOCKS)].to_numpy()], index=idx)
        full_b, full_v = hb.notna().all(axis=1), hv.notna().all(axis=1)
        both = full_b & full_v
        n_days, n_both = len(idx), int(both.sum())
        chg = (lb != lv) & both
        n_chg = int(chg.sum())
        # 그 밖의 날: 한쪽(또는 양쪽) 블록이 N/A → 라벨 비교는 별도
        part = ~both
        n_part_chg = int(((lb != lv) & part).sum())
        # 라벨 점유율
        for arm_lab, ser in (("base", lb[both]), (c, lv[both])):
            for lab, k in ser.value_counts().items():
                add("hist_label_days", a, arm_lab, lab, float(k))
        for yr, k in chg[chg].groupby(chg[chg].index.year).size().items():
            add("hist_label_changed_by_year", a, c, str(yr), float(k))
        trans = pd.crosstab(lb[chg].rename("from"), lv[chg].rename("to"))
        for f_, row in trans.iterrows():
            for t_, k in row.items():
                if k:
                    add("hist_transition", a, c, f"{f_} -> {t_}", float(k))
        # 블록의 50선 교차
        thr = float(rg_cfg.get(THR_KEY, 50))
        sb_, sv_ = hb[blk], hv[blk]
        bb = sb_.notna() & sv_.notna()
        diff = bb & ((sb_ >= thr) != (sv_ >= thr))
        down = bb & (sb_ >= thr) & (sv_ < thr)
        up = bb & (sb_ < thr) & (sv_ >= thr)
        dlt = (sv_ - sb_)[bb]
        stat = {"asset_id": a, "candidate": c, "block": blk, "n_days": n_days,
                "n_days_all_blocks_both": n_both, "n_days_label_changed": n_chg,
                "pct_label_changed": 100 * n_chg / n_both if n_both else np.nan,
                "n_days_partial_label_changed": n_part_chg, "n_days_na_in_either": int(part.sum()),
                "n_days_block_both": int(bb.sum()), "n_block_cross50": int(diff.sum()),
                "pct_block_cross50": 100 * diff.sum() / bb.sum() if bb.sum() else np.nan,
                "n_cross_down": int(down.sum()), "n_cross_up": int(up.sum()),
                "pct_block_ge50_base": 100 * (sb_[bb] >= thr).mean(), "pct_block_ge50_variant": 100 * (sv_[bb] >= thr).mean(),
                "block_mean_base": float(sb_[bb].mean()), "block_mean_variant": float(sv_[bb].mean()),
                "block_delta_mean": float(dlt.mean()), "block_delta_mean_abs": float(dlt.abs().mean()),
                "block_delta_min": float(dlt.min()), "block_delta_max": float(dlt.max()),
                "first_day_both": str(idx[both.to_numpy()][0].date()) if n_both else None,
                "block_first_base": str(sb_.first_valid_index().date()) if sb_.notna().any() else None,
                "block_first_variant": str(sv_.first_valid_index().date()) if sv_.notna().any() else None}
        hist_stats.append(stat)
        for k, v in stat.items():
            if k in ("asset_id", "candidate"):
                continue
            add("hist_summary", a, c, k, v if isinstance(v, (int, float, np.integer, np.floating)) else None,
                None if isinstance(v, (int, float, np.integer, np.floating)) else v)
        note(f"[이력] {a}({c}) {HIST_FROM}~{AS_OF}: 3블록 모두 있는 날 {n_both}/{n_days}, 국면 라벨 변경 {n_chg}일 "
             f"({stat['pct_label_changed']:.1f}%), {BLOCK_KO[blk]} 50선 교차 {int(diff.sum())}일 "
             f"({stat['pct_block_cross50']:.1f}%: 내려감 {int(down.sum())}·올라감 {int(up.sum())}), "
             f"블록 평균 {stat['block_mean_base']:.1f}→{stat['block_mean_variant']:.1f}")
    HS = pd.DataFrame(hist_stats)

    # ---- 4. SP500 CAPE: 현재 위치와 이력상 하락폭
    sp_b, sp_v = H["base"]["SP500"], H["D1"]["SP500"]
    cape_raw = sp_v.raw["cape"]
    cape_pct = sp_v.percentile["cape"]
    cape_sc = sp_v.score["cape"]
    first_cape = cape_sc.first_valid_index()
    last_cape_rows = cape_sc.dropna()
    sp_note = {"cape_last_raw": float(cape_raw.dropna().iloc[-1]), "cape_last_pct": float(cape_pct.dropna().iloc[-1]),
               "cape_last_score": float(last_cape_rows.iloc[-1]), "cape_first_score_date": str(first_cape.date()),
               "valuation_base_last": float(sp_b.blocks["valuation"].iloc[-1]),
               "valuation_d1_last": float(sp_v.blocks["valuation"].iloc[-1]),
               "n_cape_score_days": int(last_cape_rows.shape[0]),
               "cape_score_lt5_share_pct": float(100 * (last_cape_rows < 5).mean()),
               "cape_score_lt20_share_pct": float(100 * (last_cape_rows < 20).mean()),
               "cape_raw_max": float(cape_raw.max()), "cape_raw_max_date": str(cape_raw.idxmax().date()),
               "cape_score_min_date": str(last_cape_rows.idxmin().date())}
    vb, vv = sp_b.blocks["valuation"], sp_v.blocks["valuation"]
    m = vb.notna() & vv.notna() & (vb.index >= pd.Timestamp(HIST_FROM))
    # 최근 구간별 평균 하락폭(2013~2019 / 2020~, 사전 등록 선택·확인 구간)
    for lab, lo, hi in (("2013-2019", "2013-01-01", "2019-12-31"), ("2020-2026", "2020-01-01", AS_OF)):
        mm = m & (vb.index >= pd.Timestamp(lo)) & (vb.index <= pd.Timestamp(hi))
        sp_note[f"valuation_delta_mean_{lab}"] = float((vv - vb)[mm].mean())
        sp_note[f"valuation_base_mean_{lab}"] = float(vb[mm].mean())
        sp_note[f"valuation_d1_mean_{lab}"] = float(vv[mm].mean())
        sp_note[f"valuation_delta_min_{lab}"] = float((vv - vb)[mm].min())
        sp_note[f"valuation_delta_max_{lab}"] = float((vv - vb)[mm].max())
    for k, v in sp_note.items():
        add("sp500_cape", "SP500", "D1", k, v if isinstance(v, (int, float)) else None, v if isinstance(v, str) else None)
    note(f"[SP500 CAPE] {json.dumps(sp_note, ensure_ascii=False)}")

    imp = pd.DataFrame(rows)
    imp.to_csv(OUT / "phase4e_impact.csv", index=False)

    # 이전 Phase 4 D-1 의 민감도 기록(2026-10-27 CAPE 41.23, 점수 2.04, 밸류에이션 11.9)과 대조 — 정보용
    prev = json.loads((OUT / "phase4d_run_info.json").read_text(encoding="utf-8"))["e10_sensitivity_skip_missing"]
    note(f"[대조] phase4d 민감도 기록 cape {prev['cape_last']}·점수 {prev['cape_score_last']}·밸류 {prev['valuation_last']} vs "
         f"이번 {sp_note['cape_last_raw']:.2f}·{sp_note['cape_last_score']:.2f}·{sp_note['valuation_d1_last']:.2f}")
    assert abs(prev["cape_last"] - sp_note["cape_last_raw"]) < 0.01 and abs(prev["cape_score_last"] - sp_note["cape_last_score"]) < 0.01 \
        and abs(prev["valuation_last"] - sp_note["valuation_d1_last"]) < 0.01, "phase4d 민감도 기록과 불일치"

    write_report(res, H, HS, snap_new, sp_note, sanity, cinfo, e10s, ids)
    note(f"총 {time.time() - t0:.1f}초")
    (OUT / "phase4e_run_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")


def fnum(x, d=1):
    return "N/A" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{d}f}"


def write_report(res, H, HS, snap_new, sp, sanity, cinfo, e10s, ids):
    imp = pd.read_csv(OUT / "phase4e_impact.csv")
    snap = imp[imp.section == "snapshot"]

    def blk(a, arm, b):
        return float(snap[(snap.asset_id == a) & (snap.arm == arm) & (snap.item == b)].value_num.iloc[0])

    def lab(a, arm):
        return snap[(snap.asset_id == a) & (snap.arm == arm) & (snap.item == "regime_label")].value_text.iloc[0]

    L = []
    w = L.append
    w("# Phase 4 E — 후보 3개를 반영하면 현재 점수·국면이 얼마나 바뀌나 (영향 평가)")
    w("")
    w(f"기준일 {AS_OF} · 비교 구간 {HIST_FROM}~{AS_OF} · 이 문서는 **채택 여부를 정하는 글이 아니라, 사용자 결정 1을 정하기 위한 '반영 전후 비교'** 다. "
      "설정 파일은 바꾸지 않았고, 모든 수치는 메모리 안 설정 사본으로 다시 계산했다.")
    w("")
    w("## 0. 한눈에 보기")
    w("")
    d = {a: (blk(a, "base", b), blk(a, "all3", b)) for a in AFFECTED for b in [CANDS[AFFECTED[a]]["block"]]}
    chg_assets = [a for a in AFFECTED if lab(a, "base") != lab(a, "all3")]
    w(f"- 바뀌는 자산은 4개(금·WTI·USDKRW·S&P500)뿐이다. 나머지 6개(KOSPI200·KTB10Y·UST10Y·US_HY·US_IG·KR_CORP)는 "
      "블록 점수·지표 점수가 완전히 같다(코드로 단언).")
    w(f"- 현재(2026-10-27) 국면 라벨이 바뀌는 자산: **{', '.join(chg_assets) if chg_assets else '없음'}**.")
    mv = sorted(((abs(d[a][1] - d[a][0]), a) for a in d), reverse=True)
    w("- 현재 블록 점수 변화량(절댓값) 순: " + ", ".join(f"{a} {BLOCK_KO[CANDS[AFFECTED[a]]['block']]} {d[a][0]:.1f} → {d[a][1]:.1f}" for _, a in mv) + ".")
    if "USDKRW" in chg_assets:
        w(f"- USDKRW 는 펀더멘털이 50선 바로 위({d['USDKRW'][0]:.1f})에 있어, 환율 금리차 수준(점수 {snap_new['USDKRW']['score']:.1f}) 하나가 들어오면 50 아래({d['USDKRW'][1]:.1f})로 내려가 라벨이 '{lab('USDKRW', 'base')}' → '{lab('USDKRW', 'all3')}' 로 바뀐다.")
    w(f"- S&P500 는 CAPE 점수가 {snap_new['SP500']['score']:.1f}(자기 역사 최상위권)이지만 밸류에이션이 이미 낮아({d['SP500'][0]:.1f}) 라벨은 그대로다.")
    w("- 기본 설정은 Phase 2 점수 이력(`outputs/phase2/score_history.csv.gz`)을 한 행도 틀리지 않고 재현한다(단언 통과).")
    w("")
    w("## 1. 지금(2026-10-27) 점수와 국면: 현재 vs 3개 모두 반영")
    w("")
    w("블록 점수는 0~100(클수록 매수 매력), 국면은 세 블록을 50점 기준 높음/낮음으로 나눠 정한다. 괄호는 반영으로 인한 변화량이다.")
    w("")
    w("| 자산 | 과매도 | 밸류에이션 | 펀더멘털 | 국면 (현재) | 국면 (3개 반영) |")
    w("|---|---|---|---|---|---|")
    for a in ids:
        cells = []
        for b in BLOCKS:
            x0, x1 = blk(a, "base", b), blk(a, "all3", b)
            cells.append(fnum(x0) if abs(x1 - x0) < 1e-9 or np.isnan(x0) else f"{x0:.1f} → **{x1:.1f}** ({x1 - x0:+.1f})")
        l0, l1 = lab(a, "base"), lab(a, "all3")
        w(f"| {a} | {cells[0]} | {cells[1]} | {cells[2]} | {l0} | {l1 if l0 == l1 else '**' + l1 + '**'} |")
    w("")
    w("### 1-1. 후보를 하나씩만 반영했을 때 (영향받는 자산)")
    w("")
    w("| 후보 | 자산 | 바뀌는 블록 | 현재 | 단독 반영 | 국면 (현재 → 단독 반영) |")
    w("|---|---|---|---|---|---|")
    for c, v in CANDS.items():
        for a in v["assets"]:
            b = v["block"]
            x0, x1 = blk(a, "base", b), blk(a, c, b)
            l0, l1 = lab(a, "base"), lab(a, c)
            w(f"| {c} {v['label']} | {a} | {BLOCK_KO[b]} | {x0:.1f} | {x1:.1f} ({x1 - x0:+.1f}) | {l0} → {l1} |")
    w("")
    w("### 1-2. 새 지표의 현재 값")
    w("")
    w("'자기 역사 백분위' 는 그 자산의 과거 값 중 지금보다 낮은 비율이다. 점수 = 방향을 반영한 백분위(CAPE·REER 처럼 '높을수록 비싼' 지표는 100 − 백분위).")
    w("")
    w("| 후보 | 자산 | 새 지표 | 원값 | 자기 역사 백분위 | 지표 점수 | 소속 하위블록(지표 수) | 블록 내 비중 |")
    w("|---|---|---|---|---|---|---|---|")
    members = imp[imp.section == "block_members"]
    for c, v in CANDS.items():
        for a in v["assets"]:
            n = v["indicator"][a]
            s = snap_new[a]
            sbn = members[(members.asset_id == a) & (members.item == f"{n}.sub_block")].value_text.iloc[0]
            nn = int(members[(members.asset_id == a) & (members.item == f"{n}.sub_block_n_indicators")].value_num.iloc[0])
            w(f"| {c} | {a} | `{n}` | {fnum(s['raw'], 3)} | {fnum(s['percentile'], 1)} | {fnum(s['score'], 1)} | {sbn} ({nn}) | {s['weight_in_block'] * 100:.0f}% |")
    w("")
    w("원값의 뜻: `long_reversal_60m` = 60개월 가격 변화율(0.80 = +80%, 많이 오를수록 비싸다고 보아 점수가 낮다), `rate_diff_level` = 한국 국채 10년 − 미국 국채 10년 금리(%p, 높을수록 원화 매수에 유리), `cape` = 종가 ÷ 10년 평균 실질이익.")
    w("")
    w("`rate_diff_level` 은 같은 하위블록의 기존 지표 `rate_diff_chg_3m` 과 같은 원천(`rate_diff`)을 쓴다(수준 vs 3개월 변화). 사전 등록 중복 점검(상관 > 0.9)은 통과했다 — 기록: `outputs/phase4/phase4c_redundancy.csv`.")
    w("")
    w("같은 하위블록의 기존 지표(참고) — 새 지표 점수가 이들과 얼마나 다른지 보면 변화 원인을 알 수 있다.")
    w("")
    w("| 자산 | 기존 지표 | 점수 |")
    w("|---|---|---|")
    for a in AFFECTED:
        n = CANDS[AFFECTED[a]]["indicator"][a]
        mm = members[(members.asset_id == a) & members.item.str.endswith(".score")]
        for r_ in mm.itertuples():
            w(f"| {a} | `{r_.item[:-6]}` | {r_.value_num:.1f} |")
    w("")
    w("## 2. 과거 이력: 2013-01 ~ 2026-10 에 국면이 얼마나 달라지나")
    w("")
    w("'바뀐 날' = 같은 날 현재 설정과 반영 설정의 국면 라벨이 다른 날(두 설정 모두 세 블록이 다 있는 날만 센다). "
      "'50선 교차' = 해당 블록 점수가 한쪽은 50 이상, 한쪽은 50 미만인 날 — 국면의 높음/낮음 판정이 갈리는 날이다.")
    w("")
    w("| 자산(후보) | 비교한 날 | 국면 라벨이 바뀐 날 | 비율 | 바뀐 블록 | 블록 50선 교차 | 내려감 / 올라감 | 블록 평균 (현재 → 반영) | 50 이상인 날 비율 (현재 → 반영) |")
    w("|---|---|---|---|---|---|---|---|---|")
    for r_ in HS.itertuples():
        w(f"| {r_.asset_id} ({r_.candidate}) | {r_.n_days_all_blocks_both:,} | {r_.n_days_label_changed:,} | {r_.pct_label_changed:.1f}% | "
          f"{BLOCK_KO[r_.block]} | {r_.n_block_cross50:,} ({r_.pct_block_cross50:.1f}%) | {r_.n_cross_down:,} / {r_.n_cross_up:,} | "
          f"{r_.block_mean_base:.1f} → {r_.block_mean_variant:.1f} | {r_.pct_block_ge50_base:.0f}% → {r_.pct_block_ge50_variant:.0f}% |")
    w("")
    note_days = HS[["asset_id", "n_days", "n_days_all_blocks_both", "n_days_na_in_either", "n_days_partial_label_changed"]]
    w("비교하지 않은 날(어느 한쪽 설정에서 블록이 N/A — 새 지표 때문에 시작일이 달라지는 경우 포함): "
      + ", ".join(f"{r_.asset_id} {r_.n_days_na_in_either}일(그중 부분판정 라벨이 달랐던 날 {r_.n_days_partial_label_changed}일)" for r_ in note_days.itertuples()) + ".")
    w("")
    by = imp[imp.section == "hist_label_changed_by_year"]
    for r0 in HS.itertuples():
        t = by[by.asset_id == r0.asset_id].sort_values("value_num", ascending=False).head(4)
        if len(t):
            w(f"- {r0.asset_id}: 라벨이 바뀐 날이 많은 연도 " + ", ".join(f"{q.item}년 {int(q.value_num)}일" for q in t.itertuples()))
    w("")
    w("### 2-1. 국면 전이표 (현재 라벨 → 반영 후 라벨, 일수)")
    w("")
    tr = imp[imp.section == "hist_transition"]
    for r0 in HS.itertuples():
        a = r0.asset_id
        t = tr[tr.asset_id == a].sort_values("value_num", ascending=False)
        w(f"**{a} ({r0.candidate})** — 바뀐 {r0.n_days_label_changed:,}일")
        w("")
        if t.empty:
            w("- 바뀐 날 없음")
        else:
            w("| 현재 라벨 → 반영 후 라벨 | 일수 | 바뀐 날 중 비중 |")
            w("|---|---|---|")
            for q in t.itertuples():
                w(f"| {q.item.replace(' -> ', ' → ')} | {int(q.value_num):,} | {100 * q.value_num / r0.n_days_label_changed:.0f}% |")
        w("")
    w("## 3. 정합성 확인 (코드 단언, 하나라도 어긋나면 스크립트가 멈춘다)")
    w("")
    for k, v in sanity.items():
        w(f"- {k} 설정으로 만든 점수 이력 {v['rows']:,}행 = `outputs/phase2/score_history.csv.gz` {v['rows_ref']:,}행, 블록 불일치 "
          f"{v['mismatch_oversold']}/{v['mismatch_valuation']}/{v['mismatch_fundamental']}건, 한쪽에만 있는 행 {v['only_new']}/{v['only_ref']}.")
    w("- 영향 없는 자산 6개: 세 블록 이력·지표 점수·지표 목록이 모든 설정에서 현재와 완전히 같다.")
    w("- 영향 자산도 바뀌는 블록 외 다른 블록과 기존 지표 점수는 같다. 3개 동시 반영의 영향 자산 이력은 해당 후보 단독 이력과 같다(후보끼리 간섭 없음).")
    w(f"- 이전 Phase 4 D-1 민감도 기록(2026-10-27 CAPE 41.23·점수 2.04·밸류에이션 11.9)을 이번에 다시 만든 값과 대조해 일치했다.")
    w("")
    w("## 4. S&P500 CAPE — 밸류에이션을 얼마나 끌어내리나")
    w("")
    w(f"- 지금 CAPE 는 **{sp['cape_last_raw']:.2f}**, 자기 역사(2009년 말 이후 계산 가능한 값) 백분위 **{sp['cape_last_pct']:.1f}**% → 지표 점수 **{sp['cape_last_score']:.1f}** "
      "(역사상 거의 가장 비싼 구간이라 0~2 점대, 방향이 '높을수록 비쌈' 이라 점수가 낮다).")
    w(f"- 밸류에이션 블록은 `per_fwd_12m`·`erp`·`cape` 세 지표의 동일 가중 평균이 된다(각 1/3). 현재 {sp['valuation_base_last']:.2f} → **{sp['valuation_d1_last']:.2f}** "
      f"({sp['valuation_d1_last'] - sp['valuation_base_last']:+.2f}). 두 기존 지표의 평균 점수가 이미 낮아(50 미만) 국면은 '낮음' 그대로라 라벨은 {'바뀌지 않는다' if lab('SP500', 'base') == lab('SP500', 'D1') else '바뀐다'}.")
    w(f"- 이력으로 보면 CAPE 점수가 5 미만인 날이 전체의 {sp['cape_score_lt5_share_pct']:.0f}%, 20 미만인 날이 {sp['cape_score_lt20_share_pct']:.0f}% 다 "
      f"(CAPE 점수 이력 {sp['n_cape_score_days']:,}일, 첫 점수일 {sp['cape_first_score_date']}). 지표 자체는 대부분의 날 매우 낮은 점수를 낸다.")
    w(f"- 밸류에이션 블록의 반영 전후 평균 차: 2013~2019 {sp['valuation_delta_mean_2013-2019']:+.1f}점 "
      f"(평균 {sp['valuation_base_mean_2013-2019']:.1f} → {sp['valuation_d1_mean_2013-2019']:.1f}), "
      f"2020~2026 {sp['valuation_delta_mean_2020-2026']:+.1f}점 (평균 {sp['valuation_base_mean_2020-2026']:.1f} → {sp['valuation_d1_mean_2020-2026']:.1f}). "
      f"하루 최대 하락 {sp['valuation_delta_min_2013-2019']:.1f}(2013~2019)·{sp['valuation_delta_min_2020-2026']:.1f}(2020~2026).")
    w("- 해석: 이력 전체로 보면 평균 하락폭은 구간에 따라 다르다(2013~2019 는 낮추고, 2020~ 은 기존 두 지표도 이미 낮아 거의 같다). 즉 CAPE 는 '늘 밸류에이션을 끌어내리는 지표' 가 아니라, "
      "기존 두 지표(Fwd PER·ERP)와 순위 신호가 달라지는 날에 점수를 움직인다. 사전 등록 채택 근거는 IC(순위 상관) 개선이었고, 점수 수준이 낮아지는 효과는 별개다(가정: 국면 판정 50선 용도에서는 이 차이를 감안).")
    w("")
    w("## 5. 가정과 한계")
    w("")
    w("- **가정**: 새 지표는 변형 파일·phase4_d 가 정한 기존 하위블록에 가중치 1로 들어간다(하위블록 안 동일 가중). 다른 배치(별도 하위블록·다른 가중)에서는 변화량이 달라진다.")
    w("- **가정**: C1 은 사전 등록 판정에서 채택된 원자재(금·WTI)에만 적용했다. 같은 변형 파일의 환율·금리 가지는 기각이라 쓰지 않았다.")
    w(f"- **가정**: D1 은 '빠진 달 건너뛰기' 정의(결정 3, 결과를 본 뒤의 사후 수정)다. CPI 2025-10 이 공표되지 않아 이 정의의 창이 2026-02 부터 달력 121개월에 걸친다(최대 {int(e10s.span_months.max())}개월). "
      "엄격 정의(달력 120개월)는 2026-01-13 에서 값이 끊겨 현재 점수를 낼 수 없다.")
    w("- 이력은 '그날까지 알려진 정보만' 쓰는 일별 점수(PIT)다. 새 지표가 시작하는 날짜가 달라 비교 가능한 일수가 자산마다 다르다.")
    w("- 이 문서는 '바뀌는 정도' 만 보인다. 바뀐 점수가 더 나은지는 사전 등록 IC 판정(Phase 4 C·D)이 이미 채택으로 답한 부분이고, 채택 여부의 최종 결정은 사용자 몫이다.")
    w("")
    w("## 6. 파일과 재현")
    w("")
    w("- `scripts/phase4_impact.py` — 계산 스크립트(설정 파일은 읽기만)")
    w("- `outputs/phase4/phase4e_impact.csv` — 긴 형식 결과(section·asset_id·arm·item·값)")
    w("- `outputs/phase4/phase4e_impact_report.md` — 이 문서")
    w("- `outputs/phase4/phase4e_run_log.txt` — 실행 로그")
    w("- `outputs/phase4/phase4e_cape_e10_skipmissing.csv` — 건너뛰기 정의 CAPE 분모 필드(재생성본)")
    w("")
    w("재현: `cd /home/infomax/Desktop/Infomax/_project/mtscore && PYTHONPATH=src .venv/bin/python scripts/phase4_impact.py`")
    (OUT / "phase4e_impact_report.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
