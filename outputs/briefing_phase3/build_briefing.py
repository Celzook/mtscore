"""mtscore Phase 3 판단 자료(브리핑): outputs/phase3 CSV → briefing_phase3.html · .pdf

실행(WSL 셸, pymupdf 필요):
    /home/infomax/Desktop/Infomax/_project/기술적분석/.venv/bin/python outputs/briefing_phase3/build_briefing.py [--no-pdf]

- 입력은 작업 트리의 outputs/phase3/*.csv(브랜치 phase3-backtest, 미커밋)다. 입력 파일 md5 를 각주에 남긴다.
- 숫자는 전부 CSV 에서 읽는다. 사람이 쓴 판정 문구는 assert 로 CSV 값과 대조한다(어긋나면 중단).
- 양식: ../기술적분석/40_report/template.html 의 <style> + outputs/briefing_phase2/build_briefing.py 의 EXTRA_CSS(두 파일 모두
  읽기만 한다). PDF 는 Windows Edge 헤드리스 print-to-pdf(A4 가로, 창 폭 1017px).
"""
import hashlib
import html
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
P3 = REPO / "outputs" / "phase3"
TEMPLATE = REPO.parent / "기술적분석" / "40_report" / "template.html"
P2_BUILD = REPO / "outputs" / "briefing_phase2" / "build_briefing.py"
DATE = "2026-10-28"
H = [21, 63, 126, 252]
BLK = ["oversold", "valuation", "fundamental"]
BLK_KO = {"oversold": "과매도", "valuation": "밸류에이션", "fundamental": "펀더멘털"}
SHORT = {"KOSPI200": "KOSPI200", "SP500": "S&P500", "KTB10Y": "국고 10년", "UST10Y": "미국채 10년", "USDKRW": "원화(USDKRW)",
         "GOLD": "금", "WTI": "WTI", "US_HY": "미국 HY", "US_IG": "미국 IG", "KR_CORP": "국내 회사채"}
ASSETS = list(SHORT)
FILES = ["verdict.csv", "verdict_rules.csv", "ic.csv", "ic_cells.csv", "pooled_ic.csv", "bands.csv", "events.csv",
         "event_list.csv", "regimes_pooled_excess.csv", "threshold50.csv", "score_distribution.csv",
         "exp_currency_variant_ic.csv", "exp_percentile_method_ic.csv", "exp_price_exclusion_corr.csv",
         "exp_price_exclusion_result.csv", "exp_kospi_earnings_ic.csv", "exp_kospi_earnings_corr.csv",
         "exp_contrarian_pooled_ic.csv", "exp_trend_gate.csv", "exp_trend_gate_2022_banddays.csv",
         "ust10y_valuation_split.csv", "ic_nonoverlap_halves.csv", "run_info.json", "pytest_run.txt"]
MD5 = {f: hashlib.md5((P3 / f).read_bytes()).hexdigest()[:8] for f in FILES}
L = {f[:-4]: pd.read_csv(P3 / f) for f in FILES if f.endswith(".csv")}
SCFG = yaml.safe_load((REPO / "config" / "scoring.yaml").read_text(encoding="utf-8"))
PYTEST = (P3 / "pytest_run.txt").read_text(encoding="utf-8").strip().splitlines()[-1]
N_PL = int(SCFG["backtest"]["placebo_shifts"])

IC = L["ic"]
FULL = IC[IC.period == "full"].set_index(["asset_id", "block", "horizon"]).sort_index()
CELL = L["ic_cells"].set_index(["asset_id", "block"])
RULES = L["verdict_rules"].set_index(["asset_id", "block"])
POOL = L["pooled_ic"].set_index(["asset_class", "block", "horizon"]).sort_index()
BANDS = L["bands"].set_index(["asset_id", "block", "horizon", "band"]).sort_index()
EVS = L["events"].set_index(["asset_id", "block", "band", "horizon"]).sort_index()
NOV = L["ic_nonoverlap_halves"].set_index(["asset_id", "block", "horizon"]).sort_index()
NULL = "유의하지 않음/혼재"


def F(a, b, h, col="ic"):
    return float(FULL.at[(a, b, h), col])


# ---------------------------------------------------------------- 형식 도우미
def e(s):
    return html.escape(str(s), quote=False)


def n(x, d=2):
    if x is None or pd.isna(x):
        return "–"
    s = f"{x:.{d}f}"
    if re.fullmatch(r"-0(\.0+)?", s):
        s = s[1:]
    return s.replace("-", "−")


def sg(x, d=2):
    s = n(x, d)
    return s if s.startswith("−") or s == "–" or float(s.replace("−", "-")) == 0 else "+" + s


def pc(x, d=1):
    return sg(x * 100, d) + "%"


def pv(x):
    """플라시보 p·q 표기: 2001회 중 최소값은 '<0.001'."""
    return "<0.001" if x < 0.001 else n(x, 3)


def table(head, rows, cls="", num_from=1, colgroup=""):
    hd = "<tr>" + "".join(f'<th class="n">{c}</th>' if i >= num_from else f"<th>{c}</th>" for i, c in enumerate(head)) + "</tr>"
    body = []
    for r in rows:
        rc = ""
        if isinstance(r, tuple):
            rc, r = r
        tds = "".join(c if str(c).startswith("<td") else (f'<td class="n">{c}</td>' if i >= num_from else f"<td>{c}</td>")
                      for i, c in enumerate(r))
        body.append(f'<tr class="{rc}">{tds}</tr>' if rc else f"<tr>{tds}</tr>")
    return f'<div class="tablewrap"><table class="{cls}">{colgroup}<thead>{hd}</thead><tbody>{"".join(body)}</tbody></table></div>'


def judge(items, title="판단할 점"):
    return f'<div class="judge"><div class="jt">{title}</div><ul>{"".join(f"<li>{t}</li>" for t in items)}</ul></div>'


def must(cond, msg):
    if not cond:
        sys.exit(f"근거 대조 실패: {msg}")


# ---------------------------------------------------------------- 판정(문구) + 근거 대조
def q(a, b, h):
    return float(FULL.at[(a, b, h), "q_placebo"])


V = {}   # (asset, block) → (신뢰 등급, 한 줄 판정)
must(all(RULES.loc[("US_HY", "valuation")] == "지지") and CELL.at[("US_HY", "valuation"), "q_cell"] < 0.01,
     "US_HY 밸류 견고")
V[("US_HY", "valuation")] = ("good", "근거 있음(견고)",
                             f"4개 기간 IC {n(F('US_HY', 'valuation', 21))}~{n(F('US_HY', 'valuation', 252))}, 셀 q {pv(CELL.at[('US_HY', 'valuation'), 'q_cell'])}, 판정 규칙 4개 모두 통과. 단, 점수와 수익이 같은 스프레드에 묶여 일부는 평균회귀")
must(RULES.at[("KR_CORP", "valuation"), "base"] == "지지" and RULES.at[("KR_CORP", "valuation"), "A_nonoverlap_halves"] != "지지"
     and CELL.at[("KR_CORP", "valuation"), "q_cell"] < 0.01, "KR_CORP 밸류")
