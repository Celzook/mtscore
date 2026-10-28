"""mtscore Phase 2 판단 자료(브리핑): 커밋 bd4ded2(phase2-data)의 outputs/phase2·config·CLAUDE.md → briefing_phase2.html · .pdf

실행(WSL 셸):
    /home/infomax/Desktop/Infomax/_project/기술적분석/.venv/bin/python outputs/briefing_phase2/build_briefing.py [--no-pdf]

- 입력은 작업 트리가 아니라 `git show bd4ded2:<경로>`로 읽는다(다른 브랜치 작업이 작업 트리를 바꿔도 같은 결과).
- 숫자는 전부 입력 파일에서 읽는다. 사람이 쓴 문장(자산별 이유·판단할 점·결정 요지)에 들어가는 숫자도 f-string 이고,
  문장이 가리키는 지표가 실제 기여 상위인지, 결정 요지의 근거 문구가 CLAUDE.md 해당 절에 있는지 assert 로 대조한다.
- 양식은 ../기술적분석/40_report/template.html 의 <style>(파일은 수정하지 않음) + 70_report_v3/build_v3.py 와 같은 덮어쓰기.
- PDF 는 Windows Edge 헤드리스 print-to-pdf(A4 가로, 창 폭 1017px). 임시 폴더는 따로 쓴다.
"""
import html
import io
import json
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
COMMIT = "bd4ded2"
TEMPLATE = REPO.parent / "기술적분석" / "40_report" / "template.html"
DATE = "2026-10-28"


def G(path):
    return subprocess.run(["git", "-C", str(REPO), "show", f"{COMMIT}:{path}"], capture_output=True, check=True).stdout


def T(path):
    return G(path).decode("utf-8")


P2 = "outputs/phase2/"
SC = pd.read_csv(io.BytesIO(G(P2 + "latest_scores.csv"))).set_index("asset_id")
IND = pd.read_csv(io.BytesIO(G(P2 + "latest_indicators.csv")))
COV = pd.read_csv(io.BytesIO(G(P2 + "coverage.csv")))
CC = pd.read_csv(io.BytesIO(G(P2 + "crosscheck.csv")))
RJ = json.loads(T(P2 + "result_2026-10-27.json"))
HIST = pd.read_csv(io.BytesIO(G(P2 + "score_history.csv.gz")), compression="gzip", parse_dates=["date"])
BI = json.loads(T(P2 + "build_info.json"))
SI = json.loads(T(P2 + "score_info.json"))
REP = T(P2 + "phase2_report.md")
COVMD = T(P2 + "coverage.md")
CL = T("CLAUDE.md")
SCFG = yaml.safe_load(T("config/scoring.yaml"))
UNIV_TXT = T("config/universe.yaml")
UNIV = {a["asset_id"]: a for a in yaml.safe_load(UNIV_TXT)}
ASSETS = list(SC.index)
AS_OF = RJ["as_of"]
HEAD_SUBJ = subprocess.run(["git", "-C", str(REPO), "log", "-1", "--format=%h %s", COMMIT], capture_output=True, text=True,
                           check=True).stdout.strip()

# ---------------------------------------------------------------- 입력 대조(어긋나면 중단)
assert AS_OF == "2026-10-27", AS_OF
assert len(ASSETS) == 10 and len(RJ["assets"]) == 10
assert (SC["date"] == AS_OF).all()
assert HIST["date"].max() == pd.Timestamp(AS_OF)
N_CC, N_PASS = len(CC), int(CC["pass"].sum())
assert (N_CC, N_PASS) == (51, 47), (N_CC, N_PASS)
assert f"{N_PASS}/{N_CC} 통과" in REP
CONC = BI["kospi200_concentration"]
assert (round(CONC["cap_share"], 4), round(CONC["earn_share"], 4)) == (0.5454, 0.7535)
for a in RJ["assets"]:  # JSON 기여도 = latest_indicators.csv, 블록 점수 = latest_scores.csv
    sub = IND[IND.asset_id == a["asset_id"]]
    assert len(sub) == len(a["contributions"])
    for blk, v in a["blocks"].items():
        assert abs(v - SC.at[a["asset_id"], f"score_{blk}"]) < 1e-3
        assert abs(sub[sub.block == blk].contribution.sum() - v) < 1e-3, (a["asset_id"], blk)
RJA = {a["asset_id"]: a for a in RJ["assets"]}

BLK = ["oversold", "valuation", "fundamental"]
BLK_KO = {"oversold": "과매도", "valuation": "밸류에이션", "fundamental": "펀더멘털"}
BLK_COL = {"oversold": "var(--s1)", "valuation": "var(--s2)", "fundamental": "var(--s3)"}
SUB_KO = {"price": "가격", "confluence": "동시판정", "breadth": "시장폭", "vol_sentiment": "변동성·심리", "flows": "수급",
          "multiples": "배수", "earnings": "이익", "macro": "거시", "volatility": "변동성", "positioning": "포지셔닝",
          "level": "수준", "reer": "환율 수준", "real_price": "실질가격", "real_rate": "실질금리", "curve": "커브",
          "inventory": "재고", "spread": "스프레드", "cycle": "사이클", "defaults": "부도"}
CLS = {a: UNIV[a]["asset_class"] for a in ASSETS}
NAME = {a: UNIV[a]["name"] for a in ASSETS}
SHORT = {"KOSPI200": "KOSPI200", "SP500": "S&P500", "KTB10Y": "국고 10년", "UST10Y": "미국채 10년", "USDKRW": "원화(USDKRW)",
         "GOLD": "금", "WTI": "WTI", "US_HY": "미국 HY", "US_IG": "미국 IG", "KR_CORP": "국내 회사채"}


# ---------------------------------------------------------------- 형식 도우미
def e(s):
    return html.escape(str(s), quote=False)


def fix0(s):
    return s[1:] if re.fullmatch(r"-0(\.0+)?", s) else s


def n(x, d=1):
    return "–" if x is None or pd.isna(x) else fix0(f"{x:.{d}f}").replace("-", "−")


def sg(x, d=1):
    s = n(x, d)
    return s if s.startswith("−") or s in ("0", "–") or float(s.replace("−", "-")) == 0 else "+" + s


def pct(x, d=1):  # 비율 → % (0.7535 → 75.4%: 이진 부동소수 반올림 보정)
    return n(x * 100 + 1e-9, d) + "%"


def spct(x, d=1):
    return sg(x * 100, d) + "%"


def R(a, ind, col="raw"):
    r = IND[(IND.asset_id == a) & (IND.indicator == ind)]
    assert len(r) == 1, (a, ind)
    return float(r.iloc[0][col])


def S(a, blk):
    return float(SC.at[a, f"score_{blk}"])


def top(a, blk, k):
    sub = IND[(IND.asset_id == a) & (IND.block == blk)].sort_values("contribution", ascending=False)
    return list(sub.indicator[:k])


def short_(a, blk, k):
    """가장 크게 깎은 지표: 비중 × (100 − 점수)."""
    sub = IND[(IND.asset_id == a) & (IND.block == blk)].copy()
    sub["gap"] = sub.weight_in_block * (100 - sub.score)
    return list(sub.sort_values("gap", ascending=False).indicator[:k])


def must(cond, msg):
    if not cond:
        sys.exit(f"문장 근거 대조 실패: {msg}")


def table(head, rows, cls="", num_from=1, colgroup=""):
    h = "<tr>" + "".join(f'<th class="n">{c}</th>' if i >= num_from else f"<th>{c}</th>" for i, c in enumerate(head)) + "</tr>"
    body = []
    for r in rows:
        rc = ""
        if isinstance(r, tuple):
            rc, r = r
        tds = "".join(c if str(c).startswith("<td") else (f'<td class="n">{c}</td>' if i >= num_from else f"<td>{c}</td>")
                      for i, c in enumerate(r))
        body.append(f'<tr class="{rc}">{tds}</tr>' if rc else f"<tr>{tds}</tr>")
    return f'<div class="tablewrap"><table class="{cls}">{colgroup}<thead>{h}</thead><tbody>{"".join(body)}</tbody></table></div>'


def band_cls(b):
    return {"극단": "hi2", "경계": "hi1", "반대경계": "lo1", "반대극단": "lo2"}.get(b, "mid")


def score_cell(a, blk):
    v, b = S(a, blk), SC.at[a, f"band_{blk}"]
    return f'<td class="n sc {band_cls(b)}"><b>{n(v)}</b><span class="bd">{e(b)}</span></td>'


def judge(items, title="판단할 점"):
    li = "".join(f"<li>{t}</li>" for t in items)
    return f'<div class="judge"><div class="jt">{title}</div><ul>{li}</ul></div>'


def md_tables(text, heading):
    lines = text.splitlines()
    i0 = next(i for i, l in enumerate(lines) if l.startswith("#") and l.lstrip("#").strip().startswith(heading))
    lvl = len(lines[i0]) - len(lines[i0].lstrip("#"))
    out, cur = [], []
    for l in lines[i0 + 1:]:
        if l.startswith("#") and len(l) - len(l.lstrip("#")) <= lvl:
            break
        if l.startswith("|"):
            cur.append([c.strip() for c in l.strip().strip("|").split("|")])
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [pd.DataFrame(t[2:], columns=t[0]) for t in out]


def rx(pat, text=REP):
    m = re.search(pat, text)
    if not m:
        sys.exit(f"보고서에서 찾지 못함: {pat}")
    return m


def code(s):
    """md 의 `x` → <code>x</code>, **x** → <b>x</b>."""
    s = e(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)


