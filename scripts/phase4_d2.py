"""Phase 4 D-2 — KOSPI200 바텀업 CAPE `cape_bu`(민감도 필드, 점수 미사용) 생성 + 참고용 IC(채택 대상 아님).

    PYTHONPATH=$PWD/src .venv/bin/python scripts/phase4_d2_collect.py   # 원자료(한 번)
    PYTHONPATH=$PWD/src .venv/bin/python scripts/phase4_d2.py

입력: data/raw/phase4d2_kr/(수집분), data/raw/refinitiv/holdings/kodex200.csv, data/processed/panel.csv.gz(읽기만).
산출: data/processed/phase4d2_cape_bu.csv.gz(패널 형식 행, 공유 패널에 합치지 않음),
      outputs/phase4/phase4d2_*.csv, phase4d2_run_log.txt, phase4d2_info.json.
설정 파일(config/*)과 공유 패널은 바꾸지 않는다. IC 는 메모리 안 설정 사본(Phase 3 §5 와 같은 방식)으로 낸다.
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
import mtscore  # noqa: E402
from mtscore import ScoringEngine, build_config, load_config  # noqa: E402
from mtscore.core import backtest as bt  # noqa: E402
from mtscore.data import cape_bu as C  # noqa: E402
from mtscore.data.adapters import ecos  # noqa: E402
from mtscore.data.schema import validate_panel  # noqa: E402

RAW = ROOT / "data" / "raw" / "phase4d2_kr"
OUT = ROOT / "outputs" / "phase4"
PROC = ROOT / "data" / "processed"
END = pd.Timestamp("2026-10-27")
MAX_FIRST_YEAR = 2003          # 사전 등록 §D-2
WINDOW = 10                    # 연간 10개(= 120개월)
MIN_SHARE = 0.9                # 가정: 창이 성립한 종목 시총 ≥ 시총 있는 집합 종목 시총의 90% 인 달만
SPLITS = {"select_2013_2019": ("2013-01-01", "2019-12-31"), "confirm_2020_end": ("2020-01-01", "2026-12-31")}
VAL_MULTIPLES = ["pbr_trailing", "per_fwd_12m", "dividend_yield", "erp"]
FIELD = "cape_bu"
SOURCE = "refinitiv:KODEX200 보유종목(결산 ≤2003 고정 집합) TR.F.NetIncAfterMinIntr·TR.CompanyMarketCap 바텀업 + ecos:901Y009"
NOTE = ("민감도(점수 미사용). 현재 KOSPI200 구성종목(KODEX200 보유) 중 2003년 이전부터 연간 이익이 있는 종목 고정 — "
        "생존편향(가정, 사전 등록 2026-10-29 §D-2)")


def load_inputs():
    rd = lambda sec: pd.concat([pd.read_csv(p) for p in sorted((RAW / sec).glob("*.csv"))], ignore_index=True)
    fiscal = C.parse_fiscal(rd("ni"), rd("eps"))
    m = rd("mcap").iloc[:, :3]
    m.columns = ["ric", "date", "mcap"]
    m["date"] = pd.to_datetime(m["date"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    m["mcap"] = pd.to_numeric(m["mcap"], errors="coerce")
    m = m.dropna().query("date <= @END").drop_duplicates(["ric", "date"])
    cp = ecos.read_raw(RAW / "ecos" / "901Y009_M_0_199501_202610.csv", "M")
    cp["as_of"] = ecos.AS_OF_RULES["901Y009"](pd.DatetimeIndex(cp["date"]))
    hold = pd.read_csv(ROOT / "data" / "raw" / "refinitiv" / "holdings" / "kodex200.csv")
    hold.columns = ["inst", "ric", "w"]
    w = hold.dropna(subset=["ric"]).set_index("ric")["w"]
    eps = rd("eps").iloc[:, [0, 1, 3]]
    eps.columns = ["ric", "pe", "eps"]
    eps["pe"] = pd.to_datetime(eps["pe"], errors="coerce")
    return fiscal, m, cp, w, eps.dropna()


def ic_rows(score, fwd_df, label, horizons, n_shifts, seed):
    rows = []
    for sp, (a, b) in SPLITS.items():
        s = score[(score.index >= a) & (score.index <= b)].dropna()
        fw = {h: fwd_df[f"fwd_{h}"] for h in horizons}
        shifts = bt.shift_draws(int(len(s)), n_shifts, seed)
        obs, P = bt.placebo_ic(s, fw, shifts) if len(s) else (np.full(len(horizons), np.nan), np.empty((0, 0)))
        p = bt.placebo_p(obs, P) if len(shifts) else np.full(len(horizons), np.nan)
        for j, h in enumerate(horizons):
            st = bt.spearman_ic(s, fwd_df[f"fwd_{h}"].reindex(s.index), h)
            rows.append({"series": label, "split": sp, "horizon": h, "first": str(s.index.min().date()) if len(s) else "",
                         "ic": st["ic"], "n": st["n"], "ic_nonoverlap": st["ic_nonoverlap"],
                         "n_nonoverlap": st["n_nonoverlap"], "p_placebo": p[j], "n_shifts": int(len(shifts))})
    return rows


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    log = []

    def note(msg):
        print(msg, flush=True)
        log.append(str(msg))

    note(f"mtscore = {mtscore.__file__}")
    fiscal, mcap, cpi, w, eps = load_inputs()
    info = {}

    # ---- 1. 고정 종목 집합
    members = C.fixed_set(fiscal, MAX_FIRST_YEAR)
    eps_first = eps.groupby("ric")["pe"].min()
    eps_set = eps_first[eps_first.dt.year <= MAX_FIRST_YEAR].index
    info["set"] = {"n_holdings": int(len(w)), "n_with_ni": int(fiscal["ric"].nunique()), "n_members": len(members),
                   "weight_share_pct": round(float(w.reindex(members).sum()), 2),
                   "eps_def_n": int(len(eps_set)), "eps_def_weight_pct": round(float(w.reindex(eps_set).sum()), 2)}
    pd.DataFrame({"ric": members, "weight_pct": w.reindex(members).to_numpy(),
                  "first_fy": fiscal.groupby("ric")["pe"].min().reindex(members).dt.date.to_numpy(),
                  "first_mcap": mcap.groupby("ric")["date"].min().reindex(members).dt.date.to_numpy()}
                 ).to_csv(OUT / "phase4d2_members.csv", index=False)
    note(f"[집합] {info['set']}")

    # ---- 2. PIT 가용일 출처(집합 종목·연도)
    fa = C.available_date(fiscal[fiscal["ric"].isin(members)])
    src = fa["avail_src"].value_counts(normalize=True).round(4).to_dict()
    late = float(((fa["avail"] - fa["pe"]).dt.days > 90).mean())
    fye = fa["pe"].dt.month.value_counts().to_dict()
    info["pit"] = {"avail_src_share": src, "share_avail_after_fye90": round(late, 4), "fye_months": fye,
                   "firm_years": int(len(fa))}
    note(f"[PIT] {info['pit']}")

    # ---- 3. cape_bu
    cape = C.cape_bottomup(fiscal, mcap, cpi, members, window=WINDOW, min_share=MIN_SHARE)
    cape = cape[cape["date"] <= END].reset_index(drop=True)
    cape.to_csv(OUT / "phase4d2_cape_bu_monthly.csv", index=False, float_format="%.6g")
    ok = cape.dropna(subset=["value"])
    info["coverage"] = {"first": str(ok["date"].min().date()), "last": str(ok["date"].max().date()),
                        "months": int(len(ok)),
                        "n_used_first": int(ok["n_used"].iloc[0]), "n_used_2013_01": int(
                            ok.loc[ok["date"].dt.to_period("M") == "2013-01", "n_used"].iloc[0]) if (
                            ok["date"].dt.to_period("M") == "2013-01").any() else None,
                        "n_used_last": int(ok["n_used"].iloc[-1]),
                        "mcap_share_used_min_from_2013": round(float(ok[ok["date"] >= "2013-01-01"]["mcap_share_used"].min()), 4)}
    note(f"[coverage] {info['coverage']}")
    rows = ok.assign(asset_id="KOSPI200", field=FIELD, source=SOURCE)[["date", "asset_id", "field", "value", "as_of",
                                                                        "source"]]
    rows = validate_panel(rows)
    rows.to_csv(PROC / "phase4d2_cape_bu.csv.gz", index=False)
    pd.DataFrame([{"asset_id": "KOSPI200", "field": FIELD, "source": SOURCE,
                   "as_of_rule": "as_of = 그달 집합 종목 시총 표본일 최댓값(월말); 연간 이익은 max(결산+90일, 공시일 다음 날)부터",
                   "note": NOTE, "rows": len(rows), "first": str(rows["date"].min().date()),
                   "last": str(rows["date"].max().date())}]).to_csv(OUT / "phase4d2_field_map.csv", index=False)

    # ---- 4. 비율지수 대안(검토용): .KS200 월말 ÷ 같은 달 Σ E10 — 구성 불일치라 주 정의 아님
    panel = pd.read_csv(PROC / "panel.csv.gz", parse_dates=["date", "as_of"])
    k = panel[panel["asset_id"] == "KOSPI200"]
    px = k[k["field"] == "close"].set_index("date")["value"]
    mc_sum = mcap[mcap["ric"].isin(members)].assign(m=lambda d: d["date"].dt.to_period("M")).groupby("m")["mcap"].sum()
    pxm = px.groupby(px.index.to_period("M")).last()
    j = pd.concat({"ks200": pxm, "mcap_sum": mc_sum}, axis=1).dropna()
    j = j[j.index >= "2011-01"]
    info["proxy_check"] = {"corr_dlog_ks200_vs_set_mcap_2011_": round(float(np.log(j).diff().corr().iloc[0, 1]), 4)}
    note(f"[비교] {info['proxy_check']}")

    # ---- 5. 크기 점검·기존 밸류 지표 상관(월별, 같은 달 마지막 값)
    def monthly(fld):
        s = k[k["field"] == fld].sort_values("as_of").set_index("as_of")["value"]
        return s.groupby(s.index.to_period("M")).last()
    cm = ok.set_index(ok["date"].dt.to_period("M"))
    mm = pd.concat({"cape_bu": cm["value"], "pe_trailing_set": cm["pe_ratio_trailing"], "fwd_per": monthly("fwd_per"),
                    "pbr": monthly("pbr"), "div_yield": monthly("div_yield")}, axis=1).dropna()
    corr_rows = []
    for sp, (a, b) in {"all": ("2000-01", "2026-12"), **SPLITS}.items():
        sub = mm[(mm.index >= pd.Period(a[:7], "M")) & (mm.index <= pd.Period(b[:7], "M"))]
        for c in ["pe_trailing_set", "fwd_per", "pbr", "div_yield"]:
            corr_rows.append({"split": sp, "with": c, "n_months": len(sub),
                              "pearson_level": sub["cape_bu"].corr(sub[c]),
                              "spearman_level": sub["cape_bu"].corr(sub[c], method="spearman")})
    desc = mm.describe().T[["mean", "min", "50%", "max"]]
    note("[크기] 월별 요약(겹치는 달)\n" + desc.round(2).to_string())
    info["magnitude"] = {c: {kk: round(float(v), 2) for kk, v in desc.loc[c].items()} for c in desc.index}
    info["cape_last"] = {"date": str(ok["date"].iloc[-1].date()), "value": round(float(ok["value"].iloc[-1]), 2),
                         "pe_trailing_set": round(float(ok["pe_ratio_trailing"].iloc[-1]), 2)}

    # ---- 6. IC(참고용) — 설정 사본: KOSPI200 밸류 multiples 를 cape_bu 하나로 바꾼 밸류 블록 = cape 백분위 점수(방향 −)
    uni = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text(encoding="utf-8"))
    sc = yaml.safe_load((ROOT / "config" / "scoring.yaml").read_text(encoding="utf-8"))
    profs = {}
    for p in sorted((ROOT / "config" / "profiles").glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        profs[d.get("asset_class", p.stem)] = d
    n_sh, seed = int(sc["backtest"]["placebo_shifts"]), int(sc["backtest"]["placebo_seed"])
    panel2 = pd.concat([panel, rows], ignore_index=True)
    base = ScoringEngine(build_config(copy.deepcopy(uni), copy.deepcopy(profs), copy.deepcopy(sc))).backtest(
        panel2, asset_ids=["KOSPI200"], placebo=0)
    u2 = copy.deepcopy(uni)
    kk = next(it for it in u2 if it["asset_id"] == "KOSPI200")
    kk["overrides"] = {"exclude": VAL_MULTIPLES,
                       "add": {"valuation.multiples": [{"name": "cape_bu", "indicator": "level", "direction": "-",
                                                        "fields": [FIELD]}]}}
    var = ScoringEngine(build_config(u2, copy.deepcopy(profs), copy.deepcopy(sc))).backtest(
        panel2, asset_ids=["KOSPI200"], placebo=0)
    hz = list(base.horizons)
    fwd = base.forward["KOSPI200"]
    cape_score = var.history["KOSPI200"].blocks["valuation"]
    base_val = base.history["KOSPI200"].blocks["valuation"]
    info["cape_score_first"] = str(cape_score.dropna().index.min().date())
    # 원 수준(방향 − 이므로 −cape)의 PIT 일별 값: 엔진 달력 위 as_of 기준 최신값(최대 70일 유지와 같은 효과는 월별이라 불필요)
    lvl = -rows.set_index("as_of")["value"].sort_index()
    lvl_d = lvl.reindex(fwd.index.union(lvl.index)).ffill().reindex(fwd.index)
    ic = []
    ic += ic_rows(cape_score, fwd, "cape_bu 백분위 점수(엔진, 방향 −)", hz, n_sh, seed)
    ic += ic_rows(lvl_d, fwd, "−cape_bu 원 수준(참고, Phase 3 규칙 아님)", hz, n_sh, seed)
    ic += ic_rows(base_val, fwd, "기준선: 현행 KOSPI200 밸류 블록", hz, n_sh, seed)
    ic += ic_rows(base_val.where(cape_score.notna()), fwd, "기준선(cape 점수 있는 날만)", hz, n_sh, seed)
    icdf = pd.DataFrame(ic)
    icdf.to_csv(OUT / "phase4d2_ic.csv", index=False, float_format="%.4f")
    note("[IC]\n" + icdf.pivot_table(index=["series", "split"], columns="horizon", values=["ic", "p_placebo"]).round(3)
         .to_string())
    for sp, (a, b) in {"all": ("2000-01-01", "2026-12-31"), **SPLITS}.items():
        d = pd.concat({"cape": cape_score, "val": base_val}, axis=1).loc[a:b].dropna()
        corr_rows.append({"split": sp, "with": "score: 현행 밸류 블록(일별)", "n_months": len(d),
                          "pearson_level": d["cape"].corr(d["val"]), "spearman_level": d["cape"].corr(d["val"], "spearman")})
    pd.DataFrame(corr_rows).to_csv(OUT / "phase4d2_corr.csv", index=False, float_format="%.4f")
    note("[상관]\n" + pd.DataFrame(corr_rows).round(3).to_string())

    # ---- 7. 기본 점수 불변 증명: 공유 설정 그대로 + cape_bu 행을 더한 패널 → score_history 재계산 후 저장본과 비교
    eng = ScoringEngine(load_config(ROOT / "config"))
    out = {}
    for tag, pn in (("panel", panel), ("panel+cape_bu", panel2)):
        res = eng.score(pn, as_of=str(END.date()))
        hs = []
        for aid, h in res.history.items():
            b = h.blocks.copy()
            b.index.name = "date"
            hs.append(b.reset_index().assign(asset_id=aid))
        hist = pd.concat(hs, ignore_index=True)[["asset_id", "date", "oversold", "valuation", "fundamental"]]
        out[tag] = hist.dropna(subset=["oversold", "valuation", "fundamental"], how="all").round(4).to_csv(index=False)
    saved = pd.read_csv(ROOT / "outputs" / "phase2" / "score_history.csv.gz").to_csv(index=False)
    mine = {t: pd.read_csv(pd.io.common.StringIO(s)).to_csv(index=False) for t, s in out.items()}
    info["default_unchanged"] = {"panel+cape_bu == panel": mine["panel+cape_bu"] == mine["panel"],
                                 "panel+cape_bu == outputs/phase2/score_history.csv.gz": mine["panel+cape_bu"] == saved,
                                 "rows": int(mine["panel"].count("\n") - 1)}
    note(f"[불변] {info['default_unchanged']}")

    info["seconds"] = round(time.time() - t0, 1)
    (OUT / "phase4d2_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (OUT / "phase4d2_run_log.txt").write_text("\n".join(log) + f"\n완료 {info['seconds']}초\n", encoding="utf-8")


if __name__ == "__main__":
    main()
