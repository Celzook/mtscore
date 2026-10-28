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
  - WTI 재고는 Phase 2에서 EIA·Refinitiv로 확인한다.
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

## 환경
- `uv` venv `.venv`(Python 3.12). 테스트: `.venv/bin/python -m pytest`.
- **Refinitiv**는 Windows `python.exe`로만 접속된다(WSL은 불가).
  - pandas 3.0 shim을 `import eikon` 전에 넣는다.
  - 키는 stdin으로 넣는다: `cat ~/.claude/reference/refinitiv-workspace/.appkey | python.exe probes/probe_refinitiv.py`
  - 레퍼런스: `~/.claude/reference/refinitiv-workspace/README.md`
- 키는 환경변수 `ECOS_API_KEY`, `FRED_API_KEY`, `KRX_ID`/`KRX_PW`로 넣는다. 코드·로그에 남기지 않는다.

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