V[("KR_CORP", "valuation")] = ("warn", "통계적 지지·기계적",
                               f"셀 q {pv(CELL.at[('KR_CORP', 'valuation'), 'q_cell'])}이지만 점수(스프레드 백분위)와 수익(스프레드 변화)이 같은 변수 — 평균회귀에 가깝고 후반부가 주도")
must(q("SP500", "oversold", 21) < 0.01 and q("SP500", "oversold", 63) > 0.1 and RULES.at[("SP500", "oversold"), "base"] == "지지",
     "SP500 과매도 21일")
V[("SP500", "oversold")] = ("warn", "21일만 견고",
                            f"21일 IC {n(F('SP500', 'oversold', 21))}(q {pv(q('SP500', 'oversold', 21))}); 63일 q {n(q('SP500', 'oversold', 63))}, 그 뒤는 근거 없음")
must(q("KR_CORP", "oversold", 21) < 0.01 and q("KR_CORP", "oversold", 63) < 0.01 and q("KR_CORP", "oversold", 126) > 0.1,
     "KR_CORP 과매도 역방향")
V[("KR_CORP", "oversold")] = ("crit", "21·63일 역방향",
                              f"IC {n(F('KR_CORP', 'oversold', 21))}·{n(F('KR_CORP', 'oversold', 63))}(q {pv(q('KR_CORP', 'oversold', 21))}): 스프레드가 벌어진 뒤 더 벌어졌다")
must(RULES.at[("US_IG", "fundamental"), "base"] == "역방향" and CELL.at[("US_IG", "fundamental"), "q_cell"] > 0.1, "US_IG 펀더")
V[("US_IG", "fundamental")] = ("muted", "약한 역방향",
                               f"NW 기준 역방향이나 플라시보 보정 후 비유의(셀 q {n(CELL.at[('US_IG', 'fundamental'), 'q_cell'])})")
must(q("KOSPI200", "valuation", 252) < 0.01 and RULES.at[("KOSPI200", "valuation"), "base"] == NULL
     and RULES.at[("KOSPI200", "valuation"), "C_nonoverlap_t"] == "지지", "KOSPI200 밸류 252일")
V[("KOSPI200", "valuation")] = ("muted", "252일만",
                                f"252일 IC {n(F('KOSPI200', 'valuation', 252))}(q {pv(q('KOSPI200', 'valuation', 252))}); 짧은 기간은 근거 없음. 표본 13개")
for a in ASSETS:
    for b in BLK:
        if (a, b) not in V:
            must(RULES.at[(a, b), "base"] == NULL and CELL.at[(a, b), "q_cell"] > 0.3, f"{a} {b} 근거 없음")
            V[(a, b)] = ("none", "근거 없음", "")
N_NONE = sum(1 for v in V.values() if v[0] == "none")
SR = FULL["se_ratio"]
SR_MED, SR_LO, SR_HI = SR.median(), SR.quantile(0.1), SR.quantile(0.9)
must(1.2 <= SR_MED <= 1.3, f"SD 비 중앙 {SR_MED}")


# ---------------------------------------------------------------- SVG: 구간별 평균 forward return 막대
def svg_bands(a, b, h, w=300, hgt=118):
    labs = [f"<={SCFG['bands']['contra_extreme']}", f"<={SCFG['bands']['contra_alert']}", "all",
            f">={SCFG['bands']['alert']}", f">={SCFG['bands']['extreme']}"]
    names = ["≤10", "≤25", "전체", "≥75", "≥90"]
    rows = [BANDS.loc[(a, b, h, lb)] for lb in labs]
    vals = [r["mean"] for r in rows]
    vmax = max(0.005, np.nanmax(np.abs(vals))) * 1.15
    pl, pr, pt, pb = 34, 6, 14, 30
    y0 = pt + (hgt - pt - pb) / 2
    Y = lambda v: y0 - v / vmax * (hgt - pt - pb) / 2
    bw = (w - pl - pr) / len(labs)
    g = [f'<line x1="{pl}" x2="{w - pr}" y1="{y0:.1f}" y2="{y0:.1f}" style="stroke:var(--ink-3)"/>']
    dd = 2 if vmax < 0.02 else 1
    for t in (-vmax / 1.15, vmax / 1.15):
        g.append(f'<text x="{pl - 4}" y="{Y(t) + 3:.1f}" text-anchor="end" class="ax">{pc(t, dd - 1)}</text>'
                 f'<line x1="{pl}" x2="{w - pr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" style="stroke:var(--rule-2)"/>')
    for i, (r, nm) in enumerate(zip(rows, names)):
        x = pl + i * bw + bw * 0.18
        v = r["mean"]
        if pd.isna(v):
            g.append(f'<text x="{x + bw * 0.32:.1f}" y="{y0 - 4:.1f}" text-anchor="middle" class="ax">없음</text>')
        else:
            weak = r["n"] < 10 or r["n_indep_approx"] < 10
            col = "var(--neg)" if v < 0 else ("var(--muted-line)" if nm == "전체" else "var(--pos)")
            op = "0.45" if weak else "1"
            y1, y2 = sorted([Y(v), y0])
            g.append(f'<rect x="{x:.1f}" y="{y1:.1f}" width="{bw * 0.64:.1f}" height="{max(y2 - y1, 0.8):.1f}" '
                     f'style="fill:{col};opacity:{op}"/>')
            ty = y1 - 3 if v >= 0 else y2 + 10
            g.append(f'<text x="{x + bw * 0.32:.1f}" y="{ty:.1f}" text-anchor="middle" class="lb">{pc(v, dd)}</text>')
        g.append(f'<text x="{x + bw * 0.32:.1f}" y="{hgt - pb + 13}" text-anchor="middle" class="lb">{nm}</text>'
                 f'<text x="{x + bw * 0.32:.1f}" y="{hgt - pb + 24}" text-anchor="middle" class="ax">n {int(r["n"])}</text>')
    return (f'<svg viewBox="0 0 {w} {hgt}" width="100%" role="img" class="svgc" aria-label="{e(a)} {e(b)} {h}일 구간별 평균 수익">'
            + "".join(g) + "</svg>")


# ---------------------------------------------------------------- 머리 + 1. 결론
def masthead():
    ri = (P3 / "run_info.json").read_text(encoding="utf-8")
    first = re.search(r'"KOSPI200": "(\d{4}-\d{2}-\d{2})"', ri).group(1)
    return f"""
<header class="masthead bhead">
  <div class="eyebrow">mtscore · Phase 3 백테스트 판단 자료 · 점수 {first}~2026-10-27 · 브랜치 phase3-backtest(미커밋)</div>
  <h1>점수가 이후 수익을 예측하는가 — 10개 자산 × 3개 점수 검증 결과</h1>
  <p class="lede">높은 점수(과거 대비 ‘싸다·많이 빠졌다’) 뒤에 수익이 실제로 높았는지 2013~2026 일별 자료로 확인했다. 21·63·126·252영업일 뒤 수익과 점수의 순위상관(IC)을 우연히 나올 수 있는 IC 분포(점수를 시간축으로 {N_PL:,}번 굴린 플라시보)와 비교했다. <b>결론: 근거가 있는 것은 밸류에이션 점수(특히 크레딧)뿐이고, 과매도·펀더멘털 점수는 대부분 예측력이 확인되지 않는다.</b></p>
</header>"""


