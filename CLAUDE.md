# mtscore — 멀티에셋 마켓타이밍 스코어링 엔진

원본 스펙: `../기술적분석/market_timing_prompt.md`. 결정 이력은 `outputs/phase*/` 보고서에 있다.

## 설계 원칙
- **자산 추가는 설정 추가**
  - `config/universe.yaml` 항목과 `config/profiles/<asset_class>.yaml`만 고친다.
  - 코어 코드를 고쳐야 한다면 설계 결함으로 보고한다.
- **코어와 I/O 분리**
  - `src/mtscore/core/`는 순수 함수다(DataFrame in → 결과 out). 파일·네트워크 접근 금지.
  - 수집은 `src/mtscore/data/adapters/`가 맡는다. 출력은 모두 `data/schema.py` 검증을 통과해야 한다.
- **Point-in-time**
  - t 시점 점수는 t에 알 수 있던 값(`as_of ≤ t`)만 쓴다.
  - 백분위는 expanding(워밍업 3년)이고, rolling 10년은 비교용이다.
- **결측**
  - 일별 필드: 최대 5영업일까지 ffill.
  - 월별·주별 필드: 다음 공표 전까지 유지.
  - 데이터가 없거나 적용할 수 없는 지표·블록은 N/A로 두고 coverage에 사유를 남긴다. 다른 값으로 대체하지 않는다.
- **날조 금지**: 받을 수 없는 데이터는 추정·생성하지 않는다. `data/manual/` 템플릿으로 받는다.
- **하드코딩 금지**: 지표·가중치·임계값·윈도우는 YAML에 둔다.
- **가정 표기**: 검증하지 않은 가정은 코드 주석과 보고서에 "가정"으로 적는다.
  - 예: 금리·크레딧 수익률의 듀레이션 근사
  - 예: KOSPI200 바텀업의 생존편향
- **합성 데이터**: 테스트 전용이다. 보고 결과에 쓰지 않는다.
- **튜닝**: 금지가 기본이다. 튜닝할 때는 표본 분할 검증 결과를 함께 낸다.

## 코어 설계 (Phase 1)
- **레지스트리는 두 층이다**
  - 계산 함수(`core/indicators/*`, `@register`): 자산과 무관한 순수 함수다.
  - 지표 정의: 프로파일 YAML 항목이다. name, indicator(=계산 함수), block, sub_block, fields, direction, params, status, flags, weight를 갖는다.
  - 같은 함수를 파라미터만 바꿔 여러 지표로 쓸 수 있다.
- **자산 설정**(`universe.yaml`)
  - `refs`: 다른 자산의 필드를 빌려 쓴다. 변환 전 원값이다.
  - `field_transforms`: reciprocal, negate.
  - `overrides`: exclude(지표·블록·하위블록), weights, params, add(자산 전용 지표).
  - 오타는 모두 ConfigError로 거부한다.
- **PIT 처리**
  - `pit_frame`이 가용일(as_of)로 색인한 최신값을 만든다.
  - 값을 유지하는 기간은 그 관측까지의 기준일 간격 중앙값으로만 정한다(인과적). 저빈도면 70일, 일별이면 5일이다.
  - 전체 이력으로 빈도를 판정하면 미래 행이 과거를 바꾼다(리뷰 pit-1).
- **자산 달력**
  - 자기 가격 필드(close, yield, spread 중 하나, 또는 `calendar_field`) 가운데 PIT로 채택된 관측의 가용일이다.
  - 휴장일에 값을 복제하면 롤링 합과 수익률이 왜곡되기 때문이다.
  - 빈도로 달력을 고르지 않는다. 고르면 미래 행이 과거 달력을 바꾼다(2차 검증 a). 늦은 수정 행은 달력일을 만들지 않는다(2차 검증 b).
  - 기준일보다 자산 달력일이 `daily_ffill_max_bdays` 넘게 오래되면 stale로 본다. 블록 N/A, `unavailable_at_as_of`, 순위 제외다.
  - 다른 시장의 refs는 이 달력에 맞춰 최대 5일까지 유지한다.
  - **가정**: refs 원천의 마감 시각이 이 자산보다 늦으면(예: 미국 지표를 한국 자산에 쓰는 경우) 공급자가 as_of를 하루 늦춰 넣어야 한다.