# ---------------------------------------------------------------- 지표 사전(자산군별: 같은 이름이 가격·금리·스프레드에서 뜻이 다르다)
# (이름, 원시값 형식, 점수가 높아지는 쪽) — 형식: pct=비율→%, pctv=이미 %, pp=%p, x=배, n1/n2/n3=소수, musd=백만달러
PX = {
    "disparity_20": ("20일 이동평균 대비 괴리", "spct", "이평보다 많이 내려갈수록 ↑"),
    "disparity_60": ("60일 이동평균 대비 괴리", "spct", "이평보다 많이 내려갈수록 ↑"),
    "disparity_200": ("200일 이동평균 대비 괴리", "spct", "이평보다 많이 내려갈수록 ↑"),
    "drawdown_52w_over_rv": ("52주 고점 대비 낙폭 ÷ 변동성", "n2", "낙폭이 클수록 ↑"),
    "return_z_5": ("5일 수익률 z", "n2", "급락할수록 ↑"),
    "return_z_20": ("20일 수익률 z", "n2", "급락할수록 ↑"),
    "rsi_2": ("RSI(2일)", "n1", "낮을수록 ↑"),
    "bb_pctb_20": ("볼린저 %b(20일)", "n2", "밴드 하단에 가까울수록 ↑"),
    "rsi_14": ("RSI(14일)", "n1", "낮을수록 ↑"),
    "rv_ratio_20": ("실현변동성 ÷ 1년 평균", "x", "평소보다 출렁일수록 ↑(가정)"),
}
DICT = {
    "equity_index": {**PX,
        "pct_above_ma20": ("20일선 위 종목 비중", "pctv", "적을수록 ↑"),
        "pct_above_ma200": ("200일선 위 종목 비중", "pctv", "적을수록 ↑"),
        "pct_new_low_52w": ("52주 신저가 종목 비중", "pctv", "많을수록 ↑"),
        "adr_20": ("등락비율(20일, 상승÷하락)", "n2", "하락 종목이 많을수록 ↑"),
        "vol_index_level": ("변동성지수 수준", "n1", "높을수록(공포) ↑"),
        "vol_index_over_rv": ("내재변동성 ÷ 실현변동성", "x", "높을수록 ↑"),
        "vol_term_inversion": ("VIX ÷ VIX 3개월", "n2", "1을 넘어 역전될수록 ↑"),
        "home_ccy_shock_20": ("원/달러 20일 변화", "spct", "원화가 급약세일수록 ↑"),
        "pbr_trailing": ("PBR(바텀업)", "n2", "낮을수록 ↑"),
        "per_fwd_12m": ("12개월 선행 PER", "n2", "낮을수록 ↑"),
        "dividend_yield": ("배당수익률", "pctv", "높을수록 ↑"),
        "erp": ("주식위험프리미엄(이익수익률 − 10년물)", "pp", "높을수록 ↑"),
        "revision_breadth": ("선행 EPS 상향 종목 시총 비중", "pct", "많을수록 ↑"),
        "fwd_eps_chg_1m": ("선행 EPS 1개월 변화", "spct", "오를수록 ↑"),
        "fwd_eps_chg_3m": ("선행 EPS 3개월 변화", "spct", "오를수록 ↑"),
        "revision_momentum": ("선행 EPS 변화율의 가속(1개월)", "sppf", "가속할수록 ↑"),
        "home_ccy_trend_3m": ("원/달러 3개월 변화", "spct", "원화 약세일수록 ↑(수출 이익)"),
    },
    "rates": {
        "yield_chg_z_20": ("금리 20일 변화 z", "n2", "금리가 급등할수록 ↑"),
        "yield_chg_z_60": ("금리 60일 변화 z", "n2", "금리가 급등할수록 ↑"),
        "yield_disparity_60": ("금리 − 60일 평균", "spp", "금리가 평균보다 높을수록 ↑"),
        "bb_pctb_20": ("금리 볼린저 %b(20일)", "n2", "금리가 밴드 상단일수록 ↑"),
        "rsi_14": ("금리 RSI(14일)", "n1", "금리가 과열될수록 ↑(가정)"),
        "level_rv_ratio_20": ("금리 변동성 ÷ 1년 평균", "x", "평소보다 출렁일수록 ↑(가정)"),
        "futures_net_spec": ("투기적 순포지션 z(CFTC)", "n2", "순매도 쏠림일수록 ↑"),
        "real_yield": ("실질금리", "pctv", "높을수록 ↑"),
        "spread_to_policy": ("10년물 − 기준금리", "pp", "벌어질수록 ↑"),
        "term_premium": ("기간프리미엄(Kim-Wright)", "pp", "높을수록 ↑"),
        "inflation_momentum": ("CPI 전년비 3개월 변화", "spp", "물가가 둔화될수록 ↑"),
        "policy_direction": ("기준금리 6개월 변화", "spp", "인하할수록 ↑"),
        "financial_conditions": ("NFCI 3개월 변화", "sn3", "금융여건이 긴축될수록 ↑"),
    },
    "fx": {
        "disparity_60": ("원화 60일 이동평균 대비 괴리", "spct", "원화가 많이 약해질수록 ↑"),
        "return_z_20": ("원화 20일 수익률 z", "n2", "원화가 급락할수록 ↑"),
        "bb_pctb_20": ("원화 볼린저 %b(20일)", "n2", "밴드 하단일수록 ↑"),
        "rsi_14": ("원화 RSI(14일)", "n1", "낮을수록 ↑"),
        "rv_ratio_20": ("원화 변동성 ÷ 1년 평균", "x", "평소보다 출렁일수록 ↑(가정)"),
        "reer_level": ("실질실효환율(REER, BIS)", "n1", "낮을수록(원화 저평가) ↑"),
        "rate_diff_chg_3m": ("한−미 10년 금리차 3개월 변화", "spp", "한국 금리 상대 상승일수록 ↑"),
        "current_account_trend": ("경상수지 12개월 합의 3개월 변화", "musd", "개선될수록 ↑"),
    },
    "commodity": {**PX,
        "spec_positioning": ("투기적 순포지션 z(CFTC)", "n2", "순매도 쏠림일수록 ↑"),
        "real_price_level_spot": ("실질가격(근월물 ÷ 미국 CPI)", "n3", "쌀수록 ↑"),
        "real_rate_change": ("미국 실질금리 3개월 변화", "spp", "실질금리가 내릴수록 ↑"),
        "backwardation_spot": ("근월 ÷ 차월 − 1(백워데이션)", "spct", "근월이 비쌀수록 ↑"),
        "inventory_change": ("원유 재고 1개월 변화율", "spct", "재고가 줄수록 ↑"),
    },
    "credit": {
        "spread_chg_z_20": ("스프레드 20일 변화 z", "n2", "급확대일수록 ↑"),
        "bb_pctb_20": ("스프레드 볼린저 %b(20일)", "n2", "밴드 상단일수록 ↑"),
        "rsi_14": ("스프레드 RSI(14일)", "n1", "과열될수록 ↑(가정)"),
        "level_rv_ratio_20": ("스프레드 변동성 ÷ 1년 평균", "x", "평소보다 출렁일수록 ↑(가정)"),
        "spread_level": ("스프레드 수준", "pp", "넓을수록 ↑"),
        "equity_eps_momentum": ("주가지수 선행 EPS 3개월 변화", "spct", "늘수록 ↑"),
        "quality_gap_trend": ("저등급 − 고등급 스프레드 차 3개월 변화", "spp", "격차가 줄수록 ↑"),
    },
}
NA_KO = {  # 데이터 없음 지표의 이름(사전 밖)
    "vol_term_inversion": "VKOSPI 기간구조(3개월물 대비)", "put_call": "Put/Call 비율", "foreign_net_buy_intensity": "외국인 순매수 강도",
    "inst_net_buy_intensity": "기관 순매수 강도", "margin_debt_change": "신용잔고 변화", "forced_liquidation": "반대매매",
    "revision_ratio": "이익수정비율(상향−하향 건수)", "macro_surprise": "경기·물가 서프라이즈", "terms_of_trade_trend": "교역조건 추세",
    "default_rate": "부도율", "default_trend": "부도율 추세",
    "real_price_level": "실질가격(연속물판)", "backwardation": "백워데이션(연속물판)",
}


def label(a, ind):
    lab = DICT[CLS[a]][ind][0]
    if ind == "vol_index_level":
        lab = ("VKOSPI" if a == "KOSPI200" else "VIX") + " 수준"
    if ind == "equity_eps_momentum":
        lab += " (" + ("KOSPI200" if a == "KR_CORP" else "S&P500") + ")"
    if ind == "erp":
        lab = "주식위험프리미엄(이익수익률 − " + ("국고 10년" if a == "KOSPI200" else "미국채 10년") + ")"
    return lab


def fmt_raw(a, ind, x):
    f = DICT[CLS[a]][ind][1]
    return {"pct": lambda: pct(x), "spct": lambda: spct(x), "pctv": lambda: n(x, 2) + "%", "pp": lambda: n(x, 2) + "%p",
            "spp": lambda: sg(x, 2) + "%p", "sppf": lambda: sg(x * 100, 2) + "%p", "x": lambda: n(x, 2) + "배",
            "n1": lambda: n(x, 1), "n2": lambda: n(x, 2), "n3": lambda: n(x, 3), "sn3": lambda: sg(x, 3),
            "musd": lambda: musd(x) + "백만$"}[f]()


def musd(x):
    s = f"{x:,.0f}"
    return ("+" if x > 0 else "") + s.replace("-", "−")


# ---------------------------------------------------------------- 결측 사유(coverage.md 의 한글 사유)
def cov_reasons():
    out, asset = {}, None
    for l in COVMD.splitlines():
        if l.startswith("## "):
            asset = l[3:].strip()
        elif l.startswith("|") and asset and "| — |" in l:
            c = [x.strip() for x in l.strip().strip("|").split("|")]
            out[(asset, c[2])] = c[5]
    return out


COVR = cov_reasons()


def na_rows(a):
    """(데이터 없음 [(지표, 사유)], 설정 제외 [지표])."""
    sub = COV[(COV.asset_id == a) & (~COV.used)]
    miss, excl = [], []
    for _, r in sub.iterrows():
        if str(r.reason).startswith("override_exclude"):
            excl.append(r.indicator)
        else:
            txt = COVR[(a, r.indicator)]
            parts = [p.strip() for p in txt.split(" — ")]
            why = parts[1] if len(parts) > 1 else parts[0]
            if why.startswith("위와 같음"):
                why = "외국인 순매수와 같은 사유(KRX 로그인 필요)"
            miss.append((r.indicator, why))
    return miss, excl


SHORT_WHY = {  # 패널용 짧은 사유: (핵심 문구가 원 사유에 있어야 함, 짧은 문장)
    "vol_term_inversion": ("3개월물", "VKOSPI 3개월물 소스 없음"),
    "put_call": ("미확인", "소스 미확인"),
    "foreign_net_buy_intensity": ("KRX_ID/KRX_PW", "KRX 로그인 계정 필요(없음). Open API·naver로는 불가"),
    "inst_net_buy_intensity": ("KRX 로그인", "외국인과 같은 사유(KRX 로그인 필요)"),
    "margin_debt_change": ("KOFIA", "KOFIA 신용잔고 소스 미확인"),
    "forced_liquidation": ("KOFIA", "KOFIA 소스 미확인"),
    "revision_ratio": ("revision_breadth", "수정 건수 필드 실패 → ‘EPS 상향 종목 비중’이 대신함"),
    "macro_surprise": ("미확인", "소스 미확인"),
    "terms_of_trade_trend": ("403Y", "ECOS 항목코드 미확인"),
    "default_trend": ("미확인", "부도율 소스 미확인"),
}


def short_why(ind, why):
    k, txt = SHORT_WHY[ind]
    assert k in why, (ind, why)
    return txt


def ko_name(a, ind):
    if ind in NA_KO:
        return NA_KO[ind]
    for d in [DICT[CLS[a]]] + list(DICT.values()):
        if ind in d:
            return d[ind][0]
    return ind


EXCL_WHY = {  # (universe.yaml 주석 원문 — 존재 확인, 표시용 요약)
    "SP500": ("PBR·배당 불가(R2), 자국통화 지표 해당 없음", "PBR·배당 소스 불가, 원화 지표는 해당 없음"),
    "KTB10Y": ("KTB 포지셔닝·한국 기간프리미엄 미확인, NFCI 는 미국 지표", "한국 선물 포지셔닝·기간프리미엄 소스 미확인, NFCI는 미국 지표"),
    "USDKRW": ("CFTC KRW 계약 검색 0건", "CFTC에 원화 계약 없음"),
    "GOLD": ("재고는 WTI 전용, 금 커브는 금리 캐리만 반영(사용자 결정 2026-10-26)", "재고는 WTI 전용, 금 커브는 금리 캐리뿐(2026-10-26 결정); 실질가격은 근월물판으로 대체"),
    "WTI": ("close 는 백어저스트 연속물이라 수준(실질가격)과 커브(c1/c2) 비교에는 맞지 않는다", "연속물 대신 원 근월물판으로 대체(수준·커브 비교용)"),
}
for k, (v, _) in EXCL_WHY.items():
    assert v in UNIV_TXT, (k, v)