def sec_conclusion():
    rows = []
    for a in ASSETS:
        cells = []
        for b in BLK:
            k, lab, why_ = V[(a, b)]
            chip = {"good": "good", "warn": "warn", "crit": "crit", "muted": "b", "none": ""}[k]
            if k == "none":
                cells.append('<td class="vc vnone">근거 없음</td>')
                continue
            cells.append(f'<td class="vc v{k}"><span class="chip {chip}">{e(lab)}</span>'
                         + (f'<span class="vw">{e(why_)}</span>' if why_ else "") + "</td>")
        rows.append([f"<b>{e(SHORT[a])}</b>", *cells])
    t = table(["자산", "과매도", "밸류에이션", "펀더멘털"], rows, cls="vt", num_from=99,
              colgroup='<colgroup><col style="width:92px"><col><col><col></colgroup>')
    pv_ = POOL.loc[("ALL", "valuation")]
    po, pf = POOL.loc[("ALL", "oversold")], POOL.loc[("ALL", "fundamental")]
    must(pv_.at[21, "p_placebo"] < 0.01 and pv_.at[63, "p_placebo"] < 0.01 and pv_.at[126, "p_placebo"] > 0.05,
         "풀링 밸류 21·63 견고, 126 약함")
    must((po["p_placebo"] > 0.3).all() and (pf["p_placebo"] > 0.3).all(), "풀링 과매도·펀더 비유의")
    items = [
        f"30개 칸 중 <b>{N_NONE}개는 ‘근거 없음’</b>이다. 점수가 높든 낮든 이후 수익과 통계적으로 구분되는 관계가 보이지 않았다.",
        f"10개 자산을 합쳐 보면 밸류에이션은 21·63일 IC {n(pv_.at[21, 'ic'])}·{n(pv_.at[63, 'ic'])}(플라시보 p {pv(pv_.at[21, 'p_placebo'])}·{pv(pv_.at[63, 'p_placebo'])})로 견고하다. 126·252일은 p {n(pv_.at[126, 'p_placebo'], 3)}·{n(pv_.at[252, 'p_placebo'], 3)}로 약하다. 과매도·펀더멘털은 합쳐도 IC 가 0 근처다(p {n(min(po['p_placebo'].min(), pf['p_placebo'].min()), 2)} 이상).",
        "가장 강한 결과(국내 회사채·미국 HY 밸류)는 점수와 수익이 같은 스프레드에서 나온다. ‘스프레드가 넓으면 이후 좁아진다’는 평균회귀가 섞여 있어, 예측력으로 과대평가하면 안 된다.",
        f"판정 규칙은 결과를 본 뒤에 정했다. 다른 규칙 3개로 바꿔도 남는 것은 <b>미국 HY 밸류(지지)</b>와 <b>국내 회사채 과매도(역방향)</b> 두 칸뿐이다(4절).",
    ]
    li = "".join(f"<li><p>{x}</p></li>" for x in items)
    return f"""<section id="concl"><h2>1. 결론 — 점수가 이후 수익을 예측하나</h2>
<p class="sub leg">신뢰 수준 — <span class="chip good">견고</span> 대안 규칙·플라시보 모두 통과 · <span class="chip warn">조건부</span> 한 기간만 또는 구조적 주의 · <span class="chip crit">역방향</span> 높은 점수 뒤 수익이 낮음 · <span class="chip b">약함</span> 보정 후 비유의 또는 252일만</p>
{t}
<ol class="findings">{li}</ol>
</section>"""


# ---------------------------------------------------------------- 2. 블록별 해설
def sec_blocks():
    rows = []
    for cls, nm in (("ALL", "전체 10개"), ("equity_index", "주가지수 2"), ("rates", "금리 2"), ("credit", "크레딧 3"),
                    ("commodity", "원자재 2"), ("fx", "원화 1")):
        r = [nm]
        for b in BLK:
            d = POOL.loc[(cls, b)]
            parts = []
            for h in H:
                p_ = d.at[h, "p_placebo"]
                s = n(d.at[h, "ic"])
                parts.append(f"<b>{s}</b>" if p_ < 0.05 else s)
            r.append(" · ".join(parts))
        rows.append(r)
    t = table(["자산군(풀링)", "과매도 IC 21·63·126·252", "밸류에이션 IC", "펀더멘털 IC"], rows, cls="pt", num_from=99)
    th = L["threshold50"]
    cnt = {b: (int((th[th.block == b]["diff"] > 0).sum()), int((th[th.block == b]["t_nw"] >= 1.96).sum()),
               int((th[th.block == b]["t_nw"] <= -1.96).sum()), int((th.block == b).sum())) for b in BLK}
    must(cnt["valuation"] == (32, 9, 0, 40) and cnt["oversold"][0] == 17 and cnt["fundamental"][0] == 21, f"임계 50 분할 {cnt}")
    return f"""<section id="blocks" class="pg"><h2>2. 블록별 해설 — 무엇을 믿고 무엇을 믿지 말까</h2>
<p class="sub">굵은 숫자 = 플라시보 p&lt;0.05(점수를 시간축으로 {N_PL:,}번 굴려 만든 ‘우연 IC’ 분포에서 관측값보다 극단인 비율). IC 는 점수 순위와 이후 수익 순위의 상관(−1~1)이다. 0.1 이면 ‘약하지만 의미 있는’ 수준이다.</p>
{t}
<div class="grid3">
<div class="panel"><h3>밸류에이션 — 근거 있음(주로 크레딧)</h3><ul class="plain">
<li>크레딧 3개를 합친 IC 가 4개 기간 모두 플라시보 p {pv(POOL.loc[('credit', 'valuation')]['p_placebo'].max())} 이하다. 주가지수는 21일만 유의하다.</li>
<li>점수가 50 이상일 때와 미만일 때 이후 수익 차가 40개 자산×기간 중 {cnt['valuation'][0]}개에서 양수다(유의 양수 {cnt['valuation'][1]}, 유의 음수 {cnt['valuation'][2]}).</li>
<li>쓰는 법: ‘싸다’ 신호를 <b>수개월 이상</b> 보유 판단의 근거로 쓸 수 있다. 다만 크레딧은 평균회귀 성분이 크다.</li></ul></div>
<div class="panel"><h3>과매도 — 일반적으로 근거 없음</h3><ul class="plain">
<li>전체 풀링 IC 는 4개 기간 모두 0 근처다. 예외는 S&amp;P500 21일 하나다.</li>
<li>국내 회사채는 <b>반대</b>다. 스프레드가 급히 벌어진 뒤 더 벌어졌다.</li>
<li>50 분할 차는 {cnt['oversold'][0]}/{cnt['oversold'][3]}개만 양수이고 유의 음수가 {cnt['oversold'][2]}개다. 쓰는 법: 과매도 점수 단독으로 ‘사라’는 신호로 쓰지 않는다.</li></ul></div>
<div class="panel"><h3>펀더멘털 — 근거 없음</h3><ul class="plain">
<li>전체 풀링 IC 는 음수 쪽(유의 아님)이다. 미국 IG 는 역방향에 가깝다(보정 후 비유의).</li>
<li>50 분할 차는 {cnt['fundamental'][0]}/{cnt['fundamental'][3]}개 양수, 유의 음수 {cnt['fundamental'][2]}개다.</li>
<li>쓰는 법: 국면 이름 안에서 펀더멘털 high/low 의 의미는 현재 근거로는 약하다.</li></ul></div>
</div>
{judge([
        "점수를 ‘무엇을 살지’가 아니라 ‘지금 자기 역사에서 어디인지’를 보는 지표로 쓰는 것이 현재 근거와 맞다. 밸류 점수만 예측 근거로 해석할 여지가 있다.",
        "국면 매트릭스는 세 점수를 같은 무게로 쓴다. 과매도·펀더멘털의 근거가 없다는 결과를 매트릭스에 반영할지는 별도 결정이다(이번에는 바꾸지 않음).",
    ], "의미")}
</section>"""


