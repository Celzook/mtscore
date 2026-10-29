import os, sys, json
sys.path.insert(0, "/home/infomax/.claude/templates/hanwha-report")
import hanwha_docx as H
assert getattr(H, "HELPER_VARIANT", None) == "hanwha-report", H.__file__
from hanwha_docx import *  # noqa

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_JSON = os.path.join(HERE, "..", "phase2", "result_2026-10-27.json")
OUT = os.path.join(HERE, "마켓타이밍_요약_261029.docx")

d = json.load(open(SRC_JSON, encoding="utf-8"))
A = {a["asset_id"]: a for a in d["assets"]}
asof = d["as_of"]                                   # 2026-10-27
asof_s = "'" + asof[2:].replace("-", ".")           # '26.10.27

# 계산 예시: KOSPI200 20일 이평선 이격 (JSON 기여도 목록에서 읽음)
ex = next(c for c in A["KOSPI200"]["contributions"] if c["indicator"] == "disparity_20")
ex_raw = abs(ex["raw"]) * 100                       # 9.2
ex_pct = ex["percentile"]                           # 1.2
ex_score = ex["score"]                              # 98.8

NAMES = [("KOSPI200", "KOSPI200"), ("SP500", "S&P500"), ("KTB10Y", "국고10년"),
         ("UST10Y", "미국채10년"), ("USDKRW", "달러/원(원화 매수)"), ("GOLD", "금"),
         ("WTI", "WTI"), ("US_HY", "미국 하이일드"), ("US_IG", "미국 투자등급"),
         ("KR_CORP", "국내 회사채 AA-")]
rows = []
for k, nm in NAMES:
    a = A[k]; bl = a["blocks"]
    rows.append([nm, a["regime"]["display"], f'{bl["oversold"]:.0f}', f'{bl["valuation"]:.0f}',
                 f'{bl["fundamental"]:.0f}', "상승" if a["trend"]["sign"] > 0 else "하락"])
credit_basis = {A[k]["trend"]["basis"] for k in ("US_HY", "US_IG", "KR_CORP")}
assert credit_basis == {"국채 대비", "국고 대비"}, credit_basis

configure(cant_split=True)
doc = new_document("마켓타이밍 점수 검증 결과와 대시보드 반영", "2026.10.29")

exec_summary(doc, [
    [b("마켓타이밍 점수는 '많이 빠졌나·싼가·기초 체력이 받쳐 주나' 같은 세 질문을 자산 10개에 던져 만든 참고 지표이며, 대시보드 홈에 기존 기술 점수와 나란히 반영"),
     (" (정밀 매매 도구 아님)", {})],
    "근거: 질문마다 자산군에 맞는 지표를 골라 자기 과거 대비 위치(0~100)로 바꾸고, 가격을 따라 사는 모멘텀은 점수에서 최소화하는 역발상 방식",
    "다음 단계: 현행 방식 유지 결정(2026.10.29), 대시보드 나머지 33개 자산으로 확장 검토",
], bold_first=False)

section(doc, "점수를 이렇게 만든 이유")
bullet(doc, [b("세 블록, 세 질문"), (": 자산마다 과매도·밸류·펀더멘털 점수를 매기고, 셋을 합친 총점 없이 조합으로 국면 이름을 붙임", {})])
data_table(doc,
    ["자산군", "과매도: 많이 빠졌나", "밸류: 싼가", "펀더멘털: 기초 체력이 받쳐 주나"],
    [["주가지수", "이동평균선 대비 이격, 52주 고점 대비 낙폭, 단기 급락, 볼린저·RSI 동시 판정, 변동성·심리", "선행 PER, 주식위험프리미엄 (KOSPI200은 PBR·배당 추가)", "이익 상향 종목 비중, 선행 이익 전망 변화, 원화 3개월 변화(KOSPI200만)"],
     ["금리", "금리 상승폭(채권값 하락), 볼린저·RSI 동시 판정", "실질금리, 기준금리 대비 스프레드", "물가 둔화, 정책금리 인하 방향"],
     ["환율", "이동평균선 이격, 단기 급락 (원화 약할수록 과매도)", "실질실효환율 (원화가 쌀수록 높음)", "한미 금리차·경상수지 변화"],
     ["금·WTI", "이동평균선 이격, 단기 급락, 투기 포지션", "물가로 나눈 실질가격", "금은 미국 실질금리 하락, WTI는 근월물 우위(백워데이션)·재고 감소"],
     ["크레딧", "스프레드 확대 정도", "스프레드 수준 (넓을수록 높음)", "주식 이익 전망 변화, 등급 간 스프레드 격차 축소"]],
    col_widths_cm=[1.9, 5.2, 3.9, 4.0], size=9.5, aligns="llll")
