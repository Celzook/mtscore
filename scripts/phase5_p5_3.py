"""Phase 5 P5-3 — 크레딧(US_HY·US_IG) 추세 표시를 국채 대비로 통일(표시만, 점수 불변). 사전 등록 docs/prereg_phase5.md §P5-3.

    .venv/bin/python scripts/phase5_p5_3.py

정의: r_t = −D_(t−1)×Δspread_t/100 + spread_(t−1)/100/252 (KR_CORP duration_approx 와 같은 식, D 만 시변).
  spread = 현행 패널 필드(평균만기 매칭 G-스프레드), D = lseg 원자료 iBoxx MOD_DURTN(as_of = date, phase2_build 와 같은 규칙).
  MOD_DURTN 은 패널(data/processed/panel.csv.gz)에 아직 없다 → 이 스크립트가 원자료에서 `mod_durtn` 행을 만들어 메모리 패널에
  붙인다(패널 파일·phase2_build.py 는 건드리지 않음). 켜는 설정은 메모리 사본(dataclasses.replace)이고, universe.yaml 에 쓸 줄은
  임시 폴더 사본에 적용해 load_config 로 같은 설정이 나오는지 확인한다.
산출(outputs/phase5/): p5_3_*.csv|json|txt, p5_3_run_log.txt. 판정 셀은 없다(점검 3건).
"""
import dataclasses
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from mtscore import ScoringEngine, load_config  # noqa: E402
from mtscore.core import backtest as bt  # noqa: E402

OUT = ROOT / "outputs" / "phase5"
CFG = ROOT / "config"
AS_OF = "2026-10-27"            # Phase 2 score_history 산출 기준일(phase2_score.py)
END = "2026-10-27"              # phase2_build.py END
ASSETS = {"US_HY": "IBLUS0004", "US_IG": "IBLUS0005"}
TREND_RETURN = {"yield_field": "spread", "duration_field": "mod_durtn"}
BASIS = "국채 대비"
# universe.yaml 에 적을 줄(활성화 패치). 사전 등록 P5-3: 12개월 초과수익 부호, 현금 미차감, basis 국채 대비
YAML_TREND = ("  trend: {cash: none, basis: 국채 대비, return: {yield_field: spread, duration_field: mod_durtn}}   # P5-3: 추세는 스프레드 −D×Δs + s 캐리"
              "(국채 대비 초과수익 근사, D = iBoxx MOD_DURTN). 점수·국면·백테스트 수익률 불변")   # p5_3_adopt.patch 와 같은 줄
LOG = []


def note(msg):
    print(msg, flush=True)
    LOG.append(msg)


def load_iboxx(ric):
    ib = pd.concat([pd.read_csv(p) for p in sorted((ROOT / "data" / "raw" / "lseg" / "iboxx").glob(f"{ric}__*.csv"))])
    ib["Date"] = pd.to_datetime(ib["Date"]).dt.normalize()
    ib = ib.drop_duplicates("Date", keep="last").set_index("Date").sort_index()
    return ib[ib.index <= pd.Timestamp(END)]


def mod_durtn_rows(raw):
    rows = []
    for aid, ib in raw.items():
        d = ib["MOD_DURTN"].dropna()
        rows.append(pd.DataFrame({"date": d.index, "asset_id": aid, "field": "mod_durtn", "value": d.values,
                                  "as_of": d.index,   # as_of = date: phase2_build.py 의 iBoxx 필드와 같은 규칙(그 날 종가 후 확정)
                                  "source": f"lseg:.{ASSETS[aid]} MOD_DURTN (iBoxx 수정듀레이션, 년)"}))
    return pd.concat(rows, ignore_index=True)


def score_hist_frame(res):
    rows = []
    for aid, h in res.history.items():
        b = h.blocks.copy()
        b.index.name = "date"
        rows.append(b.reset_index().assign(asset_id=aid))
    hist = pd.concat(rows, ignore_index=True)[["asset_id", "date", "oversold", "valuation", "fundamental"]]
    return hist.dropna(subset=["oversold", "valuation", "fundamental"], how="all").round(4).reset_index(drop=True)