- **월 단위 변화**(`pct_change_months`, `diff_months`, `revision_momentum`)
  - 고정 21영업일이 아니라 달력월 기준이다. `t − n개월` 시점의 달력값과 비교한다.
  - 그 시점에 유지 한도를 넘겨 결측이었으면 결측이다. 오래된 값을 되살리지 않는다.
  - **가정**: '지금 알려진 값 vs n개월 전에 알려진 값' 정의를 쓴다. 공표일이 매달 흔들리는 월별 필드는 약 4%의 날에 직전 공표가 아니라 그 전 공표와 비교된다.
- **결과 동작**
  - coverage `available`이 거짓이면 reason은 `unavailable_at_as_of`다.
  - 부분판정은 `regime.display`에 표기한다.
  - 결과 JSON 스키마: `docs/result_schema.md`.
- **리뷰 회귀 테스트**: `tests/test_review_gaps.py`. 리뷰 2회(4관점 리뷰와 반박 검증, 수정 검증과 회귀 탐색)에서 나온 결함마다 테스트가 있다. 고치기 전 동작을 되살린 뮤턴트 17개가 모두 이 테스트에 걸린다.
- **설정 검증**: scoring.yaml의 알 수 없는 키, overrides 형식 오류, 비유한 가중치는 모두 ConfigError로 거부한다.
  `sub_block_agg`의 키 형식(공백 없는 `block.sub_block`, 점 하나)·값(mean·min) 오류도 ConfigError다.
  어느 프로파일에도 없는 하위블록 키는 `load_config`(전 프로파일)에서 ConfigError다. `build_config`는 기본으로 경고만 한다
  (scoring.yaml은 자산군 공유라 일부 프로파일만 넘기는 dict 설정에서는 키가 비는 것이 정상). `strict_agg_keys=True`면 오류다.

## 확정 결정 (2026-10-26)
- 표본 2010~, 일별 산출.
- 유니버스 10개: KOSPI200, S&P500, KTB10Y, UST10Y, USDKRW, 금, WTI, US HY, US IG, 국내 회사채.
- USDKRW는 원화 매수 관점이다.
- 미국 HY·IG 스프레드: iBoxx USD Liquid HY·IG(`.IBLUS0004`·`.IBLUS0005`) 만기수익률 − 같은 듀레이션 UST(G-스프레드). ICE OAS는 Refinitiv 권한 없음, FRED 2023-10~.
- KOSPI200: KRX 계정(`KRX_ID`/`KRX_PW`)으로 pykrx 공식 지수 펀더멘털·과거 구성종목·수급을 우선한다. 이익수정비율은 바텀업 확산지표(1개월 전보다 NTM EPS가 오른 종목의 시총 비중)로 대체한다(가정).
- S&P500 밸류에이션은 Fwd PER·ERP만 쓴다(ERP는 PER과 겹치지만 유지).
- 프로파일 검토 결과(2026-10-26)
  - 주가지수에서 신용스프레드 지표를 뺐다(크레딧 자산과 중복).
  - 금리 Fundamental: 물가 모멘텀(CPI YoY 3개월 변화), 기준금리 6개월 방향, NFCI 3개월 변화(미국만).
  - 크레딧 Fundamental: 같은 지역 주가지수 Fwd EPS 3개월 변화, 하위−상위 등급 스프레드 차이 추세.
  - 금 Fundamental: 커브 대신 미국 실질금리 3개월 변화.
  - USDKRW에 RSI 14를 추가했다.
  - WTI 재고는 Phase 2에서 EIA·Refinitiv로 확인한다. → 2026-10-28 lseg `PS-ESPR-EIA`로 확보.
  - 주가지수 가격 지표 8개는 유지한다. Phase 3에서 미리 정한 규칙으로 판단한다: 전반부 상관 > 0.9인 쌍에서 IC가 낮은 쪽을 후보로 두고, 후반부에서 뺀 블록의 IC가 나빠지지 않을 때만 뺀다.
- 통화 이중반영은 3개 변형을 비교한다(기본값 both). 확인 트리거는 보류한다.