# ---------------------------------------------------------------- 2b. 국면
def sec_regime():
    rg = L["regimes_pooled_excess"]
    order = [r["label"] for r in SCFG["regime"]["matrix"]]
    rg = rg[rg.regime.isin(order)].set_index(["regime", "horizon"])
    best = rg.xs(252, level="horizon")["mean_excess"]
    must(best.idxmax() == "최우선 매수" and best.idxmin() == "단기 반등 트레이드", "국면 252일 최고·최저")
    mx = {r["label"]: "·".join({"high": "高", "low": "低", None: "–"}[r.get(k)] for k in ("o", "v", "f"))
          for r in SCFG["regime"]["matrix"]}
    rows = [[f"{e(lb)} <span class='sb'>과·밸·펀 {mx[lb]}</span>", f"{int(rg.at[(lb, 126), 'n']):,}",
             *[sg(rg.at[(lb, h), 'mean_excess'] * 100, 2) for h in H]] for lb in order]
    t = table(["국면(임계 50)", "자산-일 n(126일)", "21일", "63일", "126일", "252일"], rows, cls="rt", num_from=1)
    sd = L["score_distribution"]
    sv = sd[sd.block == "valuation"].set_index("asset_id")["share_ge50"]
    th = L["threshold50"]
    drows = []
    for a in ASSETS:
        r = [e(SHORT[a])]
        for b in BLK:
            x = sd[(sd.asset_id == a) & (sd.block == b)].iloc[0]
            t_ = th[(th.asset_id == a) & (th.block == b) & (th.horizon == 63)].iloc[0]
            r += [n(x["median"], 0), f"{x['share_ge50']:.0%}", sg(t_["diff"] * 100, 1)]
        drows.append(r)
    dt = table(["자산", "과매도 중앙값", "≥50 비율", "≥50−<50 63일 %p", "밸류 중앙값", "≥50 비율", "≥50−<50 63일 %p",
                "펀더 중앙값", "≥50 비율", "≥50−<50 63일 %p"], drows, cls="xt", num_from=1)
    return f"""<section id="regime" class="pg"><h2>국면 이름별 이후 수익(참고)과 임계값 50</h2>
<p class="sub">10개 자산의 일별 국면 라벨별로, 그 자산의 무조건 평균 대비 초과수익(%p)을 합쳤다. 겹치는 표본이고 <b>검정하지 않은 기술 통계</b>다.</p>
{t}
<ul class="plain"><li>‘최우선 매수’(세 점수 모두 50 이상)가 252일 {sg(best['최우선 매수'] * 100, 2)}%p 로 가장 높고, ‘단기 반등 트레이드’(과매도만 높고 밸류 낮음)가 {sg(best['단기 반등 트레이드'] * 100, 2)}%p 로 가장 낮다. 밸류 점수의 유효성과 같은 방향이다.</li>
<li>라벨 순서가 기대와 어긋나는 곳도 있다(‘고점 경계’ 252일 {sg(best['고점 경계'] * 100, 2)}%p). 국면 이름을 매매 지시로 읽을 근거는 아직 약하다.</li>
<li>밸류 점수가 50 이상인 날은 S&amp;P500 {sv['SP500']:.0%}·미국 HY {sv['US_HY']:.0%} 뿐이라, 이 두 자산은 ‘최우선 매수’가 거의 나오지 않는다(7절 결정 2).</li></ul>
<h3>블록 점수 분포와 50 분할의 수익 차(63일)</h3>
{dt}
<p class="tnote">중앙값이 50 에서 멀면 국면의 high/low 가 한쪽으로 쏠린다. 수익 차는 점수 ≥50 인 날과 &lt;50 인 날의 63일 평균 수익 차(겹치는 표본).</p>
</section>"""


# ---------------------------------------------------------------- 3. 자산별 핵심 차트
CASES = [("US_HY", "valuation", 63, 252, ">=90"), ("KR_CORP", "valuation", 63, 252, ">=90"),
         ("SP500", "oversold", 21, 63, ">=75"), ("KR_CORP", "oversold", 21, 63, ">=75"),
         ("KOSPI200", "valuation", 63, 252, ">=75"), ("US_IG", "fundamental", 21, 63, ">=90")]


def case_panel(a, b, h1, h2, evb):
    k, lab, why_ = V[(a, b)]
    ev = L["event_list"]
    ev = ev[(ev.asset_id == a) & (ev.block == b) & (ev.band == evb)].copy()
    est = EVS.loc[(a, b, evb)]
    must(len(ev) == int(est.at[h1, "n"]) or len(ev) >= int(est.at[h1, "n"]), f"이벤트 수 {a} {b}")
    last = ev.tail(5)
    erows = [[str(r["date"]), n(r["score"], 1), pc(r[f"fwd_{h1}"]) if pd.notna(r[f"fwd_{h1}"]) else "–",
              pc(r[f"fwd_{h2}"]) if pd.notna(r[f"fwd_{h2}"]) else "–"] for _, r in last.iterrows()]
    et = table(["진입일", "점수", f"{h1}일 뒤", f"{h2}일 뒤"], erows, cls="evt", num_from=1)
    no = NOV.loc[(a, b)]
    ics = " · ".join(f"{h}일 {n(F(a, b, h))}" for h in H)
    pq = " · ".join(f"{h}일 {pv(F(a, b, h, 'q_placebo'))}" for h in H)
    chip = {"good": "good", "warn": "warn", "crit": "crit", "muted": "b"}[k]
    return f"""<div class="panel asset"><div class="ahead"><h3>{e(SHORT[a])} · {BLK_KO[b]}</h3><span class="chip {chip}">{e(lab)}</span><span class="an">{e(why_)}</span></div>
<div class="cgrid"><div><div class="ct">{h1}일 뒤 평균 수익(점수 구간별)</div>{svg_bands(a, b, h1)}</div>
<div><div class="ct">{h2}일 뒤 평균 수익(점수 구간별)</div>{svg_bands(a, b, h2)}</div>
<div><div class="ct">최근 {len(last)}개 이벤트(점수 {e(evb.replace('>=', '≥'))} 진입, 쿨다운 20일) — 전체 {int(est.at[h1, 'n'])}개, {h1}일 평균 {pc(est.at[h1, 'mean'])}(무조건 대비 {pc(est.at[h1, 'excess_mean'])})</div>{et}</div></div>
<p class="tnote">IC {ics}. 플라시보 q(120개 BH) {pq}. 겹치지 않는 표본 IC 전반부 {n(no.at[h2, 'ic_nonoverlap_first_half'])}·후반부 {n(no.at[h2, 'ic_nonoverlap_second_half'])}({h2}일, 후반부 n {int(no.at[h2, 'n_nonoverlap_second_half'])}). 흐린 막대 = n&lt;10 또는 독립 표본(n/h)&lt;10.</p></div>"""


