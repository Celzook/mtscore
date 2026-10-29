"""Phase 4 단계 C — 장기 반전(C1)·FX 캐리 수준(C2) 사전 등록 검증(docs/prereg_2026-10-29.md, 튜닝 없음).

    .venv/bin/python scripts/phase4c_build.py     # 장기 필드 패널(먼저)
    .venv/bin/python scripts/phase4_c.py

입력: data/processed/panel.csv.gz(Phase 2, 읽기만) + data/processed/phase4c_long_panel.csv.gz(장기 필드).
설정 파일(config/profiles·universe·scoring)은 바꾸지 않는다. 변형은 config/variants/phase4c.yaml 의 지표를 설정 사본의
프로파일 하위블록에 붙여 만든다(메모리 안).
산출(outputs/phase4/phase4c_*): 재현 대조·커버리지·중복 점검·분할 IC·판정표·실행 로그.

판정(사전 등록 §1): 해당 블록(C1 = 밸류에이션, C2 = 펀더멘털) 자산군 풀링 Spearman IC, 시평 63일.
선택 구간 2013-01-01~2019-12-31 / 확인 구간 2020-01-01~(관측 시작일 기준). 채택 = 선택 IC > 기준선 AND 확인 IC ≥ 기준선
AND 확인 구간 플라시보 p ≤ 기준선 p. 플라시보는 Phase 3 설정(2,000회, 이동 [252, n−252), 모든 자산 같은 이동)이고
기준선과 변형에 같은 이동 배열을 준다(몬테카를로 잡음이 판정을 가르지 않게). 21·126·252일은 보조.
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
from mtscore.core import backtest as bt  # noqa: E402
from phase3_backtest import engine, raw_cfg  # noqa: E402  (Phase 3 와 같은 설정 사본 방식)

OUT = ROOT / "outputs" / "phase4"
PROC = ROOT / "data" / "processed"
AS_OF = "2026-10-27"                    # Phase 2 점수 기준일
PRIMARY_H = 63                          # 사전 등록 §1
CORR_CUT = 0.9                          # 사전 등록 §1 · Phase 3 §6-3
PERIODS = {"selection": ("2013-01-01", "2019-12-31"), "confirmation": ("2020-01-01", None)}
SEED_OFFSET = 4000                      # 플라시보 시드 = backtest.placebo_seed + 4000 + 10·자산군 순번 + 구간 순번(고정)
CLASSES = {"commodity": ["GOLD", "WTI"], "fx": ["USDKRW"], "rates": ["KTB10Y", "UST10Y"]}
VARIANT_BLOCK = {"C1": "valuation", "C2": "fundamental"}
NEW_IND = {"C1": "long_reversal_60m", "C2": "rate_diff_level"}
EXISTING = {   # 중복 점검 대상(같은 블록 기존 지표; 자산에서 빠진 지표는 점수 열에 없어 자동 제외)
    "C1": {"commodity": ["real_price_level", "real_price_level_spot"], "fx": ["reer_level"],
           "rates": ["real_yield", "spread_to_policy", "term_premium"]},
    "C2": {"fx": ["rate_diff_chg_3m"]}}
VARS = yaml.safe_load((ROOT / "config" / "variants" / "phase4c.yaml").read_text(encoding="utf-8"))


def variant_profiles(profs, variant):
    """설정 사본의 프로파일 하위블록에 변형 지표를 붙인다(기존 하위블록 — 사전 등록 '블록 구조 그대로')."""
    p = copy.deepcopy(profs)
    for cls, adds in VARS["variants"][variant].items():
        for key, items in adds.items():
            blk, sb = key.split(".")
            p[cls]["blocks"][blk][sb].extend(copy.deepcopy(items))
    return p


def window(idx, per):
    lo, hi = PERIODS[per]
    m = idx >= pd.Timestamp(lo)
    return m & (idx <= pd.Timestamp(hi)) if hi else m


def hist_frame(hist):
    rows = []
    for a, h in hist.items():
        b = h.blocks.copy()
        b.index.name = "date"
        rows.append(b.reset_index().assign(asset_id=a))
    return pd.concat(rows, ignore_index=True)[["asset_id", "date", "oversold", "valuation", "fundamental"]]


def diff_blocks(a, b, cols, keys=("asset_id", "date")):
    m = a.merge(b, on=list(keys), how="outer", suffixes=("", "_ref"), indicator=True)
    out = {"rows": int(len(a)), "rows_ref": int(len(b)), "only_new": int((m["_merge"] == "left_only").sum()),
           "only_ref": int((m["_merge"] == "right_only").sum())}
    for c in cols:
        x, y = m[c], m[c + "_ref"]
        out[f"mismatch_{c}"] = int((~((x == y) | (x.isna() & y.isna()))).sum())
        out[f"maxabs_{c}"] = float((x - y).abs().max())
    return out


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    log = []

    def note(msg):
        print(msg, flush=True)
        log.append(msg)

    panel = pd.read_csv(PROC / "panel.csv.gz", parse_dates=["date", "as_of"])
    longp = pd.read_csv(PROC / "phase4c_long_panel.csv.gz", parse_dates=["date", "as_of"])
    full = pd.concat([panel, longp], ignore_index=True)
    note(f"패널 {len(panel):,}행 + 장기 필드 {len(longp):,}행")
    uni, profs, sc = raw_cfg()
    n_pl, seed0 = int(sc["backtest"]["placebo_shifts"]), int(sc["backtest"]["placebo_seed"])
    horizons = [int(h) for h in sc["backtest"]["horizons"]]

    # ---- C5. 기본 설정 재현: Phase 2 score_history(4자리 반올림)·Phase 3 forward 파일 블록(6자리)과 대조
    ref2 = pd.read_csv(ROOT / "outputs" / "phase2" / "score_history.csv.gz", parse_dates=["date"])
    ref3 = pd.read_csv(PROC / "phase3_forward_returns.csv.gz", parse_dates=["date"])
    ref3 = ref3[["asset_id", "date", "oversold", "valuation", "fundamental"]]
    eng0 = ScoringEngine(load_config(ROOT / "config"))
    rep = []
    for name, p in (("panel", panel), ("panel+long", full)):
        h = hist_frame(eng0.score_history(p, as_of=AS_OF))
        h2 = h.dropna(subset=["oversold", "valuation", "fundamental"], how="all").round(4)
        rep.append({"input": name, "reference": "outputs/phase2/score_history.csv.gz(round 4)",
                    **diff_blocks(h2, ref2, ["oversold", "valuation", "fundamental"])})
        rep.append({"input": name, "reference": "data/processed/phase3_forward_returns.csv.gz(round 6)",
                    **diff_blocks(h.round(6), ref3, ["oversold", "valuation", "fundamental"])})
    rep = pd.DataFrame(rep)
    rep.to_csv(OUT / "phase4c_reproduce_diff.csv", index=False)
    for r in rep.to_dict("records"):
        note(f"[재현] {r['input']} vs {r['reference']}: 행 {r['rows']}/{r['rows_ref']}, 불일치 "
             f"{r['mismatch_oversold']}/{r['mismatch_valuation']}/{r['mismatch_fundamental']}, "
             f"한쪽에만 {r['only_new']}/{r['only_ref']}")

    # ---- 점수 이력(기준선·변형) + forward return(기준선 1회 — 수익은 점수와 무관)
    ids = [a for m in CLASSES.values() for a in m]
    base_eng = engine(uni, profs, sc)
    res = base_eng.backtest(full, asset_ids=ids, placebo=0)
    hist = {"base": res.history}
    for v in VARIANT_BLOCK:
        hist[v] = engine(uni, variant_profiles(profs, v), sc).score_history(full, asset_ids=ids)
        note(f"[점수] 변형 {v} 완료")
    fwd = res.forward

    # 변형이 기존 지표 점수를 바꾸지 않는지(해당 블록 외 블록과 기존 지표 열이 같아야 한다)
    inv = []
    for v, blk in VARIANT_BLOCK.items():
        for a in ids:
            hb, hv = hist["base"][a], hist[v][a]
            common = [c for c in hb.score.columns if c in hv.score.columns]
            d_ind = float((hb.score[common] - hv.score[common]).abs().max().max())
            same_ind = bool(((hb.score[common] == hv.score[common]) | (hb.score[common].isna() & hv.score[common].isna()))
                            .all().all())
            other = [b for b in ("oversold", "valuation", "fundamental") if b != blk]
            same_other = bool(((hb.blocks[other] == hv.blocks[other]) | (hb.blocks[other].isna() & hv.blocks[other].isna()))
                              .all().all())
            inv.append({"variant": v, "asset_id": a, "existing_indicator_scores_identical": same_ind,
                        "max_abs_diff_existing": d_ind, "other_blocks_identical": same_other,
                        "new_in_variant": ",".join(sorted(set(hv.score.columns) - set(hb.score.columns)))})
    inv = pd.DataFrame(inv)
    inv.to_csv(OUT / "phase4c_invariance.csv", index=False)
    note(f"[불변] 기존 지표 점수 동일 {inv.existing_indicator_scores_identical.all()}, "
         f"다른 블록 동일 {inv.other_blocks_identical.all()}")

    # ---- 커버리지: 새 지표 첫 원값·첫 점수일
    cov = []
    for v in VARIANT_BLOCK:
        for cls in VARS["variants"][v]:
            for a in CLASSES[cls]:
                h = hist[v][a]
                n = NEW_IND[v]
                cov.append({"variant": v, "asset_id": a, "indicator": n,
                            "first_raw": h.raw[n].first_valid_index() if n in h.raw else None,
                            "first_score": h.score[n].first_valid_index() if n in h.score else None,
                            "n_score_selection": int(h.score[n][window(h.score.index, "selection")].notna().sum()),
                            "n_score_confirmation": int(h.score[n][window(h.score.index, "confirmation")].notna().sum()),
                            "block_first_score_base": hist["base"][a].blocks[VARIANT_BLOCK[v]].first_valid_index(),
                            "selection_meaningful(first_score<=2013-12-31)":
                                bool(h.score[n].first_valid_index() is not None
                                     and h.score[n].first_valid_index() <= pd.Timestamp("2013-12-31"))})
    cov = pd.DataFrame(cov)
    cov.to_csv(OUT / "phase4c_coverage.csv", index=False)
    for r in cov.to_dict("records"):
        note(f"[커버리지] {r['variant']} {r['asset_id']}: 첫 원값 {r['first_raw']}, 첫 점수 {r['first_score']}")

    # ---- C3. 중복 점검(선택 구간 지표 점수 Pearson; 자산군 풀링 = 자산 행 이어 붙임, 자산별 보조)
    red, ind_ic = [], []
    for v, per_cls in EXISTING.items():
        n = NEW_IND[v]
        for cls, olds in per_cls.items():
            members = CLASSES[cls]
            sel = {a: hist[v][a].score[window(hist[v][a].score.index, "selection")] for a in members}
            for ind in [n] + olds:
                pairs = [(sel[a][ind], fwd[a][f"fwd_{PRIMARY_H}"]) for a in members if ind in sel[a]]
                if pairs:
                    ind_ic.append({"variant": v, "asset_class": cls, "indicator": ind, "horizon": PRIMARY_H,
                                   "period": "selection", **bt.pooled_ic(pairs, PRIMARY_H)})
            ic_of = {r["indicator"]: r["ic"] for r in ind_ic if r["variant"] == v and r["asset_class"] == cls}
            for o in olds:
                have = [a for a in members if o in sel[a]]
                if not have:
                    red.append({"variant": v, "asset_class": cls, "new": n, "existing": o, "note": "이 자산군에서 제외된 지표"})
                    continue
                pooled = pd.concat([sel[a][[n, o]] for a in have]).corr().iat[0, 1]
                per_a = {f"corr_{a}": sel[a][[n, o]].corr().iat[0, 1] for a in have}
                n_pair = int(pd.concat([sel[a][[n, o]] for a in have]).dropna().shape[0])
                hit = bool(pooled > CORR_CUT)
                lower = n if ic_of.get(n, np.nan) < ic_of.get(o, np.nan) else o
                red.append({"variant": v, "asset_class": cls, "new": n, "existing": o, "assets": ",".join(have),
                            "n_pairs": n_pair, "corr_selection_pooled": pooled, **per_a, "over_cut": hit,
                            f"ic{PRIMARY_H}_new": ic_of.get(n), f"ic{PRIMARY_H}_existing": ic_of.get(o),
                            "candidate": lower if hit else "",
                            "over_cut_any_asset": bool(any(x > CORR_CUT for x in per_a.values() if pd.notna(x)))})
    red = pd.DataFrame(red)
    red.to_csv(OUT / "phase4c_redundancy.csv", index=False)
    pd.DataFrame(ind_ic).to_csv(OUT / "phase4c_indicator_ic_selection.csv", index=False)
    cands = red[red.get("over_cut", False) == True]  # noqa: E712
    note(f"[중복] 0.9 초과 쌍(풀링): {len(cands)}개" + (": " + ", ".join(f"{r.new}~{r.existing}" for r in cands.itertuples())
                                                     if len(cands) else ""))

    # ---- C4. 분할 IC + 확인·선택 구간 플라시보(기준선·변형에 같은 이동)
    rows = []
    for ci, (cls, members) in enumerate(CLASSES.items()):
        for v, blk in VARIANT_BLOCK.items():
            if cls not in VARS["variants"][v]:
                continue
            for pi, per in enumerate(PERIODS):
                ser = {lab: {a: hist[lab][a].blocks[blk].where(window(hist[lab][a].blocks.index, per)) for a in members}
                       for lab in ("base", v)}
                nmin = min(int(ser["base"][a].notna().sum()) for a in members)
                shifts = bt.shift_draws(nmin, n_pl, seed0 + SEED_OFFSET + 10 * ci + pi)
                for lab in ("base", v):
                    pp = [(ser[lab][a], {hz: fwd[a][f"fwd_{hz}"] for hz in horizons}) for a in members]
                    obs, P = bt.pooled_placebo_ic(pp, shifts)
                    ph = bt.placebo_p(obs, P)
                    for j, hz in enumerate(horizons):
                        r = bt.pooled_ic([(ser[lab][a], fwd[a][f"fwd_{hz}"]) for a in members], hz)
                        rows.append({"asset_class": cls, "assets": ",".join(members), "variant": v, "arm": lab,
                                     "block": blk, "period": per, "horizon": hz, **r, "ic_placebo_obs": obs[j],
                                     "p_placebo": ph[j], "placebo_sd": float(np.nanstd(P[:, j])) if len(P) else np.nan,
                                     "n_shifts": len(shifts), "role": "판정" if hz == PRIMARY_H else "보조"})
        note(f"[IC] {cls} 완료")
    ic = pd.DataFrame(rows)
    ic.to_csv(OUT / "phase4c_split_ic.csv", index=False)

    # 판정표(63일)
    vd = []
    for (cls, v), g in ic[ic.horizon == PRIMARY_H].groupby(["asset_class", "variant"], sort=False):
        k = g.set_index(["arm", "period"])
        b_s, v_s = k.at[("base", "selection"), "ic"], k.at[(v, "selection"), "ic"]
        b_c, v_c = k.at[("base", "confirmation"), "ic"], k.at[(v, "confirmation"), "ic"]
        b_p, v_p = k.at[("base", "confirmation"), "p_placebo"], k.at[(v, "confirmation"), "p_placebo"]
        c1, c2, c3 = bool(v_s > b_s), bool(v_c >= b_c), bool(v_p <= b_p)
        vd.append({"asset_class": cls, "variant": v, "block": VARIANT_BLOCK[v], "assets": g["assets"].iloc[0],
                   "ic_sel_base": b_s, "ic_sel_variant": v_s, "ic_conf_base": b_c, "ic_conf_variant": v_c,
                   "p_conf_base": b_p, "p_conf_variant": v_p,
                   "p_sel_base": k.at[("base", "selection"), "p_placebo"],
                   "p_sel_variant": k.at[(v, "selection"), "p_placebo"],
                   "t_sel_variant": k.at[(v, "selection"), "t_nw"], "t_conf_variant": k.at[(v, "confirmation"), "t_nw"],
                   "n_dates_sel": k.at[(v, "selection"), "n_dates"], "n_dates_conf": k.at[(v, "confirmation"), "n_dates"],
                   "cond1_sel_improves": c1, "cond2_conf_not_worse": c2, "cond3_p_not_worse": c3,
                   "verdict": "채택" if (c1 and c2 and c3) else "기각"})
    vd = pd.DataFrame(vd)
    vd.to_csv(OUT / "phase4c_verdict.csv", index=False)
    for r in vd.to_dict("records"):
        note(f"[판정] {r['asset_class']} {r['variant']}: 선택 {r['ic_sel_base']:.3f}→{r['ic_sel_variant']:.3f}, "
             f"확인 {r['ic_conf_base']:.3f}→{r['ic_conf_variant']:.3f}, p {r['p_conf_base']:.3f}→{r['p_conf_variant']:.3f} "
             f"⇒ {r['verdict']}")

    # 보조: 해당 블록 이벤트 통계(전체 표본, Phase 3 방식) — 판정에 쓰지 않음
    ev = []
    for v, blk in VARIANT_BLOCK.items():
        aids = [a for cls in VARS["variants"][v] for a in CLASSES[cls]]
        for lab, h in (("base", hist["base"]), (v, hist[v])):
            r = base_eng.backtest(full, asset_ids=aids, history={a: h[a] for a in aids}, placebo=0)
            ev.append(r.events[r.events.block == blk].assign(variant=v, arm=lab))
    pd.concat(ev, ignore_index=True).to_csv(OUT / "phase4c_events_aux.csv", index=False)

    info = {"seconds": round(time.time() - t0, 1), "as_of_reproduce": AS_OF, "primary_horizon": PRIMARY_H,
            "periods": PERIODS, "corr_cut": CORR_CUT, "placebo_shifts": n_pl,
            "placebo_seed_rule": f"{seed0} + {SEED_OFFSET} + 10*class_idx + period_idx", "classes": CLASSES,
            "long_months": VARS["long_months"],
            "verdict": vd[["asset_class", "variant", "verdict"]].to_dict("records")}
    (OUT / "phase4c_run_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1, default=str),
                                               encoding="utf-8")
    note(f"총 {info['seconds']}초")
    (OUT / "phase4c_run_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
