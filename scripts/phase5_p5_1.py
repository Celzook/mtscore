"""Phase 5 레인 p5_1 — §P5-1 블록 집계 방법 비교(base·R·D·M·G·P), docs/prereg_phase5.md 를 그대로 따른다(튜닝 없음).

    .venv/bin/python scripts/phase5_p5_1.py

입력: data/processed/panel.csv.gz(읽기만). 설정·src 는 바꾸지 않는다 — 모든 변형은 엔진이 만든 AssetScores(지표 점수 h.score,
커버리지 h.coverage, 가중치 h.weights, 하위블록 집계 h.sub_block_agg)를 후처리해 블록 점수를 다시 만든다(메모리 안).
산출: outputs/phase5/p5_1_*.csv · p5_1_run_info.json · p5_1_run_log.txt (보고서 p5_1_report.md 는 결과를 보고 따로 쓴다).

사전 등록(§0·§P5-1)에 없어 실행 전에 정한 빈칸 메우기 — 결과를 본 뒤 바꾸지 않는다:
 (a) 비교 표본: 판정(주)은 '짝지은 표본' — 변형이 값을 가진 날과 기준선이 값을 가진 날의 교집합에서 둘 다 계산한다
     (R 은 재백분위 최소 이력 252 관측 때문에 선택 구간 앞 1년이 빠지므로 방법과 표본이 섞이는 것을 막는다).
     각자 가용한 날 전체로 비교한 값(기준선 원표본)은 참고 열로 함께 낸다.
 (b) R 워밍업은 '유효 관측 252개'(달력 1년이 아니라 개수). 첫 252번째 관측부터 값이 나온다.
 (c) D 와 P 는 지표 단위다(하위블록 구조 무시, confluence 의 bb_pctb_20·rsi_14 도 각각 1개 지표). M 은 평균 하위블록만
     중앙값으로 바꾸고 min 하위블록(confluence)은 그대로 둔다. G 는 하위블록 가중치(기본 1)로 가중한 기하평균, 0점은 0.5 하한.
 (d) P: 자산군별·블록별로 선택 구간(2013-01-01~2019-12-31) 지표 점수 행을 자산군 안 자산에서 이어 붙이고, 지표별 표준화(평균 0·표준편차 1)
     후 쌍별 완전 관측(최소 252쌍)으로 상관행렬을 만든다(상관 정의 불가 쌍은 0). 제1주성분의 부호는 적재값 합이 양수가 되게 고정하고
     음수 적재는 0 으로 둔다. 선택 구간 관측 252개 미만인 지표는 가중치 0(추정 불가)으로 두고 목록을 낸다. 가중치는 한 번 추정해 고정.
 (e) 판정 시평 63일에만 플라시보를 건다(2,000회, 같은 이동 배열). 21·126·252일은 IC 만(보조).
 (g) 1차 실행(결과 확인 후) 사후 표기: P 는 (i) 지표 2개 블록에서 상관이 음수면 PC1 적재값이 ±0.707 동률이라 '합이 양수' 부호 규칙이 부동소수 오차로
     정해지고, (ii) 자산 전용 지표는 쌍 관측이 없어 적재 0 이 된다. 이 두 경우(IC·p 를 쓰지 않는 구조적 판별)는 판정을 '판정 불가(P 퇴화)'로 표기한다.
     IC 계산·시드·판정 규칙은 1차와 같고 해당 표기만 추가했다(1차 실행의 원 판정은 보고서 사후 수정 기록에 둔다).
 (f) 임계 50 보조분석: 두 구간 모두 한쪽 표본이 min_n_warning(10) 미만이면 개수에서 뺀다. 유의 = 차이 > 0 이고 양측 플라시보 p < 0.05
     (한쪽 p 는 참고 열).
"""
import hashlib
import json
import subprocess
import sys
import time
from bisect import bisect_left, bisect_right, insort
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from mtscore.core import backtest as bt  # noqa: E402
from mtscore.core.scoring import BLOCKS, _min_joint, _weighted_mean  # noqa: E402
from phase3_backtest import engine, raw_cfg  # noqa: E402  (Phase 3 와 같은 설정 사본 방식)

OUT = ROOT / "outputs" / "phase5"
PROC = ROOT / "data" / "processed"
PRIMARY_H = 63
AUX_H = (21, 126, 252)
PERIODS = {"selection": ("2013-01-01", "2019-12-31"), "confirmation": ("2020-01-01", None)}
VARIANTS = ("R", "D", "M", "G", "P")
SEED_OFFSET_VERDICT = 5000      # 시드 = backtest.placebo_seed + 5000 + 100·집단 순번 + 10·블록 순번 + 구간 순번 (4c 는 +4000)
SEED_OFFSET_THR = 6000          # 임계 50 보조: + 6000 + 100·자산 순번 + 10·블록 순번 + 구간 순번
R_MIN_OBS = 252
G_FLOOR = 0.5
HI, LO = 80.0, 20.0
PCA_MIN_PAIRS = 252
NEAR_IDENT = 0.01               # '거의 동일' 표기 기준(차이 나는 날 비율 < 1%) — 표기 전용, 판정 불변
BLOCK_KO = {"oversold": "과매도", "valuation": "밸류에이션", "fundamental": "펀더멘털"}