def sec_cases():
    p1 = "".join(case_panel(*c) for c in CASES[:2])
    p2 = "".join(case_panel(*c) for c in CASES[2:4])
    p3 = "".join(case_panel(*c) for c in CASES[4:])
    return f"""<section id="cases" class="pg"><h2>3. 자산별 핵심 — 근거가 있거나 반대로 나온 칸</h2>
<p class="sub">막대 = 점수 구간별 이후 평균 수익(겹치는 일별 표본). ‘전체’는 그 자산의 무조건 평균이다. 크레딧 수익은 iBoxx 총수익(US), 국고 대비 초과수익 근사(국내 회사채)다.</p>
{p1}</section>
<section class="pg"><h2 class="cont">3. 자산별 핵심(계속) — 단기 과매도</h2>{p2}</section>
<section class="pg"><h2 class="cont">3. 자산별 핵심(계속) — 약한 신호</h2>{p3}</section>"""


# ---------------------------------------------------------------- 4. 판정 규칙·통계 보정
def sec_rules():
    rn = {"base": "기본(2개 기간 NW t≥1.96 + 전·후반 같은 부호)", "A_nonoverlap_halves": "A: 전·후반 조건을 겹치지 않는 표본 IC 로",
          "B_t2.58": "B: t≥2.58", "C_nonoverlap_t": "C: 겹치지 않는 표본 t≥1.96"}
    rows = []
    for col, nm in rn.items():
        s = RULES[RULES[col] == "지지"].index
        r = RULES[RULES[col] == "역방향"].index
        rows.append([nm, e(", ".join(f"{SHORT[a]} {BLK_KO[b][:2]}" for a, b in s)) or "–",
                     e(", ".join(f"{SHORT[a]} {BLK_KO[b][:2]}" for a, b in r)) or "–"])
    must(list(RULES[RULES["A_nonoverlap_halves"] == "지지"].index) == [("US_HY", "valuation")], "규칙 A")
    must(len(RULES[RULES["B_t2.58"] == "지지"]) == 3, "규칙 B")
    must(RULES.at[("KR_CORP", "valuation"), "C_nonoverlap_t"] != "지지" and RULES.at[("KOSPI200", "valuation"), "C_nonoverlap_t"] == "지지", "규칙 C")
    t = table(["판정 규칙", "지지", "역방향"], rows, cls="rt", num_from=99)
    pall = POOL.loc[("ALL", "valuation")]
    cl = L["ic_cells"].copy()
    for h in H:
        cl[f"q{h}"] = [FULL.at[(a, b, h), "q_placebo"] for a, b in zip(cl.asset_id, cl.block)]
    cl["sr"] = [FULL.loc[(a, b)]["se_ratio"].median() for a, b in zip(cl.asset_id, cl.block)]
    cl["qmin"] = cl[[f"q{h}" for h in H]].min(axis=1)
    top = cl[(cl.q_cell < 0.5) | (cl.qmin < 0.2)].sort_values("p_cell")
    must(len(top) >= 6, "상위 셀 수")
    trows = [[f"{e(SHORT[r.asset_id])} · {BLK_KO[r.block]}", n(r.mean_ic), pv(r.p_cell), pv(r.q_cell),
              *[(f"<b>{pv(r[f'q{h}'])}</b>" if r[f"q{h}"] < 0.05 else pv(r[f"q{h}"])) for h in H], n(r.sr)]
             for _, r in top.iterrows()]
    ctab = table(["칸", "평균 IC(4기간)", "셀 p", "셀 q(30)", "q 21일", "q 63일", "q 126일", "q 252일", "SD비"], trows, cls="rt", num_from=1)
    return f"""<section id="rules" class="pg"><h2>4. 판정이 얼마나 단단한가</h2>
<p class="sub">판정 규칙은 결과(IC 요약표)를 본 뒤에 정했다. 자산별로 맞추지는 않았지만 사전 등록이 아니므로, 규칙을 바꿨을 때 무엇이 남는지 함께 본다.</p>
{t}
<h3>플라시보 p·다중검정 q 가 작은 칸(나머지 칸은 셀 q ≥ 0.5 이고 기간별 q ≥ 0.2)</h3>
{ctab}
<p class="tnote">셀 p = 4개 기간 평균 IC 의 플라시보 p, 셀 q = 30칸 BH-FDR, 기간별 q = 120개 검정 BH-FDR(굵게 &lt;0.05). SD비 = 플라시보 표준편차 ÷ NW 표준오차(기간 중앙값) — 1보다 크면 NW t 가 그만큼 부풀려져 있다.</p>
<ul class="plain">
<li><b>표준오차 보정</b>: 점수는 며칠·몇 달씩 이어지는 값이라 일반적인 겹침 보정(Newey-West, lag h−1)이 불확실성을 덜 잡는다. 플라시보 분포의 표준편차가 NW 표준오차의 중앙 {n(SR_MED)}배(10~90% {n(SR_LO)}~{n(SR_HI)}배)다. 전체 밸류 풀링 252일은 {n(pall.at[252, 'se_ratio'])}배다. 그래서 NW t 가 아니라 플라시보 p 와 다중검정 보정(BH-FDR q)을 우선한다.</li>
<li><b>다중검정</b>: {len(FULL)}개 검정(30칸×4기간)에서 5% 수준으로 우연히 유의해 보일 수 있는 수는 약 {len(FULL) * 0.05:.0f}개다. q&lt;0.05 로 남는 칸×기간은 {int((FULL['q_placebo'] < 0.05).sum())}개다.</li>
<li>검증 레인이 따로 계산한 플라시보와 대조했다. 기간별 p 의 최대 차는 0.03 이고, q&lt;0.10 판정은 120개 모두 같다(<code>placebo_vs_verifier.csv</code>).</li>
</ul></section>"""


