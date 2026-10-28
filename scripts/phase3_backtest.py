"""Phase 3 — 백테스트·비교 실험(엔진 공개 API 와 core.backtest 순수 함수만 사용, 튜닝 없음).

    .venv/bin/python scripts/phase3_backtest.py

입력: data/processed/panel.csv.gz(Phase 2). 설정 파일(config/*)은 바꾸지 않는다 — 비교 실험은 메모리 안 설정 사본.
산출(outputs/phase3/): 분석별 CSV, 이벤트 목록, verdict.csv·verdict_rules.csv, ic_cells.csv(플라시보), run_info.json.
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
from mtscore.core.scoring import BLOCKS  # noqa: E402

OUT = ROOT / "outputs" / "phase3"
CFG = ROOT / "config"
PRIMARY_H = 63          # 가격 지표 제외 규칙의 IC 순위 기준 기간(제외 규칙 실행 전에 지정: 63영업일, 나머지 기간은 참고로 함께 낸다)
CORR_CUT = 0.9          # 사전 등록 규칙(CLAUDE.md 2026-10-26)
REGISTERED_PRICE = ["disparity_20", "disparity_60", "disparity_200", "drawdown_52w_over_rv", "return_z_5",
                    "return_z_20", "rsi_2", "rsi_14"]   # 2026-10-26 등록 당시 price 8개(rsi_14 는 10-28 confluence 로 이동)
EQUITY = ["KOSPI200", "SP500"]
UST_TP_START = pd.Timestamp("2019-05-28")   # UST10Y term_premium 첫 점수일(Phase 2)


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


def ic_table(res, label, assets=None, blocks=BLOCKS):
    d = res.ic[res.ic.block.isin(blocks)]
    if assets:
        d = d[d.asset_id.isin(assets)]
    return d.assign(variant=label)


def pooled_block_ic(res, assets, blk, hz, mask_fn=None):
    pairs = []
    for a in assets:
        s = res.history[a].blocks[blk]
        f = res.forward[a][f"fwd_{hz}"]
        if mask_fn is not None:
            m = mask_fn(a, s)
            s, f = s[m], f[m]
        pairs.append((s, f))
    return bt.pooled_ic(pairs, hz)


def threshold_split(res, thr, min_n):
    """블록 ≥ thr vs < thr 의 forward return 평균 차와 NW t(회귀 f = a + b·1[s≥thr], lag h−1). 튜닝 아님(현행값만)."""
    rows = []
    for a, h in res.history.items():
        for blk in BLOCKS:
            s = h.blocks[blk]
            for hz in res.horizons:
                f = res.forward[a][f"fwd_{hz}"]
                d = pd.concat([s, f], axis=1, keys=["s", "f"]).dropna()
                if len(d) < 3:
                    continue
                D = (d["s"] >= thr).astype(float)
                vd = D.var(ddof=0)
                hi, lo = d["f"][D == 1], d["f"][D == 0]
                if vd == 0:
                    b, t = np.nan, np.nan
                else:
                    b = hi.mean() - lo.mean()
                    e = d["f"] - (lo.mean() + b * D)
                    se = bt.newey_west_se(((D - D.mean()) * e).to_numpy(), hz - 1) / vd
                    t = b / se if se > 0 else np.nan
                rows.append({"asset_id": a, "block": blk, "horizon": hz, "threshold": thr, "share_high": D.mean(),
                             "n_high": int(D.sum()), "n_low": int((1 - D).sum()), "mean_high": hi.mean(),
                             "mean_low": lo.mean(), "diff": b, "t_nw": t,
                             "warning": "표본 부족" if min(D.sum(), (1 - D).sum()) < min_n else ""})
    return pd.DataFrame(rows)


def verdict(ic, t_col="t_nw", t_cut=1.96, half_col="ic"):
    """판정 규칙 — 사전 등록이 아니다: 전체 표본 IC·t 요약표를 본 뒤에 정한 일반 규칙(자산별로 맞추지는 않음).
    기본(base): 전체 표본 기준
    - 지지: IC>0·t(t_col)≥t_cut 인 기간이 4개 중 2개 이상, 그 기간들에서 전·후반 half_col 이 모두 > 0
    - 역방향: 부호를 뒤집은 같은 조건
    - 그 밖: 유의하지 않음/혼재
    민감도 규칙은 main 의 RULES(A: 전·후반 겹치지 않는 표본 IC, B: t≥2.58, C: 겹치지 않는 표본 t≥1.96)."""
    rows = []
    for (a, blk), g in ic.groupby(["asset_id", "block"]):
        full = g[g.period == "full"].set_index("horizon")
        h1 = g[g.period == "first_half"].set_index("horizon")[half_col]
        h2 = g[g.period == "second_half"].set_index("horizon")[half_col]
        tt = full[t_col]
        pos = [h for h in full.index if full.at[h, "ic"] > 0 and tt[h] >= t_cut and h1[h] > 0 and h2[h] > 0]
        neg = [h for h in full.index if full.at[h, "ic"] < 0 and tt[h] <= -t_cut and h1[h] < 0 and h2[h] < 0]
        sig_pos = [h for h in full.index if full.at[h, "ic"] > 0 and tt[h] >= t_cut]
        sig_neg = [h for h in full.index if full.at[h, "ic"] < 0 and tt[h] <= -t_cut]
        v = "지지" if len(pos) >= 2 else ("역방향" if len(neg) >= 2 else "유의하지 않음/혼재")
        rows.append({"asset_id": a, "block": blk, "verdict": v, "stable_pos_h": ",".join(map(str, pos)),
                     "stable_neg_h": ",".join(map(str, neg)), "sig_pos_h": ",".join(map(str, sig_pos)),
                     "sig_neg_h": ",".join(map(str, sig_neg)),
                     **{f"ic_{h}": round(full.at[h, "ic"], 3) for h in full.index},
                     **{f"t_{h}": round(full.at[h, "t_nw"], 2) for h in full.index}})
    return pd.DataFrame(rows)


def contrarian_profiles(profs, variant):
    """2026-10-28 역발상 추가분(confluence·rv_ratio) 유무 변형.
    pre_rework: 둘 다 없음(equity·fx 는 rsi_14 를 price 로 되돌림) / only_confluence: rv_ratio 만 뺌 /
    only_rv: confluence 만 뺌(equity·fx rsi_14 는 price 로) / current: 그대로."""
    p = copy.deepcopy(profs)
    if variant == "current":
        return p
    for cls, d in p.items():
        ov = d["blocks"]["oversold"]
        drop_conf = variant in ("pre_rework", "only_rv")
        drop_rv = variant in ("pre_rework", "only_confluence")
        if drop_conf and "confluence" in ov:
            conf = ov.pop("confluence")
            if cls in ("equity_index", "fx"):
                ov["price"].extend([it for it in conf if it["name"] == "rsi_14"])
        if drop_rv:
            if cls == "equity_index":
                ov["vol_sentiment"] = [it for it in ov["vol_sentiment"] if it["name"] != "rv_ratio_20"]
            else:
                ov.pop("volatility", None)
    return p


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    log = []

    def note(msg):
        print(msg, flush=True)
        log.append(msg)

    panel = pd.read_csv(ROOT / "data" / "processed" / "panel.csv.gz", parse_dates=["date", "as_of"])
    uni, profs, sc = raw_cfg()
    min_n = int(sc["backtest"]["min_n_warning"])
    note(f"패널 {len(panel):,}행, as_of 최대 {panel['as_of'].max().date()}")

    # ---- 1. 기본 백테스트
    t = time.time()
    eng = engine(uni, profs, sc)
    res = eng.backtest(panel)
    note(f"[base] 백테스트 {time.time() - t:.1f}초, horizons {res.horizons}")
    for a, r in res.return_rule.items():
        note(f"  수익률 규칙 {a}: {r}")
    res.quantiles.to_csv(OUT / "quantiles.csv", index=False)
    res.bands.to_csv(OUT / "bands.csv", index=False)
    res.events.to_csv(OUT / "events.csv", index=False)
    res.event_list.to_csv(OUT / "event_list.csv", index=False)
    res.ic.to_csv(OUT / "ic.csv", index=False)
    res.regimes.to_csv(OUT / "regimes.csv", index=False)
    res.pooled_ic.to_csv(OUT / "pooled_ic.csv", index=False)
    res.pooled_bands.to_csv(OUT / "pooled_bands.csv", index=False)
    rows = []
    for a, fr in res.forward.items():
        d = fr.join(res.history[a].blocks).join(res.regime_daily[a][["label", "partial"]])
        d.index.name = "date"
        rows.append(d.reset_index().assign(asset_id=a))
    # 일별 forward return 전체는 가격 이력을 되살릴 수 있어 커밋 대상 밖(data/processed, .gitignore)에 둔다
    pd.concat(rows, ignore_index=True).round(6).to_csv(ROOT / "data" / "processed" / "phase3_forward_returns.csv.gz",
                                                       index=False)
    pd.DataFrame([{"asset_id": a, "rule": r} for a, r in res.return_rule.items()]).to_csv(OUT / "return_rules.csv",
                                                                                          index=False)
    # 국면 풀링: 자산마다 forward return 에서 그 자산 무조건 평균(점수 있는 날)을 뺀 초과수익을 라벨별로 합친다
    rows = []
    for hz in res.horizons:
        ex = []
        for a, fr in res.forward.items():
            lab = res.regime_daily[a]["label"]
            f = fr[f"fwd_{hz}"].where(lab.notna())
            ex.append(pd.DataFrame({"label": lab, "excess": f - f.mean(), "asset_id": a}).dropna())
        ex = pd.concat(ex)
        for name, g in ex.groupby("label"):
            st = bt.ret_stats(g["excess"], None, hz, min_n)
            rows.append({"regime": name, "horizon": hz, "n_assets": g["asset_id"].nunique(), "n": st["n"],
                         "mean_excess": st["mean"], "median_excess": st["median"], "share_excess_pos": st["hit_rate"],
                         "warning": st["warning"]})
    pd.DataFrame(rows).to_csv(OUT / "regimes_pooled_excess.csv", index=False)
    vd = verdict(res.ic)
    cells = res.ic_cells
    vd = vd.merge(cells, on=["asset_id", "block"], how="left")
    full_ic = res.ic[res.ic.period == "full"]
    for col in ("p_placebo", "q_placebo", "q_nw", "se_ratio"):
        w = full_ic.pivot(index=["asset_id", "block"], columns="horizon", values=col)
        w.columns = [f"{col}_{h}" for h in w.columns]
        vd = vd.merge(w.reset_index(), on=["asset_id", "block"], how="left")
    vd.to_csv(OUT / "verdict.csv", index=False)
    cells.to_csv(OUT / "ic_cells.csv", index=False)
    # 판정 규칙 민감도(규칙은 결과를 본 뒤 정했으므로 대안 규칙의 결과를 함께 낸다)
    RULES = {"base": {}, "A_nonoverlap_halves": {"half_col": "ic_nonoverlap"}, "B_t2.58": {"t_cut": 2.58},
             "C_nonoverlap_t": {"t_col": "t_nonoverlap"}}
    vr = None
    for name, kw in RULES.items():
        v = verdict(res.ic, **kw)[["asset_id", "block", "verdict"]].rename(columns={"verdict": name})
        vr = v if vr is None else vr.merge(v, on=["asset_id", "block"])
    vr.to_csv(OUT / "verdict_rules.csv", index=False)
    for name in RULES:
        sel = vr[vr[name] != "유의하지 않음/혼재"]
        note(f"  판정 규칙 {name}: " + ", ".join(f"{a}/{b}={x}" for a, b, x in sel[["asset_id", "block", name]].values))
    # 겹치지 않는 표본 IC 의 전·후반
    nov = res.ic.pivot_table(index=["asset_id", "block", "horizon"], columns="period",
                             values=["ic_nonoverlap", "t_nonoverlap", "n_nonoverlap"])
    nov.columns = [f"{a}_{b}" for a, b in nov.columns]
    nov.reset_index().to_csv(OUT / "ic_nonoverlap_halves.csv", index=False)
    sr = full_ic["se_ratio"]
    note(f"  플라시보 SD / NW SE: 중앙 {sr.median():.2f}, 10~90% {sr.quantile(.1):.2f}~{sr.quantile(.9):.2f}")
    thr = float(sc["regime"]["threshold"])
    th = threshold_split(res, thr, min_n)
    th.to_csv(OUT / "threshold50.csv", index=False)
    dist = []
    for a, h in res.history.items():
        for blk in BLOCKS:
            s = h.blocks[blk].dropna()
            dist.append({"asset_id": a, "block": blk, "n": len(s), "median": s.median(), "share_ge50": (s >= thr).mean(),
                         "share_ge75": (s >= 75).mean(), "share_ge90": (s >= 90).mean(),
                         "share_le25": (s <= 25).mean(), "share_le10": (s <= 10).mean()})
    pd.DataFrame(dist).to_csv(OUT / "score_distribution.csv", index=False)

    # UST10Y 밸류에이션 분할(term_premium 첫 점수일 전후: 지표 2개 vs 3개)
    s = res.history["UST10Y"].blocks["valuation"]
    rows = []
    for per, m in (("before_2019-05-28(2/3 지표)", s.index < UST_TP_START), ("from_2019-05-28(3/3 지표)", s.index >= UST_TP_START)):
        for hz in res.horizons:
            r = bt.spearman_ic(s[m], res.forward["UST10Y"][f"fwd_{hz}"][m], hz)
            rows.append({"period": per, "horizon": hz, **r, "warning": "표본 부족" if r["n_nonoverlap"] < min_n else ""})
    pd.DataFrame(rows).to_csv(OUT / "ust10y_valuation_split.csv", index=False)

    # ---- 2. 통화 이중반영 3변형(KOSPI200 만 해당 — SP500 은 두 통화 지표를 모두 제외)
    rows, rg = [], []
    for v in ("both", "oversold_only", "fundamental_only"):
        sc2 = copy.deepcopy(sc)
        sc2["currency_variant"] = v
        r = engine(uni, profs, sc2).backtest(panel, asset_ids=["KOSPI200"], placebo=0)
        rows.append(ic_table(r, v, ["KOSPI200"]))
        rg.append(r.regimes.assign(variant=v))
        rg.append(r.events[r.events.block.isin(["oversold", "fundamental"])].assign(variant=v, kind="event"))
    pd.concat(rows).to_csv(OUT / "exp_currency_variant_ic.csv", index=False)
    pd.concat(rg).to_csv(OUT / "exp_currency_variant_regime_events.csv", index=False)
    note("[exp] 통화 변형 3개 완료")

    # ---- 3. expanding vs rolling(10년)
    t = time.time()
    sc2 = copy.deepcopy(sc)
    sc2["percentile"]["method"] = "rolling"
    rr = engine(uni, profs, sc2).backtest(panel, placebo=0)
    pd.concat([ic_table(res, "expanding"), ic_table(rr, "rolling")]).to_csv(OUT / "exp_percentile_method_ic.csv",
                                                                             index=False)
    diff = []
    for a in res.history:
        for blk in BLOCKS:
            x, y = res.history[a].blocks[blk], rr.history[a].blocks[blk]
            d = (x - y).abs()
            diff.append({"asset_id": a, "block": blk, "first_diff_date": d[d > 1e-9].first_valid_index(),
                         "share_days_diff": (d > 1e-9).mean(), "mean_abs_diff": d.mean()})
    pd.DataFrame(diff).to_csv(OUT / "exp_percentile_method_diff.csv", index=False)
    note(f"[exp] rolling 백분위 {time.time() - t:.1f}초")

    # ---- 4. 가격 지표 제외 규칙(사전 등록): 전반부 상관 > 0.9 쌍 → IC 낮은 쪽 후보 → 후반부 블록 IC 가 나빠지지 않을 때만 제외
    corr_rows, ind_ic, cand = [], [], set()
    firsts, seconds = {}, {}
    for a in EQUITY:
        s = res.history[a].blocks["oversold"].dropna()
        mid = s.index[len(s) // 2]
        firsts[a], seconds[a] = (lambda idx, m=mid: idx < m), (lambda idx, m=mid: idx >= m)
    sc_first = pd.concat([res.history[a].score[REGISTERED_PRICE][firsts[a](res.history[a].score.index)] for a in EQUITY])
    cm = sc_first.corr()
    for hz in res.horizons:
        for n in REGISTERED_PRICE:
            pairs = [(res.history[a].score[n][firsts[a](res.history[a].score.index)],
                      res.forward[a][f"fwd_{hz}"][firsts[a](res.forward[a].index)]) for a in EQUITY]
            r = bt.pooled_ic(pairs, hz)
            ind_ic.append({"indicator": n, "horizon": hz, "half": "first", **r})
            for a in EQUITY:
                m = firsts[a](res.history[a].score.index)
                ind_ic.append({"indicator": n, "horizon": hz, "half": f"first:{a}",
                               **bt.spearman_ic(res.history[a].score[n][m], res.forward[a][f"fwd_{hz}"][m], hz)})
    ii = pd.DataFrame(ind_ic)
    ic_p = ii[(ii.half == "first") & (ii.horizon == PRIMARY_H)].set_index("indicator")["ic"]
    for i, x in enumerate(REGISTERED_PRICE):
        for y in REGISTERED_PRICE[i + 1:]:
            c = cm.at[x, y]
            per_asset = {a: res.history[a].score[[x, y]][firsts[a](res.history[a].score.index)].corr().iat[0, 1]
                         for a in EQUITY}
            lower = x if ic_p[x] < ic_p[y] else y
            hit = c > CORR_CUT
            if hit:
                cand.add(lower)
            corr_rows.append({"a": x, "b": y, "corr_first_pooled": c, **{f"corr_first_{k}": v for k, v in per_asset.items()},
                              "over_cut": hit, f"ic{PRIMARY_H}_a": ic_p[x], f"ic{PRIMARY_H}_b": ic_p[y],
                              "candidate": lower if hit else ""})
    pd.DataFrame(corr_rows).to_csv(OUT / "exp_price_exclusion_corr.csv", index=False)
    ii.to_csv(OUT / "exp_price_exclusion_indicator_ic.csv", index=False)
    note(f"[exp] 제외 후보: {sorted(cand) or '없음'}")
    res_rows = []
    trials = [[c] for c in sorted(cand)] + ([sorted(cand)] if len(cand) > 1 else [])
    for drop in trials:
        u2 = copy.deepcopy(uni)
        for it in u2:
            if it["asset_id"] in EQUITY:
                ov = it.setdefault("overrides", {}) or {}
                it["overrides"] = ov
                ov["exclude"] = list(ov.get("exclude", []) or []) + drop
        r2 = engine(u2, profs, sc).backtest(panel, asset_ids=EQUITY, placebo=0)
        for hz in res.horizons:
            w = pooled_block_ic(res, EQUITY, "oversold", hz, lambda a, s_: seconds[a](s_.index))
            wo = pooled_block_ic(r2, EQUITY, "oversold", hz, lambda a, s_: seconds[a](s_.index))
            row = {"drop": ",".join(drop), "horizon": hz, "ic_second_with": w["ic"], "t_with": w["t_nw"],
                   "ic_second_without": wo["ic"], "t_without": wo["t_nw"], "n": wo["n"],
                   "not_worse": wo["ic"] >= w["ic"]}
            for a in EQUITY:
                m1 = seconds[a](res.history[a].blocks.index)
                m2 = seconds[a](r2.history[a].blocks.index)
                row[f"ic_with_{a}"] = bt.spearman_ic(res.history[a].blocks["oversold"][m1],
                                                     res.forward[a][f"fwd_{hz}"][m1], hz)["ic"]
                row[f"ic_without_{a}"] = bt.spearman_ic(r2.history[a].blocks["oversold"][m2],
                                                        r2.forward[a][f"fwd_{hz}"][m2], hz)["ic"]
            res_rows.append(row)
    # 보조(자산별 적용): 자산 안 상관 > 0.9 쌍 → 그 자산 전반부 IC(63) 낮은 쪽 → 그 자산 후반부 블록 IC 비교
    for a in EQUITY:
        m1 = firsts[a](res.history[a].score.index)
        cma = res.history[a].score[REGISTERED_PRICE][m1].corr()
        ica = ii[(ii.half == f"first:{a}") & (ii.horizon == PRIMARY_H)].set_index("indicator")["ic"]
        ca = sorted({(x if ica[x] < ica[y] else y) for i, x in enumerate(REGISTERED_PRICE)
                     for y in REGISTERED_PRICE[i + 1:] if cma.at[x, y] > CORR_CUT})
        note(f"[exp] 자산별 제외 후보 {a}: {ca or '없음'}")
        for c in ca:
            u2 = copy.deepcopy(uni)
            it = next(x for x in u2 if x["asset_id"] == a)
            ov = it.get("overrides") or {}
            it["overrides"] = ov
            ov["exclude"] = list(ov.get("exclude", []) or []) + [c]
            r2 = engine(u2, profs, sc).backtest(panel, asset_ids=[a], placebo=0)
            for hz in res.horizons:
                m_w = seconds[a](res.history[a].blocks.index)
                m_o = seconds[a](r2.history[a].blocks.index)
                w = bt.spearman_ic(res.history[a].blocks["oversold"][m_w], res.forward[a][f"fwd_{hz}"][m_w], hz)
                wo = bt.spearman_ic(r2.history[a].blocks["oversold"][m_o], r2.forward[a][f"fwd_{hz}"][m_o], hz)
                res_rows.append({"drop": f"{a}:{c}", "horizon": hz, "ic_second_with": w["ic"], "t_with": w["t_nw"],
                                 "ic_second_without": wo["ic"], "t_without": wo["t_nw"], "n": wo["n"],
                                 "not_worse": wo["ic"] >= w["ic"]})
    rex = pd.DataFrame(res_rows)
    if len(rex):
        rex["decision_primary"] = rex["drop"].map(
            rex[rex.horizon == PRIMARY_H].set_index("drop")["not_worse"].map({True: "제외 조건 충족", False: "유지"}))
    rex.to_csv(OUT / "exp_price_exclusion_result.csv", index=False)

    # ---- 5. KOSPI200 이익 민감도(시총가중 vs _ew vs _ex2) — 설정 사본의 KOSPI200 overrides 로 필드만 바꾼다
    swap = {"valuation.multiples": [("per_fwd_12m", "level", "-", ["fwd_per"]), ("erp", "erp", "+", ["fwd_per", "local_10y"])],
            "fundamental.earnings": [("revision_breadth", "level", "+", ["eps_up_share"]),
                                     ("fwd_eps_chg_1m", "pct_change_months", "+", ["fwd_eps_12m"], {"months": 1}),
                                     ("fwd_eps_chg_3m", "pct_change_months", "+", ["fwd_eps_12m"], {"months": 3}),
                                     ("revision_momentum", "revision_momentum", "+", ["fwd_eps_12m"], {"months": 1})]}
    subst = {"fwd_per", "fwd_eps_12m", "eps_up_share"}
    rows, corr = [], []
    base_k = None
    for sfx in ("", "_ew", "_ex2"):
        u2 = copy.deepcopy(uni)
        if sfx:
            k = next(it for it in u2 if it["asset_id"] == "KOSPI200")
            ov = k.setdefault("overrides", {}) or {}
            k["overrides"] = ov
            ov["exclude"] = [x[0] for items in swap.values() for x in items]
            ov["add"] = {key: [{"name": x[0] + sfx, "indicator": x[1], "direction": x[2],
                                "fields": [f + sfx if f in subst else f for f in x[3]],
                                **({"params": x[4]} if len(x) > 4 else {})} for x in items]
                         for key, items in swap.items()}
        r = engine(u2, profs, sc).backtest(panel, asset_ids=["KOSPI200"], placebo=0)
        lab = sfx or "_capweight(main)"
        rows.append(ic_table(r, lab, ["KOSPI200"], ["valuation", "fundamental"]))
        if base_k is None:
            base_k = r.history["KOSPI200"].blocks
        for blk in ("valuation", "fundamental"):
            corr.append({"variant": lab, "block": blk,
                         "corr_with_main": base_k[blk].corr(r.history["KOSPI200"].blocks[blk]),
                         "last_score": r.history["KOSPI200"].blocks[blk].dropna().iloc[-1]})
    pd.concat(rows).to_csv(OUT / "exp_kospi_earnings_ic.csv", index=False)
    pd.DataFrame(corr).to_csv(OUT / "exp_kospi_earnings_corr.csv", index=False)
    note("[exp] KOSPI200 이익 민감도 완료")

    # ---- 6. 역발상 개편 점검(confluence·rv_ratio 유무)
    rows, prow, brow = [], [], []
    classes = {}
    for it in uni:
        classes.setdefault(it["asset_class"], []).append(it["asset_id"])
    classes["ALL"] = [it["asset_id"] for it in uni]
    for v in ("pre_rework", "only_confluence", "only_rv", "current"):
        r = res if v == "current" else engine(uni, contrarian_profiles(profs, v), sc).backtest(panel, placebo=0)
        rows.append(ic_table(r, v, blocks=["oversold"]))
        for cls, members in classes.items():
            for hz in r.horizons:
                prow.append({"variant": v, "asset_class": cls, "horizon": hz,
                             **pooled_block_ic(r, members, "oversold", hz)})
        brow.append(r.events[r.events.block == "oversold"].assign(variant=v))
        note(f"[exp] 역발상 변형 {v} 완료")
    pd.concat(rows).to_csv(OUT / "exp_contrarian_ic.csv", index=False)
    pd.DataFrame(prow).to_csv(OUT / "exp_contrarian_pooled_ic.csv", index=False)
    pd.concat(brow).to_csv(OUT / "exp_contrarian_events.csv", index=False)

    # ---- 7. 200일 SMA 추세 게이트(민감도 전용, 설정 반영 안 함): 과매도 ≥ alert 구간·이벤트를 추세 상·하로 나눈다
    alert = float(sc["bands"]["alert"])
    cooldown = int(sc["backtest"]["event_cooldown_bdays"])
    rows, ev22 = [], []
    for a, h in res.history.items():
        s = h.blocks["oversold"]
        fr = res.forward[a]
        up = fr["trend_up"]
        ev_all = bt.event_dates(s >= alert, cooldown)
        ev_up = bt.event_dates((s >= alert) & (up == 1), cooldown)
        for hz in res.horizons:
            f, m = fr[f"fwd_{hz}"], fr[f"mae_{hz}"]
            for gate, mk in (("no_gate", s >= alert), ("trend_up", (s >= alert) & (up == 1)),
                             ("trend_down", (s >= alert) & (up == 0))):
                rows.append({"asset_id": a, "horizon": hz, "kind": "band", "gate": gate, **bt.ret_stats(f[mk], m, hz, min_n)})
            for gate, ev in (("no_gate", ev_all), ("trend_up", ev_up)):
                st = bt.ret_stats(f.reindex(ev), m, hz, min_n)
                st["warning"] = "표본 부족" if st["n"] < min_n else ""
                rows.append({"asset_id": a, "horizon": hz, "kind": "event", "gate": gate, **st})
            for yr_gate, mk in (("no_gate", s >= alert), ("trend_up", (s >= alert) & (up == 1))):
                m22 = mk & (s.index.year == 2022)
                ev22.append({"asset_id": a, "horizon": hz, "gate": yr_gate, **bt.ret_stats(f[m22], m, hz, min_n)})
        gi = pd.Series(np.where(up == 1, s, np.where(up == 0, 50.0, np.nan)), index=s.index).where(s.notna())
        for hz in res.horizons:
            rows.append({"asset_id": a, "horizon": hz, "kind": "ic_gated(하락추세=50)", "gate": "trend_up",
                         **{k: v for k, v in bt.spearman_ic(gi, fr[f"fwd_{hz}"], hz).items()}})
    pd.DataFrame(rows).to_csv(OUT / "exp_trend_gate.csv", index=False)
    pd.DataFrame(ev22).to_csv(OUT / "exp_trend_gate_2022_banddays.csv", index=False)
    note("[exp] 추세 게이트 완료")

    info = {"seconds": round(time.time() - t0, 1), "panel_rows": int(len(panel)), "horizons": res.horizons,
            "primary_horizon_exclusion_rule": PRIMARY_H, "corr_cut": CORR_CUT,
            "score_first": {a: str(h.blocks.dropna(how="all").index[0].date()) for a, h in res.history.items()},
            "return_rules": res.return_rule, "exclusion_candidates": sorted(cand)}
    (OUT / "run_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    note(f"총 {info['seconds']}초")


if __name__ == "__main__":
    main()