def window(idx, per):
    lo, hi = PERIODS[per]
    m = idx >= pd.Timestamp(lo)
    return m & (idx <= pd.Timestamp(hi)) if hi else m


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


# ---------------------------------------------------------------- 블록 점수 재구성(base·M·G·P·D)
def used_cov(h):
    c = h.coverage
    return c[c["used"].astype(bool)]


def build_blocks(h, mode, pw=None):
    """h(AssetScores)의 지표 점수로 블록 점수를 다시 만든다. mode: base | M | G | D | P.  pw[block][indicator] = P 가중치."""
    sc, cov = h.score, used_cov(h)
    out = {}
    for blk in BLOCKS:
        c = cov[cov.block == blk]
        if c.empty:
            out[blk] = pd.Series(np.nan, index=sc.index)
            continue
        names_all = list(c.indicator)
        if mode == "D":
            s = sc[names_all]
            n = s.notna().sum(axis=1)
            hi = (s >= HI).sum(axis=1)
            lo = (s <= LO).sum(axis=1)
            out[blk] = (50.0 + 50.0 * (hi - lo) / n.where(n > 0)).where(n > 0)
            continue
        if mode == "P":
            w = pd.Series({n: float(pw[blk].get(n, 0.0)) for n in names_all})
            v = _weighted_mean(sc[names_all], w)
            # 가중치가 있는 지표가 하나도 없는 날(가중치 0 지표만 남은 날)은 NaN — _weighted_mean 이 den=0 → NaN 으로 처리
            out[blk] = v
            continue
        subs, sw = {}, {}
        for sb in dict.fromkeys(c.sub_block):
            names = list(c[c.sub_block == sb].indicator)
            agg = h.sub_block_agg[(blk, sb)]
            if agg == "min":
                s = _min_joint(sc[names])
            elif mode == "M":
                s = sc[names].median(axis=1, skipna=True)
            else:
                s = _weighted_mean(sc[names], pd.Series({n: h.weights[n] for n in names}))
            subs[sb] = s
            sw[sb] = float(h.weights[(blk, sb)])
        frame = pd.DataFrame(subs, index=sc.index)
        if mode == "G":
            v = frame.to_numpy(dtype=float)
            w = np.array([sw[k] for k in frame.columns])
            m = ~np.isnan(v)
            lg = np.where(m, np.log(np.maximum(np.where(m, v, 1.0), G_FLOOR)), 0.0)
            num = (lg * w).sum(axis=1)
            den = (m * w).sum(axis=1)
            with np.errstate(invalid="ignore", divide="ignore"):
                g = np.where(den > 0, np.exp(num / den), np.nan)
            out[blk] = pd.Series(g, index=sc.index)
        else:
            out[blk] = _weighted_mean(frame, pd.Series(sw))
    return pd.DataFrame(out, index=sc.index)[list(BLOCKS)]


def expanding_midrank(x, min_obs=R_MIN_OBS):
    """자기 이력 대비 expanding 백분위(현재 포함, 동률 mid-rank). 유효 관측이 min_obs 개가 되는 날부터 값이 나온다(개수 기준)."""
    vals = x.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    hist = []
    for i, v in enumerate(vals):
        if np.isnan(v):
            continue
        insort(hist, v)
        if len(hist) < min_obs:
            continue
        lo, hi = bisect_left(hist, v), bisect_right(hist, v)
        out[i] = 100.0 * (lo + 0.5 * (hi - lo)) / len(hist)
    return pd.Series(out, index=x.index)


