# 다음에 할 일 (2026-10-26 중단 시점)

현재 상태: Phase 0 → 1 → 프로파일 검토까지 끝났다(`336d216`, 테스트 137개). 이 문서는 다음 세션의 작업 목록이다.
결정 이력과 데이터 소스 함정은 `CLAUDE.md`에, 확보 근거는 `outputs/phase0/coverage_matrix.md`에 있다.

진행 방식(사용자 요청)
- 결정이 필요할 때마다 AskUserQuestion으로 묻는다.
- Phase마다 끝날 때 별도 레인(워크플로 리뷰와 반박 검증)으로 검증한 뒤 보고하고 멈춘다.

---

## 0. 시작 전 확인
- [ ] `~/.config/mtscore/env`가 있는지 확인한다. 키 **이름만** 출력한다. 필요한 키는 `ECOS_API_KEY`, `FRED_API_KEY`, `KRX_ID`, `KRX_PW`이고, `EIA_API_KEY`는 선택이다.
- [ ] KRX 로그인으로 pykrx가 실제로 되는지 확인한다(지수 펀더멘털, 과거 구성종목, 투자자 수급). 안 되면 아래 '대체'를 쓴다.
- [ ] Phase 0에서 미확인으로 남은 RIC를 확인한다.
  - `KRCORP=KQ`(회사채 BBB−)
  - UST 2·5·7·30년 RIC(iBoxx G-스프레드 보간용)
  - WTI 재고(EIA API 또는 Refinitiv)
  - USDKRW 내재변동성은 이번 범위에서 뺐다

## 1. Phase 2 — 실데이터 수집과 지표 계산 (10개 자산)
### 1-1. 어댑터 (`src/mtscore/data/adapters/`)
모든 어댑터는 출력이 `validate_panel`을 통과해야 한다. 원자료는 `data/raw/`, 수동 입력은 `data/manual/`에 둔다.

| 어댑터 | 방식 | 주의 |
|---|---|---|
| `refinitiv.py` | WSL에서 Windows `python.exe`(eikon + pandas shim)를 subprocess로 호출, 키는 stdin | `.SPX`는 `get_data TR.PriceClose Frq=D`. 월별 컨센서스 날짜는 불규칙하다 |
| `lseg.py` | `%LOCALAPPDATA%\lsegvenv` python.exe로 `get_history` 호출 | iBoxx `.IBLUS0004`(HY)·`.IBLUS0005`(IG) |
| `fred.py` | `User-Agent: curl/8`(브라우저 UA는 응답 없음) | `<!DOCTYPE` 응답은 HTML이므로 거부. ICE OAS는 2023-10~만 있다(대조용) |
| `ecos.py` | 정식 키로 페이징 | 항목코드 오류 2건 주의(CLAUDE.md) |
| `cftc.py` | Socrata `6dca-aqww` legacy | 금 088691, WTI 067651, UST10Y 043602 |
| `krx.py` | pykrx(KRX 로그인) | 실패하면 Refinitiv 바텀업으로 대체 |
| `eia.py` | 선택 | 키가 없으면 건너뛴다 |

### 1-2. 자산별 필드 매핑
| 자산 | 필드 → 소스 |
|---|---|
| KOSPI200 | close `.KS200`, close_tr `.KS200TR`, vol_index `.KSVKOSPI`, pbr·div_yield(pykrx 공식, 또는 바텀업), fwd_per·fwd_eps_12m·eps_up_share(구성종목 바텀업 `TR.EPSMean NTM` 월별), 시장폭 4개(구성종목 일봉), foreign_net_buy(pykrx) |
| SP500 | close `TR.PriceClose`, vol_index FRED `VIXCLS`, vol_index_3m `VXVCLS`, fwd_per `TR.PtoEPSMeanEst`, fwd_eps_12m `TR.EPSMean(NTM)`, eps_up_share(SPY 구성종목 바텀업 — 결정 필요) |
| KTB10Y | yield `KRTSY10Y=KQ`, policy_rate `KRBASE=BOKK`, cpi ECOS 901Y009, real_yield = KTB10Y − CPI YoY(대리지표·가정) |
| UST10Y | yield `US10YT=RR`, real_yield `DFII10`, policy_rate `DFF`, term_premium `THREEFYTP10`, cot_net CFTC, cpi `CPIAUCSL`, nfci `NFCI` |
| USDKRW | close `KRW=KFTC`(서울 마감), reer `RBKRBIS`, rate_diff = KTB10Y − UST10Y, current_account_12m(ECOS 301Y013 12개월 합) |
| GOLD | close `GCc1`, cot_net CFTC, cpi `CPIAUCSL`(real_yield_us는 refs) |
| WTI | close `CLc1`, close_c2 `CLc2`, cot_net CFTC, cpi, inventory(확인 후) |
| US_HY·US_IG | spread = iBoxx `YLDTOMAT` − 같은 `MOD_DURTN`의 UST 보간, index_level `TRDPRC_1`(총수익지수인지 확인). 2023-10 이후는 FRED ICE OAS와 상관을 대조한다 |
| KR_CORP | spread = AA−(3년) − 국고3년, spread_low_grade = BBB−(`KRCORP=KQ`) − 국고3년(확인 후) |

