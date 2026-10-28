# 수동 입력 필요 / 미확보 목록 (Phase 0)

> 2026-10-28 Phase 2 갱신판: `outputs/phase2/manual_input_list.md`

템플릿: `data/manual/TEMPLATE.csv`. 스키마는 `date, asset_id, field, value, as_of, source`이다.
- `as_of`: 그 값이 실제로 알려진 날(공표일).
- 예시 행의 value는 비워 두었다. 실제 값을 채워야 한다.

| 우선 | 자산 | 필드 | 상태 | 대체 경로 |
|---|---|---|---|---|
| 1 | US_HY·US_IG | ICE BofA OAS 2010~2023-10 | FRED는 2023-10-24부터만 | 회사 단말 export(CSV) / IG는 Moody's `BAA10Y` 대리 |
| 1 | KOSPI200 | 지수 PER·PBR·배당(공식) | pykrx는 KRX 로그인 필요 | `KRX_ID`/`KRX_PW` 설정 → pykrx / Refinitiv 바텀업 |
| 1 | KOSPI200 | 과거 구성종목(시장폭·PIT 바텀업) | pykrx는 KRX 로그인 필요, Refinitiv TR.IndexConstituentRIC 0행 | 현재 상위 30종목(비중 85%) 바텀업 — 생존편향, 가정 표기 (R3) |
| 2 | KOSPI200 | 외국인 순매수 | pykrx 로그인 필요(0행), naver HTTP 410 (F3) | KRX 로그인 / 단말 export |
| 2 | 전 주식지수 | 이익수정비율(상향/하향 건수) | 수정 건수 계열 9개 필드 모두 실패(R2) | 필드명 확인(단말 Data Item Browser) / 바텀업 "NTM EPS 상승 종목 비율"로 대체 |
| 3 | KOSPI200 | Put/Call, VKOSPI 기간구조, 신용잔고, 반대매매 | 미확인 | KOFIA·KRX 수동 |
| 3 | KTB10Y | 한국 실질금리·기간프리미엄 | 물가연동채 ECOS 코드 오류로 미해결, 기간프리미엄 미확인 | 실질금리는 KTB10Y − CPI YoY 대리(가정) |
| 3 | 금리 | 경기·물가 서프라이즈 | 미확인 | 단말 export 또는 N/A |
| 3 | WTI | 원유 재고 | FRED `WCESTUS1` 이 HTML 반환(원인 미확인) | EIA API(키 필요) |
| 3 | US_HY | 부도율 | 미확인 | N/A (FRED DRALACBN 은 은행 대손상각률 대리) |