# ---------------------------------------------------------------- P: 주성분 가중치 추정(선택 구간만)
def estimate_pca_weights(hist, uni_class):
    """자산군·블록별 PC1 적재값 → 가중치(음수 0, 합 1). 반환: (pw[cls][blk][ind], 상세 DataFrame)."""
    pw, rows, degen = {}, [], {}
    for cls, members in uni_class.items():
        pw[cls] = {}
        for blk in BLOCKS:
            parts, names = [], []
            for a in members:
                h = hist[a]
                c = used_cov(h)
                nm = list(c[c.block == blk].indicator)
                if not nm:
                    continue
                s = h.score[nm]
                parts.append(s[window(s.index, "selection")])
                names += [n for n in nm if n not in names]
            if not parts:
                pw[cls][blk] = {}
                continue
            X = pd.concat(parts, axis=0)[names]
            nobs = X.notna().sum()
            keep = [n for n in names if nobs[n] >= PCA_MIN_PAIRS]
            drop = [n for n in names if n not in keep]
            w = {n: 0.0 for n in names}
            ev_share, k = np.nan, len(keep)
            if k == 1:
                w[keep[0]] = 1.0
                ev_share = 1.0
                loads = {keep[0]: 1.0}
            elif k >= 2:
                Z = (X[keep] - X[keep].mean()) / X[keep].std(ddof=0)
                C = Z.corr(min_periods=PCA_MIN_PAIRS).to_numpy()
                iso = [keep[i] for i in range(k) if np.isnan(np.delete(C[i], i)).all()]   # 다른 지표와 쌍 관측이 없는 지표(자산 전용)
                C = np.where(np.isnan(C), 0.0, C)
                np.fill_diagonal(C, 1.0)
                vals, vecs = np.linalg.eigh(C)
                v1 = vecs[:, -1]
                if v1.sum() < 0:
                    v1 = -v1
                ev_share = float(vals[-1] / vals.sum())
                reasons = []
                if abs(v1.sum()) < 1e-6:
                    reasons.append("PC1 동률(적재값 합 0 — 부호 규칙이 부동소수 오차로 정해짐)")
                if iso:
                    reasons.append("고립 지표(상관 정의 불가 → 적재 0): " + ",".join(iso))
                if reasons:
                    degen[(cls, blk)] = "; ".join(reasons)
                loads = dict(zip(keep, v1))
                pos = np.clip(v1, 0.0, None)
                if pos.sum() <= 0:
                    raise RuntimeError(f"P: 양의 적재값 없음 {cls}/{blk}")
                for n, p in zip(keep, pos / pos.sum()):
                    w[n] = float(p)
            else:
                loads = {}
            pw[cls][blk] = w
            for n in names:
                rows.append({"asset_class": cls, "block": blk, "indicator": n, "n_obs_selection": int(nobs[n]),
                             "loading_pc1": loads.get(n, np.nan), "weight": w[n],
                             "equal_weight_reference": 1.0 / len(names),
                             "pc1_explained_share": ev_share, "n_indicators_in_pca": k,
                             "note": "선택 구간 관측 252 미만 → 가중치 0" if n in drop else
                                     ("음수 적재 → 0" if loads.get(n, 0) < 0 else "")})
    out = pd.DataFrame(rows)
    out["degenerate"] = [degen.get((r.asset_class, r.block), "") for r in out.itertuples()]
    return pw, out, degen