# ---------------------------------------------------------------- 보고서에서 읽는 값(개정 절 우선)
REV = md_tables(REP, "개정")[0].set_index("결정")
C_ROW = REV.loc[[i for i in REV.index if i.startswith("C.")][0], "결과"]
m = rx(r"fwd_per 시총 ([\d.]+) / 동일가중 ([\d.]+) / 두 종목 제외 ([\d.]+)\. eps_up_share ([\d.]+) / ([\d.]+) / ([\d.]+)", C_ROW)
PER_CW, PER_EW, PER_EX2, UP_CW, UP_EW, UP_EX2 = m.groups()
assert abs(float(PER_CW) - R("KOSPI200", "per_fwd_12m")) < 0.01
m = rx(r"연말 범위 \*\*([\d.]+)\((\d{4})\)~([\d.]+)\((\d{4})\)\*\*")
PER_LO, PER_LO_Y, PER_HI, PER_HI_Y = m.groups()
m = rx(r"삼성전자\(10-27 NTM EPS ([\d,]+)원, 주가 ([\d,]+)원\)·SK하이닉스\(([\d,]+)원, ([\d,]+)원\)")
SS_EPS, SS_PX, HX_EPS, HX_PX = [float(x.replace(",", "")) for x in m.groups()]
m = rx(r"PIT 재현 (\d+)건 최대 차 ([\de.\-]+)")
PIT_N, PIT_D = m.groups()
m = rx(r"테스트 \*\*(\d+) passed")
N_TEST = m.group(1)
m = rx(r"KRX 코스피200 시총\(유동주식 기준 아님, 지수 시총\) 대비 \+([\d.]+)%")
MCAP_GAP = m.group(1)
assert "2025-10분은 공표되지 않아 결측" in REP
m = rx(r"2010-01 에 EPS 가 있는 종목 (\d+)개, 삼성전자 EPS 는 (\d{4}-\d{2}) 부터")
EPS2010_N, SS_EPS_FROM = m.groups()
m = rx(r"패널 \*\*([\d,]+)행\*\*")
PANEL = m.group(1)
assert PANEL.replace(",", "") == str(BI["panel_rows"])

COV_FIRST = COV.set_index(["asset_id", "indicator"]).first_score_date
FMAP = T(P2 + "field_map.md")
REER_LAST = rx(r"\| USDKRW \| reer \| fred:RBKRBIS \|[^|]*\| \d+ \| [\d-]+~(\d{4}-\d{2})-\d{2} \|", FMAP).group(1)


# ---------------------------------------------------------------- SVG: 블록 점수 이력(0~100 고정 축)
def svg_hist(a, w=400, h=96):
    pl, pr, pt, pb = 28, 66, 8, 20
    t1 = pd.Timestamp(AS_OF)
    t0 = t1 - pd.DateOffset(years=3)
    d = HIST[(HIST.asset_id == a) & (HIST.date >= t0)].set_index("date")[BLK]
    wk = d.resample("W-FRI").last()
    wk.loc[d.index[-1]] = d.iloc[-1]  # 마지막 점 = 기준일 값
    wk = wk[~wk.index.duplicated(keep="last")].sort_index()
    wk = wk[wk.index <= t1]
    X = lambda t: pl + (t - t0).days / (t1 - t0).days * (w - pl - pr)
    Y = lambda v: pt + (100 - v) / 100 * (h - pt - pb)
    g = []
    for v in (10, 25, 50, 75, 90):
        st = "stroke:var(--muted-line);stroke-dasharray:3 3" if v == 50 else "stroke:var(--rule-2)"
        g.append(f'<line x1="{pl}" x2="{w - pr}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" style="{st}"/>')
    for v in (0, 25, 50, 75, 100):
        g.append(f'<text x="{pl - 5}" y="{Y(v) + 3.5:.1f}" text-anchor="end" class="ax">{v}</text>')
    g.append(f'<line x1="{pl}" x2="{w - pr}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" style="stroke:var(--ink-3)"/>')
    for yr in range(t0.year + 1, t1.year + 1):
        t = pd.Timestamp(f"{yr}-01-01")
        g.append(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{pt}" y2="{h - pb}" style="stroke:var(--rule-2)"/>'
                 f'<text x="{X(t):.1f}" y="{h - pb + 13}" text-anchor="middle" class="ax">{yr}</text>')
    ends = []
    for b in BLK:
        s = wk[b]
        seg, segs = [], []
        for t, v in s.items():
            if pd.isna(v):
                if seg:
                    segs.append(seg)
                seg = []
            else:
                seg.append(f"{X(t):.1f},{Y(v):.1f}")
        if seg:
            segs.append(seg)
        for sgm in segs:
            g.append(f'<polyline points="{" ".join(sgm)}" style="fill:none;stroke:{BLK_COL[b]};stroke-width:1.4;stroke-linejoin:round"/>')
        last = S(a, b)
        ends.append([Y(last), {"oversold": "과매도", "valuation": "밸류", "fundamental": "펀더"}[b], last, BLK_COL[b]])
    ends.sort()
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + 12)
    for y, lab, v, col in ends:
        g.append(f'<circle cx="{w - pr + 5}" cy="{y - 3.5:.1f}" r="3" style="fill:{col}"/>'
                 f'<text x="{w - pr + 11}" y="{y:.1f}" class="lb">{lab} {v:.0f}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{e(a)} 블록 점수 3년 이력" class="svgc">'
            + "".join(g) + "</svg>")


# ---------------------------------------------------------------- 자산별 이유 문장(한 문장) + 근거 대조
def why():
    W = {}
    a = "KOSPI200"
    must(set(top(a, "oversold", 4)) >= {"bb_pctb_20", "pct_above_ma200", "pct_above_ma20"}, a)
    must(top(a, "valuation", 2) == ["per_fwd_12m", "erp"] or set(top(a, "valuation", 2)) == {"per_fwd_12m", "erp"}, a)
    must(short_(a, "fundamental", 1) == ["home_ccy_trend_3m"], a)
    W[a] = (f"20일선·200일선 위 종목이 {n(R(a, 'pct_above_ma20'), 0)}%·{n(R(a, 'pct_above_ma200'), 0)}%로 과거 최저권이고 "
            f"볼린저 하단·RSI(14)가 동시에 과매도이며 VKOSPI {n(R(a, 'vol_index_level'), 1)}도 높아 과매도가 높고, "
            f"밸류는 선행 PER {n(R(a, 'per_fwd_12m'), 1)}배(두 종목 착시, 4절)가 끌어올렸으며, "
            f"펀더멘털은 선행 EPS 3개월 {spct(R(a, 'fwd_eps_chg_3m'))} 상향에도 원화 강세(원/달러 3개월 {spct(R(a, 'home_ccy_trend_3m'))})가 절반 비중으로 깎았다.")
    a = "SP500"
    must(top(a, "oversold", 1) == ["rsi_14"] and "vol_index_over_rv" in top(a, "oversold", 2), a)
    must(short_(a, "valuation", 2) == ["erp", "per_fwd_12m"], a)
    must(set(top(a, "fundamental", 3)) == {"fwd_eps_chg_1m", "fwd_eps_chg_3m", "revision_momentum"}, a)
    W[a] = (f"RSI(14) {n(R(a, 'rsi_14'), 0)}·VIX/실현변동성 {n(R(a, 'vol_index_over_rv'), 2)}배로 약간 눌린 정도라 과매도는 중간 위, "
            f"선행 PER {n(R(a, 'per_fwd_12m'), 1)}배에 ERP가 {n(R(a, 'erp'), 2)}%p(역사 하위 {n(R(a, 'erp', 'percentile'), 0)}%)로 얇아 밸류는 낮고, "
            f"선행 EPS가 1개월 {spct(R(a, 'fwd_eps_chg_1m'))}·3개월 {spct(R(a, 'fwd_eps_chg_3m'))} 올라 펀더멘털이 높다.")
    a = "KTB10Y"
    must(set(short_(a, "oversold", 3)) >= {"rsi_14"} and R(a, "yield_chg_z_20", "score") < 5, a)
    must(set(top(a, "valuation", 2)) == {"spread_to_policy", "real_yield"}, a)
    must(short_(a, "fundamental", 1) == ["policy_direction"], a)
    W[a] = (f"금리가 20일·60일 동안 이례적으로 빨리 내려(변화 z {n(R(a, 'yield_chg_z_20'), 1)}·{n(R(a, 'yield_chg_z_60'), 1)}, 금리 RSI {n(R(a, 'rsi_14'), 0)}) "
            f"채권이 이미 많이 오른 상태라 과매도가 낮고, 10년물−기준금리 {n(R(a, 'spread_to_policy'), 2)}%p·실질금리 {n(R(a, 'real_yield'), 2)}%가 보통 이상이라 밸류는 중간 위, "
            f"기준금리 6개월 {sg(R(a, 'policy_direction'), 2)}%p 상승이 펀더멘털을 깎았다.")
    a = "UST10Y"
    must(top(a, "oversold", 2) == ["level_rv_ratio_20", "futures_net_spec"], a)
    must(set(top(a, "valuation", 2)) == {"real_yield", "term_premium"}, a)
    must(top(a, "fundamental", 1) == ["financial_conditions"], a)
    must(min(R(a, "real_yield", "percentile"), R(a, "term_premium", "percentile")) > 98, a)
    W[a] = (f"금리 변동성이 1년 평균의 {n(R(a, 'level_rv_ratio_20'), 2)}배이고 투기 순포지션이 매도 쪽(z {n(R(a, 'futures_net_spec'), 2)})이라 과매도가 중간 위, "
            f"실질금리 {n(R(a, 'real_yield'), 2)}%·기간프리미엄 {n(R(a, 'term_premium'), 2)}%p가 자기 역사 상위 2% 안이라 밸류가 높고, "
            f"펀더멘털은 금융여건 긴축(가점)을 물가 재가속(CPI 전년비 3개월 {sg(R(a, 'inflation_momentum'), 2)}%p)과 기준금리 상승이 상쇄해 50 아래다.")
    a = "USDKRW"
    must(R(a, "rsi_14", "score") < 10 and R(a, "disparity_60", "score") < 15, a)
    must(R(a, "current_account_trend", "percentile") > 99 and R(a, "rate_diff_chg_3m") < 0, a)
    must(top(a, "fundamental", 1) == ["current_account_trend"] and short_(a, "fundamental", 1) == ["rate_diff_chg_3m"], a)
    W[a] = (f"원화가 이미 강해져(원화 RSI {n(R(a, 'rsi_14'), 0)}, 60일선보다 {spct(R(a, 'disparity_60'))}) 원화 과매도는 아니지만, "
            f"실질실효환율 {n(R(a, 'reer_level'), 1)}이 역사 하위 {n(R(a, 'reer_level', 'percentile'), 0)}%라 원화가 싸 보이고(밸류 극단), "
            f"펀더멘털은 경상수지 개선(상위 1% 안)과 한−미 금리차 축소(3개월 {sg(R(a, 'rate_diff_chg_3m'), 2)}%p)가 반반으로 상쇄했다.")
    a = "GOLD"
    must(top(a, "oversold", 1) == ["bb_pctb_20"] and short_(a, "oversold", 1) == ["rv_ratio_20"], a)
    W[a] = (f"60일선 대비 {spct(R(a, 'disparity_60'))} 하락에 볼린저 하단·RSI가 동시에 과매도라 과매도는 중간 위지만 변동성은 오히려 낮고(1년 평균의 {n(R(a, 'rv_ratio_20'), 2)}배), "
            f"실질가격(근월물÷CPI)이 역사 상위 {n(100 - R(a, 'real_price_level_spot', 'percentile'), 0)}%로 비싸 밸류가 극단적으로 낮으며, "
            f"미국 실질금리 3개월 {sg(R(a, 'real_rate_change'), 2)}%p 상승이 펀더멘털을 낮췄다.")
    a = "WTI"
    must(top(a, "oversold", 1) == ["spec_positioning"] and R(a, "disparity_60", "score") < 10, a)
    must(set(top(a, "fundamental", 2)) == {"backwardation_spot", "inventory_change"}, a)
    W[a] = (f"가격이 60일선보다 {spct(R(a, 'disparity_60'))} 높고 RSI {n(R(a, 'rsi_14'), 0)}이라 과매도가 아니며(투기 순포지션만 매도 쪽 z {n(R(a, 'spec_positioning'), 2)}), "
            f"실질가격이 자기 역사 중간 위(백분위 {n(R(a, 'real_price_level_spot', 'percentile'), 0)})라 밸류도 낮고, "
            f"반대로 근월물이 차월물보다 {pct(R(a, 'backwardation_spot'))} 비싼 백워데이션과 재고 감소(1개월 {spct(R(a, 'inventory_change'))})로 펀더멘털은 강하다.")
    for a in ("US_HY", "US_IG"):
        must(top(a, "oversold", 1) == ["level_rv_ratio_20"] and top(a, "fundamental", 1) == ["equity_eps_momentum"], a)
        must(short_(a, "fundamental", 1) == ["quality_gap_trend"], a)
    a = "US_HY"
    W[a] = (f"스프레드 변동성이 1년 평균의 {n(R(a, 'level_rv_ratio_20'), 2)}배이고 20일 스프레드 확대(z {sg(R(a, 'spread_chg_z_20'), 2)})까지 겹쳐 과매도가 높지만, "
            f"스프레드 {n(R(a, 'spread_level'), 2)}%p는 역사 하위 {n(R(a, 'spread_level', 'percentile'), 0)}%로 얇아 밸류가 낮고, "
            f"S&P500 선행 EPS 3개월 {spct(R(a, 'equity_eps_momentum'))} 증가가 등급 간 격차 확대({sg(R(a, 'quality_gap_trend'), 2)}%p)를 이겨 펀더멘털은 중간 위다.")
    a = "US_IG"
    W[a] = (f"스프레드 변동성 {n(R(a, 'level_rv_ratio_20'), 2)}배와 스프레드 RSI {n(R(a, 'rsi_14'), 0)}로 과매도가 중간 위, "
            f"스프레드 {n(R(a, 'spread_level'), 2)}%p가 역사 하위 {n(R(a, 'spread_level', 'percentile'), 0)}%라 밸류는 낮고, "
            f"펀더멘털은 HY와 같은 두 지표(S&P500 이익 증가 vs 등급 간 격차 확대)로 {n(S(a, 'fundamental'))}이다.")
    a = "KR_CORP"
    must(top(a, "oversold", 1) == ["level_rv_ratio_20"] and top(a, "fundamental", 1) == ["equity_eps_momentum"], a)
    must(all(50 <= S(a, b) < 75 for b in BLK), a)
    W[a] = (f"세 점수가 모두 50을 조금 넘어(최고 {n(max(S(a, b) for b in BLK))}) ‘최우선 매수’로 분류됐을 뿐 극단값은 없고, "
            f"스프레드 변동성 {n(R(a, 'level_rv_ratio_20'), 2)}배가 과매도를, 스프레드 {n(R(a, 'spread_level'), 2)}%p(백분위 {n(R(a, 'spread_level', 'percentile'), 0)})가 밸류를, "
            f"KOSPI200 선행 EPS 3개월 {spct(R(a, 'equity_eps_momentum'))}가 펀더멘털을 받쳤다.")
    assert set(W) == set(ASSETS)
    return W


