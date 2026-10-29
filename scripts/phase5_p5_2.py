"""Phase 5 / P5-2 — 추세를 국면 보조 조건으로 (사전 등록 docs/prereg_phase5.md §P5-2, 결과 보기 전 고정).

    .venv/bin/python scripts/phase5_p5_2.py

입력: data/processed/panel.csv.gz(Phase 2), config/*(현행 설정, 바꾸지 않음). 점수·국면은 불변이고 추세 부호만 쓴다.
산출(outputs/phase5/, 접두어 p5_2_): cells·placebo·counts·per_asset·aux csv, run_log.txt, run_info.json.

사전 등록이 열어 둔 선택을 결과 보기 전에 아래처럼 고정했다(보고서 '가정'에 그대로 옮긴다).
 A1 국면 묶음 소속 = regime.matrix 에서 o(과매도) 상태로 정한 라벨 이름(사전 등록의 7개 이름과 같아야 함, assert).
    '축약:…' 라벨(N/A 블록으로 라벨이 하나로 모이지 않은 날)은 어느 묶음에도 넣지 않는다.
 A2 추세 부호 = ScoringEngine.trend_history 의 sign(현행: TSMOM 12개월, 현금 대비 초과, KR_CORP 만 국고 대비 = 결정 4).
    sign == 0 인 날은 ▲▼ 어느 쪽에도 넣지 않는다.
 A3 초과수익 = 63영업일 forward return − 자산별 무조건 평균. 무조건 평균은 '구간별'(선택·확인 각각)로,
    국면 라벨이 있고 fwd_63 이 있는 모든 날 위에서 계산한다(Phase 3 regimes_pooled_excess 의 관례를 구간 안에 적용).
    자산별 평균 차감은 ▲/▼ 의 자산 구성이 다르면 풀링 차이에서 상쇄되지 않으므로 사전에 고정한다. 전 기간 평균판은 보조.
 A4 통계량 = 묶음 안 (자산, 날) 관측을 모두 합친 평균 초과수익의 차이 D = mean(▲) - mean(▼). H1·H2 모두 D > 0 이 가설 방향이다.
    H1: 과매도 낮음 묶음에서 ▲ > ▼.  H2: 과매도 높음 묶음에서 ▼ 의 초과수익이 ▲ 보다 낮다 = 같은 D > 0.
 A5 플라시보 = 추세 부호 계열만 순환 이동(np.roll). 구간 안에서, 자산별로 (국면 라벨 있음 & 추세 있음)인 날 위에서 굴리고 같은 k 를
    모든 자산에 적용한다. 라벨·초과수익·묶음은 고정. 이동 배열은 구간마다 1개이고 H1·H2 가 함께 쓴다(Phase 3 pooled 방식).
    이동 크기 = bt.shift_draws(nmin, 2000, seed), nmin = 구간 안 자산별 롤링 대상 일수의 최솟값,
    seed = placebo_seed + 2000 + 10 * ci + si (ci = phase4_b 의 ALL 순번 = 5, si = 구간 순번: 선택 0·확인 1; Phase 3/4 시드 규칙).
 A6 p = 양측 bt.placebo_p(채택 판정). 단측 p(D > 0 방향)는 보조.
 A7 채택(가설별) = 선택 D > 0 and 확인 D > 0 and 확인 양측 p <= 0.20.
 A8 시험한 칸 = H1·H2 x (선택·확인) = 4칸(가설 판정은 2개). 자산별·민감도·시평별은 보조이며 시험 칸에 세지 않는다.
"""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "phase5"
CFG_DIR = ROOT / "config"
PREFIX = "p5_2_"
SPLITS = {"selection": ("2013-01-01", "2019-12-31"), "confirmation": ("2020-01-01", None)}   # prereg §0
SPLIT_ORDER = list(SPLITS)
PRIMARY_H = 63
AUX_H = (21, 126, 252)                 # 보조: 시평별 D (p 없음)
N_PLACEBO = 2000
ALL_CLASS_INDEX = 5                    # phase4_b 의 classes 순서(universe 등장 순 5개 + ALL)에서 ALL 의 순번
P_ADOPT = 0.20
LOW_GROUP = ["보유 분할 매수", "고점 경계", "비중 축소"]
HIGH_GROUP = ["최우선 매수", "저평가 패닉 분할 진입", "단기 반등 트레이드", "가치함정 경계"]
HYPOTHESES = {"H1": ("low", "과매도 낮음 묶음: ▲ > ▼"), "H2": ("high", "과매도 높음 묶음: ▼ 가 ▲ 보다 낮다(떨어지는 칼)")}


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True).stdout.strip()


