"""Phase 4 D-1 — S&P500 CAPE 필드 구성·커버리지·중복 점검·분할 검증(사전 등록 docs/prereg_2026-10-29.md §1·§D-1).

    PYTHONPATH=src .venv/bin/python scripts/phase4_d.py

입력
- data/processed/panel.csv.gz(Phase 2, 읽기만)
- data/raw/phase4d_shiller/ie_data_20261029.csv(Shiller ie_data.xls → scripts/phase4d_shiller_to_csv.py)
- data/raw/phase4d_shiller/alfred/CPIAUCSL/*.csv(1999-09~2006-12 빈티지, 패널 CPI 이전 구간)
설정 파일(config/*)은 바꾸지 않는다 — cape 변형은 메모리 안 설정 사본(SP500 overrides.add). Phase 3 와 같은 방식.
산출: outputs/phase4/phase4d_*.csv·phase4d_run_log.txt·phase4d_run_info.json, data/processed/phase4d_cape_e10.csv
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
from mtscore import ScoringEngine, build_config  # noqa: E402
from mtscore.core import backtest as bt  # noqa: E402
from mtscore.data import shiller as SH  # noqa: E402
from mtscore.data.adapters import fred as fred_mod  # noqa: E402
from mtscore.data.schema import validate_panel  # noqa: E402

CFG = ROOT / "config"
OUT = ROOT / "outputs" / "phase4"
RAW = ROOT / "data" / "raw" / "phase4d_shiller"
PROC = ROOT / "data" / "processed"
SHILLER_CSV = RAW / "ie_data_20261029.csv"
SHILLER_OLD_CSV = RAW / "ie_data_vintage2023.csv"
END = "2026-10-27"            # Phase 2 패널 기준일
CPI_PANEL_FROM = "2006-12-01"  # 패널 CPI(2007-01-01 첫 빈티지)의 2006-11 행은 빈티지 첫날 잔여분(as_of 인위적) → 그 이전은 새 수집분
ALFRED_LOOKBACK = 75          # phase2_build.ALFRED_LOOKBACK["CPIAUCSL"] 와 같게
ASSET = "SP500"
SEL = ("2013-01-01", "2019-12-31")   # 사전 등록 §1 선택 구간
CONF_FROM = "2020-01-01"             # 확인 구간(끝 = 표본 끝)
PRIMARY_H = 63
CORR_CUT = 0.9
CAPE_ITEM = {"name": "cape", "indicator": "ratio", "direction": "-", "fields": ["close", "cape_e10"]}
# 가정: cape 는 기존 하위블록 valuation.multiples 에 넣는다(SP500 밸류에이션의 유일한 하위블록, per_fwd_12m·erp 와 동일 가중 → 지표 비중 1/3)


def raw_cfg():
    uni = yaml.safe_load((CFG / "universe.yaml").read_text(encoding="utf-8"))
    sc = yaml.safe_load((CFG / "scoring.yaml").read_text(encoding="utf-8"))
    profs = {}
    for p in sorted((CFG / "profiles").glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        profs[d.get("asset_class", p.stem)] = d
    return uni, profs, sc


def engine(uni, profs, sc):
    return ScoringEngine(build_config(copy.deepcopy(uni), copy.deepcopy(profs), copy.deepcopy(sc)))


def with_cape(uni):
    u = copy.deepcopy(uni)
    for it in u:
        if it["asset_id"] == ASSET:
            ov = it.setdefault("overrides", {}) or {}
            it["overrides"] = ov
            add = ov.setdefault("add", {}) or {}
            ov["add"] = add
            add.setdefault("valuation.multiples", []).append(dict(CAPE_ITEM))
    return u


def cpi_first_release(panel):
    """CPI 최초 공표값: 2006-12 이후 = 패널 UST10Y cpi 그대로, 그 이전 = 새 수집 빈티지(1999-09~2006-12)의 first_releases."""
    files = sorted((RAW / "alfred" / "CPIAUCSL").glob("*.csv"))
    long = pd.concat([fred_mod.parse_alfred(p.read_text(encoding="utf-8")) for p in files], ignore_index=True)
    new = fred_mod.first_releases(long, max_lag_days=ALFRED_LOOKBACK)
    pc = panel[(panel.asset_id == "UST10Y") & (panel.field == "cpi")][["date", "value", "as_of"]]
    ov = new.merge(pc, on="date", suffixes=("", "_panel"))
    cpi = pd.concat([new[new.date < CPI_PANEL_FROM], pc[pc.date >= CPI_PANEL_FROM]]).sort_values("date")
    months = pd.date_range(cpi.date.min(), cpi.date.max(), freq="MS")
    lag = (new.as_of - new.date).dt.days
    info = {"vintage_first": str(long.vintage.min().date()), "vintage_last": str(long.vintage.max().date()),
            "new_first_obs": str(new.date.min().date()), "new_first_obs_as_of(빈티지 첫날 잔여분)": str(new.as_of.iloc[0].date()),
            "new_n_obs": int(len(new)), "new_lag_days_median": float(lag.median()), "new_lag_days_max": int(lag.max()),
            "overlap_with_panel": ov.assign(date=ov.date.dt.date.astype(str), as_of=ov.as_of.dt.date.astype(str),
                                            as_of_panel=ov.as_of_panel.dt.date.astype(str)).to_dict("records"),
            "combined_first": str(cpi.date.min().date()), "combined_last": str(cpi.date.max().date()),
            "combined_missing_months": [str(d.date()) for d in months.difference(cpi.date)]}
    return cpi.reset_index(drop=True), info


def score_history(eng, panel):
    res = eng.score(panel, as_of=END)
    rows = []
    for aid, h in res.history.items():
        b = h.blocks.copy()
        b.index.name = "date"
        rows.append(b.reset_index().assign(asset_id=aid))
    hist = pd.concat(rows, ignore_index=True)[["asset_id", "date", "oversold", "valuation", "fundamental"]]
    return hist.dropna(subset=["oversold", "valuation", "fundamental"], how="all").round(4).reset_index(drop=True)


def diff_history(a, b):
    m = a.merge(b, on=["asset_id", "date"], how="outer", suffixes=("_a", "_b"), indicator=True)
    out = {"rows_a": int(len(a)), "rows_b": int(len(b)), "only_a": int((m._merge == "left_only").sum()),
           "only_b": int((m._merge == "right_only").sum())}
    for blk in ("oversold", "valuation", "fundamental"):
        x, y = m[f"{blk}_a"], m[f"{blk}_b"]
        diff = ~((x == y) | (x.isna() & y.isna()))
        out[f"diff_{blk}"] = int(diff.sum())
        out[f"max_abs_{blk}"] = float((x - y).abs().max()) if diff.any() else 0.0
    out["identical"] = out["only_a"] == 0 and out["only_b"] == 0 and all(out[f"diff_{b}"] == 0 for b in
                                                                        ("oversold", "valuation", "fundamental"))
    return out


def period_masks(idx):
    return {"selection": (idx >= SEL[0]) & (idx <= SEL[1]), "confirmation": idx >= CONF_FROM}


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    log = []

    def note(msg):
        print(msg, flush=True)
        log.append(str(msg))

    panel = pd.read_csv(PROC / "panel.csv.gz", parse_dates=["date", "as_of"])
    note(f"패널 {len(panel):,}행, as_of 최대 {panel['as_of'].max().date()}")
    info = {"shiller_csv": str(SHILLER_CSV.relative_to(ROOT))}

    # ---- 1. 필드 구성
    sh = SH.parse_shiller_csv(SHILLER_CSV)
    e = SH.e_pit(sh)
    cpi, cinfo = cpi_first_release(panel)
    info["cpi"] = cinfo
    note(f"CPI 최초 공표값 {cinfo['combined_first']}~{cinfo['combined_last']}, 빠진 달 {cinfo['combined_missing_months']}")
    note(f"  새 수집분 vs 패널 겹침: {cinfo['overlap_with_panel']}")
    e10 = SH.real_e10(e, cpi)
    e10 = e10[e10.date <= END].reset_index(drop=True)
    e10_out = e10.assign(asset_id=ASSET, field="cape_e10",
                         source="phase4d: Shiller ie_data(2026-10판) E(as_of=기준월+4개월 1일) × ALFRED CPIAUCSL 최초 공표값")
    e10_out = e10_out[["date", "asset_id", "field", "value", "as_of", "source"]]
    e10_out.to_csv(PROC / "phase4d_cape_e10.csv", index=False)
    panel2 = validate_panel(pd.concat([panel, e10_out], ignore_index=True))
    info["e10"] = {"rows": int(len(e10)), "first": str(e10.date.min().date()), "last": str(e10.date.max().date()),
                   "e_last_month": str(e.date.max().date()), "e_last_as_of": str(e.as_of.max().date())}
    note(f"cape_e10 {len(e10)}행 {info['e10']['first']}~{info['e10']['last']} (E 마지막 월 {info['e10']['e_last_month']}, "
         f"as_of {info['e10']['e_last_as_of']})")

    # E 빈티지 대조(2023-09판 vs 2026-10판)
    old = SH.parse_shiller_csv(SHILLER_OLD_CSV)
    vv = sh[["month", "E"]].merge(old[["month", "E"]], on="month", suffixes=("_new", "_old")).dropna()
    vv["pct"] = (vv.E_new / vv.E_old - 1) * 100
    chg = vv[vv.pct.abs() > 1e-9]
    info["vintage_revision"] = {"overlap_months": int(len(vv)), "months_changed": [str(d.date()) for d in chg.month],
                                "pct_changed": [round(x, 4) for x in chg.pct]}
    note(f"Shiller E 빈티지 대조(겹침 {len(vv)}개월): 바뀐 달 {info['vintage_revision']['months_changed']} "
         f"{info['vintage_revision']['pct_changed']}%")

    uni, profs, sc = raw_cfg()

    # ---- 5. 기본 설정 재현(cape 없음): Phase 2 score_history 와 비교
    t = time.time()
    ref = pd.read_csv(ROOT / "outputs" / "phase2" / "score_history.csv.gz", parse_dates=["date"])
    eng0 = engine(uni, profs, sc)
    h_orig = score_history(eng0, panel)
    h_aug = score_history(eng0, panel2)
    rep = {"default_on_original_panel_vs_phase2": diff_history(h_orig, ref),
           "default_on_panel_plus_cape_e10_vs_phase2": diff_history(h_aug, ref)}
    info["reproduction"] = rep
    pd.DataFrame([{"comparison": k, **v} for k, v in rep.items()]).to_csv(OUT / "phase4d_reproduction.csv", index=False)
    note(f"[재현] {time.time() - t:.1f}초 {json.dumps(rep, ensure_ascii=False)}")

    # ---- 2. 기준선·변형 백테스트(SP500)
    t = time.time()
    rb = engine(uni, profs, sc).backtest(panel2, asset_ids=[ASSET], placebo=0)
    rv = engine(with_cape(uni), profs, sc).backtest(panel2, asset_ids=[ASSET], placebo=0)
    note(f"[백테스트] 기준선·변형 {time.time() - t:.1f}초")
    hb, hv = rb.history[ASSET], rv.history[ASSET]
    # Phase 3 기준선 IC 재현(SP500, full)
    p3 = pd.read_csv(ROOT / "outputs" / "phase3" / "ic.csv")
    p3 = p3[(p3.asset_id == ASSET) & (p3.period == "full")][["block", "horizon", "ic"]]
    cmp3 = p3.merge(rb.ic[(rb.ic.period == "full")][["block", "horizon", "ic"]], on=["block", "horizon"],
                    suffixes=("_phase3", "_now"))
    info["phase3_ic_max_abs_diff"] = float((cmp3.ic_phase3 - cmp3.ic_now).abs().max())
    note(f"[재현] Phase 3 SP500 full IC 최대 차 {info['phase3_ic_max_abs_diff']:.2e} ({len(cmp3)}셀)")

    raw = hv.raw["cape"]
    cape_sc = hv.score["cape"]
    vb, vvb = hb.blocks["valuation"], hv.blocks["valuation"]
    # 민감도(사전 등록 정의 아님): CPIAUCSL 2025-10 은 공표되지 않았다(셧다운) → 달력 120개월 창은 그 달이 창에 들어오는
    # 2026-02-01 부터 값이 없다. 'E·CPI 가 모두 있는 최근 120개월' 창(빠진 달 건너뜀)으로 같은 평가를 낸다. 판정에는 쓰지 않는다.
    e10s = SH.real_e10(e, cpi, skip_missing=True)
    e10s = e10s[e10s.date <= END].reset_index(drop=True)
    info["e10_sensitivity_skip_missing"] = {"rows": int(len(e10s)), "last": str(e10s.date.max().date()),
                                            "span_months_max": int(e10s.span_months.max()),
                                            "first_span_121": str(e10s[e10s.span_months > 120].date.min().date())}
    panel3 = validate_panel(pd.concat([panel, e10s.drop(columns="span_months").assign(
        asset_id=ASSET, field="cape_e10", source="phase4d 민감도: 빠진 달 건너뛴 120개월")], ignore_index=True))
    rs = engine(with_cape(uni), profs, sc).backtest(panel3, asset_ids=[ASSET], placebo=0)
    vsb = rs.history[ASSET].blocks["valuation"]
    raw_s = rs.history[ASSET].raw["cape"].dropna()
    info["e10_sensitivity_skip_missing"].update({"cape_last": round(float(raw_s.iloc[-1]), 2),
                                                 "cape_last_date": str(raw_s.index[-1].date()),
                                                 "cape_score_last": round(float(rs.history[ASSET].score["cape"].dropna().iloc[-1]), 2),
                                                 "valuation_last": round(float(vsb.dropna().iloc[-1]), 2)})
    note(f"[민감도: 빠진 달 건너뜀] {json.dumps(info['e10_sensitivity_skip_missing'], ensure_ascii=False)}")
    cov = {"first_cape_value": str(raw.first_valid_index().date()), "first_cape_score": str(cape_sc.first_valid_index().date()),
           "first_base_valuation_score": str(vb.first_valid_index().date()),
           "first_variant_valuation_score": str(vvb.first_valid_index().date()),
           "cape_last": round(float(raw.dropna().iloc[-1]), 2), "cape_last_date": str(raw.dropna().index[-1].date()),
           "cape_score_last": round(float(cape_sc.dropna().iloc[-1]), 2),
           "valuation_last_base": round(float(vb.dropna().iloc[-1]), 2),
           "valuation_last_variant": round(float(vvb.dropna().iloc[-1]), 2),
           "cape_n_days": int(raw.notna().sum()), "cape_nan_after_first": int(raw[raw.first_valid_index():].isna().sum())}
    cov["first_score_le_2013"] = cov["first_cape_score"] <= "2013-12-31"
    info["coverage"] = cov
    pd.DataFrame([cov]).to_csv(OUT / "phase4d_coverage.csv", index=False)
    note(f"[커버리지] {json.dumps(cov, ensure_ascii=False)}")
    w = hv.coverage
    note(f"  변형 SP500 밸류 지표: {w[w.block == 'valuation'][['indicator', 'sub_block']].to_dict('records') if 'block' in w else w}")

    # ---- 3. 중복 규칙(선택 구간 지표 점수 Pearson)
    S = hv.score[["cape", "per_fwd_12m", "erp"]]
    S1 = S[(S.index >= SEL[0]) & (S.index <= SEL[1])].dropna()
    red = []
    for other in ("per_fwd_12m", "erp"):
        c = float(S1["cape"].corr(S1[other]))
        ic_c = bt.spearman_ic(S1["cape"], rv.forward[ASSET][f"fwd_{PRIMARY_H}"].reindex(S1.index), PRIMARY_H)["ic"]
        ic_o = bt.spearman_ic(S1[other], rv.forward[ASSET][f"fwd_{PRIMARY_H}"].reindex(S1.index), PRIMARY_H)["ic"]
        hit = c > CORR_CUT
        red.append({"a": "cape", "b": other, "corr_selection": c, "n": int(len(S1)), "over_cut": hit,
                    f"ic{PRIMARY_H}_selection_cape": ic_c, f"ic{PRIMARY_H}_selection_other": ic_o,
                    "candidate": ("cape" if ic_c < ic_o else other) if hit else ""})
    red = pd.DataFrame(red)
    red.to_csv(OUT / "phase4d_redundancy.csv", index=False)
    note(f"[중복] {red.round(3).to_dict('records')}")

    # ---- 4. 분할 검증: 같은 날짜(두 변형 모두 점수 있음)만, 시작일 기준 구간
    n_pl = int(sc["backtest"]["placebo_shifts"])
    seed = int(sc["backtest"]["placebo_seed"])
    common = vb.dropna().index.intersection(vvb.dropna().index)
    rows = []
    for per, m in period_masks(common).items():
        d = common[m]
        shifts = bt.shift_draws(len(d), n_pl, seed)   # 두 변형에 같은 이동(같은 n, 같은 시드)
        for var, s in (("base", vb), ("with_cape", vvb), ("sens_cape_skip_missing", vsb)):
            s_ = s.reindex(d)
            F = {"base": rb, "with_cape": rv, "sens_cape_skip_missing": rs}[var].forward[ASSET]
            fw = {h: F[f"fwd_{h}"].reindex(d) for h in rb.horizons}
            obs, P = bt.placebo_ic(s_, fw, shifts)
            ps = bt.placebo_p(obs, P)
            for j, h in enumerate(rb.horizons):
                r = bt.spearman_ic(s_, fw[h], h)
                rows.append({"period": per, "variant": var, "horizon": h, "ic": r["ic"], "t_nw": r["t_nw"], "n": r["n"],
                             "ic_nonoverlap": r["ic_nonoverlap"], "n_nonoverlap": r["n_nonoverlap"],
                             "ic_placebo_check": obs[j], "p_placebo": ps[j],
                             "placebo_sd": float(np.nanstd(P[:, j])) if len(P) else np.nan,
                             "first": str(d.min().date()), "last_with_fwd": str(fw[h].dropna().index.max().date())})
    ic = pd.DataFrame(rows)
    ic.to_csv(OUT / "phase4d_ic.csv", index=False)
    assert (ic.ic - ic.ic_placebo_check).abs().max() < 1e-9

    def g(per, var, h, col="ic"):
        return float(ic[(ic.period == per) & (ic.variant == var) & (ic.horizon == h)][col].iloc[0])

    c1 = g("selection", "with_cape", PRIMARY_H) > g("selection", "base", PRIMARY_H)
    c2 = g("confirmation", "with_cape", PRIMARY_H) >= g("confirmation", "base", PRIMARY_H)
    c3 = g("confirmation", "with_cape", PRIMARY_H, "p_placebo") <= g("confirmation", "base", PRIMARY_H, "p_placebo")
    verdict = {"horizon": PRIMARY_H,
               "sel_ic_base": g("selection", "base", PRIMARY_H), "sel_ic_cape": g("selection", "with_cape", PRIMARY_H),
               "conf_ic_base": g("confirmation", "base", PRIMARY_H), "conf_ic_cape": g("confirmation", "with_cape", PRIMARY_H),
               "conf_p_base": g("confirmation", "base", PRIMARY_H, "p_placebo"),
               "conf_p_cape": g("confirmation", "with_cape", PRIMARY_H, "p_placebo"),
               "cond1_sel_ic_up": c1, "cond2_conf_ic_not_lower": c2, "cond3_conf_p_not_worse": c3,
               "redundancy_candidate": bool(red.over_cut.any()), "adopt": bool(c1 and c2 and c3)}
    pd.DataFrame([verdict]).to_csv(OUT / "phase4d_verdict.csv", index=False)
    info["verdict"] = verdict
    note(f"[판정] {json.dumps(verdict, ensure_ascii=False)}")
    note(ic.pivot_table(index=["period", "horizon"], columns="variant", values=["ic", "p_placebo"]).round(3).to_string())

    # cape 단독 지표 IC(참고)
    ind = []
    for per, m in period_masks(cape_sc.dropna().index).items():
        s = cape_sc.dropna()[m]
        for h in rv.horizons:
            ind.append({"indicator": "cape", "period": per, "horizon": h,
                        **bt.spearman_ic(s, rv.forward[ASSET][f"fwd_{h}"].reindex(s.index), h)})
        for other in ("per_fwd_12m", "erp"):
            o = hv.score[other].dropna()
            o = o[period_masks(o.index)[per]]
            for h in rv.horizons:
                ind.append({"indicator": other, "period": per, "horizon": h,
                            **bt.spearman_ic(o, rv.forward[ASSET][f"fwd_{h}"].reindex(o.index), h)})
    pd.DataFrame(ind).to_csv(OUT / "phase4d_indicator_ic.csv", index=False)

    # ---- 4-보조. Shiller 공표 CAPE 와 수준 대조(월평균)
    mon = raw.dropna().groupby(raw.dropna().index.to_period("M")).mean()
    shm = sh.set_index(sh.month.dt.to_period("M"))
    # Shiller 자기 자료로 같은 식을 재현: 실질가격 = P_M/CPI_M, 분모 = 평균(E_m/CPI_m), E 창 끝 = M − k
    rE = (shm["E"] / shm["CPI"])
    rP = shm["P"] / shm["CPI"]
    rep_k = {}
    E_LAG = SH.E_LAG_MONTHS
    for k in (0, E_LAG):
        den = rE.shift(k).rolling(SH.WINDOW_MONTHS, min_periods=SH.WINDOW_MONTHS).mean()
        rep_k[k] = rP / den
    cmp = pd.DataFrame({"ours_monthly_mean": mon, "shiller_cape": shm["CAPE"], "shiller_P": shm["P"],
                        "replica_lag0": rep_k[0], f"replica_lag{E_LAG}": rep_k[E_LAG]}).dropna(subset=["ours_monthly_mean"])
    cmp.index = cmp.index.astype(str)
    cmp.to_csv(OUT / "phase4d_shiller_sanity.csv", index_label="month")

    def pair(a, b):
        d = cmp[[a, b]].dropna()
        return {"n": int(len(d)), "corr": round(float(d[a].corr(d[b])), 4),
                "mean_abs_diff": round(float((d[a] - d[b]).abs().mean()), 3),
                "mean_diff": round(float((d[a] - d[b]).mean()), 3), "first": d.index[0], "last": d.index[-1]}

    san = {"ours_vs_shiller": pair("ours_monthly_mean", "shiller_cape"),
           "replica_lag0_vs_shiller": pair("replica_lag0", "shiller_cape"),
           f"replica_lag{E_LAG}_vs_shiller": pair(f"replica_lag{E_LAG}", "shiller_cape"),
           f"ours_vs_replica_lag{E_LAG}": pair("ours_monthly_mean", f"replica_lag{E_LAG}")}
    # CPI 정의 차: Shiller CPI(CPI-U NSA, 최신) vs ALFRED CPIAUCSL(SA, 최초 공표)
    cc = cpi.set_index(cpi.date.dt.to_period("M"))["value"].to_frame("alfred_first").join(shm["CPI"].rename("shiller"))
    cc = cc.dropna()
    san["cpi_alfred_first_vs_shiller_pct"] = {"mean": round(float(((cc.alfred_first / cc.shiller) - 1).mean() * 100), 3),
                                              "max_abs": round(float(((cc.alfred_first / cc.shiller) - 1).abs().max() * 100), 3),
                                              "n": int(len(cc))}
    info["shiller_sanity"] = san
    note(f"[Shiller 대조] {json.dumps(san, ensure_ascii=False)}")

    info["seconds"] = round(time.time() - t0, 1)
    (OUT / "phase4d_run_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (OUT / "phase4d_run_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    note(f"끝 {info['seconds']}초")


if __name__ == "__main__":
    main()