### 1-3. PIT as_of 규칙 (어댑터에서 넣는다. 확인하지 않은 것은 '가정'으로 표기)
- CPI: 기준월 + 공표 시차(미국 약 2주, 한국 익월 초).
- REER: 약 3개월 지연. 경상수지: 약 1개월 지연.
- CFTC COT: 화요일 기준, 금요일 공표.
- NFCI: 주간 공표 시차를 따른다. Kim-Wright 기간프리미엄도 공표 지연을 확인한다.
- Refinitiv 월별 컨센서스: 반환된 날짜를 as_of로 쓴다.
- 시장 간 시차: 미국 지표를 한국 자산에 쓰면 as_of를 +1일 한다.

### 1-4. 산출과 보고
- [ ] 자산별 커버리지(지표마다 사용/제외와 사유), 최근 지표값, 최신 점수와 국면.
- [ ] 받을 수 없는 것은 날조하지 않고 N/A로 두고, `manual_input_list.md`를 갱신한다.
- [ ] 별도 레인에서 검증한다: 원천 대조 표본 점검, PIT 점검, 재현.
- [ ] 보고하고 멈춘다.

## 2. Phase 3 — 백테스트와 검증
- [ ] `core/backtest.py`와 `engine.backtest(panel, horizons=[21, 63, 126, 252])`.
- [ ] 자산별 forward return 규칙
  - KOSPI200: close_tr
  - USDKRW: 원화 가격(역수)
  - KTB10Y·UST10Y·KR_CORP: −D×Δy + 캐리(가정)
  - US_HY·US_IG: iBoxx 레벨
  - WTI: 연속물 롤 처리 결정
- [ ] 집계 통계
  - 5분위와 극단 구간별 평균·중앙값 수익률, 승률, MAE.
  - 이벤트 스터디: 쿨다운 20영업일, 이벤트 리스트 출력.
  - Spearman IC와 Newey-West t.
  - 국면별 forward return.
  - 자산군 풀링 분석.
- [ ] 모든 통계에 n을 붙이고, n<10이면 '표본 부족'으로 경고한다. 튜닝 금지가 기본이다.
- [ ] 비교 실험
  - 통화 이중반영 3개 변형.
  - expanding vs rolling.
  - 가격 지표 제외 규칙(사전 등록): 전반부에서 상관 > 0.9인 쌍의 IC 열위 쪽을 후보로 두고, 후반부에서 IC가 나빠지지 않을 때만 뺀다.
- [ ] 멈추고 묻는다: 통화 변형을 무엇으로 할지, 국면 임계값을 유지할지.

## 3. Phase 4 — 리포트
- [ ] 엑셀(openpyxl), HTML 대시보드, 인쇄용 PDF(Edge 헤드리스, 메모리 `headless-render-wsl`), JSON.
- [ ] 회사 양식 DOCX는 `/hanwha-report`로 만든다. 보고서 유형(표준 개조식, 서술형, 쉬운판, 요약본)은 먼저 묻는다.

## 4. Phase 5 — 호스트 이식
- [ ] 사용자에게 호스트 프로젝트 경로를 받는다.
- [ ] 구조를 읽기 전용으로 분석한다.
- [ ] 이식 계획서를 낸다: 의존성, 호출 위치, 데이터 공급 방식, 스케줄.
- [ ] 승인을 받은 뒤 별도 브랜치에서 작업한다.

## 5. 사용자에게 물어야 할 결정 (해당 Phase에서)
- KOSPI200 바텀업: pykrx 과거 구성종목(PIT) vs 현재 상위 30종목(생존편향).
- S&P500 eps_up_share: SPY 구성종목 바텀업을 할지, 몇 종목까지 할지.
- CPI 등 공표 시차 값.
- 듀레이션 가정(KTB·UST 8.5, KR_CORP 2.7).
- WTI 롤 처리.
- iBoxx가 가격지수이면 쿠폰을 반영할지.

## 6. 정리할 것 (이 프로젝트 밖, 사용자 확인 후)
- [ ] 학습 스킬 `kr-market-free-data-sources`: naver `investorDealTrendDay`가 '가능'으로 적혀 있지만 2026-10-26 실측은 HTTP 410이다. 수정을 제안한다.
- [ ] Refinitiv 레퍼런스 README에 추가를 제안한다: ICE BofA 권한 없음(lseg-data), iBoxx 지수 사용 가능, 열별 이력 시작 시점.
- [ ] 기술적분석 저장소
  - 미추적 파일: `market_timing_prompt.md`, `40_report/review_qa_detail.pdf`.
  - origin보다 1커밋 뒤처져 있다(`50_review` 미반영).
  - 이전에 제안했지만 요청받지 않은 엔진 수정 H1~H3.