WHY = why()


# ---------------------------------------------------------------- 머리 + 1. 한 장 요약
def masthead():
    return f"""
<header class="masthead bhead">
  <div class="eyebrow">mtscore · Phase 2 decision briefing · as of {AS_OF} · commit {COMMIT}</div>
  <h1>10개 자산 타이밍 점수 — 지금 어디에 있고, 왜 그렇게 나왔나</h1>
  <p class="lede">과매도·밸류에이션·펀더멘털 세 점수(0~100, 클수록 매수 매력)와 국면 이름을 실데이터로 처음 계산했다(기준일 {AS_OF}, 점수 이력 {SI['history_first']['KOSPI200']}~, 원천 대조 {N_PASS}/{N_CC} 통과). 점수는 각 자산이 <b>자기 과거</b>에 비해 어디쯤인지를 말할 뿐, 자산 간 기대수익 비교나 수익 예측이 아니다. <b>이 점수가 실제로 다음 수익을 맞히는지는 아직 검증되지 않았다(Phase 3 백테스트 진행 중).</b></p>
</header>"""


def sec_summary():
    groups = {}
    for a in ASSETS:
        groups.setdefault(SC.at[a, "label"], []).append(SHORT[a])
    order = [r["label"] for r in SCFG["regime"]["matrix"]]
    gl = " · ".join(f"<b>{e(l)}</b> {e(', '.join(groups[l]))}" for l in order if l in groups)
    ext = [(a, b) for a in ASSETS for b in BLK if SC.at[a, f"band_{b}"] in ("극단", "반대극단")]
    ext_t = ", ".join(f"{SHORT[a]} {BLK_KO[b]} {n(S(a, b))}({SC.at[a, f'band_{b}']})" for a, b in ext)
    near = [(a, b) for a in ASSETS for b in BLK if abs(S(a, b) - SCFG["regime"]["threshold"]) < 6]
    near_t = ", ".join(f"{SHORT[a]} {BLK_KO[b][:3]} {n(S(a, b))}" for a, b in near)
    rows = []
    for a in ASSETS:
        rows.append([f"<b>{e(SHORT[a])}</b>", score_cell(a, "oversold"), score_cell(a, "valuation"), score_cell(a, "fundamental"),
                     f'<td><span class="chip b">{e(SC.at[a, "display"])}</span></td>', f'<td class="why">{e(WHY[a])}</td>'])
    t = table(["자산", "과매도", "밸류", "펀더", "국면", "왜 이렇게 나왔나 (기여 상위·하위 지표)"], rows, cls="sumt", num_from=99,
              colgroup='<colgroup><col style="width:84px"><col style="width:54px"><col style="width:54px"><col style="width:54px"><col style="width:124px"><col></colgroup>')
    items = [
        f"국면 분류: {gl}. 국면은 세 점수가 각각 {SCFG['regime']['threshold']} 이상인지만 보고 정한다(3절 매트릭스).",
        f"자기 역사의 끝단(상·하위 10%)에 있는 값은 {ext_t}뿐이다. 나머지는 대부분 ‘중립’ 구간(25~75) 안이다.",
        f"문턱 {SCFG['regime']['threshold']}에서 ±6 안쪽이라 작은 변화로 국면 이름이 바뀔 수 있는 값: {near_t}.",
    ]
    li = "".join(f"<li><p>{t}</p></li>" for t in items)
    return f"""<section id="summary"><h2>1. 한 장 요약 — {AS_OF} 기준</h2>
<p class="sub">점수 = 각 지표가 자기 과거 분포에서 몇 % 지점인지(백분위)를 ‘매수 매력’ 방향으로 맞춘 뒤 평균한 값. 칸 아래 작은 글씨는 구간: 극단 ≥{SCFG['bands']['extreme']}, 경계 ≥{SCFG['bands']['alert']}, 반대경계 ≤{SCFG['bands']['contra_alert']}, 반대극단 ≤{SCFG['bands']['contra_extreme']}.</p>
{t}
<ol class="findings">{li}</ol>
{judge([
        "점수가 높다 = 과거에 비해 ‘싸거나 많이 빠졌다’는 뜻이지 ‘곧 오른다’는 뜻이 아니다. 예측력 검증 결과가 나오기 전까지 이 표는 <b>현재 위치 점검용</b>으로만 쓰는 것이 맞는지.",
        f"‘최우선 매수’로 나온 국내 회사채는 세 점수 모두 50~{n(max(S('KR_CORP', b) for b in BLK), 0)} 사이다. 라벨의 무게만큼 강한 신호인지, 문턱 근처 값의 우연인지 구분해서 볼 필요가 있다.",
        "KOSPI200 밸류 점수를 그대로 볼지, 두 종목 착시를 걷어낸 민감도(동일가중·두 종목 제외)를 함께 볼지 — Phase 3 비교 뒤 결정할 항목이다.",
    ])}</section>"""


# ---------------------------------------------------------------- 2. 자산별
JUDGE = {
    "KOSPI200": lambda a: [
        f"밸류 {n(S(a, 'valuation'))} = PER·ERP(각 {n(R(a, 'per_fwd_12m', 'score'), 0)}점)와 PBR({n(R(a, 'pbr_trailing', 'score'), 1)}점)·배당({n(R(a, 'dividend_yield', 'score'), 1)}점)의 평균이다. PBR {n(R(a, 'pbr_trailing'), 2)}배는 자기 역사 상위 {n(100 - R(a, 'pbr_trailing', 'percentile'), 0)}%로 비싸다 — 이익 기준과 장부 기준이 정반대를 말한다.",
        "수급(외국인·기관 순매수 등 4개)이 통째로 비어 있어, 과매도 점수는 가격·시장폭·변동성만으로 나온 값이다.",
    ],
    "SP500": lambda a: [
        f"지수 선행 EPS는 1개월 {spct(R(a, 'fwd_eps_chg_1m'))}(역사 상위 1% 안)인데, EPS가 오른 종목의 시총 비중은 {pct(R(a, 'revision_breadth'), 0)}로 역사 하위 {n(R(a, 'revision_breadth', 'percentile'), 0)}%다. 이익 증가가 일부 종목에 몰려 있을 가능성(추정).",
        f"ERP {n(R(a, 'erp'), 2)}%p — 주식 이익수익률이 미국채 10년과 거의 같다. 밸류 점수가 낮은 이유의 대부분이다.",
    ],
    "KTB10Y": lambda a: [
        "‘고점 경계’ = 과매도·펀더멘털이 모두 50 미만. 금리가 이미 빠르게 내려 채권 쪽 반등 여지가 과거보다 작다는 읽기다.",
        "실질금리는 ‘명목 − 이미 공표된 CPI 전년비’ 대리값(가정)이고, 한국 기간프리미엄·선물 포지셔닝은 소스가 없어 뺐다.",
    ],
    "UST10Y": lambda a: [
        f"기간프리미엄은 ALFRED 최초 공표값만 쓰므로 관측이 첫 빈티지({BI['alfred_THREEFYTP10']['vintage_first']})부터다(첫 점수 {COV_FIRST[(a, 'term_premium')]}). 상위 {n(100 - R(a, 'term_premium', 'percentile'), 0)}%라는 위치는 약 {(pd.Timestamp(AS_OF) - pd.Timestamp(BI['alfred_THREEFYTP10']['vintage_first'])).days / 365.25:.0f}년치 표본 기준이다.",
        f"펀더멘털 {n(S(a, 'fundamental'))}은 문턱 50 바로 아래다. 50을 넘으면 국면이 ‘저평가 패닉 분할 진입’에서 ‘최우선 매수’로 바뀐다.",
    ],
    "USDKRW": lambda a: [
        f"원화 매수 관점(점수↑ = 원화를 살 매력). 밸류 근거인 REER은 월별·3개월 늦게 반영(최신 {REER_LAST}월분)이라 최근 3개월 원화 강세(원/달러 {spct(R('KOSPI200', 'home_ccy_trend_3m'))})가 아직 없다.",
        f"경상수지 지표 원시값({musd(R(a, 'current_account_trend'))}백만달러)은 커서 단위·계열 확인이 필요해 보인다(추정). 펀더멘털의 절반이 이 값이다.",
    ],
    "GOLD": lambda a: [
        f"‘가치함정 경계’ = 과매도만 50을 넘었다({n(S(a, 'oversold'))}). 가격은 빠졌지만 실질가격은 여전히 역사적으로 비싸고 실질금리도 오르는 중이라는 읽기다.",
        "실질가격은 연속물이 아니라 원 근월물로 계산한다(결정 B). 포지셔닝(CFTC) 외에 금 고유의 수급 데이터는 없다.",
    ],
    "WTI": lambda a: [
        f"펀더멘털 {n(S(a, 'fundamental'))}(경계)인데 국면이 ‘비중 축소’인 것은 매트릭스 규칙 때문이다 — 과매도·밸류가 모두 50 미만이면 펀더멘털은 보지 않는다.",
        "원천 대조에서 근월 선물(CLc1)과 EIA 현물이 2026-10에 6~7달러 벌어졌다(정의 차, 4절). 실질가격 수준은 선물 근월물 기준임을 감안해야 한다.",
    ],
    "US_HY": lambda a: [
        f"스프레드는 ICE OAS가 아니라 iBoxx 만기수익률 − 평균만기 국채(G-스프레드)다. OAS보다 평균 {n(float(CC[CC.item.str.startswith('US_HY spread vs')]['diff'].iloc[0]), 2)}%p 넓지만 수준 상관 {n(float(CC[CC.item.str.startswith('US_HY spread vs')].value_a.iloc[0]), 3)}로 움직임은 거의 같다.",
        "부도율 데이터가 없어 펀더멘털은 주가지수 이익과 등급 간 격차 두 개뿐이다.",
    ],
    "US_IG": lambda a: [
        f"과매도 {n(S(a, 'oversold'))}는 HY({n(S('US_HY', 'oversold'))})보다 낮다. 같은 국면 이름이어도 HY 쪽 스트레스 신호가 더 강하다.",
        f"G-스프레드(평균만기 매칭)와 ICE OAS의 수준 상관은 {n(float(CC[CC.item.str.startswith('US_IG spread vs')].value_a.iloc[0]), 3)}다. 듀레이션 매칭판은 {n(float(CC[CC.item.str.startswith('US_IG spread_dur')].value_a.iloc[0]), 3)}으로 기준 0.8에 못 미쳐 결정 A로 바꿨다.",
    ],
    "KR_CORP": lambda a: [
        f"펀더멘털의 핵심인 ‘주가지수 선행 EPS’는 KOSPI200 시총가중 값이고, 그 선행이익의 {pct(CONC['earn_share'])}가 두 종목이다. 사실상 반도체 이익 모멘텀이 회사채 점수를 받치고 있다.",
        "스프레드는 AA−(3년) − 국고 3년이다. 국내 크레딧 전체가 아니라 우량물 한 구간이다.",
    ],
}