footnote(doc, "주요 지표만 표시, 자산별로 일부 다름 / PER·PBR은 주가 대비 이익·순자산 배율, RSI는 상승·하락 강도, 볼린저는 평균 대비 이탈 폭, 스프레드는 국채 대비 추가 금리")
bullet(doc, [b("자기 과거 대비 위치"), (f": 지표값을 자산 자신의 과거와 비교해 '과거 몇 %의 날보다 매력적인가'로 환산, 높을수록 매력으로 통일 (예: KOSPI200이 20일 평균선보다 {ex_raw:.1f}% 아래, 이보다 아래였던 날 과거의 {ex_pct:.1f}% → {ex_score:.1f}점)", {})])
bullet(doc, [b("블록 점수는 평균"), (": 같은 묶음 안 지표끼리, 이어 묶음끼리 평균(볼린저·RSI 동시 판정 묶음은 둘 중 낮은 점수)하고 자산 간 점수는 직접 비교하지 않음", {})])
bullet(doc, [b("역발상 철학"), (": 모멘텀은 점수에서 최소화하고 많이 빠질수록 높게 매김, 추세(최근 12개월 수익이 현금보다 높은지)는 점수와 별도로 상승·하락 표시, 변동성이 평소보다 크면 과매도 쪽으로 봄(설계상 가정)", {})])
bullet(doc, [b("결정(2026.10.29)"), (": 추가 표시 두 가지(크레딧 추세 국채 대비, 과매도 극단 지표 개수) 반영, 지표 추가·변경은 하지 않기로 결정", {})])

section(doc, "대시보드 반영 (1단계)")
bullet(doc, "Stock_Dashboard 홈 유니버스 점수판의 겹치는 7개 자산(KOSPI 종합 타일은 KOSPI200 점수 대용, 달러/원은 원화 매수 관점)에 마켓타이밍 국면 표시, 팝오버에 블록 점수·추세·극단 지표 개수 제공")
bullet(doc, "10개 자산 표(크레딧 포함)를 추가하고 기존 기술 점수와 나란히 보여 줄 뿐 합치지 않음, 임계값 이벤트 신호는 보류")
data_table(doc, ["자산", "국면", "과매도", "밸류", "펀더", "추세"], rows,
           col_widths_cm=[3.4, 4.6, 1.6, 1.6, 1.6, 1.6], size=10, aligns="llcccc")
footnote(doc, f"국면 이름은 세 블록의 높음·낮음(50점 기준) 조합, 극단 지표 개수는 과매도 지표 중 80점 이상·20점 이하 개수, {asof_s} 기준, 블록 점수는 자기 과거 대비 0~100(높을수록 매력), 추세는 현금 대비(상승·하락)이며 크레딧은 국채(국내는 국고) 대비")

section(doc, "한계와 다음 단계")
bullet(doc, "과거 수익률을 맞히는 용도가 아닌 참고 지표, 지표 선정은 설계 판단")
bullet(doc, "대상은 대시보드 41개 자산 중 7개 + 크레딧 3개(대시보드 점수판에는 없음), 수치는 '26.10.27 기준")
bullet(doc, "다음 단계: 나머지 33개 자산 확장(팩터·섹터 ETF는 새 블록 정의 필요), 임계값 이벤트 신호는 보류 유지")
footnote(doc, "상세 전문: outputs/guide/scoring_model_guide.html, outputs/phase5/phase5_easy.html, mtscore CLAUDE.md '확정 결정', outputs/phase2/result_2026-10-27.json, docs/dashboard_universe.md")

save(doc, OUT)
print("saved", OUT)