def _source_roots():
    """src/config 가 HEAD 와 같으면 작업 트리를 쓴다. 동시에 다른 레인이 src 를 고치는 중이면 HEAD 사본(git archive)을 쓴다.
    사전 등록 기준선 = 브랜치의 커밋된 현행 설정이므로 어느 쪽이든 같다."""
    dirty = _git("status", "--porcelain", "--", "src", "config")
    if not dirty:
        return ROOT / "src", CFG_DIR, "worktree(clean vs HEAD)", None
    tmp = tempfile.TemporaryDirectory()
    subprocess.run(f"git -C {ROOT} archive HEAD src config | tar -x -C {tmp.name}", shell=True, check=True)
    return Path(tmp.name) / "src", Path(tmp.name) / "config", "HEAD archive(작업 트리 src/config 가 다른 레인으로 수정 중)", tmp


SRC, CFG, SOURCE_MODE, _TMP = _source_roots()
sys.path.insert(0, str(SRC))
from mtscore import ScoringEngine, load_config  # noqa: E402
from mtscore.core import backtest as bt  # noqa: E402


def split_mask(idx, split):
    lo, hi = SPLITS[split]
    m = idx >= pd.Timestamp(lo)
    if hi is not None:
        m &= idx <= pd.Timestamp(hi)
    return np.asarray(m)


def build_long(res, th, horizons):
    """자산별 (date, label, partial, sign, fwd_h...) 긴 표. 같은 자산 달력 위에서 맞춘다."""
    rows = []
    for aid, rd in res.regime_daily.items():
        blocks = res.history[aid].blocks
        # 달력 일치: 국면 라벨·추세·forward 모두 같은 자산 달력(조용한 reindex 로 관측이 빠지는 것을 막는다)
        assert rd.index.equals(blocks.index), aid
        assert th[aid].index.equals(blocks.index), aid
        assert res.forward[aid].index.equals(blocks.index), aid
        assert int(rd["label"].notna().sum()) == int(blocks.notna().any(axis=1).sum()), aid   # 블록이 하나라도 있는 날 = 라벨 있는 날
        d = pd.DataFrame({"asset_id": aid, "label": rd["label"], "partial": rd["partial"], "sign": th[aid]["sign"]},
                         index=blocks.index)
        for h in horizons:
            d[f"fwd_{h}"] = res.forward[aid][f"fwd_{h}"]
        d.index.name = "date"
        rows.append(d.reset_index())
    return pd.concat(rows, ignore_index=True)


def add_group(df, low_names, high_names):
    g = pd.Series(None, index=df.index, dtype=object)
    g[df["label"].isin(low_names)] = "low"
    g[df["label"].isin(high_names)] = "high"
    return df.assign(group=g)


def center(df, h, per_split=True):
    """초과수익 = fwd_h - 자산별 무조건 평균(국면 라벨 있고 fwd_h 있는 날). per_split 이면 구간별로, 아니면 전 기간."""
    col = f"fwd_{h}"
    out = pd.Series(np.nan, index=df.index)
    base = df["label"].notna() & df[col].notna()
    keys = ["asset_id", "split"] if per_split else ["asset_id"]
    mean = df[base].groupby(keys)[col].transform("mean")
    out[base] = df.loc[base, col] - mean
    return out


def diff_stats(d):
    """▲ - ▼ 풀링 평균 차이와 칸 크기. d: group 이 이미 걸러진 (sign, ex) 표."""
    up, dn = d[d["sign"] == 1]["ex"], d[d["sign"] == -1]["ex"]
    return {"mean_up": up.mean() if len(up) else np.nan, "mean_dn": dn.mean() if len(dn) else np.nan,
            "n_up": len(up), "n_dn": len(dn),
            "diff": (up.mean() - dn.mean()) if len(up) and len(dn) else np.nan}


def placebo_split(df, split, grp_names, shifts):
    """한 구간의 플라시보: 자산별로 (라벨 있음 & 추세 부호 있음)인 날 위에서 sign 을 np.roll. Returns {group: (obs, P[shift])}."""
    prep = []
    for aid, g in df[df["split"] == split].groupby("asset_id", sort=False):
        dom = g[g["label"].notna() & g["sign"].notna()]
        prep.append((dom["sign"].to_numpy(dtype=float), dom["group"].to_numpy(dtype=object),
                     dom["ex"].to_numpy(dtype=float)))
    out = {}
    for gname in grp_names:
        masks = [(grp == gname) & np.isfinite(ex) for _, grp, ex in prep]
        exs = [np.where(m, ex, 0.0) for m, (_, _, ex) in zip(masks, prep)]

        def stat(k):
            su = sd = nu = nd = 0.0
            for (sg, _, _), m, e in zip(prep, masks, exs):
                r = np.roll(sg, int(k)) if k else sg
                u, dn = m & (r == 1), m & (r == -1)
                su += e[u].sum()
                nu += u.sum()
                sd += e[dn].sum()
                nd += dn.sum()
            return (su / nu - sd / nd) if nu and nd else np.nan

        out[gname] = (stat(0), np.array([stat(k) for k in shifts]))
    return out