def asset_panel(a):
    sub = IND[IND.asset_id == a]
    rows = []
    for b in BLK:
        sb = sub[sub.block == b]
        rows.append(("blk", [f'<td colspan="6">{BLK_KO[b]} <b>{n(S(a, b))}</b> · {e(SC.at[a, f"band_{b}"])}</td>']))
        for _, r in sb.iterrows():
            conf = r.sub_block == "confluence"
            wt = "0 (미채택)" if conf and r.weight_in_block == 0 else pct(r.weight_in_block, 1)
            rows.append([f'{e(label(a, r.indicator))}<span class="sb">{e(SUB_KO.get(r.sub_block, r.sub_block))}</span>',
                         fmt_raw(a, r.indicator, r.raw), n(r.percentile, 1), f"<b>{n(r.score, 1)}</b>", wt,
                         f'<td class="dir">{e(DICT[CLS[a]][r.indicator][2])}</td>'])
    body = []
    for r in rows:
        if isinstance(r, tuple):
            body.append(f'<tr class="blk">{r[1][0]}</tr>')
        else:
            body.append("<tr>" + f"<td>{r[0]}</td>" + "".join(f'<td class="n">{c}</td>' for c in r[1:5]) + r[5] + "</tr>")
    t = (f'<div class="tablewrap"><table class="indt"><colgroup><col><col style="width:68px"><col style="width:44px"><col style="width:40px">'
         f'<col style="width:72px"><col style="width:128px"></colgroup><thead><tr><th>지표</th><th class="n">원시값</th>'
         f'<th class="n">백분위</th><th class="n">점수</th><th class="n">반영 비중</th><th>점수가 높아지는 쪽</th></tr></thead>'
         f'<tbody>{"".join(body)}</tbody></table></div>')
    miss, excl = na_rows(a)
    if miss:
        ml = "".join(f"<li><b>{e(NA_KO.get(i, i))}</b> — {e(short_why(i, w))}</li>" for i, w in miss)
        mtxt = f'<ul class="na">{ml}</ul>'
    else:
        mtxt = '<p class="na0">없음 — 프로파일 지표가 모두 계산됐다.</p>'
    if excl:
        ex = f'<p class="exl">설정에서 뺀 지표 {len(excl)}개(해당 없음·대체): {e(", ".join(ko_name(a, i) for i in excl))}' + (
            f" — {e(EXCL_WHY[a][1])}" if a in EXCL_WHY else "") + "</p>"
    else:
        ex = ""
    st = SC.loc[a]
    chips = " ".join(f'<span class="mini {band_cls(st[f"band_{b}"])}">{BLK_KO[b]} <b>{n(S(a, b))}</b></span>' for b in BLK)
    foot = ""
    jd = judge(JUDGE[a](a))
    cf = f'<p class="tnote">{foot}</p>' if foot else ""
    return f"""<div class="panel asset" id="a-{a}">
<div class="ahead"><h3>{e(SHORT[a])} <span class="an">{e(NAME[a])}</span></h3><span class="chip b">{e(st['display'])}</span> {chips}</div>
<div class="agrid">
 <div class="aleft">
  <div class="svgleg">{''.join(f'<span><i style="background:{BLK_COL[b]}"></i>{BLK_KO[b]}</span>' for b in BLK)}<span class="small">최근 3년 · 주말 값 · 점선 = 국면 문턱 {SCFG['regime']['threshold']}</span></div>
  {svg_hist(a)}
  <h4>빠진 데이터</h4>{mtxt}{ex}
  {jd}
 </div>
 <div class="aright">{t}{cf}</div>
</div></div>"""


def sec_assets():
    panels = "".join(asset_panel(a) for a in ASSETS)  # universe 순서
    n_miss = {a: len(na_rows(a)[0]) for a in ASSETS}
    full = [SHORT[a] for a in ASSETS if n_miss[a] == 0]
    must(all(top(a, "oversold", 1) == ["level_rv_ratio_20"] for a in ("US_HY", "US_IG", "KR_CORP", "UST10Y")), "변동성 기여")
    return f"""<section id="assets"><h2>2. 자산별 — 점수 이력, 지표, 빠진 데이터</h2>
<p class="sub">자산별로 왜 이 점수가 나왔는지는 1절 표의 한 문장에 있다. 왼쪽: 세 블록 점수의 최근 3년 흐름, 빠진 데이터, 판단할 점. 오른쪽: 기준일 지표별 원시값·백분위·점수 — <b>백분위</b> = 자기 과거(현재 포함) 분포에서의 위치, <b>점수</b> = 방향을 맞춘 백분위(낮을수록 매력인 지표는 100 − 백분위), <b>반영 비중</b> = 블록 점수 안에서의 몫. <b>동시판정</b>(볼린저 %b·RSI14)은 둘 중 낮은 점수만 채택하므로 다른 쪽은 ‘0 (미채택)’으로 보인다. ‘빠진 데이터’는 소스를 못 구해 비워 둔 것만 적었다(다른 값으로 메우지 않았다). 빠진 데이터가 없는 자산: {e(', '.join(full))}.</p>
{judge([
        "빠진 데이터가 가장 많은 것은 KOSPI200(수급 4개·Put/Call·VKOSPI 기간구조)이다. 국내 주식 과매도 판단에서 수급이 빠진 점수를 얼마나 믿을지.",
        "금리·크레딧의 RSI·볼린저는 ‘금리·스프레드가 오를수록 과매도’로 읽도록 뒤집어 계산했다(가정). 이 해석이 맞는지는 Phase 3에서 확인된다.",
        "‘평소보다 변동성이 높으면 과매도 점수를 올린다(패닉 = 기회)’는 규칙은 사용자 결정(2026-10-28)이지만 아직 검증 전 가정이다. 미국 HY·IG·국내 회사채·UST의 과매도는 이 지표가 가장 크게 올렸다.",
    ], "판단할 점 — 자산 공통 (자산별 판단할 점은 각 패널에)")}
{panels}
</section>"""


# ---------------------------------------------------------------- 3. 점수가 어떻게 만들어지나
def sec_method():
    k = "KOSPI200"
    sub = IND[(IND.asset_id == k) & (IND.block == "oversold")]
    subs = sub.groupby("sub_block", sort=False).indicator.count()
    n_sub = len(subs)
    mx = SCFG["regime"]["matrix"]
    st = {"high": "≥ 50", "low": "< 50", None: "무관"}
    cur = {}
    for a in ASSETS:
        cur.setdefault(SC.at[a, "label"], []).append(SHORT[a])
    rows = [[st[r["o"]], st[r["v"]], st[r["f"]], f"<b>{e(r['label'])}</b>", e(", ".join(cur.get(r["label"], [])) or "—")] for r in mx]
    mt = table(["과매도", "밸류", "펀더", "국면 이름", "지금 해당 자산"], rows, num_from=99)
    vk, pb = ("vol_index_level", "pbr_trailing")
    bb, rs = R(k, "bb_pctb_20", "score"), R(k, "rsi_14", "score")
    steps = [
        f"<b>① 자기 과거 대비 백분위.</b> 각 지표의 오늘 값이 그 자산의 과거(데이터 시작 ~ 오늘) 값들 중 몇 % 지점인지 잰다. 과거가 최소 {SCFG['percentile']['min_history_years']}년 쌓여야 점수를 내므로 점수 이력은 {SI['history_first']['KOSPI200']}부터다. 다른 자산과 비교하지 않는다. "
        f"예: VKOSPI {n(R(k, vk), 2)}는 과거 값의 {n(R(k, vk, 'percentile'), 1)}%보다 높다.",
        f"<b>② 방향 맞추기.</b> ‘클수록 매수 매력’이 되도록 뒤집는다. 높을수록 좋은 지표(VKOSPI: 공포가 클수록 기회)는 백분위 그대로 {n(R(k, vk, 'score'), 1)}점, 낮을수록 좋은 지표(PBR {n(R(k, pb), 2)}배, 백분위 {n(R(k, pb, 'percentile'), 1)})는 100 − 백분위 = {n(R(k, pb, 'score'), 1)}점.",
        f"<b>③ 하위블록 평균 → 블록 점수.</b> 블록 안에서 하위블록(가격·시장폭·변동성 등)끼리 같은 비중, 하위블록 안에서 지표끼리 같은 비중이다. KOSPI200 과매도는 계산된 하위블록 {n_sub}개 × {pct(1 / n_sub, 0)}씩이라 가격 지표 {subs['price']}개는 각각 {pct(1 / n_sub / subs['price'], 1)}, 시장폭 지표 {subs['breadth']}개는 각각 {pct(1 / n_sub / subs['breadth'], 2)}다. 데이터가 없는 하위블록(수급)은 빠지고 나머지로 평균한다.",
        f"<b>④ 동시판정(confluence).</b> 볼린저 %b와 RSI(14)는 평균하지 않고 <b>둘 중 낮은 점수</b>를 쓴다. ‘볼린저 하단 근접’과 ‘과매도’가 동시에 성립해야 높게 나온다. KOSPI200은 볼린저 {n(bb, 1)}·RSI {n(rs, 1)} → {n(min(bb, rs), 1)} 채택.",
        f"<b>⑤ 구간과 국면.</b> 블록 점수 ≥{SCFG['bands']['extreme']} 극단, ≥{SCFG['bands']['alert']} 경계, ≤{SCFG['bands']['contra_alert']} 반대경계, ≤{SCFG['bands']['contra_extreme']} 반대극단, 나머지 중립. 국면은 세 점수가 각각 문턱 {SCFG['regime']['threshold']} 이상(높음)인지 미만(낮음)인지의 조합으로 아래 표에서 고른다. 구간과 국면은 서로 다른 잣대라, 세 점수가 모두 ‘중립’이어도 ‘최우선 매수’가 나올 수 있다(국내 회사채).",
        f"<b>⑥ 시점 규칙.</b> 그날 실제로 알 수 있던 값만 쓴다(공표일 기준, 4절). 일별 값은 최대 {SCFG['missing']['daily_ffill_max_bdays']}영업일까지만 이어 붙이고, 월·주별 값은 다음 공표까지 유지하되 {SCFG['missing']['lowfreq_max_hold_bdays']}영업일을 넘기면 결측이다.",
    ]
    li = "".join(f"<li><p>{s}</p></li>" for s in steps)
    return f"""<section id="method" class="pg"><h2>3. 점수가 어떻게 만들어지나</h2>
<p class="sub">가중치·문턱·구간은 모두 설정 파일(config/scoring.yaml)에 있고, 과거 성과에 맞춰 조정하지 않았다(튜닝 금지가 기본).</p>
<ol class="findings">{li}</ol>
<h3>국면 매트릭스 (scoring.yaml, 위에서부터 먼저 맞는 줄)</h3>
{mt}
{judge([
        f"문턱 {SCFG['regime']['threshold']}은 ‘자기 역사의 중앙’이라는 뜻일 뿐 근거가 검증된 값이 아니다. Phase 3에서 문턱별 성과를 본 뒤 정하기로 했다.",
        "블록 점수는 지표를 같은 비중으로 평균한 것이라, 지표 수가 많은 하위블록의 개별 지표는 하나하나의 영향이 작다. 동시판정만 ‘최솟값’ 규칙을 쓴다.",
        "‘최우선 매수’와 ‘저평가 패닉 분할 진입’ 등 국면 이름은 행동 지침처럼 들리지만, 이름에 맞는 성과가 났는지는 아직 아무도 확인하지 않았다.",
    ])}
</section>"""