# ---------------------------------------------------------------- 5. 비교 실험
def sec_experiments():
    cp = L["exp_contrarian_pooled_ic"].set_index(["variant", "asset_class", "horizon"])
    eq_pre = [cp.at[("pre_rework", "equity_index", h), "ic"] for h in H]
    eq_cur = [cp.at[("current", "equity_index", h), "ic"] for h in H]
    must(all(p_ > c_ for p_, c_ in zip(eq_pre, eq_cur)), "역발상: 주가지수 개편 전 > 현행")
    crow = []
    for v, nm in (("pre_rework", "개편 전"), ("only_confluence", "동시판정만"), ("only_rv", "변동성비만"), ("current", "현행")):
        crow.append([nm] + [" · ".join(n(cp.at[(v, c, h), "ic"]) for h in H) for c in ("ALL", "equity_index", "credit", "rates")])
    ct = table(["변형", "전체 10개 과매도 IC", "주가지수", "크레딧", "금리"], crow, cls="xt xw", num_from=99,
               colgroup='<colgroup><col style="width:110px"><col><col><col><col></colgroup>')

    tg = L["exp_trend_gate"]
    ev = tg[(tg.kind == "event") & (tg.horizon == 63)].set_index(["asset_id", "gate"])
    trow = [[SHORT[a], f"{pc(ev.at[(a, 'no_gate'), 'mean'])} ({int(ev.at[(a, 'no_gate'), 'n'])})",
             f"{pc(ev.at[(a, 'trend_up'), 'mean'])} ({int(ev.at[(a, 'trend_up'), 'n'])})"] for a in ASSETS]
    tt = table(["자산", "게이트 없음 63일(n)", "200일선 위만(n)"], trow, cls="xt", num_from=1)
    y22 = L["exp_trend_gate_2022_banddays"].set_index(["asset_id", "gate", "horizon"])
    n0 = sum(int(y22.at[(a, "trend_up", 252), "n"]) == 0 for a in ASSETS)
    must(n0 == 7, f"2022 게이트 n=0 자산 수 {n0}")
    wti_g, wti_n = y22.at[("WTI", "trend_up", 252), "mean"], y22.at[("WTI", "no_gate", 252), "mean"]
    must(wti_g < wti_n, "WTI 게이트 악화")

    ke = L["exp_kospi_earnings_ic"]
    ke = ke[ke.period == "full"].set_index(["variant", "block", "horizon"])
    krow = [[nm] + [n(ke.at[(v, "valuation", h), "ic"]) for h in H] + [n(ke.at[(v, "valuation", 252), "t_nw"])]
            for v, nm in (("_capweight(main)", "시총가중(현행)"), ("_ew", "동일가중"), ("_ex2", "삼성·하이닉스 제외"))]
    must(round(ke.at[("_ew", "valuation", 252), "t_nw"], 2) == 4.49 and round(ke.at[("_ex2", "valuation", 252), "t_nw"], 2) == 4.06,
         "KOSPI 민감도 t")
    kt = table(["KOSPI200 밸류", "21일", "63일", "126일", "252일", "252일 t"], krow, cls="xt", num_from=1)

    cv = L["exp_currency_variant_ic"]
    cv = cv[(cv.period == "full") & (cv.block == "fundamental")].set_index(["variant", "horizon"])
    vrow = [[nm] + [f"{n(cv.at[(v, h), 'ic'])} ({n(cv.at[(v, h), 't_nw'], 1)})" for h in H]
            for v, nm in (("both", "both(현행)"), ("oversold_only", "oversold_only"), ("fundamental_only", "fundamental_only"))]
    tmax = cv["t_nw"].abs().max()
    must(round(tmax, 2) == 1.33, f"통화 변형 최대 t {tmax}")
    vt = table(["KOSPI200 펀더 IC(t)", "21일", "63일", "126일", "252일"], vrow, cls="xt", num_from=1)

    pm = L["exp_percentile_method_ic"]
    pm = pm[pm.period == "full"].pivot_table(index=["asset_id", "block", "horizon"], columns="variant", values="ic")
    dmax = (pm["rolling"] - pm["expanding"]).abs()
    big = dmax.sort_values(ascending=False).head(3)
    corr = L["exp_price_exclusion_corr"]
    cmax = corr["corr_first_pooled"].max()
    must(cmax < 0.9 and not corr["over_cut"].any(), "제외 규칙 후보 없음")
    rex = L["exp_price_exclusion_result"].set_index(["drop", "horizon"])
    k63w, k63o = rex.at[("KOSPI200:disparity_20", 63), "ic_second_with"], rex.at[("KOSPI200:disparity_20", 63), "ic_second_without"]
    must(k63o < k63w, "KOSPI200 자산별 후보 후반부 악화")
    return f"""<section id="exp" class="pg"><h2>5. 비교 실험 — 바꿔 봤을 때 무엇이 달라졌나</h2>
<h3>① 역발상 개편(2026-10-28 동시판정·변동성비) — 개선 근거 없음</h3>{ct}
<p class="tnote">과매도 블록 풀링 IC 21·63·126·252일. 주가지수는 개편 전이 4개 기간 모두 높다(차 {n(min(p_ - c_ for p_, c_ in zip(eq_pre, eq_cur)))}~{n(max(p_ - c_ for p_, c_ in zip(eq_pre, eq_cur)))}, 유의 아님). ‘변동성 급등 = 기회’ 가정은 확인되지 않았다.</p>
<div class="grid2">
<div><h3>③ KOSPI200 이익 지표 가중 — 동일가중·두 종목 제외가 더 높다</h3>{kt}
<p class="tnote">시총가중은 삼성전자·SK하이닉스의 낮은 PER 에 끌려간다(Phase 2). 가중을 바꾸면 252일 IC 가 {n(ke.at[("_capweight(main)", "valuation", 252), "ic"])} → {n(ke.at[("_ew", "valuation", 252), "ic"])}·{n(ke.at[("_ex2", "valuation", 252), "ic"])}이다. 결정 C 를 다시 볼 근거이지만, 표본 분할 확인 전에는 바꾸지 않는다.</p>
<h3>④ 통화 이중반영 3변형 — 고를 근거 없음</h3>{vt}
<p class="tnote">해당 자산은 KOSPI200 하나다. 3개 중 최선을 고르는 구조이고, 최대 |t| {n(tmax)}는 우연 범위다.</p></div>
<div><h3>② 200일선 추세 게이트 — 일관된 개선 없음</h3>{tt}
<p class="tnote">과매도 ≥75 진입 이벤트의 63일 뒤 평균. 2022년에는 게이트가 10개 중 {n0}개 자산의 신호를 모두 걸러 미국채·IG 손실을 피했다. WTI 는 게이트를 건 쪽이 252일 {pc(wti_g)}로 게이트 없는 {pc(wti_n)}보다 나빴다.</p>
<h3>⑤ 백분위 방식 expanding vs rolling 10년 — 차이 미미</h3>
<p class="desc">두 방식은 2020년 이후에만 갈린다. IC 차이가 큰 셋: {", ".join(f"{SHORT[a]} {BLK_KO[b][:2]} {h}일 {n(pm.at[(a, b, h), 'expanding'])}→{n(pm.at[(a, b, h), 'rolling'])}" for (a, b, h) in big.index)}. 판정을 바꾼 칸은 없다 → expanding 유지.</p>
<h3>⑥ 가격 지표 정리 규칙(상관 &gt; 0.9 쌍 정리) — 제외 없음</h3>
<p class="desc">주가지수 2개를 합친 전반부 상관 최고는 {n(cmax, 3)}로 0.9 에 못 미친다 → 후보 없음. 자산별로 보면 KOSPI200 disparity_20 이 후보지만, 빼면 후반부 IC 가 {n(k63w, 3)} → {n(k63o, 3)}로 나빠져 유지한다. 8개 그대로.</p></div>
</div></section>"""


