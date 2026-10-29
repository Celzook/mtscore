"""Phase 4 B — 사전 등록(docs/prereg_2026-10-29.md) B1 조건부 변동성 가점 판정 + B2·B3 표시 점검 + B4 회귀 확인.

    .venv/bin/python scripts/phase4_b.py

입력: data/processed/panel.csv.gz(Phase 2). 설정 파일(config/*)의 기본 프로파일은 바꾸지 않는다 — 변형은 메모리 안
프로파일 사본(Phase 3 contrarian_profiles 와 같은 방식)이고, 사본은 outputs/phase4/variant_profiles/ 에 YAML 로 남긴다.
판정 규칙·구간·시평은 사전 등록 그대로다(결과를 본 뒤 바꾸지 않음). 시드는 scoring.yaml backtest.placebo_seed 고정.
산출(outputs/phase4/): phase4b_*.csv, phase4b_run_log.txt, phase4b_run_info.json, variant_profiles/*.yaml
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
from mtscore import ScoringEngine, build_config, load_config  # noqa: E402
from mtscore.core import backtest as bt  # noqa: E402
from mtscore.core.registry import get_func  # noqa: E402

OUT = ROOT / "outputs" / "phase4"
CFG = ROOT / "config"
AS_OF_P2 = "2026-10-27"                                       # Phase 2 score_history 산출 기준일(phase2_score.py)
SPLITS = {"selection": ("2013-01-01", "2019-12-31"), "confirmation": ("2020-01-01", None)}   # 사전 등록 §1
PRIMARY_H = 63                                                # 사전 등록 §1(판정 시평)
CORR_CUT = 0.9                                                # 사전 등록 §1 중복 규칙
PCTB_EDGE = {"lower": 0.0, "upper": 1.0}                      # %b 밴드 정의: 하단 = 0, 상단 = 1(사전 등록 B1)
SIDE_FROM_BB_DIRECTION = {"-": "lower", "+": "upper"}         # confluence bb_pctb_20 의 direction 이 과매도 쪽을 정한다
NEUTRAL = 1.0                                                 # 사전 등록 B1: 밴드 안의 날 = 1.0(평소 변동성)
COND_FUNC = {"rv_ratio": "rv_ratio_if_oversold", "level_rv_ratio": "level_rv_ratio_if_oversold"}
VARIANTS = ("base", "cond", "drop")


def raw_cfg():
    uni = yaml.safe_load((CFG / "universe.yaml").read_text(encoding="utf-8"))
    sc = yaml.safe_load((CFG / "scoring.yaml").read_text(encoding="utf-8"))
    profs = {}
    for p in sorted((CFG / "profiles").glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        profs[d.get("asset_class", p.stem)] = d
    return uni, profs, sc


def variant_profiles(profs, variant):
    """base: 현행(무조건 rv_ratio) / cond: 같은 하위블록 자리의 rv 지표를 조건부판으로 교체 /
    drop: 변동성 지표 제거(equity vol_sentiment 의 rv_ratio_20, 그 밖은 volatility 하위블록)."""
    p = copy.deepcopy(profs)
    if variant == "base":
        return p
    for cls, d in p.items():
        ov = d["blocks"]["oversold"]
        if variant == "drop":
            if cls == "equity_index":
                ov["vol_sentiment"] = [it for it in ov["vol_sentiment"] if it["name"] != "rv_ratio_20"]
            else:
                ov.pop("volatility")
            continue
        bb = next(it for it in ov["confluence"] if it["indicator"] == "bb_pctb")
        side = SIDE_FROM_BB_DIRECTION[bb["direction"]]
        n_rep = 0
        for sb, items in ov.items():
            for i, it in enumerate(items):
                if it["indicator"] not in COND_FUNC:
                    continue
                prm = {**get_func(it["indicator"]).defaults, **(it.get("params") or {})}
                items[i] = {"name": f"{it['name']}_if_oversold", "indicator": COND_FUNC[it["indicator"]],
                            "direction": it["direction"], "fields": list(it["fields"]),
                            "params": {"window": prm["window"], "lookback": prm["lookback"],
                                       "bb_window": bb["params"]["window"], "bb_k": bb["params"]["k"],
                                       "oversold_side": side, "pctb_edge": PCTB_EDGE[side], "neutral": NEUTRAL}}
                assert it["fields"] == bb["fields"], (cls, it["fields"], bb["fields"])   # %b 와 같은 입력 시계열
                n_rep += 1
        assert n_rep == 1, (cls, n_rep)
    return p


def split_mask(idx, split):
    lo, hi = SPLITS[split]
    m = idx >= pd.Timestamp(lo)
    if hi is not None:
        m &= idx <= pd.Timestamp(hi)
    return m


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "variant_profiles").mkdir(exist_ok=True)
    log = []

    def note(msg):
        print(msg, flush=True)
        log.append(msg)

    panel = pd.read_csv(ROOT / "data" / "processed" / "panel.csv.gz", parse_dates=["date", "as_of"])
    uni, profs, sc = raw_cfg()
    bcfg = sc["backtest"]
    n_pl, seed = int(bcfg["placebo_shifts"]), int(bcfg["placebo_seed"])
    alert, min_n = float(sc["bands"]["alert"]), int(bcfg["min_n_warning"])
    note(f"패널 {len(panel):,}행, as_of 최대 {panel['as_of'].max().date()}, 플라시보 {n_pl}회 시드 {seed}")

    # ---- B4. 기본 설정 회귀: Phase 2 score_history 재현(phase2_score.py 와 같은 절차)
    eng0 = ScoringEngine(load_config(CFG))
    res0 = eng0.score(panel, as_of=AS_OF_P2)
    rows = []
    for aid, h in res0.history.items():
        b = h.blocks.copy()
        b.index.name = "date"
        rows.append(b.reset_index().assign(asset_id=aid))
    hist = pd.concat(rows, ignore_index=True)[["asset_id", "date", "oversold", "valuation", "fundamental"]]
    hist = hist.dropna(subset=["oversold", "valuation", "fundamental"], how="all").round(4).reset_index(drop=True)
    p2 = pd.read_csv(ROOT / "outputs" / "phase2" / "score_history.csv.gz", parse_dates=["date"])
    pd.testing.assert_frame_equal(hist, p2, check_exact=True, check_dtype=False)   # 다르면 여기서 중단
    same_hist = True
    j_new = res0.to_dict()
    j_old = json.loads((ROOT / "outputs" / "phase2" / f"result_{AS_OF_P2}.json").read_text(encoding="utf-8"))
    for a in j_new["assets"]:
        a.pop("staged_entry")
        a.pop("trend")
    j_new.pop("schema_version")
    j_old.pop("schema_version")
    same_json = j_new == j_old
    note(f"[B4] score_history {len(hist):,}행 Phase 2 와 동일: {same_hist} / result JSON(새 필드·버전 제외) 동일: {same_json}")
    if not same_json:
        raise SystemExit("result JSON 이 Phase 2 와 다름 — 중단")

    # ---- B2·B3 현재값(기준일 = Phase 2 기준일)
    disp = res0.regime[["display"]].join(res0.staged_entry).join(res0.trend.add_prefix("trend_"))
    disp.index.name = "asset_id"
    disp.to_csv(OUT / "phase4b_display_latest.csv")
    th = eng0.trend_history(panel)
    trows = []
    for aid, fr in th.items():
        v = fr["value"]
        trows.append({"asset_id": aid, "first_value_date": v.first_valid_index(), "n_days": int(v.notna().sum()),
                      "share_pos": float((v > 0).mean() / v.notna().mean()) if v.notna().any() else np.nan,
                      "reason_when_na": ",".join(sorted(set(fr.loc[v.isna(), "reason"])))})
    pd.DataFrame(trows).to_csv(OUT / "phase4b_trend_coverage.csv", index=False)
    note("[B2·B3] 기준일 표시:\n" + disp.to_string())

    # ---- B1. 변형 3개 백테스트(셀 플라시보는 끔 — 판정용 플라시보는 아래에서 구간별로 따로)
    classes = {}
    for it in uni:
        classes.setdefault(it["asset_class"], []).append(it["asset_id"])
    classes["ALL"] = [it["asset_id"] for it in uni]
    res = {}
    for v in VARIANTS:
        t = time.time()
        pv = variant_profiles(profs, v)
        for cls, d in pv.items():
            (OUT / "variant_profiles" / f"{v}_{cls}.yaml").write_text(
                yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
        res[v] = ScoringEngine(build_config(copy.deepcopy(uni), pv, copy.deepcopy(sc))).backtest(panel, placebo=0)
        note(f"[B1] 변형 {v} 백테스트 {time.time() - t:.1f}초")
    horizons = res["base"].horizons
    for v in VARIANTS[1:]:   # forward return 은 변형과 무관해야 한다(수익 지수는 프로파일을 쓰지 않음)
        for a in classes["ALL"]:
            pd.testing.assert_frame_equal(res[v].forward[a], res["base"].forward[a])

    # 표본 수(변형 간 블록 커버리지 차이 확인)
    cov_rows = []
    for v in VARIANTS:
        for a in classes["ALL"]:
            s = res[v].history[a].blocks["oversold"]
            for sp in SPLITS:
                m = split_mask(s.index, sp)
                cov_rows.append({"variant": v, "asset_id": a, "split": sp, "n_score": int(s[m].notna().sum()),
                                 f"n_pairs_{PRIMARY_H}": int((s[m].notna() & res[v].forward[a][f"fwd_{PRIMARY_H}"][m].notna()).sum())})
    covdf = pd.DataFrame(cov_rows)
    covdf.to_csv(OUT / "phase4b_sample_counts.csv", index=False)
    piv = covdf.pivot_table(index=["asset_id", "split"], columns="variant", values=f"n_pairs_{PRIMARY_H}")
    diff_n = piv[(piv["cond"] != piv["base"]) | (piv["drop"] != piv["base"])]
    note(f"[B1] 63일 IC 쌍 수가 변형 간 다른 자산×구간: {len(diff_n)}" + ("" if diff_n.empty else "\n" + diff_n.to_string()))

    # 풀링 IC(전 시평) — 관측은 시작일이 속한 구간
    ic_rows = []
    for v in VARIANTS:
        r = res[v]
        for cls, members in classes.items():
            for sp in SPLITS:
                for hz in horizons:
                    pairs = []
                    for a in members:
                        s = r.history[a].blocks["oversold"]
                        m = split_mask(s.index, sp)
                        pairs.append((s[m], r.forward[a][f"fwd_{hz}"][m]))
                    ic_rows.append({"variant": v, "asset_class": cls, "split": sp, "horizon": hz,
                                    **bt.pooled_ic(pairs, hz)})
    icdf = pd.DataFrame(ic_rows)

    # 순환 이동 플라시보(63일, 구간별) — 이동 배열은 (자산군, 구간)마다 한 번 뽑아 세 변형에 같이 쓴다
    pl_rows = []
    for ci, (cls, members) in enumerate(classes.items()):
        for si, sp in enumerate(SPLITS):
            nmin = min(int(res["base"].history[a].blocks["oversold"][split_mask(res["base"].history[a].blocks.index, sp)]
                           .notna().sum()) for a in members)
            sd = seed + 2000 + 10 * ci + si
            shifts = bt.shift_draws(nmin, n_pl, sd)
            for v in VARIANTS:
                r = res[v]
                pp = []
                for a in members:
                    s = r.history[a].blocks["oversold"]
                    m = split_mask(s.index, sp)
                    pp.append((s[m], {PRIMARY_H: r.forward[a][f"fwd_{PRIMARY_H}"][m]}))
                obs, P = bt.pooled_placebo_ic(pp, shifts)
                pl_rows.append({"variant": v, "asset_class": cls, "split": sp, "horizon": PRIMARY_H,
                                "ic_placebo_obs": obs[0], "p_placebo": bt.placebo_p(obs, P)[0],
                                "placebo_sd": float(np.nanstd(P[:, 0])), "n_shifts": len(shifts), "shift_seed": sd,
                                "shift_n_base": nmin})
    pldf = pd.DataFrame(pl_rows)
    icdf = icdf.merge(pldf, on=["variant", "asset_class", "split", "horizon"], how="left")
    chk = icdf[icdf.horizon == PRIMARY_H]
    assert np.allclose(chk["ic"], chk["ic_placebo_obs"], atol=1e-12), "플라시보 관측 IC ≠ pooled_ic"
    icdf.to_csv(OUT / "phase4b_pooled_ic.csv", index=False)

    # 판정(사전 등록 §1 채택 조건 3개) — cond vs base 가 판정, drop vs base 는 비교용
    vrows = []
    for cand in ("cond", "drop"):
        for cls in classes:
            g = icdf[(icdf.asset_class == cls) & (icdf.horizon == PRIMARY_H)].set_index(["variant", "split"])
            sb, sc_ = g.at[("base", "selection"), "ic"], g.at[(cand, "selection"), "ic"]
            cb, cc = g.at[("base", "confirmation"), "ic"], g.at[(cand, "confirmation"), "ic"]
            pb, pc = g.at[("base", "confirmation"), "p_placebo"], g.at[(cand, "confirmation"), "p_placebo"]
            c1, c2, c3 = sc_ > sb, cc >= cb, pc <= pb
            vrows.append({"candidate": cand, "asset_class": cls, "sel_ic_base": sb, "sel_ic_cand": sc_,
                          "sel_p_base": g.at[("base", "selection"), "p_placebo"],
                          "sel_p_cand": g.at[(cand, "selection"), "p_placebo"],
                          "conf_ic_base": cb, "conf_ic_cand": cc, "conf_p_base": pb, "conf_p_cand": pc,
                          "c1_sel_gt": c1, "c2_conf_ge": c2, "c3_conf_p_le": c3,
                          "verdict": ("채택 조건 충족" if (c1 and c2 and c3) else "기각") if cand == "cond" else "비교용",
                          "conf_ic_sign_negative": bool(cb < 0 or cc < 0)})
    vd = pd.DataFrame(vrows)
    vd.to_csv(OUT / "phase4b_verdict.csv", index=False)
    note("[B1] 판정(63일):\n" + vd.round(4).to_string(index=False))

    # 이벤트(과매도 ≥ alert, 쿨다운 = backtest.event_cooldown_bdays): 자산군 풀링, 구간별 — 판정 미사용
    ev_rows = []
    for v in VARIANTS:
        el = res[v].event_list
        el = el[(el.block == "oversold") & (el.band == f">={alert:g}")]
        for cls, members in classes.items():
            for sp in SPLITS:
                e = el[el.asset_id.isin(members) & split_mask(pd.DatetimeIndex(el["date"]), sp)]
                for hz in horizons:
                    st = bt.ret_stats(e[f"fwd_{hz}"].reset_index(drop=True), e[f"mae_{hz}"].reset_index(drop=True),
                                      hz, min_n)
                    ev_rows.append({"variant": v, "asset_class": cls, "split": sp, "horizon": hz, "n": st["n"],
                                    "mean_fwd": st["mean"], "median_fwd": st["median"], "hit_rate": st["hit_rate"],
                                    "mae_mean": st["mae_mean"], "warning": "표본 부족" if st["n"] < min_n else ""})
    pd.DataFrame(ev_rows).to_csv(OUT / "phase4b_events.csv", index=False)

    # 구성상 상관·중복 규칙(선택 구간): 조건부 지표 점수 vs confluence 하위블록 점수, vs 같은 블록 다른 지표 점수
    hc, hb = res["cond"].history, res["base"].history
    corr_rows, mass_rows = [], []
    for cls, members in classes.items():
        if cls == "ALL":
            continue
        cn = next(n for n in hc[members[0]].score.columns if n.endswith("_if_oversold"))
        bn = cn[: -len("_if_oversold")]
        pool = []
        for a in members:
            m = split_mask(hc[a].score.index, "selection")
            d = pd.DataFrame({"cond": hc[a].score[cn][m], "base_rv": hb[a].score[bn][m],
                              "confluence": hc[a].sub_blocks[("oversold", "confluence")][m]})
            others = [n for n in hc[a].score.columns if n != cn and n in hc[a].coverage.set_index("indicator").index
                      and hc[a].coverage.set_index("indicator").at[n, "block"] == "oversold"]
            for n in others:
                d[f"ind:{n}"] = hc[a].score[n][m]
            pool.append(d)
            for col in ["base_rv", "confluence"] + [c for c in d.columns if c.startswith("ind:")]:
                x = d[["cond", col]].dropna()
                corr_rows.append({"asset_class": cls, "asset_id": a, "with": col, "n": len(x),
                                  "pearson": x["cond"].corr(x[col]), "spearman": x["cond"].corr(x[col], method="spearman")})
            raw = hc[a].raw[cn]
            ok = raw.notna()
            mass_rows.append({"asset_id": a, "indicator": cn, "n_raw": int(ok.sum()),
                              "share_neutral_1.0": float((raw[ok] == NEUTRAL).mean()),
                              "share_band_break": float((raw[ok] != NEUTRAL).mean()),
                              "share_break_rv_lt_1": float(((raw[ok] != NEUTRAL) & (raw[ok] < 1.0)).mean()),
                              "score_at_neutral_median_last_year": float(
                                  hc[a].score[cn][raw == NEUTRAL].iloc[-252:].median())})
        P = pd.concat(pool)
        for col in [c for c in P.columns if c != "cond"]:
            x = P[["cond", col]].dropna()
            corr_rows.append({"asset_class": cls, "asset_id": "POOLED", "with": col, "n": len(x),
                              "pearson": x["cond"].corr(x[col]), "spearman": x["cond"].corr(x[col], method="spearman")})
    cd = pd.DataFrame(corr_rows)
    cd["over_cut"] = cd["pearson"] > CORR_CUT
    cd.to_csv(OUT / "phase4b_construction_corr.csv", index=False)
    pd.DataFrame(mass_rows).to_csv(OUT / "phase4b_mass_point.csv", index=False)
    note(f"[B1] 중복 규칙(선택 구간 Pearson > {CORR_CUT}) 해당: "
         f"{cd[cd.over_cut][['asset_class', 'asset_id', 'with']].values.tolist() or '없음'}")

    # B2 이력 점검(참고): base 변형에서 분할 진입 조건(과매도 ≥ oversold_min, 변동성비 ≥ vol_ratio_min)이 성립한 날·이벤트
    se = sc["staged_entry"]
    cooldown = int(bcfg["event_cooldown_bdays"])
    srows = []
    for a in classes["ALL"]:
        h = hb[a]
        vn = [n for n in h.raw.columns if h.coverage.set_index("indicator").at[n, "function"] in se["vol_functions"]]
        assert len(vn) == 1, (a, vn)
        flag = (h.blocks["oversold"] >= se["oversold_min"]) & (h.raw[vn[0]] >= se["vol_ratio_min"])
        o75 = h.blocks["oversold"] >= se["oversold_min"]
        for sp in SPLITS:
            m = split_mask(flag.index, sp)
            ev = bt.event_dates(flag & m, cooldown)
            f63 = res["base"].forward[a][f"fwd_{PRIMARY_H}"]
            srows.append({"asset_id": a, "split": sp, "vol_indicator": vn[0], "days_oversold_ge": int((o75 & m).sum()),
                          "days_flag": int((flag & m).sum()), "share_flag_in_oversold":
                          float((flag & m).sum() / max((o75 & m).sum(), 1)), "events_flag": len(ev),
                          f"mean_fwd{PRIMARY_H}_flag_events": f63.reindex(ev).mean()})
    pd.DataFrame(srows).to_csv(OUT / "phase4b_staged_entry_history.csv", index=False)

    info = {"seconds": round(time.time() - t0, 1), "panel_rows": int(len(panel)), "splits": SPLITS,
            "primary_horizon": PRIMARY_H, "placebo_shifts": n_pl, "placebo_seed_base": seed,
            "placebo_seed_rule": "seed + 2000 + 10*class_index + split_index (class 순서: universe 등장 순 + ALL)",
            "class_order": list(classes), "regression_score_history_equal": same_hist,
            "regression_result_json_equal": same_json, "horizons": horizons}
    (OUT / "phase4b_run_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1, default=str),
                                               encoding="utf-8")
    note(f"총 {info['seconds']}초")
    (OUT / "phase4b_run_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