## 확정 결정 (2026-10-28) — 기술 점수 역발상화
- 원칙: 모멘텀은 최소화하고, 과매도·과도한 낙폭일수록 점수를 높인다. 밸류에이션 결합은 기존 국면 매트릭스 그대로다.
- **confluence 하위블록**(oversold, 5개 자산군 모두): `bb_pctb_20`(볼린저 %b, 20일·2σ) + `rsi_14`.
  - 집계는 `scoring.yaml sub_block_agg: {oversold.confluence: min}`(퍼지 AND). "볼린저 하단 근접"과 "과매도"가 동시에 성립할 때만 높다.
  - equity_index·fx의 `rsi_14`는 price에서 confluence로 옮겼다(이름 유지). commodity·rates·credit에는 새로 넣었다.
  - 금리(yield)·크레딧(spread)은 direction +(금리·스프레드 상단 = 채권·크레딧 과매도). RSI를 수준 차분에 쓰는 해석은 가정이다.
- **변동성**: 평소보다 높은 변동성이면 과매도 점수를 올린다(패닉 = 기회, 가정: 미검증).
  - equity_index `vol_sentiment`에 `rv_ratio_20`, fx·commodity `volatility` 하위블록에 `rv_ratio_20`, rates·credit `volatility`에 `level_rv_ratio_20`.
  - `rv_ratio` = 실현변동성(20일, 로그수익률) ÷ 그 실현변동성의 현재값 포함 252일 평균. `level_rv_ratio`는 1차 차분판(disparity/level_disparity 짝).
- **기관 순매수**: equity_index flows에 `inst_net_buy_intensity`(flow_intensity, direction −, `na_until_found`).
  방향은 외국인과 같다고 가정한다. 소스는 pykrx(KRX 로그인)로 확인할 예정이다.
- **코어 변경(설계 결함 보고)**: 하위블록 min 집계는 설정만으로 표현할 수 없어 `core/scoring.py`·`api.py`·`config.py`를 고쳤다.
  - min 하위블록은 지표 가중치를 쓰지 않는다. 그날까지 점수가 나온 지표가 그날 하나라도 결측이면 하위블록 결측이다.
    아직 워밍업 중인 지표는 빼고 본다. 전체 이력 coverage로 정하면 이력값과 그날로 잘라 계산한 값이 달라진다(PIT).
  - 알려진 동작: min 하위블록에서 점수가 나오다가 영구히 끊긴 지표(중단 시리즈)가 있으면 그 뒤 하위블록은 계속 결측이다.
  - min 하위블록 지표를 `overrides.weights`로 가중하면 ConfigError다(가중치가 무시되므로). 빼려면 `overrides.exclude`를 쓴다.
  - 기여도: 최솟값을 낸 지표가 하위블록 비중 전체를 갖고, 나머지는 0이다(기여도 합 = 블록 점수 유지).
  - `bb_pctb`의 σ는 pandas 기본 ddof=1이다(통상 볼린저 ddof=0보다 밴드가 약간 넓다).

## 확정 결정 (2026-10-28) — Phase 2 데이터
- **KOSPI200 컨센서스·시장폭**: 현재 구성종목(KODEX200 `069500.KS` 보유종목 201개, `TR.FundHoldingRIC`) 바텀업.
  `fwd_per`·`pbr`·`div_yield`·`fwd_eps_12m`·`eps_up_share`·시장폭 4개. **가정: 생존편향**(과거 구성 아님). KRX 로그인이 생기면 과거 구성종목으로 바꾼다.
  - `fwd_per` = Σ시총 ÷ Σ(시총×EPS_NTM÷주가), `pbr` = Σ시총 ÷ Σ(시총÷PBR), `div_yield` = 시총가중 평균.
  - `fwd_eps_12m` = 같은 종목(전월·당월 모두 있음)의 합산 선행이익 증가율 연쇄지수(첫 달 100, 주식 수는 전월 고정). 수준은 임의 단위.
- **S&P500 eps_up_share**: SPY 보유종목 전체(503개) 바텀업. **가정: 생존편향**.
  - 정의: 1개월 전보다 NTM EPS 평균이 오른 종목의 시총 비중(가중치 = 전월 표본일 시총, 0~1).
  - 가정: NTM 창이 매달 앞으로 굴러가 이익 성장 종목은 수정 없이도 오른다(상향 편향). 수준이 아니라 자기 역사 백분위로만 쓴다.
