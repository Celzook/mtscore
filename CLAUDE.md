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

## 확정 결정 (2026-10-26)
- 표본 2010~, 일별 산출.
- 유니버스 10개: KOSPI200, S&P500, KTB10Y, UST10Y, USDKRW, 금, WTI, US HY, US IG, 국내 회사채.
- USDKRW는 원화 매수 관점이다.
- 미국 HY·IG 스프레드: iBoxx USD Liquid HY·IG(`.IBLUS0004`·`.IBLUS0005`) 만기수익률 − 같은 듀레이션 UST(G-스프레드). ICE OAS는 Refinitiv 권한 없음, FRED 2023-10~.
- KOSPI200: KRX 계정(`KRX_ID`/`KRX_PW`)으로 pykrx 공식 지수 펀더멘털·과거 구성종목·수급을 우선한다. 이익수정비율은 바텀업 확산지표(1개월 전보다 NTM EPS가 오른 종목의 시총 비중)로 대체한다(가정).
- S&P500 밸류에이션은 Fwd PER·ERP만 쓴다.
- 통화 이중반영은 3개 변형을 비교한다(기본값 both). 확인 트리거는 보류한다.

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