# ---------------------------------------------------------------- 4. 데이터 신뢰도
def sec_data():
    src = md_tables(REP, "2. 자산별 수집 결과")[0]
    # 본문 §2 의 US_HY 스프레드 정의는 개정 전(듀레이션 매칭) — 결정 A(평균만기 매칭)로 바꿔 적는다
    hy = src.index[src["자산"] == "US_HY"][0]
    assert "같은 듀레이션 UST" in src.at[hy, "필드(소스)"]
    assert "평균만기(AVG_LIFE) 매칭" in FMAP
    src.at[hy, "필드(소스)"] = src.at[hy, "필드(소스)"].replace("같은 듀레이션 UST", "평균만기(AVG_LIFE) 매칭 UST 커브 수익률(G-스프레드, 결정 A)")
    srows = [[f"<b>{e(r['자산'])}</b>", f'<td class="srcs">{code(r["필드(소스)"])}</td>', e(r["사용 지표 / 전체"])] for _, r in src.iterrows()]
    for a in ASSETS:  # 사용 지표 수 = coverage.csv
        rr = src[src["자산"] == a]["사용 지표 / 전체"].iloc[0]
        u, tot = int(COV[(COV.asset_id == a)].used.sum()), int((COV.asset_id == a).sum())
        assert rr.startswith(f"{u} / {tot}"), (a, rr, u, tot)
    st = table(["자산", "필드와 소스", "사용/전체 지표"], srows, cls="srct", num_from=2,
               colgroup='<colgroup><col style="width:80px"><col><col style="width:150px"></colgroup>')
    # 원천 대조 요약
    cc = CC.copy()
    cc["src_b"] = cc.source_b.str.split(":").str[0]
    grp = []
    for (item, sb), g in cc.groupby(["item", "src_b"], sort=False):
        md = g["diff"].abs().max()
        grp.append([e(item), e(g.source_b.iloc[0]), str(len(g)), f"{int(g['pass'].sum())}/{len(g)}",
                    n(md, 3), f'<td class="dir">{e(str(g.note.iloc[0]) if pd.notna(g.note.iloc[0]) else "")[:90]}</td>'])
    ct = table(["대조 항목", "비교 상대", "건수", "통과", "최대 |차|", "비고"], grp, cls="cct", num_from=2,
               colgroup='<colgroup><col style="width:250px"><col style="width:190px"><col style="width:36px"><col style="width:40px"><col style="width:62px"><col></colgroup>')
    fails = CC[~CC["pass"]]
    assert len(fails) == 4
    f_usd = fails[fails.item == "USDKRW"].iloc[0]
    f_wti = fails[fails.item.str.startswith("WTI")]
    f_ig = fails[fails.item.str.startswith("US_IG spread_dur")].iloc[0]
    ig_ok = CC[CC.item.str.startswith("US_IG spread vs")].iloc[0]
    fl = [
        f"<b>USDKRW {f_usd.date}</b>: 서울 마감 {n(f_usd.value_a, 1)}원 vs ECOS 매매기준율 {n(f_usd.value_b, 1)}원(차 {n(f_usd['diff'], 1)}원, 허용 {n(f_usd.tolerance, 0)}원). 매매기준율은 전일 시장평균환율이라 정의가 다르다. 같은 날 FRED 대비는 통과.",
        f"<b>WTI {', '.join(f_wti.date)}</b>: 근월 선물 CLc1 vs EIA 현물(차 {', '.join(n(x, 2) for x in f_wti['diff'])}달러, 허용 {n(f_wti.tolerance.iloc[0], 1)}). 2026년 급한 백워데이션 구간에서 현물과 근월물이 벌어진 정의 차다. 2025년 표본은 통과.",
        f"<b>US_IG 듀레이션 매칭판</b>: ICE OAS와 수준 상관 {n(f_ig.value_a, 3)}(기준 0.8 미달). 이 판은 비교용으로만 남겼고, 점수에 쓰는 평균만기 매칭판은 {n(ig_ok.value_a, 3)}로 통과(결정 A).",
    ]
    assert "0.8" in REP
    # PIT
    cp, nf, tp = BI["alfred_CPIAUCSL"], BI["alfred_NFCI"], BI["alfred_THREEFYTP10"]
    pit = [
        f"<b>미국 CPI·NFCI·기간프리미엄은 ‘처음 발표된 값’을 ‘처음 발표된 날’에 쓴다(ALFRED).</b> 나중에 수정된 값을 과거에 끼워 넣으면 그때는 몰랐던 정보로 점수를 매기게 된다. "
        f"CPI 공표 지연 중앙 {cp['lag_days_median']:.0f}일·최대 {cp['lag_days_max']}일, NFCI 중앙 {nf['lag_days_median']:.0f}일·최대 {nf['lag_days_max']}일, 기간프리미엄 중앙 {tp['lag_days_median']:.0f}일·95% {tp['lag_days_p95']:.0f}일·최대 {tp['lag_days_max']}일. "
        f"첫 빈티지({nf['vintage_first']}, {tp['vintage_first']}) 이전은 비워 두어 NFCI 첫 점수 {COV_FIRST[('UST10Y', 'financial_conditions')]}, 기간프리미엄 첫 점수 {COV_FIRST[('UST10Y', 'term_premium')]}다. 2025-10월분 CPI는 공표되지 않아 결측이다.",
        "<b>그 밖의 FRED·ECOS 값은 최신 수정치다(가정).</b> REER·실질금리(DFII10)·경상수지·한국 CPI 등은 공표 시차만 반영했고 당시 값은 아니다.",
        f"<b>월별 컨센서스(EPS·PER)는 표본일(월말) 기준으로 시점을 잡는다.</b> 반환 날짜는 ‘마지막 변경일’이라 다음 달에도 같은 날짜로 다른 값이 온다 — 표본일을 쓰는 쪽이 보수적이다.",
        f"<b>재현 점검</b>: 과거 기준일(2020-03-23·2024-08-05)로 잘라 다시 계산한 블록 점수 {PIT_N}건이 이력 파일과 일치(최대 차 {PIT_D}, 반올림 수준).",
    ]
    kb, sb = BI["kospi200_bottomup"]["fwd_per"], BI["sp500_bottomup"]
    surv = [
        f"<b>KOSPI200 컨센서스·시장폭은 ‘지금의’ 구성종목 {BI['kospi200_breadth']['n_ric']}개(KODEX200 보유)로 과거까지 계산했다.</b> 과거에 지수에서 빠진 종목(대개 부진했던 종목)이 없으므로 과거 값이 실제보다 좋게 나올 수 있다(생존편향, 가정). KRX 로그인이 생기면 과거 구성종목으로 바꾼다.",
        f"월별 EPS가 있는 종목 수는 {kb['n_min']}개(2010 초)~{kb['n_last']}개(현재), 중앙 {kb['n_median']}개. 2010-01에 EPS가 있는 종목은 {EPS2010_N}개뿐이고 삼성전자 EPS는 {SS_EPS_FROM}부터라 초기 몇 달은 대형주 일부가 빠진 값이다.",
        f"S&P500 EPS 상향 비중도 SPY 현재 보유 {sb['n_ric']}종목 기준(월 {sb['n_month_min']}~{sb['n_last']}개, 중앙 {sb['n_month_median']}개)이다. 같은 생존편향.",
    ]
    ss_per, hx_per = SS_PX / SS_EPS, HX_PX / HX_EPS
    per = [
        f"KOSPI200 바텀업 선행 PER {PER_CW}배는 2010~2025 연말 범위({PER_LO}({PER_LO_Y})~{PER_HI}({PER_HI_Y}))를 크게 벗어난다. 집계식 오류가 아니라 원자료 그대로다.",
        f"삼성전자(선행 EPS {SS_EPS:,.0f}원, 주가 {SS_PX:,.0f}원 → 약 {ss_per:.1f}배)·SK하이닉스({HX_EPS:,.0f}원, {HX_PX:,.0f}원 → 약 {hx_per:.1f}배)의 선행 PER이 3배 안팎이고, 두 종목이 시총의 {pct(CONC['cap_share'])}, 선행이익의 {pct(CONC['earn_share'])}를 차지한다({CONC['month']}, {CONC['n']}종목).",
        f"민감도(점수에는 미사용): 동일가중 {PER_EW}배, 두 종목 제외 시총가중 {PER_EX2}배. EPS 상향 종목 비중도 시총가중 {UP_CW} / 동일가중 {UP_EW} / 두 종목 제외 {UP_EX2}.",
        f"그래서 PER·ERP 백분위가 극단({n(R('KOSPI200', 'erp', 'percentile'), 2)})이고, KOSPI200 밸류 점수의 절반이 이 두 지표다. 바텀업 시총 합은 KRX 지수 시총보다 {MCAP_GAP}% 크다(전체 시총 vs 지수 시총 정의 차, 허용 범위 안).",
    ]
    ul = lambda xs: '<ul class="plain">' + "".join(f"<li>{x}</li>" for x in xs) + "</ul>"
    return f"""<section id="data" class="pg"><h2>4. 데이터 신뢰도</h2>
<p class="sub">표본 2010-01 ~ {AS_OF}(오늘 장중 값은 받지 않음). 패널 {PANEL}행. 받을 수 없는 데이터는 추정·생성하지 않고 비워 두었다. 테스트 {N_TEST}개 통과(Phase 2 보고).</p>
<h3>자산별 소스</h3>{st}
<h3>원천 대조 — {N_PASS}/{N_CC} 통과</h3>
<p class="desc">같은 값을 서로 다른 원천에서 받아 맞춰 봤다. 통과하지 못한 4건은 모두 ‘비교 상대의 정의가 다른’ 경우이고, 대조한 범위에서 점수에 쓰는 값의 오류는 발견되지 않았다.</p>
{ct}
{ul(fl)}
<h3>시점 처리(그날 알 수 있던 값만)</h3>{ul(pit)}
<h3>생존편향 — 바텀업 컨센서스</h3>{ul(surv)}
<h3>KOSPI200 선행 PER {PER_CW}배는 무엇인가</h3>{ul(per)}
{judge([
        "점수에 쓰는 값 자체는 대조에서 문제가 없었다. 불확실성은 ‘값이 틀렸다’보다 ‘정의·구성이 다르다’(G-스프레드 vs OAS, 현재 구성종목, 수정치) 쪽에 있다.",
        f"KOSPI200 밸류·이익 지표는 두 종목의 이익 전망에 크게 묶여 있다. 반도체 이익 전망이 꺾이면 PER·ERP·EPS 지표가 함께 움직여 밸류·펀더멘털 점수(그리고 국내 회사채 펀더멘털)가 동시에 바뀔 수 있다.",
        "FRED·ECOS 수정치를 쓰는 지표(REER·실질금리·경상수지·한국 CPI)는 과거 점수에 사후 정보가 섞였을 수 있다. Phase 3 결과를 해석할 때 감안할 부분이다.",
    ])}
</section>"""