- **WTI 연속물**: 비율 백어저스트(마지막 값 = 실제 근월물).
  - 교체일 = NYMEX 최종거래일(인도월 전월 25일의 3영업일 전, 25일이 휴일이면 직전 영업일 기준) 다음 거래일. 영업일 = 관측 거래일(가정).
  - 교체일 5영업일 전에 다음 월물(그때의 `CLc2`)로 갈아탄다(가정: 2020-04-20 근월물 −37.63 회피).
  - c1/c2 단순 신호(|c1_t−c2_{t−1}|<|c1_t−c1_{t−1}|)는 잡음으로 연 104회 참이라 단독 사용 불가 → 검증용(규칙 교체일 k=0 에서 참 비율 최대).
  - `close`는 연속물이라 수준·커브 비교에 맞지 않는다 → WTI만 `real_price_level`·`backwardation`을 빼고 원 근월물(`close_c1_raw`)판 `real_price_level_spot`·`backwardation_spot`을 `universe.yaml`에 추가(설정만 변경).
- **기본값 수용(가정)**: 듀레이션 KTB·UST 8.5, KR_CORP 2.7. CPI 공표 시차 한국 = 다음 달 5일. 미국 CPI 는 아래 E(ALFRED 실제 공표일)로 대체.
  iBoxx `TRDPRC_1`은 총수익지수다(`TRTN_PRICE`와 전 구간 동일, 2026-10-28 확인) → 쿠폰을 더하지 않는다.
- **G-스프레드**(US_HY·US_IG, 아래 A 로 대체됨): `YLDTOMAT` − 같은 수정듀레이션의 액면가 국채 수익률. UST 1·2·3·5·7·10·30년 `=RR` 커브에서 듀레이션 → 만기 → 수익률 순으로 선형 보간(가정).
  만기 = 듀레이션으로 놓는 단순판은 IG 에서 ICE OAS 와 수준 상관 0.40, 이 방식은 0.77(평균만기 `AVG_LIFE` 매칭은 0.94 — 미채택, 결정 필요).
- **Refinitiv 월별 컨센서스 as_of**: 반환 날짜가 아니라 **표본일**(월말·스냅숏일)을 쓴다. 반환 날짜는 마지막 변경일이라 다음 달에도 같은 날짜가 다른 값으로 온다(NTM 혼합). 표본일 ≥ 반환 날짜라 더 보수적이다.

## 확정 결정 (2026-10-28) — Phase 2 검증 후 사용자 결정
- **A. G-스프레드 = 평균만기 매칭**(US_IG·US_HY 모두): `YLDTOMAT` − 지수 `AVG_LIFE`(년) 만기의 UST 커브 수익률(선형 보간).
  듀레이션 매칭판은 비교용 필드 `spread_dur_matched`로 남긴다(점수 미사용).
- **B. 금 연속물 = 활성월 비율 백어저스트**: 활성월 G·J·M·Q·V·Z, 첫 통지일(인도월 전월 마지막 영업일) 5영업일 전에 다음 활성월로 교체.
  `GCc1`은 그달 계약(그달 끝에서 3번째 영업일 = 최종거래일까지)이고 c1~c4 는 연속한 4개 달이다 → 보유 계약의 가격을 c1~c4 중에서 고른다.
  실질가격은 원 근월물 `close_c1_raw`(`real_price_level_spot`, WTI 와 같은 방식).
- **C. KOSPI200 이익 지표**: 주 점수는 시총가중(Σ시총/Σ이익) 그대로. 민감도 필드(점수 미사용, Phase 3 비교용):
  `fwd_per_ew`·`fwd_eps_12m_ew`·`eps_up_share_ew`(동일가중), `*_ex2`(삼성전자·SK하이닉스 제외 시총가중).
- **D. 승인**: 월별 컨센서스 as_of = 표본일, WTI NYMEX 규칙·5영업일 전 교체, WTI `_spot` 실질가격·커브, EIA 재고.
  근월물 가격이 0 이하인 날(2020-04-20 WTI −37.63)은 `close_c1_raw`를 결측으로 둔다(`_spot` 지표가 그날 N/A).
- **E·F. ALFRED 실시간 값**: `CPIAUCSL`·`NFCI`·`THREEFYTP10`은 최신 수정치가 아니라 **최초 공표값**, as_of = 최초 공표 빈티지 날짜.
  키 없이 `alfred.stlouisfed.org/graph/alfredgraph.csv?id=..&vintage_date=..`로 받는다(요청당 12개 빈티지까지). 평일마다 빈티지를 받아 관측이 처음 나온 날을 찾는다.
  첫 빈티지 이전 구간은 N/A(수정치로 채우지 않는다).
