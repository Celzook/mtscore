"""Phase 2 — coverage.csv·latest_*.csv·field_map.csv → 읽기용 마크다운(outputs/phase2/coverage.md, latest.md).

    .venv/bin/python scripts/phase2_tables.py
"""
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "outputs" / "phase2"
NA_REASON = {   # 지표 → 사람이 읽는 N/A 사유(근거: phase2_report.md §3)
    "vol_term_inversion": "VKOSPI 기간구조(3개월물) 소스 없음 — vol_index_3m 미확보",
    "put_call": "Put/Call 소스 미확인(KRX·KOFIA·CBOE) — na_until_found",
    "foreign_net_buy_intensity": "투자자별 순매수 소스 없음: pykrx 는 KRX_ID/KRX_PW 로그인 필요(계정 없음), "
                                 "KRX Open API(AUTH_KEY) 응답에 투자자별 매매 없음, naver HTTP 410",
    "inst_net_buy_intensity": "위와 같음(기관 순매수) — na_until_found",
    "margin_debt_change": "신용잔고(KOFIA) 미확인 — na_until_found",
    "forced_liquidation": "반대매매(KOFIA) 미확인 — na_until_found",
    "revision_ratio": "수정 건수 필드 실패(Phase 0) → revision_breadth(바텀업 상향 비중)로 대체",
    "macro_surprise": "경기·물가 서프라이즈 소스 미확인 — na_until_found",
    "terms_of_trade_trend": "교역조건(ECOS 403Y) 미확인 — na_until_found",
    "default_trend": "부도율 소스 미확인 — na_until_found",
}


def main():
    c = pd.read_csv(OUT / "coverage.csv")
    lat = pd.read_csv(OUT / "latest_indicators.csv")
    fm = pd.read_csv(OUT / "field_map.csv")
    sc = pd.read_csv(OUT / "latest_scores.csv")
    lines = ["# Phase 2 커버리지 — 자산별 지표 사용/제외와 사유 (기준일 2026-10-27)", "",
             "`used` = 계산에 들어감, `available` = 기준일에 점수가 있음. 사유 원문은 `coverage.csv`.", ""]
    for aid, g in c.groupby("asset_id", sort=False):
        lines += [f"## {aid}", "", "| 블록 | 하위블록 | 지표 | 사용 | 첫 점수일 | 사유 |", "|---|---|---|---|---|---|"]
        for _, r in g.iterrows():
            why = "" if r["available"] else str(r["reason"])
            if not r["used"] and str(r["reason"]).startswith(("status:", "missing_field")):
                why = f"{r['reason']} — {NA_REASON.get(r['indicator'], '')}"
            elif str(r["reason"]).startswith("override_exclude"):
                why = f"{r['reason']} (universe.yaml)"
            lines.append(f"| {r['block']} | {r['sub_block']} | {r['indicator']} | {'O' if r['available'] else '—'} | "
                         f"{r['first_score_date'] if isinstance(r['first_score_date'], str) else ''} | {why} |")
        lines.append("")
    (OUT / "coverage.md").write_text("\n".join(lines), encoding="utf-8")

    L = ["# Phase 2 최신값 (기준일 2026-10-27)", "", "## 블록 점수·국면", "",
         "| 자산 | 날짜 | 과매도 | 밸류에이션 | 펀더멘털 | 국면 |", "|---|---|---|---|---|---|"]
    for _, r in sc.iterrows():
        L.append(f"| {r['asset_id']} | {r['date']} | {r['score_oversold']:.1f} ({r['band_oversold']}) | "
                 f"{r['score_valuation']:.1f} ({r['band_valuation']}) | {r['score_fundamental']:.1f} ({r['band_fundamental']}) | "
                 f"{r['display']} |")
    L += ["", "## 지표 원시값·백분위·점수", "", "| 자산 | 블록 | 지표 | 원시값 | 백분위 | 점수 | 블록 비중 |",
          "|---|---|---|---|---|---|---|"]
    for _, r in lat.iterrows():
        f = lambda v, n=3: "" if pd.isna(v) else f"{v:.{n}f}"  # noqa: E731
        L.append(f"| {r['asset_id']} | {r['block']} | {r['indicator']} | {f(r['raw'], 4)} | {f(r['percentile'], 1)} | "
                 f"{f(r['score'], 1)} | {f(r['weight_in_block'], 3)} |")
    (OUT / "latest.md").write_text("\n".join(L), encoding="utf-8")

    F = ["# Phase 2 소스 → 필드 지도 (as_of 규칙 포함)", "", "| 자산 | 필드 | 소스 | as_of 규칙 | 행 | 기간 | 비고 |",
         "|---|---|---|---|---|---|---|"]
    for _, r in fm.iterrows():
        F.append(f"| {r['asset_id']} | {r['field']} | {r['source']} | {r['as_of_rule']} | {r['rows']} | "
                 f"{r['first']}~{r['last']} | {'' if pd.isna(r['note']) else r['note']} |")
    (OUT / "field_map.md").write_text("\n".join(F), encoding="utf-8")


if __name__ == "__main__":
    main()