def strip_json(j, drop):
    j = json.loads(json.dumps(j, default=str))
    for a in j["assets"]:
        for k in drop:
            a.pop(k, None)
    j.pop("schema_version", None)
    return j


def share_pos(v):
    v = v.dropna()
    return float((v > 0).sum() / len(v))


def sign_change_rate(v):
    s = np.sign(v.dropna())
    return float((s != s.shift(1)).iloc[1:].sum() / (len(s) - 1))


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    panel = pd.read_csv(ROOT / "data" / "processed" / "panel.csv.gz", parse_dates=["date", "as_of"])
    raw = {aid: load_iboxx(ric) for aid, ric in ASSETS.items()}
    ext = mod_durtn_rows(raw)
    ext.to_csv(OUT / "p5_3_panel_mod_durtn.csv.gz", index=False)
    panel_aug = pd.concat([panel, ext], ignore_index=True)
    note(f"패널 {len(panel):,}행 + mod_durtn {len(ext):,}행(원자료 MOD_DURTN, as_of=date), 플라시보 없음(판정 셀 0)")
    dur_stats = {}
    for aid, ib in raw.items():
        d = ib["MOD_DURTN"].dropna()
        sp = panel[(panel.asset_id == aid) & (panel.field == "spread")].set_index("date")["value"]
        dur_stats[aid] = {"n": int(len(d)), "first": str(d.index.min().date()), "last": str(d.index.max().date()),
                          "mean": round(float(d.mean()), 3), "median": round(float(d.median()), 3),
                          "min": round(float(d.min()), 3), "max": round(float(d.max()), 3),
                          "spread_dates": int(len(sp)), "spread_dates_without_mod_durtn": int((~sp.index.isin(d.index)).sum())}
        note(f"[D] {aid} MOD_DURTN {dur_stats[aid]}")

    # ---- 설정: 메모리 사본 + universe.yaml 활성화 줄의 로딩 동치 확인
    cfg0 = load_config(CFG)
    assert all(a.trend_return is None for a in cfg0.universe), "universe.yaml 에 trend.return 이 이미 있음"
    cfg1 = dataclasses.replace(cfg0, universe=[
        dataclasses.replace(a, trend_cash="none", trend_basis=BASIS, trend_return=dict(TREND_RETURN))
        if a.asset_id in ASSETS else a for a in cfg0.universe])
    with tempfile.TemporaryDirectory() as td:
        shutil.copytree(CFG, Path(td) / "config")
        up = Path(td) / "config" / "universe.yaml"
        txt = up.read_text(encoding="utf-8")
        for aid in ASSETS:   # `- asset_id: US_HY` 블록의 `overrides: {}` 줄 앞에 trend 줄을 넣는다(KR_CORP 와 같은 위치)
            head = f"- asset_id: {aid}\n"
            i = txt.index(head)
            j = txt.index("  overrides: {}", i)
            txt = txt[:j] + YAML_TREND + "\n" + txt[j:]
        up.write_text(txt, encoding="utf-8")
        cfg_yaml = load_config(Path(td) / "config")
    assert [dataclasses.asdict(a) for a in cfg_yaml.universe] == [dataclasses.asdict(a) for a in cfg1.universe]
    note("[설정] universe.yaml 활성화 줄(임시 사본에 적용)을 load_config 로 읽으면 메모리 사본과 AssetSpec 이 정확히 같다")

    # ---- 1) 점수 불변 증명 (phase4e 와 같은 절차)
    p2 = pd.read_csv(ROOT / "outputs" / "phase2" / "score_history.csv.gz", parse_dates=["date"])
    j_old = json.loads((ROOT / "outputs" / "phase2" / f"result_{AS_OF}.json").read_text(encoding="utf-8"))
    eng0, eng1 = ScoringEngine(cfg0), ScoringEngine(cfg1)
    res_base = eng0.score(panel, as_of=AS_OF)                      # 기준선: 현행 설정 + 현행 패널
    res_new = eng1.score(panel_aug, as_of=AS_OF)                   # 변형: 국채 대비 + mod_durtn 붙은 패널
    inv = {}
    for name, res in (("baseline(cfg0,panel)", res_base), ("variant(cfg1,panel+mod_durtn)", res_new)):
        h = score_hist_frame(res)
        pd.testing.assert_frame_equal(h, p2, check_exact=True, check_dtype=False)   # 다르면 여기서 중단
        jn = strip_json(res.to_dict(), ("trend", "staged_entry"))
        jo = strip_json(j_old, ("trend", "staged_entry"))
        assert jn == jo, f"{name}: result JSON(trend·staged_entry·schema_version 제외)이 Phase 2 와 다름"
        inv[name] = {"score_history_rows": int(len(h)), "score_history_equal_phase2_exact": True,
                     "result_json_equal_phase2_except_trend_staged_entry_schema": True}
        note(f"[1] {name}: score_history {len(h):,}행 outputs/phase2/score_history.csv.gz 와 정확히 동일, result JSON 동일")
    # staged_entry 도 같아야 한다(국면·과매도 의존)
    se0 = res_base.to_dict(); se1 = res_new.to_dict()
    assert [a["staged_entry"] for a in se0["assets"]] == [a["staged_entry"] for a in se1["assets"]]
    assert [a["regime"] for a in se0["assets"]] == [a["regime"] for a in se1["assets"]]
    note("[1b] staged_entry·regime JSON 도 기준선과 동일")

    # ---- 2) 추세: 나머지 자산 불변, 켜지 않은 패널에서의 동작
    tr0 = eng0.trend_history(panel)
    tr1 = eng1.trend_history(panel_aug)
    cov = pd.read_csv(ROOT / "outputs" / "phase4" / "phase4b_trend_coverage.csv").set_index("asset_id")
    for aid in tr0:
        if aid in ASSETS:
            continue
        pd.testing.assert_frame_equal(tr0[aid], tr1[aid], check_exact=True)
        if aid == "KR_CORP":   # phase4b_trend_coverage.csv 는 결정 4(현금 차감 면제) 이전 값이다 — 면제 후 값은 phase4e 가 따로 대조
            continue
        assert abs(share_pos(tr1[aid]["value"]) - cov.at[aid, "share_pos"]) < 1e-12
        assert int(tr1[aid]["value"].notna().sum()) == cov.at[aid, "n_days"]
    note("[2a] US_HY·US_IG 외 8개 자산의 trend_history 가 기준선과 정확히 동일(KR_CORP 포함), 7개(KR_CORP 제외)는 share_pos·n_days 가 phase4b_trend_coverage.csv 와 일치")
    for aid in ASSETS:   # 기준선 재현
        assert abs(share_pos(tr0[aid]["value"]) - cov.at[aid, "share_pos"]) < 1e-12
    unready = eng1.trend_history(panel, list(ASSETS))   # mod_durtn 이 패널에 없을 때
    unready_info = {aid: {"non_na_days": int(f["value"].notna().sum()), "reason_last": f["reason"].iloc[-1]}
                    for aid, f in unready.items()}
    note(f"[2b] 패널에 mod_durtn 이 없을 때(활성화만 하고 패널을 안 고친 경우): {unready_info}")
    jt = {a["asset_id"]: a["trend"] for a in se1["assets"] if a["asset_id"] in ASSETS}
    jt0 = {a["asset_id"]: a["trend"] for a in se0["assets"] if a["asset_id"] in ASSETS}
    note(f"[2c] 최신({AS_OF}) result JSON trend: 기준선 {jt0} → 변형 {jt}")

    # ---- 3) 점검
    months = int(cfg0.scoring["trend"]["months"])
    daily_rows, chk, tr_rows = [], {}, {}
    y22 = []
    for aid in ASSETS:
        ib = raw[aid]
        sp = panel[(panel.asset_id == aid) & (panel.field == "spread")].set_index("date")["value"]
        lvl = panel[(panel.asset_id == aid) & (panel.field == "index_level")].set_index("date")["value"]
        d = ib["MOD_DURTN"]
        ytm = ib["YLDTOMAT"]
        common = sp.index.intersection(lvl.dropna().index).intersection(d.dropna().index).intersection(ytm.dropna().index)
        c = pd.DataFrame({"s": sp.reindex(common), "tr": lvl.reindex(common), "D": d.reindex(common),
                          "ytm": ytm.reindex(common)}).sort_index()
        c["y_ust"] = c["ytm"] - c["s"]   # 항등식: 패널 spread = YLDTOMAT − (평균만기 매칭 UST 수익률)
        Dp = c["D"].shift(1)
        r_tr = c["tr"].pct_change()
        r_ust = -Dp * c["y_ust"].diff() / 100 + c["y_ust"].shift(1) / 100 / 252   # 가정: 지수 MOD_DURTN 과 같은 듀레이션의 국채(수익률은 평균만기 매칭)
        r_spread = -Dp * c["s"].diff() / 100 + c["s"].shift(1) / 100 / 252
        r_tr_exc = r_tr - r_ust
        dd = pd.DataFrame({"tr_exc": r_tr_exc, "spread_exc": r_spread}).dropna()
        per = dd.index.to_period("M")
        mon = (1 + dd).groupby(per).prod() - 1
        n_days = dd.groupby(per).size()
        mon = mon[n_days >= 10]   # 일 수가 너무 적은 월(처음/끝 부분월) 제외
        pear, spear = float(mon["tr_exc"].corr(mon["spread_exc"])), float(mon["tr_exc"].corr(mon["spread_exc"], method="spearman"))
        slope = float(np.polyfit(mon["spread_exc"], mon["tr_exc"], 1)[0])
        chk[aid] = {"n_months": int(len(mon)), "first_month": str(mon.index.min()), "last_month": str(mon.index.max()),
                    "pearson": round(pear, 4), "spearman": round(spear, 4), "ols_slope_tr_on_spread": round(slope, 4),
                    "mean_monthly_tr_exc": round(float(mon["tr_exc"].mean()), 5),
                    "mean_monthly_spread_exc": round(float(mon["spread_exc"].mean()), 5),
                    "sd_monthly_tr_exc": round(float(mon["tr_exc"].std()), 5),
                    "sd_monthly_spread_exc": round(float(mon["spread_exc"].std()), 5)}
        mon.assign(n_days=n_days.reindex(mon.index)).to_csv(OUT / f"p5_3_monthly_{aid}.csv", float_format="%.6f")
        # 12개월 값 비교: TR 기반 초과수익 지수에 같은 lag_months 규칙
        cal = tr1[aid].index
        first = r_tr_exc.dropna().index.min()
        tr_idx = bt.return_index(r_tr_exc.reindex(cal).fillna(0.0)).where(pd.Series(cal >= first, index=cal))
        v_tr = tr_idx / bt.lag_months(tr_idx, months) - 1.0
        v_old, v_new = tr0[aid]["value"], tr1[aid]["value"]
        both = pd.DataFrame({"old_cash_sub": v_old, "new_vs_ust": v_new, "tr_minus_ust_approx": v_tr}).dropna()
        both["sign_old"] = np.sign(both["old_cash_sub"]).astype(int)
        both["sign_new"] = np.sign(both["new_vs_ust"]).astype(int)
        both["sign_ref"] = np.sign(both["tr_minus_ust_approx"]).astype(int)
        both.insert(0, "asset_id", aid)
        daily_rows.append(both)
        flip = int((both["sign_old"] != both["sign_new"]).sum())
        chk[aid].update({
            "trend_days_both_defined": int(len(both)), "first_both": str(both.index.min().date()),
            "sign_flip_days_old_vs_new": flip, "sign_flip_share_old_vs_new": round(flip / len(both), 4),
            "share_pos_old": round(share_pos(both["old_cash_sub"]), 4), "share_pos_new": round(share_pos(both["new_vs_ust"]), 4),
            "share_pos_ref_tr_minus_ust": round(share_pos(both["tr_minus_ust_approx"]), 4),
            "sign_change_rate_old": round(sign_change_rate(both["old_cash_sub"]), 5),
            "sign_change_rate_new": round(sign_change_rate(both["new_vs_ust"]), 5),
            "sign_change_rate_ref": round(sign_change_rate(both["tr_minus_ust_approx"]), 5),
            "agree_new_vs_ref": round(float((both["sign_new"] == both["sign_ref"]).mean()), 4),
            "agree_old_vs_ref": round(float((both["sign_old"] == both["sign_ref"]).mean()), 4),
            "corr12_new_vs_ref": round(float(both["new_vs_ust"].corr(both["tr_minus_ust_approx"])), 4),
            "corr12_old_vs_ref": round(float(both["old_cash_sub"].corr(both["tr_minus_ust_approx"])), 4),
            "corr12_old_vs_new": round(float(both["old_cash_sub"].corr(both["new_vs_ust"])), 4),
            "mean_value_old": round(float(both["old_cash_sub"].mean()), 4), "mean_value_new": round(float(both["new_vs_ust"].mean()), 4),
        })
        for lab, lo, hi in (("2013-2019", "2013-01-01", "2019-12-31"), ("2020-", "2020-01-01", None)):
            b = both.loc[lo:hi] if hi else both.loc[lo:]
            chk[aid][f"sign_flip_share_{lab}"] = round(float((b["sign_old"] != b["sign_new"]).mean()), 4)
        # 2022
        b22 = both.loc["2022-01-01":"2022-12-31"]
        me = b22.groupby(b22.index.to_period("M")).tail(1).copy()
        me.index = me.index.strftime("%Y-%m-%d")
        y22.append(me.reset_index().rename(columns={"index": "date"}))
        chk[aid]["y2022"] = {
            "days": int(len(b22)), "neg_days_old": int((b22["sign_old"] < 0).sum()), "neg_days_new": int((b22["sign_new"] < 0).sum()),
            "neg_days_ref": int((b22["sign_ref"] < 0).sum()),
            "min_old": round(float(b22["old_cash_sub"].min()), 4), "min_new": round(float(b22["new_vs_ust"].min()), 4),
            "min_ref": round(float(b22["tr_minus_ust_approx"].min()), 4),
            "sign_changes_old": int((b22["sign_old"] != b22["sign_old"].shift(1)).iloc[1:].sum()),
            "sign_changes_new": int((b22["sign_new"] != b22["sign_new"].shift(1)).iloc[1:].sum()),
            "sign_changes_ref": int((b22["sign_ref"] != b22["sign_ref"].shift(1)).iloc[1:].sum()),
            "first_neg_date_old": str(b22.index[b22["sign_old"] < 0].min().date()) if (b22["sign_old"] < 0).any() else None,
            "first_neg_date_new": str(b22.index[b22["sign_new"] < 0].min().date()) if (b22["sign_new"] < 0).any() else None,
            "first_neg_date_ref": str(b22.index[b22["sign_ref"] < 0].min().date()) if (b22["sign_ref"] < 0).any() else None,
        }
        note(f"[3] {aid}: " + json.dumps({k: v for k, v in chk[aid].items() if k != "y2022"}, ensure_ascii=False))
        note(f"[3] {aid} 2022: " + json.dumps(chk[aid]["y2022"], ensure_ascii=False))
        tr_rows[aid] = both
    pd.concat(daily_rows).rename_axis("date").to_csv(OUT / "p5_3_trend_daily.csv.gz", float_format="%.6f")
    pd.concat(y22).to_csv(OUT / "p5_3_2022_month_end.csv", index=False, float_format="%.4f")

    info = {"as_of": AS_OF, "cells_tested": 0, "checks": 3, "months": months, "basis": BASIS,
            "universe_yaml_line": YAML_TREND, "mod_durtn_stats": dur_stats, "invariance": inv,
            "trend_not_ready_when_panel_lacks_mod_durtn": unready_info,
            "latest_trend_json_baseline": jt0, "latest_trend_json_variant": jt, "checks_result": chk,
            "runtime_sec": round(time.time() - t0, 1)}
    (OUT / "p5_3_run_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    note(f"완료 {info['runtime_sec']}s")
    (OUT / "p5_3_run_log.txt").write_text("\n".join(LOG) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