- 미국 +1영업일(`DFII10`·`DFF`)은 미국 연방 공휴일·성금요일을 뺀 영업일이다. 정부 셧다운 공표 지연은 반영하지 못한다(가정).

## 확정 결정 (2026-10-29) — 위키 모델 검토 후 (브랜치 `phase4-wiki`)
- 근거는 `outputs/briefing_wiki/briefing_wiki.pdf`, 판정 규칙은 `docs/prereg_2026-10-29.md`(사전 등록, 결과 보기 전 고정)에 있다.
- **변동성 가점**: 과매도일 때만 가점을 준다(조건 = 원 지표 `bb_pctb_20`이 과매도 쪽 밴드 밖, 그 밖의 날은 1.0). 국면에 "분할 진입" 표시를 붙인다. 사전 등록 규칙을 통과할 때만 반영한다.
- **볼린저 %b·RSI(14) 동시 판정**: 유지한다.
- **추세**: TSMOM 12개월(현금 대비 초과)의 부호를 국면 옆에 표시만 한다. 점수·국면 판정에는 쓰지 않는다.
- **장기 반전**(원자재·환율·금리, 60개월): 과거 가격을 더 받아 2013년부터 점수화한다. 받지 못한 구간은 N/A다. 기존 지표 `real_price_level`·`reer_level`과 중복 규칙(상관 > 0.9)을 적용한다.
- **캐리**: 대부분 이미 있다(원자재 백워데이션, 금리 `spread_to_policy`, 크레딧 `spread_level`, 주가지수 배당·ERP). 환율 금리차 **수준**만 추가한다.
- **CAPE**: 먼저 PIT로 쓸 수 있는 원천이 있는지 확인한다. 없으면 N/A로 둔다.
- **표본 분할**: 선택 구간 2013~2019, 확인 구간 2020~2026. 시평 63일, 자산군 풀링 IC, 순환 이동 플라시보 p를 쓴다.
- 기술적분석 시험대(52주 신고가·섹터·듀얼 모멘텀·BAB)는 그 저장소에서 따로 한다.

## 확정 결정 (2026-10-29) — Phase 4 종합 판단 후 (`outputs/phase4/phase4_summary.pdf`)
- **결정 1 (채택 조건 충족 후보 3개: 원자재 장기 반전 C1, FX 금리차 수준 C2, S&P500 CAPE)**: 반영했을 때 현재 점수·국면 변화량을 먼저 계산해서 본 뒤 정한다(보류).
- **결정 2 (무조건 변동성 가점 `rv_ratio_20`/`level_rv_ratio_20`, 볼린저×RSI confluence)**: 유지한다. 프로파일과 문서에 "효과 미확인"으로 표기한다(Phase 3 §6-5, Phase 4 B에서 개선 근거 없음).
- **결정 3 (미국 CPI 2025-10 결측)**: CAPE 분모는 빠진 달을 건너뛰고 최근 120개 가용 월로 계산한다. 결과를 본 뒤의 사후 수정이다. 사전 등록 §D-1에 날짜를 남겨 고쳤다.
- **결정 4 (KR_CORP 추세 표시)**: KR_CORP는 수익 지수가 이미 국고 대비 초과수익 근사라 현금을 빼지 않는다. 그래서 그 부호의 뜻은 "국고 대비"다. 코드를 바꿔야 한다(설계 결함 보고).
- **결정 5 (국면 임계값 50)**: 유지한다. 대시보드 이식 때 다시 검토한다.