# ---------------------------------------------------------------- 6. 한계
def sec_limits():
    us = L["ust10y_valuation_split"].set_index(["period", "horizon"])
    pre = [us.at[(p_, h), "ic"] for p_ in us.index.get_level_values(0).unique()[:1] for h in H]
    post = [us.at[(p_, h), "ic"] for p_ in us.index.get_level_values(0).unique()[1:] for h in H]
    nmin = int(NOV.xs(252, level="horizon")["n_nonoverlap_full"].min())
    nmax = int(NOV.xs(252, level="horizon")["n_nonoverlap_full"].max())
    h2 = NOV.xs(252, level="horizon")["n_nonoverlap_second_half"]
    items = [
        f"<b>표준오차</b>: NW(lag h−1)는 지속적인 점수에서 표준오차를 약 {n(SR_MED, 1)}배 작게 잡는다. 판정에는 플라시보 p·q 를 썼다.",
        "<b>사후 규칙</b>: 판정 규칙은 결과를 본 뒤 정했다. 대안 규칙 3개에서 모두 남는 칸만 단단하다고 본다(4절).",
        "<b>기계적 스프레드 관계</b>: 국내 회사채(그리고 약하게 미국 HY) 밸류는 점수와 수익이 같은 스프레드에서 나온다. 평균회귀만으로도 IC 가 생긴다.",
        "<b>생존편향</b>: KOSPI200·S&amp;P500 바텀업 지표(Fwd PER·EPS·시장폭)는 현재 구성종목이다. 밸류·펀더멘털 IC 가 과대평가됐을 수 있다.",
        "<b>빈티지 접합</b>: NFCI·기간프리미엄은 최초 공표값을 이어 붙였다. 3개월 차분이 서로 다른 빈티지를 비교한다.",
        f"미국채 10년 밸류는 2019-05 전까지 지표 2개뿐이다. 그 전 IC {n(min(pre))}~{n(max(pre))}, 그 뒤 {n(min(post))}~{n(max(post))}(유의 아님). 강한 신호는 지표 2개 시절의 것이다.",
        f"<b>252일은 표본이 짧다</b>: 겹치지 않게 세면 자산당 {nmin}~{nmax}개, 반기별로는 {int(h2.min())}~{int(h2.max())}개다. 1년 뒤 수익에 대한 결론은 모두 약하다.",
        "<b>수익률 근사</b>: 금리는 −듀레이션×금리변화+캐리(듀레이션 고정)다. 국내 회사채는 스프레드 기준 초과수익(총수익 아님)이고, S&amp;P500 은 배당 미포함이다. COT·EIA 공표 지연(셧다운·공휴일)은 반영하지 않았다.",
        "<b>단일 경로</b>: 2013~2026 한 번의 역사다(저금리 → 2022 급등 → 2025~26 KOSPI 급등). 후반부 결과는 이 국면에 좌우된다.",
    ]
    return f"""<section id="limits" class="pg"><h2>6. 한계 — 이 결과를 읽을 때</h2><div class="cols2"><ul class="plain">{"".join(f"<li>{x}</li>" for x in items)}</ul></div></section>"""


# ---------------------------------------------------------------- 7. 결정
def sec_decisions():
    sd = L["score_distribution"]
    sv = sd[sd.block == "valuation"].set_index("asset_id")
    in_mid = sorted(a for a in ASSETS if 45 <= sv.at[a, "median"] <= 55)
    must(set(in_mid) == {"KOSPI200", "KR_CORP", "UST10Y"}, f"중앙값 45~55 {in_mid}")
    out_mid = ", ".join(f"{SHORT[a]} {sv.at[a, 'median']:.0f}" for a in sv.sort_values("median").index if a not in in_mid)
    th = L["threshold50"]
    cnt = {b: (int((th[th.block == b]["diff"] > 0).sum()), int((th[th.block == b]["t_nw"] <= -1.96).sum())) for b in BLK}
    must(cnt["oversold"] == (17, 3) and cnt["fundamental"] == (21, 3), f"50 분할 {cnt}")
    ge = sv["share_ge50"]
    panel = pd.read_csv(REPO / "data" / "processed" / "panel.csv.gz", parse_dates=["date", "as_of"])
    cac = panel[(panel.asset_id == "USDKRW") & (panel.field == "current_account_12m")].set_index("date")["value"].sort_index()
    d3 = cac.diff(3)
    ca_last, ca_prev_max = d3.iloc[-1], d3[:"2025-12-31"].abs().max()
    p2i = pd.read_csv(REPO / "outputs" / "phase2" / "latest_indicators.csv")
    ca_pct = float(p2i[(p2i.asset_id == "USDKRW") & (p2i.indicator == "current_account_trend")]["percentile"].iloc[0])
    must(abs(ca_last - float(p2i[(p2i.asset_id == "USDKRW") & (p2i.indicator == "current_account_trend")]["raw"].iloc[0])) < 1,
         "경상수지 3개월 차 = Phase 2 원시값")
    must(ca_last > 3 * ca_prev_max, "경상수지 급증")
    rows = [
        ["1", "통화 이중반영 변형<br><code>currency_variant</code>",
         f"KOSPI200 한 자산, 3개 중 최선 고르기. 최대 |t| {n(L['exp_currency_variant_ic'].query('period==\"full\" and block==\"fundamental\"')['t_nw'].abs().max())} — 우연 범위다. <b>경험적 근거로는 고를 수 없다.</b>",
         "판단의 문제다. 선택지: both(현행, 통화 충격·추세 모두 반영) / oversold_only(통화 = 단기 충격) / fundamental_only(통화 = 이익 환경). 근거로 고르려면 먼저 분할 규칙을 정한다(2013~19 에서 고르고 2020~26 에서 현행보다 나쁘지 않을 때 채택). 그 전까지는 both 유지가 변경 최소다."],
        ["2", "국면 임계값 50",
         f"밸류 중앙값이 45~55 인 자산은 {len(in_mid)}개뿐이다(나머지 {out_mid}). 50 분할 수익 차: 밸류 32/40 양수, 과매도 {cnt['oversold'][0]}/40·펀더 {cnt['fundamental'][0]}/40(각 유의 음수 {cnt['oversold'][1]}).",
         f"<b>50 유지.</b> 다른 값은 시험하지 않았다(튜닝). 밸류 치우침(≥50 인 날 S&amp;P {ge['SP500']:.0%}·HY {ge['US_HY']:.0%}·IG {ge['US_IG']:.0%})은 임계값이 아니라 추세 있는 밸류 지표의 정의 문제로 따로 다룬다."],
        ["3", "KOSPI200 이익 가중(결정 C)",
         "동일가중·두 종목 제외가 밸류 IC 가 높다(252일 t 4.49·4.06 vs 2.22).",
         "<b>재검토 권고.</b> 표본 분할로 확인한 뒤 바꾼다. 그 전까지 현행 유지, 민감도는 함께 표시한다."],
        ["4", "역발상 추가분(동시판정·변동성비)",
         "과매도 블록 개선 근거가 없다. 주가지수는 개편 전이 4개 기간 모두 약간 높다(유의 아님).",
         "확정 결정이므로 판단해 주셔야 한다. 근거상으로는 유지(‘효과 미확인’ 표기)와 되돌림 사이에 차이가 없다. 단순함을 원하면 되돌림, 결정 유지를 원하면 표기만 추가한다."],
        ["5", "원화 경상수지 지표 정규화",
         f"12개월 누적 경상수지의 3개월 ‘금액’ 차분이라, 2026 급증(3개월 차 +{ca_last:,.0f}백만달러, 2025년까지 최대 {ca_prev_max:,.0f})에서 백분위가 {ca_pct:.1f} 로 극단이다. 원자료는 ECOS 실데이터로 확인됐다.",
         "<b>정규화 검토 권고</b>(GDP 대비 또는 변화율). 설정 변경이라 이번에는 바꾸지 않았다."],
    ]
    t = table(["#", "결정", "근거", "권고"], rows, cls="askt", num_from=99,
              colgroup='<colgroup><col style="width:22px"><col style="width:150px"><col style="width:38%"><col></colgroup>')
    files = " · ".join(f"{f} {h}" for f, h in MD5.items())
    return f"""<section id="ask" class="pg"><h2>7. 결정해 주실 것</h2>
<p class="sub">1·2 는 NEXT_STEPS 에 예정된 질문이고 3~5 는 이번 백테스트에서 새로 생겼다. 어느 것도 이번 작업에서 설정에 반영하지 않았다.</p>
{t}
<p class="tnote">출처: outputs/phase3/*.csv(경상수지 5번만 data/processed/panel.csv.gz·outputs/phase2/latest_indicators.csv)(브랜치 phase3-backtest, 미커밋; 입력 md5 앞 8자리 — {e(files)}). 테스트 {e(PYTEST)}. 생성 {DATE}, outputs/briefing_phase3/build_briefing.py.</p>
</section>"""