def p_two(obs, P):
    ok = np.isfinite(P)
    return float(bt.placebo_p(np.array([obs]), P[ok].reshape(-1, 1))[0]) if ok.any() and np.isfinite(obs) else np.nan


def p_one_pos(obs, P):
    ok = np.isfinite(P)
    return float(((P[ok] >= obs).sum() + 1) / (ok.sum() + 1)) if ok.any() and np.isfinite(obs) else np.nan


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    log = []

    def note(msg):
        print(msg, flush=True)
        log.append(msg)

    note(f"git HEAD {_git('rev-parse', 'HEAD')} / 브랜치 {_git('rev-parse', '--abbrev-ref', 'HEAD')} / 소스 = {SOURCE_MODE}")
    panel = pd.read_csv(ROOT / "data" / "processed" / "panel.csv.gz", parse_dates=["date", "as_of"])
    cfg = load_config(CFG)
    eng = ScoringEngine(cfg)
    sc = cfg.scoring
    seed = int(sc["backtest"]["placebo_seed"])
    note(f"패널 {len(panel):,}행, as_of 최대 {panel['as_of'].max().date()}, 시드 기준 {seed}, 플라시보 {N_PLACEBO}회")

    # ---- A1: 묶음 소속을 matrix 로 확인
    mx = sc["regime"]["matrix"]
    low_names = [r["label"] for r in mx if r["o"] == "low"]
    high_names = [r["label"] for r in mx if r["o"] == "high"]
    assert set(low_names) == set(LOW_GROUP) and set(high_names) == set(HIGH_GROUP), (low_names, high_names)
    note(f"[A1] 묶음 확인: 낮음 {low_names} / 높음 {high_names}")

    # ---- 점수 이력·forward·국면 라벨(백테스트 플라시보 끔), 추세 부호
    t = time.time()
    horizons = sorted([PRIMARY_H, *AUX_H])
    res = eng.backtest(panel, horizons=horizons, placebo=0)
    th = eng.trend_history(panel)
    note(f"[입력] backtest+trend_history {time.time() - t:.1f}초")
    trend_basis = {a.asset_id: a.trend_basis for a in cfg.universe}
    trend_cash = {a.asset_id: a.trend_cash for a in cfg.universe}
    note(f"[결정 4 확인] 추세 basis: {trend_basis} / cash: {trend_cash}")
    assert trend_basis["KR_CORP"] == "국고 대비" and trend_cash["KR_CORP"] == "none"

    df = build_long(res, th, horizons)
    df = add_group(df, low_names, high_names)
    df["split"] = None
    for sp in SPLIT_ORDER:
        df.loc[split_mask(df["date"], sp), "split"] = sp
    df = df[df["split"].notna()].reset_index(drop=True)
    # A1 검증: 묶음 안에 속한 날의 partial 여부(N/A 블록이 있어도 라벨이 하나로 모이면 이름 라벨 + partial=True)
    inside = df[df["group"].notna()]
    n_partial_inside = int(inside["partial"].astype(bool).sum())
    n_abbr = int(df["label"].astype(str).str.startswith("축약").sum())
    note(f"[A1 검증] 묶음 소속 {len(inside):,}행 중 partial=True {n_partial_inside}행 / '축약:' 라벨 {n_abbr}행(묶음 제외)")

    # 추세 부호 점검(보고용): 자산별 구간 안 ▲ 비율, 0 비율, 결측
    tsum = df.groupby(["asset_id", "split"]).agg(
        n=("sign", "size"), n_sign_na=("sign", lambda s: int(s.isna().sum())), n_zero=("sign", lambda s: int((s == 0).sum())),
        share_up=("sign", lambda s: float((s == 1).sum() / max(s.notna().sum(), 1)))).reset_index()
    tsum.to_csv(OUT / f"{PREFIX}trend_sign_summary.csv", index=False)

    # ---- A3 초과수익
    df["ex"] = center(df, PRIMARY_H, per_split=True)
    df["ex_fullsample"] = center(df, PRIMARY_H, per_split=False)
    obs_df = df[df["group"].notna() & df["sign"].isin([1, -1]) & df["ex"].notna()].copy()

    # ---- 칸 크기(n 일수, n 구별 월수) — 구간 x 묶음 x 추세
    cnt_rows = []
    for sp in SPLIT_ORDER:
        for gname in ("low", "high"):
            for sg, nm in ((1, "up"), (-1, "down")):
                c = obs_df[(obs_df["split"] == sp) & (obs_df["group"] == gname) & (obs_df["sign"] == sg)]
                cnt_rows.append({"split": sp, "group": gname, "trend": nm, "n_obs": len(c), "n_days": int(c["date"].nunique()),
                                 "n_months": int(c["date"].dt.to_period("M").nunique()), "n_assets": int(c["asset_id"].nunique()),
                                 "mean_excess": c["ex"].mean() if len(c) else np.nan, "n_indep_approx": len(c) / PRIMARY_H})
    cnt = pd.DataFrame(cnt_rows)
    cnt.to_csv(OUT / f"{PREFIX}counts.csv", index=False)
    note("[칸 크기]\n" + cnt.round(4).to_string(index=False))

    # ---- 플라시보 이동 배열(구간별 1개, H1·H2 공용)
    shift_info, pl = {}, {}
    for si, sp in enumerate(SPLIT_ORDER):
        sub = df[(df["split"] == sp) & df["label"].notna() & df["sign"].notna()]
        nmin = int(sub.groupby("asset_id").size().min())
        sd = seed + 2000 + 10 * ALL_CLASS_INDEX + si
        shifts = bt.shift_draws(nmin, N_PLACEBO, sd)
        shift_info[sp] = {"nmin": nmin, "seed": sd, "n_shifts": int(len(shifts))}
        pl[sp] = placebo_split(df, sp, ("low", "high"), shifts)
    note(f"[플라시보] 이동 배열: {shift_info}")

    # ---- 판정 칸 (H1·H2 x 구간)
    cells, pl_rows = [], []
    for hname, (gname, desc) in HYPOTHESES.items():
        for sp in SPLIT_ORDER:
            d = obs_df[(obs_df["split"] == sp) & (obs_df["group"] == gname)]
            st = diff_stats(d)
            obs, P = pl[sp][gname]
            assert np.isfinite(obs) and abs(obs - st["diff"]) < 1e-12, (hname, sp, obs, st["diff"])   # 플라시보 관측 = 직접 계산
            ok = np.isfinite(P)
            sd_ = float(np.nanstd(P))
            cells.append({"hyp": hname, "desc": desc, "split": sp, **st, "p_two_sided": p_two(obs, P),
                          "p_one_sided_pos": p_one_pos(obs, P), "placebo_sd": sd_, "placebo_mean": float(np.nanmean(P)),
                          "z": obs / sd_, "n_shifts_valid": int(ok.sum()), "n_shifts_nan": int((~ok).sum())})
            pl_rows.append(pd.DataFrame({"hyp": hname, "split": sp, "shift_no": range(len(P)), "d_placebo": P}))
    cells = pd.DataFrame(cells)
    cells.to_csv(OUT / f"{PREFIX}cells.csv", index=False)
    pd.concat(pl_rows).to_csv(OUT / f"{PREFIX}placebo_draws.csv.gz", index=False)

    ver = []
    for hname in HYPOTHESES:
        s = cells[(cells.hyp == hname) & (cells.split == "selection")].iloc[0]
        c = cells[(cells.hyp == hname) & (cells.split == "confirmation")].iloc[0]
        c1, c2 = bool(s["diff"] > 0), bool(c["diff"] > 0)
        c3 = bool(c["p_two_sided"] <= P_ADOPT)
        ver.append({"hyp": hname, "desc": HYPOTHESES[hname][1], "sel_diff": s["diff"], "sel_p_two": s["p_two_sided"],
                    "sel_p_one": s["p_one_sided_pos"], "conf_diff": c["diff"], "conf_p_two": c["p_two_sided"],
                    "conf_p_one": c["p_one_sided_pos"], "c1_sel_diff_pos": c1, "c2_conf_diff_pos": c2,
                    "c3_conf_p_le_0.20": c3, "verdict": "채택(표시 규칙 후보)" if (c1 and c2 and c3) else "기각"})
    ver = pd.DataFrame(ver)
    ver.to_csv(OUT / f"{PREFIX}verdict.csv", index=False)
    note("[판정]\n" + ver.round(4).to_string(index=False))
    note("[칸]\n" + cells.drop(columns=["desc"]).round(4).to_string(index=False))

    # ---- 보조 1: 자산별 (구간 x 묶음) ▲/▼ 평균 초과수익·차이·n·구별 월수
    pa = []
    for aid in res.regime_daily:
        for sp in SPLIT_ORDER:
            for gname in ("low", "high"):
                d = obs_df[(obs_df["asset_id"] == aid) & (obs_df["split"] == sp) & (obs_df["group"] == gname)]
                st = diff_stats(d)
                up, dn = d[d["sign"] == 1], d[d["sign"] == -1]
                pa.append({"asset_id": aid, "split": sp, "group": gname, **st,
                           "months_up": int(up["date"].dt.to_period("M").nunique()),
                           "months_dn": int(dn["date"].dt.to_period("M").nunique()),
                           "warning": "표본 부족(독립 n<10)" if min(len(up), len(dn)) / PRIMARY_H < 10 else ""})
    pa = pd.DataFrame(pa)
    pa.to_csv(OUT / f"{PREFIX}per_asset.csv", index=False)
    agree = (pa.assign(pos=pa["diff"] > 0).dropna(subset=["diff"]).groupby(["split", "group"])
             .agg(n_assets=("diff", "size"), n_pos=("pos", "sum")).reset_index())
    agree.to_csv(OUT / f"{PREFIX}per_asset_sign_agreement.csv", index=False)
    note("[보조] 자산별 D>0 개수:\n" + agree.to_string(index=False))

    # ---- 보조 2: 민감도(판정 미사용) — 단측 p 는 cells 에 있음
    aux = []
    ex_h = {h: center(df, h, per_split=True) for h in AUX_H}
    for sp in SPLIT_ORDER:
        for gname in ("low", "high"):
            base = obs_df[(obs_df["split"] == sp) & (obs_df["group"] == gname)]
            variants = {"primary(구간별 평균)": base, "전기간 평균 차감": base.assign(ex=base["ex_fullsample"]),
                        "비부분판정만": base[~base["partial"].astype(bool)]}
            for h in AUX_H:
                variants[f"시평 {h}일"] = base.assign(ex=ex_h[h].reindex(base.index))
            for vn, d in variants.items():
                aux.append({"split": sp, "group": gname, "variant": vn, **diff_stats(d.dropna(subset=["ex"]))})
    aux = pd.DataFrame(aux)
    aux.to_csv(OUT / f"{PREFIX}aux_sensitivity.csv", index=False)
    note("[보조] 민감도 D:\n" + aux.round(4).to_string(index=False))

    # ---- 보조 3: 묶음 전체(추세 무관) 평균 초과수익
    gm = obs_df.groupby(["split", "group"])["ex"].agg(["mean", "size"]).reset_index()
    gm.to_csv(OUT / f"{PREFIX}group_mean_excess.csv", index=False)

    # ---- 점검: 추세 부호 양(+) 비율이 Phase 4 산출과 같은가(KR_CORP 만 결정 4 로 달라야 함)
    cov = pd.read_csv(ROOT / "outputs" / "phase4" / "phase4b_trend_coverage.csv").set_index("asset_id")
    chk = {}
    for aid, fr in th.items():
        v = fr["value"]
        chk[aid] = {"share_pos_now": round(float((v > 0).sum() / v.notna().sum()), 4),
                    "share_pos_phase4b": round(float(cov.at[aid, "share_pos"]), 4)}
    note(f"[점검] 추세 양(+) 비율 현재 vs phase4b_trend_coverage.csv(KR_CORP 만 결정 4 로 달라야 함): {chk}")
    changed = [a for a, c in chk.items() if c["share_pos_now"] != c["share_pos_phase4b"]]
    note(f"[점검] 값이 다른 자산: {changed}")

    info = {"seconds": round(time.time() - t0, 1), "git_head": _git("rev-parse", "HEAD"), "source_mode": SOURCE_MODE,
            "splits": SPLITS, "primary_horizon": PRIMARY_H, "placebo_shifts": N_PLACEBO, "placebo_seed_base": seed,
            "placebo_seed_rule": "seed + 2000 + 10*5 + split_index (ALL 순번 5; Phase 3/4 규칙)", "shifts": shift_info,
            "n_cells_tested": 4, "n_hypotheses": 2, "adoption_p_cut": P_ADOPT, "trend_basis": trend_basis,
            "n_partial_inside_groups": n_partial_inside, "n_abbreviated_label_rows": n_abbr,
            "trend_share_pos_changed_vs_phase4b": changed}
    (OUT / f"{PREFIX}run_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    note(f"총 {info['seconds']}초")
    (OUT / f"{PREFIX}run_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