## 최종 목적 (2026-10-29 사용자 확인)
- 결과물은 Stock_Dashboard(`../../_public/_equity_manage/Stock_Dashboard`, 저장소 regime-council)에 이식한다. 대상은 **마켓타이밍 점수**이고, 기술적 지표도 그 안에 포함된다.
- 대시보드에 지금 있는 점수(`quant.tech_score`, `strategy.py`의 ±30 규칙)는 **예시**다. 실제 점수와 기준은 이 프로젝트의 분석 결과로 다시 만든다.
- **보류(2026-10-29 사용자 정정)**: "임계값을 넘으면 이벤트로 본다"는 사용 방식은 보류한다. 트리거 포인트 산정과 이벤트 승률 검증(Phase 5 안)은 사용자가 다시 정하기 전까지 진행하지 않는다.
- 점수 방향: 추세 점수와 역발상(과매도) 점수를 **함께 표시**한다. `strategy.py` 규칙은 두 점수를 조합해 다시 정의한다.
- 유니버스: 대시보드 쪽은 약 50개 이상으로 커진다. 목록은 사용자가 나중에 준다. 그 전까지는 mtscore 10개 자산으로 검증한다.
- 검증 척도: 사용 방식이 정해질 때까지 사전 등록의 IC 판정을 유지한다. 이벤트 통계(승률·최대 역행폭)는 보조로만 낸다.

## 환경
- `uv` venv `.venv`(Python 3.12). 테스트: `.venv/bin/python -m pytest`.
- **Refinitiv**는 Windows `python.exe`로만 접속된다(WSL은 불가).
  - pandas 3.0 shim을 `import eikon` 전에 넣는다.
  - 키는 stdin으로 넣는다: `cat ~/.claude/reference/refinitiv-workspace/.appkey | python.exe probes/probe_refinitiv.py`
  - 레퍼런스: `~/.claude/reference/refinitiv-workspace/README.md`
- 키는 환경변수 `ECOS_API_KEY`, `FRED_API_KEY`, `KRX_ID`/`KRX_PW`로 넣는다. 코드·로그에 남기지 않는다.
- Phase 2 실행 순서: `scripts/phase2_collect_refinitiv.py holdings ts spx bottomup_us bottomup_kr kr_daily` → (lseg iBoxx는 `refinitiv.run_jobs`에 `LSEG_PYTHON`·`LSEG_WORKER`) → `phase2_build.py` → `phase2_score.py` → `phase2_crosscheck.py` → `phase2_tables.py`.
  워커는 `python.exe -I`로 띄운다(`-I` 없으면 어댑터 폴더의 `csv.py`가 표준 `csv`를 가려 pandas import 가 죽는다).
- KRX: `~/.config/krx_key`는 **KRX Open API `AUTH_KEY`**다(pykrx ID/PW 아님). 헤더 `AUTH_KEY`로 `data-dbg.krx.co.kr/svc/apis/`.

## 데이터 소스 함정 (Phase 0 실측)
- **FRED**
  - 브라우저 UA(`Mozilla/5.0`)로 요청하면 응답이 오지 않는다(curl HTTP 000). `User-Agent: curl/8`로 요청한다.
    1차 probe에서는 requests의 IPv4 강제(`urllib3.util.connection.HAS_IPV6=False`)도 함께 넣었다. 둘 중 어느 쪽이 필요한지는 분리하지 못했다.
  - fredgraph는 일부 ID(`WCESTUS1`, `VIX9DCLS`)에 CSV 대신 HTML을 돌려준다(원인: 시리즈 중단 또는 ID 오류, 미확인). `<!DOCTYPE`을 확인한 뒤 파싱한다.
  - ICE BofA OAS(`BAMLH0A0HYM2`, `BAMLC0A0CM`)는 2023-10-24부터만 나온다.
- **ECOS**
  - sample 키는 1회 10건 제한이다(`~/.claude/reference/bok-ecos/README.md` 기록). 전 구간 페이징과 sample 키의 호출 한도는 아직 검증하지 않았다 → 정식 키 `ECOS_API_KEY`를 쓴다.
  - `731Y005/0000003`은 달러/유로이고, `817Y002/010230000`은 국고채 30년이다. REER는 FRED `RBKRBIS`로 받는다.
- **Refinitiv**
  - `.SPX`는 `get_data TR.PriceClose Frq=D`로 받는다(실측 성공). `get_timeseries` 권한 없음은 README 기록이다.
  - `.VIX`는 `get_data`가 0행이다. VIX는 FRED `VIXCLS`로 받는다.
  - ICE BofA(`.MERH0A0`·`.MERC0A0`)는 권한 없음. iBoxx 지수는 lseg-data(`%LOCALAPPDATA%\lsegvenv`) `get_history`로 받는다. `ZSPREAD`·`OAS` 열은 2025년부터만 채워져 있다.
  - `.KS200`의 `TR.EPSMean`은 412 오류다. KOSPI200 컨센서스는 종목 바텀업으로 만든다.
  - 수정 건수 필드(`TR.NumEstRevisingUp` 등)는 실패했다.
  - USD/KRW 서울 마감은 `KRW=KFTC`다(`KRW=`은 뉴욕 마감).
