"""Phase 5 레인 p5_4 — 주가지수(KOSPI200·S&P500) 펀더멘털 블록 재구성(사전 등록 docs/prereg_phase5.md §P5-4).

    .venv/bin/python scripts/phase5_p5_4.py collect    # 네트워크: FRED·ECOS·OECD → data/raw/phase5_macro/ (재개 가능)
    .venv/bin/python scripts/phase5_p5_4.py build      # data/processed/phase5_macro.csv.gz (네트워크 없음)
    .venv/bin/python scripts/phase5_p5_4.py eval       # 4a·4b 판정 → outputs/phase5/p5_4_*
    .venv/bin/python scripts/phase5_p5_4.py            # 위 셋을 차례로

구현 규칙(결과를 보기 전에 고정 — 아래 'FIXED' 표시. 바꾸면 보고서 '사후 수정'에 적는다):
- 설정 파일(config/*)은 바꾸지 않는다. 변형은 메모리 안 설정 사본(Phase 4 방식), 새 필드는 별도 패널 파일에서만 온다.
- 판정은 사전 등록 §0: 펀더멘털 블록, 자산(KOSPI200·SP500) 단위, 63일 Spearman IC, 선택 2013-01-01~2019-12-31 /
  확인 2020-01-01~, 순환 이동 플라시보 2,000회(기준선·변형에 같은 이동 배열), 채택 = 3조건.
- FIXED 비교 구간: 변형 블록은 기준선 블록이 있는 날로 자른다(같은 날짜 집합에서 IC 비교).
- FIXED 4a: 지표 동일가중 = 그날 가용한 펀더멘털 지표 점수의 단순평균(지표 weight 모두 1.0 확인). 하위블록이 1개뿐인 자산은 기준선과 같다.
- FIXED 4b: 후보는 해당 자산 overrides.add 로 fundamental.macro 하위블록에 추가(현행 가중 = 하위블록 동일가중).
  보조(판정 아님): 같은 후보를 지표 동일가중으로 합친 블록도 보고한다.
- FIXED PIT:
  * T10Y3M: as_of = 다음 미국 영업일(H.15 계열, fred.AS_OF_RULES DGS10 과 같은 규칙). 값은 FRED 최신 빈티지지만 일별 시장금리 차라 사실상 수정 없음(가정).
  * OECD CLI(LI_AA): OECD 'Original Release Data and Revisions' DB(DSD_STES_REVISIONS)의 에디션(월 단위 빈티지)을 쓴다.
    에디션 E 의 값 = 그 에디션에서 가장 최근 관측월의 CLI − 6개월 전 관측월의 CLI(같은 에디션 안 차분: 재추정 아티팩트를 섞지 않는다).
    as_of = 에디션 E 월의 말일(가정: 에디션 정확한 발간일은 DB에 없고 월 안에서 발간되므로 월말로 보수적으로 둔다).
  * 한국 수출 YoY: ECOS 901Y118/T002(통관 수출금액, 천불) 월별의 전년 동월비. ECOS 값은 확정 수치(빈티지 없음).
    as_of = 기준월 다음 달 15일(가정: 산업부 속보치 매월 1일, 통관 확정치는 중순 — 보수적으로 15일).
    속보치→확정치 수정 크기는 측정하지 못했다(OECD EX 빈티지는 에디션마다 단위가 달라 비교 불가) — 가정으로 남긴다.
"""
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

RAW = ROOT / "data" / "raw" / "phase5_macro"
PROC = ROOT / "data" / "processed"
OUT = ROOT / "outputs" / "phase5"
PREFIX = "p5_4"
START_RAW = "2007-01"          # OECD 에디션·ECOS 수집 시작(2008 WARM 구간의 YoY·6개월 차분용)
END = "2026-10-27"             # Phase 2 와 같은 마지막 완결 거래일
WARM = pd.Timestamp("2008-01-01")   # Phase 2 FRED 계열과 같은 패널 시작(백분위 워밍업)
OECD_URL = "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES_REVISIONS@DF_STES_REVISIONS,/{key}"