# ---------------------------------------------------------------- 5. 결정 기록
DECISIONS = [  # (CLAUDE.md 절 날짜 표지, 분야, 결정 요지, 근거 문구(해당 절에 있어야 함), 상태)
    ("2026-10-26", "범위", "표본 2010년~ 일별 산출. 유니버스 10개(KOSPI200, S&P500, 국고10년, 미국채10년, USDKRW, 금, WTI, 미국 HY·IG, 국내 회사채). USDKRW는 원화 매수 관점", ("표본 2010~, 일별 산출", "유니버스 10개", "USDKRW는 원화 매수 관점"), "유효"),
    ("2026-10-26", "크레딧", "미국 HY·IG 스프레드 = iBoxx 만기수익률 − 국채(G-스프레드). ICE OAS는 권한 없음", "iBoxx USD Liquid HY", "10-28 A로 구체화(평균만기 매칭)"),
    ("2026-10-26", "주식", "KOSPI200은 KRX 계정 공식 데이터 우선, 이익수정비율은 바텀업 확산지표로 대체(가정)", "이익수정비율은 바텀업 확산지표", "KRX 계정 없음 → 10-28 바텀업"),
    ("2026-10-26", "주식", "S&P500 밸류에이션은 선행 PER·ERP만(PBR·배당 불가)", "S&P500 밸류에이션은 Fwd PER·ERP만", "유효"),
    ("2026-10-26", "주식", "주가지수에서 신용스프레드 지표 제외(크레딧 자산과 중복)", "신용스프레드 지표를 뺐다", "유효"),
    ("2026-10-26", "펀더멘털", "금리 = 물가 모멘텀·기준금리 6개월 방향·NFCI 3개월 변화(미국만). 크레딧 = 같은 지역 주가지수 선행 EPS 3개월 변화·저등급−고등급 스프레드 차 추세. 금 = 미국 실질금리 3개월 변화", ("금리 Fundamental", "크레딧 Fundamental", "금 Fundamental"), "유효"),
    ("2026-10-26", "환율", "USDKRW에 RSI(14) 추가", "USDKRW에 RSI 14를 추가", "10-28 동시판정으로 이동"),
    ("2026-10-26", "원유", "WTI 재고는 Phase 2에서 확인", "WTI 재고는 Phase 2", "10-28 EIA 재고 확보"),
    ("2026-10-26", "주식", "가격 지표 8개 유지. Phase 3에서 사전 규칙(전반부 상관 > 0.9 쌍 중 IC 낮은 쪽, 후반부에서 나빠지지 않을 때만 제외)으로 판단", "전반부 상관 > 0.9", "Phase 3 대기"),
    ("2026-10-26", "통화", "통화 이중반영은 3개 변형 비교(기본 both), 확인 트리거는 보류", "통화 이중반영은 3개 변형", "Phase 3 대기"),
    ("2026-10-28", "역발상화", "모멘텀은 최소화하고 과매도·과도한 낙폭일수록 점수를 높인다. 밸류 결합(국면 매트릭스)은 그대로", "모멘텀은 최소화", "유효"),
    ("2026-10-28", "역발상화", "동시판정 하위블록: 볼린저 %b(20일) + RSI(14), 둘 중 낮은 값(5개 자산군 모두)", "퍼지 AND", "유효"),
    ("2026-10-28", "역발상화", "평소보다 높은 변동성이면 과매도 점수를 올린다(패닉 = 기회)", "패닉 = 기회", "가정: 미검증"),
    ("2026-10-28", "역발상화", "KOSPI200 기관 순매수 지표 추가(방향은 외국인과 같다고 가정)", "inst_net_buy_intensity", "소스 대기(KRX 로그인)"),
    ("2026-10-28", "엔진", "하위블록 최솟값 집계를 위해 코어 수정(설계 결함으로 보고)", "하위블록 min 집계는 설정만으로", "유효"),
    ("2026-10-28", "데이터", "KOSPI200 컨센서스·시장폭 = 현재 구성종목(KODEX200 201종목) 바텀업", "보유종목 201개", "가정: 생존편향"),
    ("2026-10-28", "데이터", "S&P500 EPS 상향 비중 = SPY 보유 503종목 바텀업, 자기 역사 백분위로만 사용", "SPY 보유종목 전체(503개)", "가정: 생존편향"),
    ("2026-10-28", "데이터", "WTI 연속물 = 비율 백어저스트(NYMEX 최종거래일 규칙, 교체 5영업일 전 갈아탐). 실질가격·커브는 원 근월물로 계산", ("WTI 연속물", "real_price_level_spot"), "D로 승인"),
    ("2026-10-28", "데이터", "기본값 수용: 듀레이션 국고·미국채 8.5, 국내 회사채 2.7, 한국 CPI 공표 = 다음 달 5일", "듀레이션 KTB·UST 8.5", "미국 CPI는 E로 대체"),
    ("2026-10-28", "데이터", "월별 컨센서스 시점 = 표본일(월말·스냅숏일)", "Refinitiv 월별 컨센서스 as_of", "D로 승인"),
    ("2026-10-28", "검증 후", "A. G-스프레드 = 평균만기 매칭(HY·IG). 듀레이션 매칭판은 비교용", "A. G-스프레드 = 평균만기 매칭", "유효"),
    ("2026-10-28", "검증 후", "B. 금 연속물 = 활성월(G·J·M·Q·V·Z) 비율 백어저스트, 실질가격은 원 근월물", "B. 금 연속물 = 활성월 비율 백어저스트", "유효"),
    ("2026-10-28", "검증 후", "C. KOSPI200 이익 지표는 시총가중 유지. 동일가중·두 종목 제외판은 민감도(점수 미사용)", "C. KOSPI200 이익 지표", "Phase 3 비교"),
    ("2026-10-28", "검증 후", "D. 승인 4건(컨센서스 시점, WTI 규칙·교체, WTI 근월물 지표, EIA 재고). 0 이하 근월물 가격은 결측", "D. 승인", "유효"),
    ("2026-10-28", "검증 후", "E·F. 미국 CPI·NFCI·기간프리미엄 = ALFRED 최초 공표값·최초 공표일", "E·F. ALFRED 실시간 값", "유효"),
    ("2026-10-28", "검증 후", "미국 +1영업일 = 연방 공휴일·성금요일 제외(셧다운 지연은 미반영)", "미국 +1영업일", "가정"),
]


def sec_decisions():
    parts = re.split(r"^## ", CL, flags=re.M)
    secs = {p.splitlines()[0]: p for p in parts if p.startswith("확정 결정")}
    assert len(secs) == 4, list(secs)
    rows, cur = [], None
    for d, area, what, key, status in DECISIONS:
        keys = key if isinstance(key, tuple) else (key,)
        hit = [h for h, body in secs.items() if d in h and all(k in body for k in keys)]
        assert hit, (d, key)
        cls = "warn" if ("가정" in status or "대기" in status or "비교" in status) else ("" if status == "유효" else "b")
        rows.append([d, e(area), e(what), f'<td><span class="chip {cls}">{e(status)}</span></td>'])
    t = table(["날짜", "분야", "결정", "상태"], rows, cls="dect", num_from=99,
              colgroup='<colgroup><col style="width:78px"><col style="width:70px"><col><col style="width:190px"></colgroup>')
    n_pend = sum(1 for r in DECISIONS if "대기" in r[4] or "비교" in r[4])
    n_asm = sum(1 for r in DECISIONS if "가정" in r[4])
    return f"""<section id="decisions" class="pg"><h2>5. 결정 기록</h2>
<p class="sub">CLAUDE.md ‘확정 결정’ 4개 절(2026-10-26 초기, 10-28 역발상화·Phase 2 데이터·검증 후)의 요지. ‘상태’ = 이후 바뀌었는지 / Phase 3 대기({n_pend}건) / 검증 안 된 가정({n_asm}건).</p>
{t}
{judge([
        "‘가정’으로 남은 결정(변동성 = 기회, 생존편향 바텀업, 미국 영업일 규칙)은 되돌릴 수 있다. Phase 3 결과가 나쁘면 가장 먼저 다시 볼 후보다.",
        "‘KRX 공식 데이터 우선’(10-26)은 계정이 없어 대체 경로(바텀업)로 갔다. KRX 계정 마련 여부가 이를 되돌리는 열쇠다.",
    ])}
</section>"""