- **pykrx** 1.2.9는 KRX 로그인(`KRX_ID`/`KRX_PW`)이 필요하다(지수 펀더멘털·구성종목·투자자 수급 모두 0행).
- **naver** `investorDealTrendDay`는 HTTP 410이다(2026-10-26 실측, 스킬 문서의 '가능' 기록은 낡은 정보).

## 데이터 소스 함정 (Phase 2 실측, 2026-10-28)
- **Refinitiv**
  - 장중에 받으면 오늘 날짜의 미완성 봉이 섞인다(KOFIA 금리는 15:30 이후 확정). 수집 끝 날짜를 마지막 완결 거래일로 둔다.
  - `get_timeseries`에 RIC 여러 개를 주면 3,000 데이터점 한도를 RIC 끼리 나눈다(20개 × 5년 → 150행). 일봉은 RIC 하나씩 받는다.
  - `get_data` 다필드 월별(`Frq=M`) 응답은 행이 표본 달마다 정렬돼 온다. 50 RIC/호출까지 잘림 없이 됐다(201행 × 50).
  - `US20YT=RR`은 2010년 구간 데이터가 없다(2020 재발행 전). 커브는 1·2·3·5·7·10·30년.
  - `0#.KS200` 체인은 `get_data`에서 412(식별자 해석 실패) → KOSPI200 구성종목은 KODEX200 보유종목으로 받는다.
  - `.SPX` `TR.PriceClose Frq=D`는 휴장일에 직전 거래일 행을 같은 날짜로 한 번 더 준다 → 반환 날짜로 중복 제거.
  - `KRCORP=KQ`(BBB− 3년)는 2010-01부터 있다.
  - EIA 주간 원유 재고는 lseg `ld.discovery.search`(SEARCH_ALL)로 찾은 `PS-ESPR-EIA`(SPR 제외, 백만 배럴, `COMM_LAST`) `get_history`로 2010~ 받는다. `USOILC=ECI`는 주간 변화(배럴).
  - KR 종목 `get_timeseries CLOSE`는 수정주가다(삼성전자 2018-05 50:1 분할 전 종가 50,400원으로 확인).
- **ECOS** sample 키 10건 페이징으로 월별 전 구간을 받았다(총건수 일치 확인). 간헐적 접속 timeout 이 있어 재시도가 필요하다.
- **KRX Open API**(`AUTH_KEY`): 지수 일별(`idx/kospi_dd_trd`)·종목 일별(`sto/stk_bydd_trd`)·ETF 일별은 되고 파생(`idx/drvprod_dd_trd`)은 401.
  지수 PER·PBR·배당, 투자자별 매매, 과거 구성종목은 응답에 없다.
- **ALFRED**(키 없음): `alfred.stlouisfed.org/graph/alfredgraph.csv?id=S,S,..&vintage_date=d1,d2,..&cosd=..`.
  한 요청에 12열까지만 준다(40개를 보내면 앞 12개만). 시리즈 첫 빈티지 이전 날짜가 섞이면 404. 드물게 `cosd`를 무시하고 전 구간을 준다 → 수집 창보다 늦은 '최초 출현'은 버린다.
  첫 빈티지: NFCI 2011-05-25, THREEFYTP10 2016-05-27(이분 탐색). Kim-Wright 공표 지연은 2016~18년에 최대 140일이었다.
- **Refinitiv 금 선물**: `GCc1`은 그달(인도월) 계약이라 활성월이 아니다(10-27 `GCc1` = OCT26). 만료 계약은 `GCZ9^1`(2019-12)·`GCG0^2`(2020-02) 꼴로 받지만 2024년 이후 만료분은 이름을 찾지 못했다 → c1~c4 로 구성.
- **FRED** `DCOILWTICO`(EIA 현물)는 2026년 급한 백워데이션 구간에서 `CLc1`과 최대 7달러 벌어진다(2025년은 중앙 0.7달러). 정의 차다.