# ---------------------------------------------------------------- 조립
CSS3 = """
.vt td { font-size: 10.6px; padding: 2px 6px; vertical-align: top; line-height: 1.3; }
.vt td.vc .chip { font-size: 10.5px; padding: 0 6px; }
.vt td.vc .vw { display: block; font-size: 9.6px; color: var(--ink-2); margin-top: 1px; }
.vt td.vnone { color: var(--ink-3); }
.vt td.vnone .chip { border-color: var(--rule); color: var(--ink-3); }
.vt td.vgood { background: #e6f4e6; } .vt td.vcrit { background: #fbecea; } .vt td.vwarn { background: #fbf3e2; } .vt td.vmuted { background: #eef3f7; }
.grid3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-top: 8px; }
.grid2 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
.grid3 .panel h3 { margin-top: 0; }
.grid3 ul.plain li, .grid2 .desc { font-size: 10.8px; line-height: 1.45; }
.pt td { font-size: 11px; padding: 2px 7px; font-family: var(--f-mono); }
.pt td:first-child { font-family: var(--f-body); }
.cgrid { display: grid; grid-template-columns: 300px 300px minmax(0, 1fr); gap: 12px; align-items: start; }
.ct { font-size: 10px; color: var(--ink-2); margin-bottom: 1px; }
.evt td, .evt th { font-size: 9.8px; padding: 1px 5px; }
.xt td, .xt th { font-size: 10px; padding: 1px 6px; }
.rt td { font-size: 10.8px; padding: 2px 7px; }
h2.cont { font-size: 18px; }
.vt td.vnone { font-size: 10px; }
.sub.leg { font-size: 10.5px; margin-bottom: 4px; }
.sub.leg .chip { font-size: 10px; padding: 0 6px; }
html[data-print] .vt td { padding: 1.5px 6px; }
.xw td { font-family: var(--f-mono); font-size: 10px; white-space: nowrap; }
.xw td:first-child { font-family: var(--f-body); }
html[data-print] .askt td { font-size: 11.4px; line-height: 1.5; vertical-align: top; padding: 4px 7px; }
html[data-print] #limits .cols2 ul.plain li { font-size: 12px; line-height: 1.55; margin-bottom: 4px; }
"""


def build():
    tpl = TEMPLATE.read_text(encoding="utf-8")
    css = re.search(r"<style>(.*?)</style>", tpl, re.S).group(1)
    old_footer = re.search(r'@bottom-left \{ content: "([^"]+)"', css).group(1)
    css = css.replace(old_footer, "mtscore Phase 3 판단 자료 · 백테스트 2013~2026 · 브랜치 phase3-backtest(미커밋)")
    fonts = re.search(r'<link rel="stylesheet" href="(https://fonts\.googleapis\.com[^"]+)">', tpl).group(1)
    p2 = P2_BUILD.read_text(encoding="utf-8")
    extra = re.search(r'EXTRA_CSS = """(.*?)"""', p2, re.S).group(1)
    body = "".join([masthead(), "<main>", sec_conclusion(), sec_blocks(), sec_regime(), sec_cases(), sec_rules(), sec_experiments(),
                    sec_limits(), sec_decisions(), "</main>"])
    doc = f"""<!doctype html>
<html lang="ko" data-print data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mtscore Phase 3 브리핑</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{fonts}">
<style>{css}{extra}{CSS3}</style>
</head>
<body>
{body}
</body>
</html>
"""
    out = HERE / "briefing_phase3.html"
    out.write_text(doc, encoding="utf-8")
    print("wrote", out, f"{len(doc) / 1e3:.0f} KB")
    return out


EDGE = "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
WIN_TMP = Path("/mnt/c/Users/infomax/AppData/Local/Temp/mtscore_briefing3_pdf")


def winpath(p):
    return subprocess.run(["wslpath", "-w", str(p)], capture_output=True, text=True, check=True).stdout.strip()


def make_pdf(src):
    WIN_TMP.mkdir(parents=True, exist_ok=True)
    s, pdf = WIN_TMP / "briefing_phase3.html", WIN_TMP / "briefing_phase3.pdf"
    shutil.copy(src, s)
    pdf.unlink(missing_ok=True)
    url = "file:///" + winpath(s).replace("\\", "/")
    cmd = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-pdf-header-footer",
           f"--user-data-dir={winpath(WIN_TMP)}\\profile", "--virtual-time-budget=25000",
           "--run-all-compositor-stages-before-draw", "--window-size=1017,900", f"--print-to-pdf={winpath(pdf)}", url]
    t0 = time.time()
    subprocess.run(cmd, capture_output=True, timeout=240)
    if not pdf.exists() or pdf.stat().st_size < 10_000:
        sys.exit(f"PDF 생성 실패: {pdf}")
    dst = HERE / "briefing_phase3.pdf"
    shutil.copy(pdf, dst)
    import pymupdf
    d = pymupdf.open(dst)
    print(f"wrote {dst}  {dst.stat().st_size / 1e6:.2f} MB  {d.page_count} pages  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    h = build()
    if "--no-pdf" not in sys.argv:
        make_pdf(h)