# ---------------------------------------------------------------- 6. 아직 판단 못 하는 것 / 판단해 주셔야 할 것
def sec_open():
    bt = SCFG["backtest"]
    miss_all = [(a, i, w) for a in ASSETS for i, w in na_rows(a)[0]]
    by_ind = {}
    for a, i, w in miss_all:
        by_ind.setdefault(i, [[], w])[0].append(SHORT[a])
    mrows = [[f"<b>{e(NA_KO.get(i, i))}</b>", e(", ".join(v[0])), e(short_why(i, v[1]))] for i, v in by_ind.items()]
    mt = '<ul class="plain">' + "".join(f"<li>{r[0]} ({r[1]}) — {r[2]}</li>" for r in mrows) + "</ul>"
    cant = [
        f"<b>이 점수가 미래 수익을 맞히는지 — 아직 모른다.</b> Phase 3 백테스트(bd4ded2 설정 기준 보유기간 {', '.join(map(str, bt['horizons']))}영업일, 신호 간 최소 간격 {bt['event_cooldown_bdays']}영업일, 표본 {bt['min_n_warning']}건 미만이면 경고)가 별도 작업으로 진행 중이다. 그 전까지 국면 이름(‘최우선 매수’ 등)은 설계상의 이름일 뿐 성과로 뒷받침된 판단이 아니다.",
        "<b>점수 사이의 비교</b>: 점수는 자산별 자기 역사 기준이라 ‘KOSPI200 74 > 금 55 → KOSPI200이 더 낫다’는 비교는 성립하지 않는다.",
        "<b>가정으로 둔 해석</b>: 변동성 상승 = 기회, 금리·스프레드 RSI를 뒤집어 읽기, KOSPI200 기관 수급 방향, 바텀업 생존편향의 크기 — 모두 Phase 3 전에는 맞는지 모른다.",
    ]
    ask = [
        ("수급 데이터(KOSPI200 외국인·기관 순매수, 과거 구성종목, 공식 지수 PER·PBR)", "KRX 로그인 계정(KRX_ID/KRX_PW)이 필요하다. 지금 키는 KRX Open API AUTH_KEY라 투자자별 매매·과거 구성종목이 응답에 없다. 계정을 마련할지, 정보데이터시스템에서 수동으로 내려받을지.", "계정 / 수동 / 보류"),
        ("VKOSPI 3개월물·Put/Call·신용잔고·반대매매·서프라이즈·교역조건·부도율", "소스 미확인으로 N/A. 수동 입력 템플릿(data/manual/templates/phase2_na_fields.csv)은 준비돼 있다. 어느 것을 우선 구할지.", "우선순위 지정"),
        ("통화 이중반영 변형", f"현재 기본값 {SCFG['currency_variant']}(과매도·펀더멘털 양쪽에 원화 지표 반영). Phase 3에서 3개 변형(과매도만·펀더멘털만·둘 다)을 비교한 뒤 확정.", "Phase 3 뒤"),
        ("국면 문턱", f"지금 {SCFG['regime']['threshold']}. Phase 3 결과를 보고 유지·변경 결정.", "Phase 3 뒤"),
        ("KOSPI200 이익 지표 가중", f"시총가중(PER {PER_CW}배) 유지 vs 동일가중({PER_EW}배)·두 종목 제외({PER_EX2}배). 민감도 필드는 이미 만들어 두었다.", "Phase 3 뒤"),
        ("주가지수 가격 지표 8개 정리", "사전 규칙(상관 > 0.9 쌍 중 IC 낮은 쪽, 후반부에서 나빠지지 않을 때만 제외)대로 Phase 3에서 기계적으로 판정.", "규칙 확정됨"),
        ("확인 트리거", "scoring.yaml confirm_trigger는 꺼져 있고 엔진은 읽지 않는다(미구현, 2026-10-26 ‘나중에’ 결정). 다시 다룰지.", "보류 유지?"),
        ("경상수지 지표 원시값", f"USDKRW 펀더멘털의 절반을 차지하는 값({musd(R('USDKRW', 'current_account_trend'))}백만달러)의 단위·계열 확인(추정상 큼).", "확인 요청"),
    ]
    at = table(["항목", "지금 상태와 선택지", "시점"], [[f"<b>{e(a)}</b>", e(b), e(c)] for a, b, c in ask], cls="askt", num_from=99,
               colgroup='<colgroup><col style="width:250px"><col><col style="width:100px"></colgroup>')
    ul = lambda xs: '<ol class="findings">' + "".join(f"<li><p>{x}</p></li>" for x in xs) + "</ol>"
    return f"""<section id="open" class="pg"><h2>6. 아직 판단 못 하는 것 / 판단해 주셔야 할 것</h2>
<h3>아직 판단 못 하는 것</h3>{ul(cant)}
<h3>판단해 주셔야 할 것</h3>{at}
<h3>빠진 데이터 전체 (N/A, 다른 값으로 메우지 않음)</h3><div class="cols2">{mt}</div>
{judge([
        "지금 단계에서 이 점수로 비중을 바꾸는 것은 검증 전 지표로 의사결정하는 셈이다. Phase 3 결과가 나올 때까지 ‘관찰용’으로 둘지가 가장 먼저 정할 일이다.",
        "데이터 보강 중 효과가 가장 클 것으로 보이는 것은 KRX 계정(수급·과거 구성종목·공식 PER을 한꺼번에 해결)이다(추정).",
    ])}
<p class="note">출처: 커밋 {e(HEAD_SUBJ)} — outputs/phase2(latest_scores·latest_indicators·coverage·crosscheck·result_{AS_OF}.json·score_history·build_info·phase2_report 개정 절), config/*.yaml, CLAUDE.md. 생성 {DATE}, outputs/briefing_phase2/build_briefing.py.</p>
</section>"""


# ---------------------------------------------------------------- 조립
EXTRA_CSS = """
/* ---- Phase 2 브리핑 덮어쓰기 ---- */
html[data-print], html[data-print] body { background: #fff; }
html[data-print] body { width: 1017px; }
:root { --f-mono: "IBM Plex Mono", "IBM Plex Sans KR", "Malgun Gothic", ui-monospace, monospace; }
html[data-print] main { display: block; }
html[data-print] main > section { padding-block: 4px 2px; }
.bhead { padding-block: 4px 10px; gap: 6px; }
html[data-print] .bhead h1 { font-size: 26px; }
html[data-print] .bhead .lede { font-size: 12.5px; max-width: none; line-height: 1.5; }
.bhead .facts b { font-size: 18px; }
html[data-print] .findings { display: block; margin-top: 6px; }
html[data-print] .findings li { margin-bottom: 4px; }
html[data-print] .findings p { font-size: 12px; }
html[data-print] .sumt td { font-size: 11px; padding: 1.5px 6px; vertical-align: middle; }
html[data-print] .sumt .chip { font-size: 11px; padding: 0 7px; }
html[data-print] .sumt td.why { font-size: 10.2px; line-height: 1.33; color: var(--ink); }
html[data-print] td.sc { text-align: center; }
html[data-print] td.sc b { display: block; font-family: var(--f-mono); font-size: 13px; font-weight: 600; }
html[data-print] td.sc .bd { display: block; font-size: 9.5px; color: var(--ink-3); }
html[data-print] td.sc.hi2 { background: #d5e6f7; } html[data-print] td.sc.hi1 { background: #e9f1fa; } html[data-print] td.sc.lo1 { background: #fbecea; } html[data-print] td.sc.lo2 { background: #f6d6d2; }
.mini { display: inline-block; font-size: 11px; padding: 0 7px; border-radius: 4px; border: 1px solid var(--rule); color: var(--ink-2); margin-left: 3px; }
.mini b { font-family: var(--f-mono); color: var(--ink); }
.mini.hi2 { background: #d5e6f7; } .mini.hi1 { background: #e9f1fa; } .mini.lo1 { background: #fbecea; } .mini.lo2 { background: #f6d6d2; }
.judge { margin: 6px 0 2px; padding: 4px 8px 4px 10px; border-left: 3px solid var(--accent); background: var(--accent-soft); border-radius: 0 4px 4px 0; break-inside: avoid; }
.judge .jt { font-weight: 600; font-size: 11.5px; color: var(--accent); margin-bottom: 1px; }
.judge ul { margin: 0; padding-left: 16px; }
.judge li { font-size: 10.8px; line-height: 1.42; margin: 0; }
.panel.asset { margin: 5px 0 0; padding: 4px 10px 5px; break-inside: avoid; }
.ahead { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; margin-bottom: 3px; }
.ahead h3 { margin: 0 6px 0 0; font-size: 15px; }
.ahead .an { font-weight: 400; font-size: 11.5px; color: var(--ink-3); }
.agrid { display: grid; grid-template-columns: 400px minmax(0, 1fr); gap: 12px; }
.awhy { font-size: 11px; line-height: 1.45; margin: 0 0 3px; }
html[data-print] .indt td, html[data-print] .indt th { font-size: 10px; padding: 1px 5px; line-height: 1.3; }
html[data-print] .indt td.dir { color: var(--ink-2); font-size: 9.5px; }
html[data-print] .indt tr.blk td { background: var(--rule-2); font-weight: 500; font-size: 10.5px; color: var(--ink); }
html[data-print] .indt .sb, html[data-print] .dect .sb { color: var(--ink-3); font-size: 8.5px; margin-left: 5px; }
html[data-print] .dect tr.blk td { background: var(--rule-2); font-weight: 500; font-size: 10.5px; }
.tnote { font-size: 9.5px; color: var(--ink-3); margin: 3px 0 0; line-height: 1.4; }
h4 { font-size: 11.5px; font-weight: 600; margin: 4px 0 1px; color: var(--ink-2); }
ul.na { margin: 0; padding-left: 16px; font-size: 10.5px; line-height: 1.45; }
p.na0, p.exl { font-size: 10.5px; margin: 0; color: var(--ink-2); }
p.exl { color: var(--ink-3); margin-top: 2px; }
.svgc { display: block; font-family: var(--f-body); }
.svgc .ax { font-size: 9.5px; fill: var(--ink-3); font-family: var(--f-mono); }
.svgc .lb { font-size: 10px; fill: var(--ink); }
.svgleg { display: flex; gap: 2px 12px; flex-wrap: wrap; font-size: 10.5px; color: var(--ink-2); margin: 2px 0 0; align-items: center; }
.svgleg i { display: inline-block; width: 10px; height: 3px; border-radius: 1px; margin-right: 4px; vertical-align: 3px; }
.svgleg .small { font-size: 9.5px; }
html[data-print] .srct td { font-size: 10px; padding: 1.5px 6px; line-height: 1.35; }
html[data-print] .srct td.srcs code { font-size: 9.5px; }
html[data-print] .cct td, html[data-print] .cct th { font-size: 10px; padding: 1px 6px; line-height: 1.3; }
html[data-print] .cct td.dir { font-size: 9.5px; color: var(--ink-2); }
html[data-print] .dect td { font-size: 10.5px; padding: 1px 6px; vertical-align: middle; line-height: 1.35; }
html[data-print] .dect .chip { font-size: 10px; padding: 0 6px; line-height: 1.35; }
html[data-print] .askt td, html[data-print] .nat td { font-size: 10.5px; padding: 1.5px 7px; line-height: 1.4; }
code { font-family: var(--f-mono); font-size: .92em; }
.cols2 { columns: 2; column-gap: 28px; }
.cols2 ul.plain { display: block; }
html[data-print] .cols2 ul.plain li { font-size: 10.8px; line-height: 1.4; break-inside: avoid; }
ul.plain { max-width: none; gap: 2px; }
html[data-print] ul.plain li { font-size: 11.5px; line-height: 1.5; }
html[data-print] h3 { margin: 8px 0 3px; font-size: 13.5px; }
html[data-print] .desc { font-size: 11.5px; margin: 0 0 4px; }
html[data-print] .sub { font-size: 11.5px; margin: 0 0 6px; }
.note { margin-top: 10px; }
@page :first { @bottom-left { content: none; } @bottom-right { content: counter(page) " / " counter(pages); font-family: "IBM Plex Mono", monospace; font-size: 8pt; color: #7a8386; } }
@media print {
  main > section { break-before: auto !important; }
  main > section.pg { break-before: page !important; }
  .panel { break-inside: avoid; }
}"""


def build():
    tpl = TEMPLATE.read_text(encoding="utf-8")
    css = re.search(r"<style>(.*?)</style>", tpl, re.S).group(1)
    old_footer = re.search(r'@bottom-left \{ content: "([^"]+)"', css).group(1)
    css = css.replace(old_footer, f"mtscore Phase 2 판단 자료 · 기준일 {AS_OF} · 커밋 {COMMIT} · 예측력 미검증(Phase 3 진행 중)")
    fonts = re.search(r'<link rel="stylesheet" href="(https://fonts\.googleapis\.com[^"]+)">', tpl).group(1)
    body = "".join([masthead(), "<main>", sec_summary(), sec_assets(), sec_method(), sec_data(), sec_decisions(), sec_open(), "</main>"])
    doc = f"""<!doctype html>
<html lang="ko" data-print data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mtscore Phase 2 브리핑</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{fonts}">
<style>{css}{EXTRA_CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""
    out = HERE / "briefing_phase2.html"
    out.write_text(doc, encoding="utf-8")
    print("wrote", out, f"{len(doc) / 1e3:.0f} KB")
    return out


EDGE = "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
WIN_TMP = Path("/mnt/c/Users/infomax/AppData/Local/Temp/mtscore_briefing_pdf")


def winpath(p):
    return subprocess.run(["wslpath", "-w", str(p)], capture_output=True, text=True, check=True).stdout.strip()


def make_pdf(src):
    WIN_TMP.mkdir(parents=True, exist_ok=True)
    s, pdf = WIN_TMP / "briefing_phase2.html", WIN_TMP / "briefing_phase2.pdf"
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
    dst = HERE / "briefing_phase2.pdf"
    shutil.copy(pdf, dst)
    try:
        import pymupdf
        d = pymupdf.open(dst)
        print(f"wrote {dst}  {dst.stat().st_size / 1e6:.2f} MB  {d.page_count} pages  ({time.time() - t0:.0f}s)")
    except ImportError:
        print(f"wrote {dst}")


if __name__ == "__main__":
    h = build()
    if "--no-pdf" not in sys.argv:
        make_pdf(h)