# ---------------------------------------------------------------- collect
def collect():
    import requests
    import urllib3.util.connection as uc

    from mtscore.data.adapters import ecos, fred
    uc.HAS_IPV6 = False
    log = []
    for sid in ("T10Y3M", "KORLOLITONOSTSAM", "USALOLITONOSTSAM"):   # 뒤 둘은 '현재 빈티지가 2024-01에 끝남' 증거용(점수 미사용)
        p = fred.download(sid, RAW / "fred")
        d = fred.parse_fredgraph(p.read_text(encoding="utf-8"), sid)
        log.append(f"FRED {sid}: {len(d)}행 {d.date.min().date()}~{d.date.max().date()}")
    p = ecos.download("901Y118", "M", "200701", "202610", "T002", RAW / "ecos")
    d = ecos.read_raw(p, "M")
    log.append(f"ECOS 901Y118/T002: {len(d)}행 {d.date.min().date()}~{d.date.max().date()}")
    (RAW / "oecd").mkdir(parents=True, exist_ok=True)
    for key, name in (("KOR.M.LI_AA......", "LI_AA_KOR"), ("USA.M.LI_AA......", "LI_AA_USA"), ("KOR.M.EX......", "EX_KOR")):
        out = RAW / "oecd" / f"{name}.csv"
        if not out.exists():
            for k in range(4):
                try:
                    r = requests.get(OECD_URL.format(key=key), params={"startPeriod": START_RAW, "format": "csvfile"},
                                     headers={"User-Agent": "curl/8"}, timeout=240)
                    r.raise_for_status()
                    break
                except requests.RequestException:
                    if k == 3:
                        raise
                    time.sleep(5 * (k + 1))
            out.write_text(r.text, encoding="utf-8")
        d = pd.read_csv(out)
        log.append(f"OECD {name}: {len(d)}행, 에디션 {d.EDITION.min()}~{d.EDITION.max()}, 관측월 {d.TIME_PERIOD.min()}~{d.TIME_PERIOD.max()}")
    print("\n".join(log))
    (RAW / "collect_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- build
def cli_edition_changes(path, months=6):
    """OECD 에디션(빈티지)별 CLI 의 months 개월 변화: 에디션 안 최근 관측월 값 − months 개월 전 관측월 값(같은 에디션).
    Returns DataFrame[date(최근 관측월 1일), value, as_of(에디션 월말), edition, n_obs]."""
    d = pd.read_csv(path, dtype={"EDITION": str})
    d["tp"] = pd.PeriodIndex(d["TIME_PERIOD"], freq="M")
    rows = []
    for ed, g in d.groupby("EDITION", sort=True):
        s = g.drop_duplicates("tp", keep="last").set_index("tp")["OBS_VALUE"].astype(float).sort_index()
        last = s.index.max()
        if (last - months) not in s.index:
            continue
        e = pd.Period(ed, freq="M")
        rows.append({"date": last.to_timestamp(), "value": s[last] - s[last - months],
                     "as_of": e.to_timestamp(how="end").normalize(), "edition": ed, "n_obs": len(s)})
    return pd.DataFrame(rows)


def build():
    from mtscore.data.adapters import ecos, fred
    from mtscore.data.schema import validate_panel
    parts, info = [], {}

    def add(asset, field, df, source, note):
        df = df[(df["date"] >= WARM) & (df["as_of"] <= pd.Timestamp(END))].sort_values(["as_of", "date"])
        parts.append(pd.DataFrame({"date": df["date"], "asset_id": asset, "field": field,
                                   "value": df["value"].astype(float), "as_of": df["as_of"], "source": source}))
        info[f"{asset}.{field}"] = {"source": source, "rows": int(len(df)), "first_date": str(df["date"].min().date()),
                                    "last_date": str(df["date"].max().date()), "first_as_of": str(df["as_of"].min().date()),
                                    "last_as_of": str(df["as_of"].max().date()), "note": note}

    # SP500 T10Y3M(일별, %p). as_of = 다음 미국 영업일(H.15 계열 규칙)
    t = fred.parse_fredgraph((RAW / "fred" / "T10Y3M.csv").read_text(encoding="utf-8"), "T10Y3M")
    t["as_of"] = fred.as_of_for("DGS10", t["date"])
    add("SP500", "t10y3m", t, "fred:T10Y3M", "as_of = 다음 미국 영업일(DGS10 과 같은 규칙, 가정). 일별 금리차라 수정 없음(가정)")
    # 한국 수출 YoY(ECOS 901Y118/T002, 천불) — as_of = 기준월 다음 달 15일
    ex = ecos.read_raw(RAW / "ecos" / "901Y118_M_T002_200701_202610.csv", "M").set_index("date")["value"]
    yoy = (ex / ex.shift(12) - 1.0) * 100.0
    full = pd.date_range(ex.index.min(), ex.index.max(), freq="MS")
    assert ex.index.equals(full), "ECOS 수출 월별에 빠진 달이 있다"
    yoy = ((ex / ex.shift(12) - 1.0) * 100.0).dropna()
    yd = pd.DataFrame({"date": yoy.index, "value": yoy.to_numpy(), "as_of": (yoy.index + pd.DateOffset(months=1, days=14))})
    add("KOSPI200", "kr_exports_yoy", yd, "ecos:901Y118/T002 (YoY %)",
        "as_of = 기준월 다음 달 15일(가정). ECOS 값은 확정치(빈티지 없음) — 속보치(매월 1일)와의 차이는 점검 불가(가정)")
    # OECD CLI 6개월 변화(에디션 안 차분)
    for asset, field, nm in (("KOSPI200", "kr_cli_chg6m", "LI_AA_KOR"), ("SP500", "us_cli_chg6m", "LI_AA_USA")):
        c = cli_edition_changes(RAW / "oecd" / f"{nm}.csv")
        add(asset, field, c, f"oecd:DSD_STES_REVISIONS LI_AA {nm[-3:]} (에디션 내 6개월 차분)",
            "as_of = 에디션 월말(가정: 에디션 발간일 미상 → 보수적). 같은 에디션 안 차분")
        info[f"{asset}.{field}"]["n_editions"] = int(len(c))
        info[f"{asset}.{field}"]["edition_first"] = str(c["edition"].iloc[0])
    panel = validate_panel(pd.concat(parts, ignore_index=True))
    PROC.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PROC / "phase5_macro.csv.gz", index=False)

    # 점검 1: FRED 현재 빈티지(2024-01 까지) 6개월 차분 대 에디션 PIT 값 — 재추정 아티팩트 크기
    chk = {}
    for asset, field, sid in (("KOSPI200", "kr_cli_chg6m", "KORLOLITONOSTSAM"), ("SP500", "us_cli_chg6m", "USALOLITONOSTSAM")):
        f = fred.parse_fredgraph((RAW / "fred" / f"{sid}.csv").read_text(encoding="utf-8"), sid).set_index("date")["value"]
        cur = (f - f.shift(6)).dropna()
        pit = panel[(panel.asset_id == asset) & (panel.field == field)].drop_duplicates("date", keep="last").set_index("date")["value"]
        j = pd.concat({"pit_edition": pit, "fred_final": cur}, axis=1).dropna()
        chk[f"{asset}.{field}"] = {"n": int(len(j)), "corr": float(j.corr().iat[0, 1]),
                                   "mean_abs_diff": float((j.pit_edition - j.fred_final).abs().mean()),
                                   "sign_agree": float((np.sign(j.pit_edition) == np.sign(j.fred_final)).mean()),
                                   "fred_final_last": str(f.index.max().date())}
    info["check_pit_vs_final_cli"] = chk
    # (점검 2 폐기: OECD EX 는 에디션마다 단위가 달라(2007 편 ≈ 1/1000) 첫값 대 최신값 비교가 성립하지 않는다 — 속보치→확정치 수정 크기는 측정 불가)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{PREFIX}_build_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    feas = pd.DataFrame([
        {"asset": "KOSPI200", "candidate": "한국 수출 YoY", "source_tried": "ECOS 901Y118/T002 (통관 수출금액, 월, 천불)", "status": "사용(가정 포함)",
         "pit_method": "as_of = 기준월 다음 달 15일", "reason": "ECOS 는 확정치만(빈티지 없음) → 속보치(매월 1일 산업부)→확정치 수정 크기는 측정 불가(가정). 2026-10-29 기준 ECOS 최신월 2026-08"},
        {"asset": "KOSPI200", "candidate": "한국 수출 YoY", "source_tried": "OECD 개정 DB(DSD_STES_REVISIONS) EX KOR", "status": "미사용",
         "pit_method": "", "reason": "에디션마다 단위가 달라(2007 편 ≈ 1/1000 규모) 빈티지 비교 불가, 통화도 KRW, 첫 등장이 보통 2개월 지연"},
        {"asset": "KOSPI200/SP500", "candidate": "OECD CLI 6개월 변화", "source_tried": "FRED KORLOLITONOSTSAM·USALOLITONOSTSAM", "status": "불가",
         "pit_method": "", "reason": "최신 빈티지가 2024-01 에서 끝남(수집 확인). 최신 빈티지는 재추정 포함 → PIT 아님(KOR 6개월 차분의 에디션 값과 상관 0.68)"},
        {"asset": "KOSPI200/SP500", "candidate": "OECD CLI 6개월 변화", "source_tried": "ALFRED 빈티지(KOR/USA CLI)", "status": "불가",
         "pit_method": "", "reason": "첫 빈티지가 약 2018-07-17(이분 탐색) → 선택 구간(2013~2019) 대부분 N/A, 2024-01 에서 끝남"},
        {"asset": "KOSPI200/SP500", "candidate": "OECD CLI 6개월 변화", "source_tried": "OECD 개정 DB(DSD_STES_REVISIONS) LI_AA KOR/USA", "status": "사용(가정 포함)",
         "pit_method": "에디션(월 빈티지) 안 최근월 − 6개월 전(같은 에디션), as_of = 에디션 월말",
         "reason": "에디션 2007-03~2026-10(결측 에디션 2016-07·08, 2020-03, 2024-08, 2025-08, 2026-08). 에디션 정확한 발간일은 DB에 없어 월말로 보수적"},
        {"asset": "SP500", "candidate": "T10Y3M 3개월 변화", "source_tried": "FRED T10Y3M(일별)", "status": "사용(가정 포함)",
         "pit_method": "as_of = 다음 미국 영업일(H.15 규칙, DGS10 과 같음)", "reason": "일별 시장금리 차라 사실상 수정 없음(가정). 최신 빈티지 사용"}])
    feas.to_csv(OUT / f"{PREFIX}_feasibility.csv", index=False)
    print(json.dumps(info, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- eval
SEED_OFFSET = 5400          # FIXED: 플라시보 시드 = backtest.placebo_seed + 5400 + 10·단위 순번 + 구간 순번 (Phase 4 의 4000 과 구별)
PRIMARY_H = 63
CORR_CUT = 0.9
PERIODS = {"selection": ("2013-01-01", "2019-12-31"), "confirmation": ("2020-01-01", None)}
EQ = ["KOSPI200", "SP500"]
CAND = {   # 후보 지표 정의(자산별 overrides.add → fundamental.macro). X1 = 수출/금리차, X2 = OECD CLI
    "KOSPI200": {"X1": {"name": "kr_exports_yoy", "indicator": "level", "direction": "+", "fields": ["kr_exports_yoy"]},
                 "X2": {"name": "kr_cli_chg6m", "indicator": "level", "direction": "+", "fields": ["kr_cli_chg6m"]}},
    "SP500": {"X1": {"name": "t10y3m_chg_3m", "indicator": "diff_months", "direction": "+", "fields": ["t10y3m"],
                     "params": {"months": 3}},
              "X2": {"name": "us_cli_chg6m", "indicator": "level", "direction": "+", "fields": ["us_cli_chg6m"]}}}
VARIANTS_4B = {"X1": ["X1"], "X2": ["X2"], "X12": ["X1", "X2"]}
PIT_DATES = ["2014-06-30", "2017-12-29", "2020-06-30", "2023-12-28", "2026-06-30"]


def window(idx, per):
    lo, hi = PERIODS[per]
    m = idx >= pd.Timestamp(lo)
    return m & (idx <= pd.Timestamp(hi)) if hi else m


def variant_universe(uni, keys):
    """설정 사본: 자산별 overrides.add 의 fundamental.macro 에 keys 후보를 붙인다(메모리 안, config 파일 불변)."""
    import copy
    u = copy.deepcopy(uni)
    for a in u:
        if a["asset_id"] in CAND:
            ov = dict(a.get("overrides") or {})
            add = {k: list(v) for k, v in (ov.get("add") or {}).items()}
            add.setdefault("fundamental.macro", []).extend(copy.deepcopy(CAND[a["asset_id"]][k]) for k in keys)
            ov["add"] = add
            a["overrides"] = ov
    return u


def fund_cols(h):
    c = h.coverage
    return [r for r, b, u in zip(c["indicator"], c["block"], c["used"]) if b == "fundamental" and u]


def ie_block(h):
    """지표 동일가중 펀더멘털 블록: 그날 가용한 펀더멘털 지표 점수의 단순평균(전부 결측이면 결측)."""
    return h.score[fund_cols(h)].mean(axis=1, skipna=True).where(h.score[fund_cols(h)].notna().any(axis=1))


def same(a, b):
    return bool(((a == b) | (a.isna() & b.isna())).all())


def eval():
    t0 = time.time()
    from phase3_backtest import engine, raw_cfg
    from mtscore import ScoringEngine, load_config
    from mtscore.core import backtest as bt
    OUT.mkdir(parents=True, exist_ok=True)
    log = []

    def note(msg):
        print(msg, flush=True)
        log.append(msg)

    panel = pd.read_csv(PROC / "panel.csv.gz", parse_dates=["date", "as_of"])
    macro = pd.read_csv(PROC / "phase5_macro.csv.gz", parse_dates=["date", "as_of"])
    full = pd.concat([panel, macro], ignore_index=True)
    note(f"패널 {len(panel):,}행 + 매크로 후보 {len(macro):,}행")
    uni, profs, sc = raw_cfg()
    n_pl, seed0 = int(sc["backtest"]["placebo_shifts"]), int(sc["backtest"]["placebo_seed"])
    horizons = [int(h) for h in sc["backtest"]["horizons"]]
    regime_cfg = sc["regime"]

    # ---- 점수 이력: 기준선 + 4b 변형 3개(수출·금리차 / CLI / 둘)
    base_eng = engine(uni, profs, sc)
    res = base_eng.backtest(full, asset_ids=EQ, placebo=0)
    hist = {"base": res.history}
    fwd = res.forward
    for v, keys in VARIANTS_4B.items():
        hist[v] = engine(variant_universe(uni, keys), profs, sc).score_history(full, asset_ids=EQ)
        note(f"[점수] 변형 {v} 완료")

    # ---- 재현·구성 점검: 새 패널 행이 기준선을 못 바꿨는지, 하위블록 평균 재계산이 블록과 같은지, 지표 가중치 1.0 인지
    ref2 = pd.read_csv(ROOT / "outputs" / "phase2" / "score_history.csv.gz", parse_dates=["date"])
    ref3 = pd.read_csv(PROC / "phase3_forward_returns.csv.gz", parse_dates=["date"])
    rep, struct = [], []
    eng0 = ScoringEngine(load_config(ROOT / "config"))
    hist0 = eng0.score_history(panel, asset_ids=EQ)   # 매크로 행 없는 원 패널·원 설정
    for a in EQ:
        b = hist["base"][a].blocks["fundamental"]
        b0 = hist0[a].blocks["fundamental"]
        r2 = ref2[ref2.asset_id == a].set_index("date")["fundamental"].dropna()
        r3 = ref3[ref3.asset_id == a].set_index("date")["fundamental"].dropna()
        bb = b.dropna()
        rep.append({"asset_id": a, "reference": "원 패널·원 설정 재계산(매크로 행 없음)", "n_new": int(len(bb)), "n_ref": int(b0.notna().sum()),
                    "identical": same(b, b0), "max_abs_diff": float((b - b0).abs().max())})
        rep.append({"asset_id": a, "reference": "outputs/phase2/score_history.csv.gz(round 4)", "n_new": int(len(bb)), "n_ref": int(len(r2)),
                    "identical": bool(bb.round(4).reindex(r2.index).equals(r2)) and len(bb) == len(r2),
                    "max_abs_diff": float((bb.round(4).reindex(r2.index) - r2).abs().max())})
        rep.append({"asset_id": a, "reference": "data/processed/phase3_forward_returns.csv.gz(round 6)", "n_new": int(len(bb)), "n_ref": int(len(r3)),
                    "identical": bool(bb.round(6).reindex(r3.index).equals(r3)) and len(bb) == len(r3),
                    "max_abs_diff": float((bb.round(6).reindex(r3.index) - r3).abs().max())})
        h = hist["base"][a]
        fb = h.sub_blocks["fundamental"]
        w = pd.Series({c: h.weights[c] for c in fund_cols(h)})
        struct.append({"asset_id": a, "fundamental_indicators": ",".join(fund_cols(h)), "sub_blocks": ",".join(fb.columns),
                       "n_sub_blocks": int(fb.shape[1]), "indicator_weights_all_1": bool((w == 1.0).all()),
                       "subblock_weights": json.dumps({k: h.weights[("fundamental", k)] for k in fb.columns}),
                       "block_equals_mean_of_subblocks": same(b.round(10), fb.mean(axis=1, skipna=True).where(fb.notna().any(axis=1)).round(10)),
                       "ie_equals_block_identical": same(b.round(10), ie_block(h).round(10))})
    pd.DataFrame(rep).to_csv(OUT / f"{PREFIX}_reproduce_diff.csv", index=False)
    pd.DataFrame(struct).to_csv(OUT / f"{PREFIX}_fundamental_structure.csv", index=False)
    for r in rep:
        note(f"[재현] {r['asset_id']} vs {r['reference']}: 동일 {r['identical']}, 행 {r['n_new']}/{r['n_ref']}, 최대차 {r['max_abs_diff']:.2e}")
    for r in struct:
        note(f"[구성] {r['asset_id']}: 지표 {r['fundamental_indicators']}; 하위블록 {r['sub_blocks']}({r['n_sub_blocks']}개); "
             f"IE==현행 {r['ie_equals_block_identical']}")

    # ---- 불변 점검: 변형이 기존 지표 점수·다른 블록을 바꾸지 않았는가
    inv = []
    for v in VARIANTS_4B:
        for a in EQ:
            hb, hv = hist["base"][a], hist[v][a]
            common = [c for c in hb.score.columns if c in hv.score.columns]
            other = ["oversold", "valuation"]
            inv.append({"variant": v, "asset_id": a,
                        "existing_indicator_scores_identical": bool(all(same(hb.score[c], hv.score[c]) for c in common)),
                        "other_blocks_identical": bool(all(same(hb.blocks[c], hv.blocks[c]) for c in other)),
                        "new_in_variant": ",".join(sorted(set(hv.score.columns) - set(hb.score.columns)))})
    inv = pd.DataFrame(inv)
    inv.to_csv(OUT / f"{PREFIX}_invariance.csv", index=False)
    note(f"[불변] 기존 지표 점수 동일 {inv.existing_indicator_scores_identical.all()}, 다른 블록 동일 {inv.other_blocks_identical.all()}")

    # ---- 커버리지
    cov = []
    for a in EQ:
        h = hist["X12"][a]
        for k in ("X1", "X2"):
            n = CAND[a][k]["name"]
            f = CAND[a][k]["fields"][0]
            cov.append({"asset_id": a, "indicator": n, "field": f, "first_raw": h.raw[n].first_valid_index() if n in h.raw else None,
                        "first_score": h.score[n].first_valid_index() if n in h.score else None,
                        "last_score": h.score[n].last_valid_index() if n in h.score else None,
                        "n_score_selection": int(h.score[n][window(h.score.index, "selection")].notna().sum()) if n in h.score else 0,
                        "n_score_confirmation": int(h.score[n][window(h.score.index, "confirmation")].notna().sum()) if n in h.score else 0,
                        "base_block_first_score": hist["base"][a].blocks["fundamental"].first_valid_index(),
                        "selection_meaningful(first_score<=2013-12-31)": bool(n in h.score and h.score[n].first_valid_index() is not None
                                                                              and h.score[n].first_valid_index() <= pd.Timestamp("2013-12-31"))})
    cov = pd.DataFrame(cov)
    cov.to_csv(OUT / f"{PREFIX}_coverage.csv", index=False)
    for r in cov.to_dict("records"):
        note(f"[커버리지] {r['asset_id']} {r['indicator']}: 첫 점수 {r['first_score']}, 선택 {r['n_score_selection']}일·확인 {r['n_score_confirmation']}일")

    # ---- 중복 점검(선택 구간 지표 점수 Pearson): 새 지표 대 기존 펀더멘털 지표 + 새 지표끼리
    red = []
    for a in EQ:
        h = hist["X12"][a]
        sel = h.score[window(h.score.index, "selection")]
        news = [CAND[a][k]["name"] for k in ("X1", "X2")]
        olds = [c for c in fund_cols(hist["base"][a])]
        blk = hist["base"][a].blocks["fundamental"][window(h.score.index, "selection")]
        for n in news:
            for o in olds + [m for m in news if m != n]:
                d = pd.concat([sel[n], sel[o]], axis=1).dropna()
                c = float(d.corr().iat[0, 1]) if len(d) > 2 else np.nan
                red.append({"asset_id": a, "new": n, "other": o, "kind": "새-새" if o in news else "새-기존", "n": int(len(d)),
                            "corr_selection": c, "over_cut": bool(c > CORR_CUT)})
            d = pd.concat([sel[n], blk], axis=1).dropna()
            red.append({"asset_id": a, "new": n, "other": "(현행 펀더멘털 블록)", "kind": "새-블록(참고)", "n": int(len(d)),
                        "corr_selection": float(d.corr().iat[0, 1]), "over_cut": bool(d.corr().iat[0, 1] > CORR_CUT)})
    red = pd.DataFrame(red)
    red.to_csv(OUT / f"{PREFIX}_redundancy.csv", index=False)
    hit = red[(red.kind != "새-블록(참고)") & red.over_cut]
    note(f"[중복] 0.9 초과 쌍: {len(hit)}개" + (": " + ", ".join(f"{r.asset_id}:{r.new}~{r.other}" for r in hit.itertuples()) if len(hit) else ""))
    redundant = {(r.asset_id, r.new) for r in hit.itertuples() if r.kind == "새-기존"}

    # ---- 팔(arm)별 블록 시리즈
    arms = {a: {} for a in EQ}
    for a in EQ:
        arms[a]["base"] = hist["base"][a].blocks["fundamental"]
        arms[a]["IE"] = ie_block(hist["base"][a])
        for v in VARIANTS_4B:
            arms[a][v] = hist[v][a].blocks["fundamental"]
            arms[a][v + "_IE"] = ie_block(hist[v][a])

    # ---- 분할 IC + 플라시보(같은 이동 배열)
    units = [("equity_index", EQ, ["base", "IE"]),
             ("KOSPI200", ["KOSPI200"], list(arms["KOSPI200"])), ("SP500", ["SP500"], list(arms["SP500"]))]
    rows = []
    for ui, (unit, members, labs) in enumerate(units):
        for pi, per in enumerate(PERIODS):
            ser = {lab: {a: arms[a][lab].where(window(arms[a][lab].index, per)) for a in members} for lab in labs}
            nmin = min(int(ser["base"][a].notna().sum()) for a in members)
            shifts = bt.shift_draws(nmin, n_pl, seed0 + SEED_OFFSET + 10 * ui + pi)
            for lab in labs:
                pp = [(ser[lab][a], {hz: fwd[a][f"fwd_{hz}"] for hz in horizons}) for a in members]
                obs, P = bt.pooled_placebo_ic(pp, shifts)
                ph = bt.placebo_p(obs, P)
                for j, hz in enumerate(horizons):
                    r = bt.pooled_ic([(ser[lab][a], fwd[a][f"fwd_{hz}"]) for a in members], hz)
                    rows.append({"unit": unit, "assets": ",".join(members), "arm": lab, "period": per, "horizon": hz, **r,
                                 "ic_placebo_obs": obs[j], "p_placebo": ph[j], "placebo_sd": float(np.nanstd(P[:, j])) if len(P) else np.nan,
                                 "n_shifts": len(shifts), "role": "판정" if hz == PRIMARY_H else "보조"})
        note(f"[IC] {unit} 완료 ({time.time() - t0:.0f}s)")
    ic = pd.DataFrame(rows)
    ic.to_csv(OUT / f"{PREFIX}_split_ic.csv", index=False)

    # ---- 판정표(63일). 비교 대상: 4a·4b 는 현행(base), 보조 *_IE 는 지표 동일가중 기준선(IE)
    cells = [("4a", "equity_index", "IE", "base", "primary"), ("4a", "KOSPI200", "IE", "base", "primary"), ("4a", "SP500", "IE", "base", "primary")]
    for a in EQ:
        cells += [("4b", a, v, "base", "primary") for v in VARIANTS_4B]
        cells += [("4b-aux(지표 동일가중)", a, v + "_IE", "IE", "aux") for v in VARIANTS_4B]
    vd = []
    for part, unit, arm, ref, tier in cells:
        k = ic[(ic.unit == unit) & (ic.horizon == PRIMARY_H)].set_index(["arm", "period"])
        g = lambda lab, per, col: k.at[(lab, per), col]  # noqa: E731
        b_s, v_s, b_c, v_c = g(ref, "selection", "ic"), g(arm, "selection", "ic"), g(ref, "confirmation", "ic"), g(arm, "confirmation", "ic")
        b_p, v_p = g(ref, "confirmation", "p_placebo"), g(arm, "confirmation", "p_placebo")
        c1, c2, c3 = bool(v_s > b_s), bool(v_c >= b_c), bool(v_p <= b_p)
        members = units[[u[0] for u in units].index(unit)][1]
        ident = all(same(arms[a][arm], arms[a][ref]) for a in members)
        key = arm.replace("_IE", "")
        cand_names = [CAND[a][x]["name"] for a in members for x in VARIANTS_4B.get(key, [])]
        red_flag = any((a, CAND[a][x]["name"]) in redundant for a in members for x in VARIANTS_4B.get(key, []))
        # 보조: 날짜 교집합에서의 IC(선택·확인) — 변형 블록을 기준선 블록이 있는 날로 자름
        com = {}
        for per in PERIODS:
            pr = [(arms[a][arm].where(window(arms[a][arm].index, per) & arms[a][ref].notna()), fwd[a][f"fwd_{PRIMARY_H}"]) for a in members]
            pb = [(arms[a][ref].where(window(arms[a][ref].index, per) & arms[a][arm].notna()), fwd[a][f"fwd_{PRIMARY_H}"]) for a in members]
            com[per] = (bt.pooled_ic(pr, PRIMARY_H)["ic"], bt.pooled_ic(pb, PRIMARY_H)["ic"])
        c12_common = bool(com["selection"][0] > com["selection"][1] and com["confirmation"][0] >= com["confirmation"][1])
        verdict = "동일(변화 없음)" if ident else ("채택" if (c1 and c2 and c3) else "기각")
        vd.append({"part": part, "tier": tier, "unit": unit, "arm": arm, "reference_arm": ref, "candidates": ",".join(cand_names),
                   "ic_sel_ref": b_s, "ic_sel_arm": v_s, "ic_conf_ref": b_c, "ic_conf_arm": v_c, "p_conf_ref": b_p, "p_conf_arm": v_p,
                   "p_sel_ref": g(ref, "selection", "p_placebo"), "p_sel_arm": g(arm, "selection", "p_placebo"),
                   "n_dates_sel": g(arm, "selection", "n_dates"), "n_dates_conf": g(arm, "confirmation", "n_dates"),
                   "cond1_sel_improves": c1, "cond2_conf_not_worse": c2, "cond3_p_not_worse": c3,
                   "ref_ic_negative_sel": bool(b_s < 0), "ref_ic_negative_conf": bool(b_c < 0),
                   "cond3_literal_on_negative_ic": bool(b_c < 0 or v_c < 0),
                   "redundant_candidate(>0.9)": red_flag, "identical_series": ident,
                   "common_dates_ic_sel_ref": com["selection"][1], "common_dates_ic_sel_arm": com["selection"][0],
                   "common_dates_ic_conf_ref": com["confirmation"][1], "common_dates_ic_conf_arm": com["confirmation"][0],
                   "common_dates_cond12": c12_common, "verdict": verdict})
    vd = pd.DataFrame(vd)
    vd.to_csv(OUT / f"{PREFIX}_verdict.csv", index=False)
    for r in vd.to_dict("records"):
        note(f"[판정] {r['part']} {r['unit']} {r['arm']} vs {r['reference_arm']}: 선택 {r['ic_sel_ref']:.3f}→{r['ic_sel_arm']:.3f}, "
             f"확인 {r['ic_conf_ref']:.3f}→{r['ic_conf_arm']:.3f}, p {r['p_conf_ref']:.3f}→{r['p_conf_arm']:.3f} ⇒ {r['verdict']}")

    # ---- PIT 절단 점검: 후보 지표 점수와 블록이 '그날로 잘라 계산한 값'과 같은가 (변형 X12)
    pit = []
    eng12 = engine(variant_universe(uni, ["X1", "X2"]), profs, sc)
    for d in PIT_DATES:
        t = pd.Timestamp(d)
        cut = eng12.score_history(full[full["as_of"] <= t], asset_ids=EQ, as_of=t)
        for a in EQ:
            hf, hc = hist["X12"][a], cut[a]
            idx = hf.score.index[hf.score.index <= t][-1]
            for col in [CAND[a]["X1"]["name"], CAND[a]["X2"]["name"]]:
                x, y = hf.score[col].get(idx, np.nan), hc.score[col].get(idx, np.nan) if col in hc.score else np.nan
                pit.append({"cut_date": d, "calendar_day": idx.date(), "asset_id": a, "series": col, "full_history": x, "truncated": y,
                            "match": bool((pd.isna(x) and pd.isna(y)) or np.isclose(x, y, rtol=0, atol=1e-9))})
            x, y = hf.blocks["fundamental"].get(idx, np.nan), hc.blocks["fundamental"].get(idx, np.nan)
            pit.append({"cut_date": d, "calendar_day": idx.date(), "asset_id": a, "series": "fundamental(block)", "full_history": x, "truncated": y,
                        "match": bool((pd.isna(x) and pd.isna(y)) or np.isclose(x, y, rtol=0, atol=1e-9))})
    pit = pd.DataFrame(pit)
    pit.to_csv(OUT / f"{PREFIX}_pit_truncation.csv", index=False)
    note(f"[PIT 절단] 일치 {int(pit.match.sum())}/{len(pit)}")

    # ---- 반영하면 달라지는 것: 최신일 점수·국면, 확인 구간 ≥50 판정 뒤집힘 비율
    imp = []
    for a in EQ:
        hb = hist["base"][a].blocks
        lastd = hb["fundamental"].dropna().index.max()
        lab_base = bt.regime_labels(hb, regime_cfg)["label"]
        for arm in arms[a]:
            if arm == "base":
                continue
            fb = hb.copy()
            fb["fundamental"] = arms[a][arm].reindex(hb.index)
            lab = bt.regime_labels(fb, regime_cfg)["label"]
            conf = window(hb.index, "confirmation") & hb["fundamental"].notna() & fb["fundamental"].notna()
            both = pd.concat([hb["fundamental"], fb["fundamental"]], axis=1, keys=["b", "v"]).dropna()
            imp.append({"asset_id": a, "arm": arm, "last_date": lastd.date(), "base_block_last": hb["fundamental"].loc[lastd],
                        "arm_block_last": fb["fundamental"].get(lastd, np.nan),
                        "label_last_base": lab_base.get(lastd), "label_last_arm": lab.get(lastd),
                        "corr_with_base_block": float(both.corr().iat[0, 1]), "mean_abs_diff": float((both.v - both.b).abs().mean()),
                        "flip_ge50_share_confirmation": float(((hb["fundamental"][conf] >= 50) != (fb["fundamental"][conf] >= 50)).mean()),
                        "regime_label_change_share_confirmation": float((lab_base[conf] != lab[conf]).mean())})
    imp = pd.DataFrame(imp)
    imp.to_csv(OUT / f"{PREFIX}_impact.csv", index=False)

    info = {"seconds": round(time.time() - t0, 1), "primary_horizon": PRIMARY_H, "periods": PERIODS, "corr_cut": CORR_CUT,
            "placebo_shifts": n_pl, "placebo_seed_rule": f"{seed0} + {SEED_OFFSET} + 10*unit_idx + period_idx",
            "units": [u[0] for u in units], "n_cells_primary": int((vd.tier == "primary").sum()),
            "n_cells_aux": int((vd.tier == "aux").sum()),
            "verdict": vd[["part", "unit", "arm", "verdict"]].to_dict("records")}
    (OUT / f"{PREFIX}_run_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    note(f"총 {info['seconds']}초")
    (OUT / f"{PREFIX}_run_log.txt").write_text("\n".join(log) + "\n", encoding="utf-8")


if __name__ == "__main__":
    steps = sys.argv[1:] or ["collect", "build", "eval"]
    for s in steps:
        globals()[s]()