# ---------------------------------------------------------------- 풀링 IC·플라시보
def series_key(d):
    h = hashlib.md5()
    for a in sorted(d):
        s = d[a]
        h.update(a.encode())
        h.update(np.nan_to_num(s.to_numpy(dtype=float), nan=-9999.0).tobytes())
    return h.hexdigest()


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    log = []

    def note(msg):
        print(msg, flush=True)
        log.append(msg)

    def sh(cmd):
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True).stdout.strip()

    prov = {"git_head": sh(["git", "rev-parse", "HEAD"]), "git_branch": sh(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
            "git_status_at_start": sh(["git", "status", "--short"]).splitlines(),
            "sha256_16": {str(p.relative_to(ROOT)): sha(p) for p in
                          [*sorted((ROOT / "config").glob("*.yaml")), *sorted((ROOT / "config" / "profiles").glob("*.yaml")),
                           ROOT / "src/mtscore/core/scoring.py", ROOT / "src/mtscore/api.py", ROOT / "src/mtscore/config.py",
                           ROOT / "src/mtscore/core/backtest.py", ROOT / "src/mtscore/core/transform.py"]}}
    panel = pd.read_csv(PROC / "panel.csv.gz", parse_dates=["date", "as_of"])
    uni, profs, sc = raw_cfg()
    bc = sc["backtest"]
    n_pl, seed0, min_n = int(bc["placebo_shifts"]), int(bc["placebo_seed"]), int(bc["min_n_warning"])
    rg_cfg = sc["regime"]
    note(f"패널 {len(panel):,}행, as_of 최대 {panel['as_of'].max().date()}, 플라시보 {n_pl}회, 시드 기준 {seed0}")
    # 기준선 확인: 결정 1 후보 3개(장기 반전 C1·FX 금리차 수준 C2·CAPE)가 설정에 없어야 한다
    txt = " ".join((ROOT / "config" / "profiles" / f"{c}.yaml").read_text(encoding="utf-8") for c in profs)
    for bad in ("long_reversal_60m", "rate_diff_level", "cape"):
        assert bad not in txt.lower(), f"기준선에 {bad} 가 들어 있음"

    eng = engine(uni, profs, sc)
    t = time.time()
    res = eng.backtest(panel, placebo=0)
    hist, fwd = res.history, res.forward
    ids = [it["asset_id"] for it in uni]
    cls_of = {it["asset_id"]: it["asset_class"] for it in uni}
    uni_class = {}
    for a in ids:
        uni_class.setdefault(cls_of[a], []).append(a)
    groups = {**uni_class, "ALL": ids}
    note(f"[base] 백테스트 {time.time() - t:.1f}초, 자산 {len(ids)}, 집단 {list(groups)}")

    # ---- 재구성 게이트: 같은 지표 점수로 만든 base 블록 == 엔진 블록(비트 단위)
    chk = []
    for a in ids:
        rb = build_blocks(hist[a], "base")
        eb = hist[a].blocks
        same = ((rb == eb) | (rb.isna() & eb.isna())).all()
        chk.append({"asset_id": a, **{f"identical_{b}": bool(same[b]) for b in BLOCKS},
                    **{f"maxabs_{b}": float((rb[b] - eb[b]).abs().max()) for b in BLOCKS}})
    chk = pd.DataFrame(chk)
    assert chk[[f"identical_{b}" for b in BLOCKS]].to_numpy().all(), "base 재구성이 엔진 블록과 다름"
    ref3 = pd.read_csv(PROC / "phase3_forward_returns.csv.gz", parse_dates=["date"])[["asset_id", "date", *BLOCKS]]
    rep = []
    for a in ids:
        x = hist[a].blocks.round(6)
        x.index.name = "date"
        m = x.reset_index().merge(ref3[ref3.asset_id == a], on="date", how="outer", suffixes=("", "_ref"), indicator=True)
        row = {"asset_id": a, "rows": len(x), "rows_phase3": int((ref3.asset_id == a).sum()),
               "only_new": int((m["_merge"] == "left_only").sum()), "only_ref": int((m["_merge"] == "right_only").sum())}
        for b in BLOCKS:
            p, q = m[b], m[b + "_ref"]
            row[f"mismatch_{b}"] = int((~((p == q) | (p.isna() & q.isna()))).sum())
        rep.append(row)
    rep = pd.DataFrame(rep)
    chk = chk.merge(rep, on="asset_id")
    chk.to_csv(OUT / "p5_1_repro_check.csv", index=False)
    note(f"[재구성] base 재구성 = 엔진 블록 (10자산×3블록 비트 동일). Phase 3 forward 파일 대비 불일치 합 "
         f"{int(rep[[f'mismatch_{b}' for b in BLOCKS]].sum().sum())}, 한쪽에만 있는 행 {int(rep.only_new.sum())}/{int(rep.only_ref.sum())}")

    # ---- 변형 블록 점수
    t = time.time()
    pw, pcaw, degen = estimate_pca_weights(hist, uni_class)
    pcaw.to_csv(OUT / "p5_1_pca_weights.csv", index=False)
    note(f"[P] PCA 가중치 추정 {time.time() - t:.1f}초 (선택 구간만), 가중치 0 지표 {int((pcaw.weight == 0).sum())}개")
    B = {"base": {a: hist[a].blocks for a in ids}}
    for v in ("D", "M", "G"):
        B[v] = {a: build_blocks(hist[a], v) for a in ids}
    B["P"] = {a: build_blocks(hist[a], "P", pw[cls_of[a]]) for a in ids}
    B["R"] = {a: B["base"][a].apply(expanding_midrank) for a in ids}
    note("[변형] R·D·M·G·P 블록 점수 완료")

    # 변형 vs base 동일성(자산×블록)
    ident = []
    for v in VARIANTS:
        for a in ids:
            for b in BLOCKS:
                x, y = B[v][a][b], B["base"][a][b]
                both = x.notna() & y.notna()
                diff = (x - y).abs()
                ident.append({"variant": v, "asset_id": a, "block": b, "n_base": int(y.notna().sum()), "n_variant": int(x.notna().sum()),
                              "same_availability": bool((x.notna() == y.notna()).all()),
                              "share_days_differ": float((diff[both] > 1e-9).mean()) if both.any() else np.nan,
                              "max_abs_diff": float(diff[both].max()) if both.any() else np.nan,
                              "first_base": y.first_valid_index(), "first_variant": x.first_valid_index()})
    ident = pd.DataFrame(ident)
    ident.to_csv(OUT / "p5_1_variant_vs_base.csv", index=False)

    # ---- 판정: 집단 × 블록 × 변형 (선택·확인 구간, 63일 + 보조 시평)
    cache = {}

    def arm_eval(gname, members, blk, per, shifts, ser):
        key = (gname, blk, per, series_key(ser))
        if key in cache:
            return cache[key]
        pp = [(ser[a], {PRIMARY_H: fwd[a][f"fwd_{PRIMARY_H}"]}) for a in members]
        obs, P = bt.pooled_placebo_ic(pp, shifts)
        p = float(bt.placebo_p(obs, P)[0])
        r = bt.pooled_ic([(ser[a], fwd[a][f"fwd_{PRIMARY_H}"]) for a in members], PRIMARY_H)
        assert abs(r["ic"] - obs[0]) < 1e-9, (key[:3], r["ic"], obs[0])
        row = {**r, "p_placebo": p, "placebo_sd": float(np.nanstd(P[:, 0])) if len(P) else np.nan, "n_shifts": len(shifts)}
        for hz in AUX_H:
            ra = bt.pooled_ic([(ser[a], fwd[a][f"fwd_{hz}"]) for a in members], hz)
            row[f"ic_{hz}"] = ra["ic"]
        cache[key] = row
        return row

    split_rows, verdict_rows = [], []
    for gi, (gname, members) in enumerate(groups.items()):
        t = time.time()
        for bi, blk in enumerate(BLOCKS):
            for pi, per in enumerate(PERIODS):
                base_sel = {a: B["base"][a][blk].where(window(B["base"][a].index, per)) for a in members}
                nmin = min(int(base_sel[a].notna().sum()) for a in members)
                shifts = bt.shift_draws(nmin, n_pl, seed0 + SEED_OFFSET_VERDICT + 100 * gi + 10 * bi + pi)
                base_as_is = arm_eval(gname, members, blk, per, shifts, base_sel)
                split_rows.append({"group": gname, "block": blk, "variant": "base", "arm": "base(원표본)", "period": per,
                                   "assets": ",".join(members), **base_as_is})
                for v in VARIANTS:
                    var_sel = {a: B[v][a][blk].where(window(B[v][a].index, per)) for a in members}
                    bm = {a: base_sel[a].where(var_sel[a].notna()) for a in members}
                    vm = {a: var_sel[a].where(base_sel[a].notna()) for a in members}
                    r_b = arm_eval(gname, members, blk, per, shifts, bm)
                    r_v = arm_eval(gname, members, blk, per, shifts, vm)
                    r_vo = arm_eval(gname, members, blk, per, shifts, var_sel)
                    split_rows.append({"group": gname, "block": blk, "variant": v, "arm": "base(짝지은 표본)", "period": per,
                                       "assets": ",".join(members), **r_b})
                    split_rows.append({"group": gname, "block": blk, "variant": v, "arm": f"{v}(짝지은 표본)", "period": per,
                                       "assets": ",".join(members), **r_v})
                    split_rows.append({"group": gname, "block": blk, "variant": v, "arm": f"{v}(원표본)", "period": per,
                                       "assets": ",".join(members), **r_vo})
        note(f"[IC] 집단 {gname} 완료 {time.time() - t:.1f}초")
    split = pd.DataFrame(split_rows)
    split.to_csv(OUT / "p5_1_split_ic.csv", index=False)

    def pick(g, blk, v, arm, per):
        r = split[(split.group == g) & (split.block == blk) & (split.variant == v) & (split.arm == arm) & (split.period == per)]
        assert len(r) >= 1, (g, blk, v, arm, per)
        return r.iloc[0]

    for gname, members in groups.items():
        for blk in BLOCKS:
            for v in VARIANTS:
                idt = ident[(ident.variant == v) & (ident.block == blk) & ident.asset_id.isin(members)]
                identical = bool((idt.share_days_differ.fillna(0) == 0).all() and idt.same_availability.all())
                near = bool(idt.share_days_differ.fillna(0).max() < NEAR_IDENT and idt.same_availability.all())
                bs, bc_ = pick(gname, blk, v, "base(짝지은 표본)", "selection"), pick(gname, blk, v, "base(짝지은 표본)", "confirmation")
                vs, vc = pick(gname, blk, v, f"{v}(짝지은 표본)", "selection"), pick(gname, blk, v, f"{v}(짝지은 표본)", "confirmation")
                c1, c2, c3 = bool(vs.ic > bs.ic), bool(vc.ic >= bc_.ic), bool(vc.p_placebo <= bc_.p_placebo)
                adopt = c1 and c2 and c3
                # 참고: 원표본(각자 가용한 날 전체) 비교
                bso, bco = pick(gname, blk, "base", "base(원표본)", "selection"), pick(gname, blk, "base", "base(원표본)", "confirmation")
                vso, vco = pick(gname, blk, v, f"{v}(원표본)", "selection"), pick(gname, blk, v, f"{v}(원표본)", "confirmation")
                u1, u2, u3 = bool(vso.ic > bso.ic), bool(vco.ic >= bco.ic), bool(vco.p_placebo <= bco.p_placebo)
                adopt_u = u1 and u2 and u3
                neg = bool(bc_.ic < 0 or vc.ic < 0)
                dg = [f"{cls_of[a]}: {degen[(cls_of[a], blk)]}" for a in dict.fromkeys(members) if v == "P" and (cls_of[a], blk) in degen]
                dg = "; ".join(dict.fromkeys(dg))
                if dg and gname != "ALL":
                    label = "판정 불가(P 퇴화)"
                else:
                    label = "동일(기준선과 같음)" if identical else ("채택" if adopt else "기각")
                verdict_rows.append({
                    "group": gname, "block": blk, "variant": v, "assets": ",".join(members),
                    "identical_to_base": identical, "near_identical(<1%일 차이)": near,
                    "ic_sel_base": bs.ic, "ic_sel_variant": vs.ic, "ic_conf_base": bc_.ic, "ic_conf_variant": vc.ic,
                    "p_conf_base": bc_.p_placebo, "p_conf_variant": vc.p_placebo,
                    "p_sel_base": bs.p_placebo, "p_sel_variant": vs.p_placebo,
                    "t_conf_base": bc_.t_nw, "t_conf_variant": vc.t_nw,
                    "n_dates_sel": vs.n_dates, "n_dates_conf": vc.n_dates,
                    "cond1_sel_improves": c1, "cond2_conf_not_worse": c2, "cond3_p_not_worse": c3,
                    "negative_ic_cell(조건3 문자 그대로)": neg,
                    "verdict_mechanical": "채택" if adopt else "기각", "p_degenerate": dg, "verdict": label,
                    "ref_unmatched_verdict": "채택" if adopt_u else "기각",
                    "ref_unmatched_ic_sel": f"{bso.ic:.4f}->{vso.ic:.4f}", "ref_unmatched_ic_conf": f"{bco.ic:.4f}->{vco.ic:.4f}",
                    "ref_unmatched_p_conf": f"{bco.p_placebo:.4f}->{vco.p_placebo:.4f}",
                    "matched_vs_unmatched_differ": bool(adopt != adopt_u),
                    "aux_ic21_sel": f"{bs.ic_21:.4f}->{vs.ic_21:.4f}", "aux_ic21_conf": f"{bc_.ic_21:.4f}->{vc.ic_21:.4f}",
                    "aux_ic126_sel": f"{bs.ic_126:.4f}->{vs.ic_126:.4f}", "aux_ic126_conf": f"{bc_.ic_126:.4f}->{vc.ic_126:.4f}",
                    "aux_ic252_sel": f"{bs.ic_252:.4f}->{vs.ic_252:.4f}", "aux_ic252_conf": f"{bc_.ic_252:.4f}->{vc.ic_252:.4f}"})
    vd = pd.DataFrame(verdict_rows)
    vd.to_csv(OUT / "p5_1_verdict.csv", index=False)
    cnt = vd.verdict.value_counts().to_dict()
    note(f"[판정] 칸 {len(vd)}개: {cnt}; 원표본과 판정이 다른 칸 {int(vd['matched_vs_unmatched_differ'].sum())}개")
    for r in vd[vd.verdict == "채택"].to_dict("records"):
        note(f"  채택: {r['group']}/{r['block']}/{r['variant']} 선택 {r['ic_sel_base']:.4f}->{r['ic_sel_variant']:.4f}, "
             f"확인 {r['ic_conf_base']:.4f}->{r['ic_conf_variant']:.4f}, p {r['p_conf_base']:.4f}->{r['p_conf_variant']:.4f}")

    # ---- R 보조: 임계 50 — 블록 ≥50 대 <50 의 63일 이후 수익 차이(자산×블록×구간)
    thr = float(rg_cfg["threshold"])
    rows = []
    for ai, a in enumerate(ids):
        f63 = fwd[a][f"fwd_{PRIMARY_H}"]
        for bi, blk in enumerate(BLOCKS):
            for pi, per in enumerate(PERIODS):
                wnd = window(B["base"][a].index, per)
                sR = B["R"][a][blk].where(wnd)
                sB = B["base"][a][blk].where(wnd)
                arms = {"base(원표본)": sB, "base(R 표본)": sB.where(sR.notna()), "R": sR}
                shifts = bt.shift_draws(int(sB.notna().sum()), n_pl, seed0 + SEED_OFFSET_THR + 100 * ai + 10 * bi + pi)
                for arm, s in arms.items():
                    sv = s.dropna()
                    f = f63.reindex(sv.index).to_numpy(dtype=float)
                    ok = ~np.isnan(f)
                    hi_ = (sv.to_numpy() >= thr)
                    n_hi, n_lo = int((hi_ & ok).sum()), int((~hi_ & ok).sum())

                    def stat(hmask):
                        a1, a0 = hmask & ok, ~hmask & ok
                        if a1.sum() == 0 or a0.sum() == 0:
                            return np.nan
                        return f[a1].mean() - f[a0].mean()

                    d = stat(hi_)
                    P = np.array([stat(np.roll(hi_, int(k))) for k in shifts])
                    if np.isnan(d) or len(P) == 0:
                        p2 = p1 = np.nan
                    else:
                        p2 = float((np.nansum(np.abs(P) >= abs(d)) + 1) / (len(P) + 1))
                        p1 = float((np.nansum(P >= d) + 1) / (len(P) + 1))
                    rows.append({"asset_id": a, "block": blk, "period": per, "arm": arm, "threshold": thr,
                                 "n_high": n_hi, "n_low": n_lo, "share_high": n_hi / max(n_hi + n_lo, 1),
                                 "mean_fwd63_high": f[hi_ & ok].mean() if n_hi else np.nan,
                                 "mean_fwd63_low": f[~hi_ & ok].mean() if n_lo else np.nan,
                                 "diff": d, "p_placebo_2sided": p2, "p_placebo_1sided_pos": p1, "n_shifts": len(shifts),
                                 "sufficient": bool(min(n_hi, n_lo) >= min_n)})
    th = pd.DataFrame(rows)
    th.to_csv(OUT / "p5_1_threshold50.csv", index=False)
    summ = []
    for (arm, per), g in th[th.sufficient].groupby(["arm", "period"]):
        summ.append({"arm": arm, "period": per, "n_cells": len(g), "n_diff_pos": int((g["diff"] > 0).sum()),
                     "n_sig_pos(p2<0.05)": int(((g["diff"] > 0) & (g.p_placebo_2sided < 0.05)).sum()),
                     "n_sig_pos_1sided(p1<0.05)": int(((g["diff"] > 0) & (g.p_placebo_1sided_pos < 0.05)).sum()),
                     "n_sig_neg(p2<0.05)": int(((g["diff"] < 0) & (g.p_placebo_2sided < 0.05)).sum()),
                     "mean_diff": g["diff"].mean(), "median_diff": g["diff"].median(),
                     "n_cells_excluded_insufficient": int((th[(th.arm == arm) & (th.period == per)].sufficient == False).sum())})  # noqa: E712
    summ = pd.DataFrame(summ)
    summ.to_csv(OUT / "p5_1_threshold50_summary.csv", index=False)
    byblk = []
    for (arm, per, blk), g in th[th.sufficient].groupby(["arm", "period", "block"]):
        byblk.append({"arm": arm, "period": per, "block": blk, "n_cells": len(g), "n_diff_pos": int((g["diff"] > 0).sum()),
                      "n_sig_pos(p2<0.05)": int(((g["diff"] > 0) & (g.p_placebo_2sided < 0.05)).sum())})
    pd.DataFrame(byblk).to_csv(OUT / "p5_1_threshold50_by_block.csv", index=False)
    note("[임계50] " + "; ".join(f"{r['arm']}/{r['period'][:3]}: 양 {r['n_diff_pos']}/{r['n_cells']}, 유의양 {r['n_sig_pos(p2<0.05)']}"
                                for r in summ.to_dict("records")))

    # ---- 블록 중앙값이 50에서 얼마나 움직이는가(base vs R, R 표본 기준 짝지음 + 원표본)
    med = []
    for a in ids:
        for blk in BLOCKS:
            sR = B["R"][a][blk]
            sB = B["base"][a][blk]
            for lab, mk in (("full", pd.Series(True, index=sB.index)), ("selection", window(sB.index, "selection")),
                            ("confirmation", window(sB.index, "confirmation"))):
                for samp, mask_ in (("R표본", sR.notna()), ("각자가용", None)):
                    xb = sB[mk & (mask_ if mask_ is not None else sB.notna())].dropna()
                    xr = sR[mk & (mask_ if mask_ is not None else sR.notna())].dropna()
                    if len(xb) == 0 or len(xr) == 0:
                        continue
                    med.append({"asset_id": a, "block": blk, "period": lab, "sample": samp, "n_base": len(xb), "n_R": len(xr),
                                "median_base": xb.median(), "median_R": xr.median(),
                                "absdev50_base": abs(xb.median() - 50), "absdev50_R": abs(xr.median() - 50),
                                "mean_base": xb.mean(), "mean_R": xr.mean(),
                                "share_ge50_base": (xb >= 50).mean(), "share_ge50_R": (xr >= 50).mean(),
                                "share_ge75_base": (xb >= 75).mean(), "share_ge75_R": (xr >= 75).mean(),
                                "share_le25_base": (xb <= 25).mean(), "share_le25_R": (xr <= 25).mean(),
                                "sd_base": xb.std(), "sd_R": xr.std()})
    med = pd.DataFrame(med)
    med.to_csv(OUT / "p5_1_block_medians.csv", index=False)
    mm = med[(med.period == "full") & (med["sample"] == "R표본")]
    note(f"[중앙값] 50에서 떨어진 정도(R 표본·전체): base 평균 {mm.absdev50_base.mean():.2f}, 최대 {mm.absdev50_base.max():.2f}; "
         f"R 평균 {mm.absdev50_R.mean():.2f}, 최대 {mm.absdev50_R.max():.2f}")

    # ---- 확산 표시(최신 기준일) — 지표 단위 개수 + D·base·R 블록 점수
    sr = eng.score(panel)
    ct = sr.contributions
    rows = []
    for a in ids:
        t_ = sr.dates[a]
        for blk in BLOCKS:
            c = ct[(ct.asset_id == a) & (ct.block == blk)]
            s = c["score"].astype(float)
            stale = bool(sr.stale[a])
            n_av = 0 if stale else int(s.notna().sum())
            rows.append({"asset_id": a, "date": t_.date(), "block": blk,
                         "n_ge80": 0 if stale else int((s >= HI).sum()), "n_le20": 0 if stale else int((s <= LO).sum()),
                         "n_available": n_av, "n_indicators_in_block(used)": int(len(c)),
                         "display": f"≥80 {int((s >= HI).sum())} / ≤20 {int((s <= LO).sum())} / 가용 {n_av}",
                         "block_score_base": sr.blocks.at[a, blk], "block_score_D": B["D"][a].at[t_, blk],
                         "block_score_R": B["R"][a].at[t_, blk], "block_score_M": B["M"][a].at[t_, blk],
                         "block_score_G": B["G"][a].at[t_, blk], "block_score_P": B["P"][a].at[t_, blk]})
    disp = pd.DataFrame(rows)
    assert np.allclose(disp.block_score_base.astype(float), [B["base"][r.asset_id].at[pd.Timestamp(r.date), r.block] for r in disp.itertuples()],
                       equal_nan=True)
    disp.to_csv(OUT / "p5_1_diffusion_display_latest.csv", index=False)
    note(f"[확산표시] 최신 기준일 표 {len(disp)}행 (자산 달력일 {sorted({str(pd.Timestamp(d).date()) for d in sr.dates.values})})")

    # ---- 채택했을 때 바뀌는 것: 국면 라벨이 base 와 달라지는 날의 비율, 최신일 라벨
    chg, lat = [], []
    lab_base = {a: bt.regime_labels(B["base"][a], rg_cfg) for a in ids}
    for v in VARIANTS:
        for a in ids:
            lv = bt.regime_labels(B[v][a], rg_cfg)
            lb = lab_base[a]
            both = lv["label"].notna() & lb["label"].notna()
            chg.append({"variant": v, "asset_id": a, "n_compared_days": int(both.sum()),
                        "share_label_differs": float((lv["label"][both] != lb["label"][both]).mean()) if both.any() else np.nan})
            t_ = sr.dates[a]
            lat.append({"variant": v, "asset_id": a, "date": t_.date(), "label_base": lb["label"].get(t_),
                        "label_variant": lv["label"].get(t_), "blocks_variant": ",".join(f"{B[v][a].at[t_, b]:.1f}" for b in BLOCKS),
                        "blocks_base": ",".join(f"{B['base'][a].at[t_, b]:.1f}" for b in BLOCKS)})
        note(f"[국면] 변형 {v} 국면 라벨 비교 완료")
    pd.DataFrame(chg).to_csv(OUT / "p5_1_regime_label_change.csv", index=False)
    pd.DataFrame(lat).to_csv(OUT / "p5_1_regime_latest.csv", index=False)

    prov["git_status_at_end"] = sh(["git", "status", "--short"]).splitlines()
    info = {"seconds": round(time.time() - t0, 1), "cells_tested": int(len(vd)), "groups": groups, "variants": VARIANTS,
            "periods": PERIODS, "primary_horizon": PRIMARY_H, "placebo_shifts": n_pl,
            "seed_rule": f"{seed0} + {SEED_OFFSET_VERDICT} + 100*group_idx + 10*block_idx + period_idx (임계50: +{SEED_OFFSET_THR} + 100*asset_idx + ...)",
            "r_min_obs": R_MIN_OBS, "g_floor": G_FLOOR, "pca_min_pairs": PCA_MIN_PAIRS, "verdict_counts": cnt,
            "provenance": prov}
    (OUT / "p5_1_run_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    note(f"총 {info['seconds']}초")
    (OUT / "p5_1_run_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
