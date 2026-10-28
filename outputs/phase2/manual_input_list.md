# 수동 입력 필요 / 미확보 목록 (Phase 2 갱신, 2026-10-28)

Phase 0 목록(`outputs/phase0/manual_input_list.md`)을 Phase 2 실측으로 갱신했다. 템플릿: `data/manual/templates/phase2_na_fields.csv`
(스키마 `date, asset_id, field, value, as_of, source`, value 는 비어 있음). 채운 파일은 `data/manual/` 바로 아래에 두면 `CsvAdapter`가 읽는다.

| 우선 | 자산 | 필드 | Phase 2 상태 | 대체 경로 |
|---|---|---|---|---|
| 1 | KOSPI200 | foreign_net_buy·inst_net_buy | N/A. pykrx 는 KRX_ID/KRX_PW 필요(계정 없음). `~/.config/krx_key` 는 KRX Open API AUTH_KEY 이고 투자자별 매매 응답이 없다. naver HTTP 410 | KRX 로그인 계정 / 정보데이터시스템 export |
| 1 | KOSPI200 | 과거 구성종목(PIT) | 미해결 → 현재 구성종목 바텀업으로 대체(생존편향, 사용자 결정 2026-10-28) | KRX 로그인 → pykrx `get_index_portfolio_deposit_file` |
| 1 | KOSPI200 | 공식 지수 PER·PBR·배당 | 미해결 → 바텀업(`fwd_per`·`pbr`·`div_yield`)으로 대체 | KRX 로그인 → pykrx `get_index_fundamental` |
| 2 | 전 주식지수 | 이익수정비율(상향/하향 건수) | N/A(수정 건수 필드 실패, Phase 0) → `eps_up_share` 바텀업으로 대체 | 단말 Data Item Browser 로 필드명 확인 |
| 2 | US_HY·US_IG | ICE BofA OAS 2010~2023-10 | 불필요해짐(iBoxx G-스프레드로 대체, 2023-10~ OAS 와 대조: HY 수준 상관 0.98, IG 0.77) | — |
| 3 | KOSPI200 | Put/Call, VKOSPI 3개월물(기간구조), 신용잔고, 반대매매 | N/A(미확인) | KRX·KOFIA 수동 |
| 3 | KTB10Y | 실질금리(물가연동채)·기간프리미엄·선물 포지셔닝 | 실질금리는 KTB10Y − CPI YoY 대리(가정), 나머지 N/A | ECOS 물가연동채 항목코드 확인 |
| 3 | 금리 | 경기·물가 서프라이즈 | N/A(미확인) | 단말 export |
| 3 | USDKRW | 교역조건 | N/A(ECOS 403Y 미확인) | ECOS 항목코드 확인 |
| — | WTI | 원유 재고 | **해결**: lseg `PS-ESPR-EIA`(EIA 주간, SPR 제외) 2008~ | — |
| 3 | US_HY·US_IG·KR_CORP | 부도율 | N/A(미확인) | 신평사 자료 |
