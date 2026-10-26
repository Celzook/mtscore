# Phase 0 — 지표 × 데이터 확보 매트릭스 (실측 2026-10-26, 검증 반영판 v2)

## 상태 정의
| 상태 | 뜻 |
|---|---|
| 가능 | 2010-01 무렵부터 지금까지 **이번에 실제 호출로** 확인 |
| 부분 | 기간이 짧거나, 일부만 확인했거나, 대리지표 |
| 불가 | 호출했지만 실패 |
| 미확인 | 호출하지 않음 |
| 추정 | 호출 없이 레퍼런스나 외부 지식으로 판단(근거를 적음) |

## 근거 로그 (`outputs/phase0/`)
| 기호 | 파일 | 내용 |
|---|---|---|
| R1 | `probe_refinitiv_run1.txt` | 가격·금리·원자재 |
| R2 | `probe_refinitiv_run2.txt` | 컨센서스·밸류에이션·COT RIC. `probe_refinitiv.json`에는 R2만 있다 |
| R3 | `probe_refinitiv_extra_run.txt` | KOSPI200 상위 30종목 바텀업·종목 일봉 |
| F1 | `probe_free_run.txt` | FRED·ECOS·CFTC·naver·pykrx |
| F2 | `probe_free_run2.txt` | VIX 기간구조 |
| F3 | `probe_free_extra_run.txt` | BAA10Y·AAA10Y, CFTC KRW 검색, naver HTTP 상태, pykrx 수급 |
| R4 | `probe_refinitiv_credit_run.txt` | ICE 권한·lseg-data 검색(HY/IG/CDX/iBoxx) |
| R5 | `probe_refinitiv_iboxx_run.txt` | iBoxx HY·IG 열별 비결측 기간 |
| RM | `~/.claude/reference/refinitiv-workspace/README.md` | 이전 실측 기록. 이번 세션에서 재호출하지 않은 사유의 근거 |

## 수집 방식
- **ECOS**: 키가 환경에 없어 `sample` 키로 호출했다. 기간의 처음 10건과 마지막 10건만 받았다. 행 수는 `list_total_count`이며 내려받은 행이 아니다. 전 구간 페이징은 Phase 2에서 확인한다.
- **FRED**: 키 없이 fredgraph CSV 경로로 받았다.

## 1. KOSPI200 (equity_index)
| 블록 | 지표 | 소스 | 상태 | 근거 |
|---|---|---|---|---|
| 가격 | 종가(이격도·낙폭·수익률 z·RSI) | Refinitiv `.KS200` | 가능 4,137행 2010-01-04~2026-10-23 | R1 |
| 가격 | 종가(교차확인) | naver siseJson `KPI200` | 가능 4,136행 2010-01-04~ | F1 |
| 가격 | 총수익지수 | Refinitiv `.KS200TR` | 부분 2011-01-03~(3,886행) | R1 |
| 변동성 | VKOSPI | Refinitiv `.KSVKOSPI` | 가능 4,137행 | R1 |
| 변동성 | VKOSPI 기간구조 | — | 미확인 | |
| 심리 | Put/Call | KOFIA·KRX | 미확인 | |
| 심리 | 신용스프레드 | ECOS 817Y002 회사채 AA-(3년) − 국고3년 | 가능 4,152(총건수) 20100104~20261023 | F1 |
| 심리 | 원화 급약세 | Refinitiv `KRW=KFTC` | 가능 4,147행 | R1 |
| 시장폭 | 과거 구성종목(PIT) | pykrx `get_index_portfolio_deposit_file` | 불가: KRX 로그인 필요(`KRX_ID/KRX_PW` 미설정 메시지) | F1 |
| 시장폭 | 과거 구성종목(PIT) | Refinitiv `.KS200` `TR.IndexConstituentRIC` SDate=2015 | 불가: 0행 | R2 |
| 시장폭 | (대안) 현재 구성종목 일봉 | Refinitiv `get_timeseries` 종목 일봉 | 부분: 상위 5종목 중 4개는 2010-01-04~, 402340.KS는 2010~14 구간 데이터 없음. 현재 구성 기준이라 생존편향 | R3 |
| 수급 | 외국인 순매수 | naver `investorDealTrendDay` | 불가: HTTP 410(3개 쿼리 모두) | F3 |
| 수급 | 외국인 순매수 | pykrx `get_market_trading_value_by_date` | 불가: KRX 로그인 필요, 0행 | F3 |
| 수급 | 신용잔고·반대매매 | KOFIA | 미확인 | |
| 밸류에이션 | 공식 지수 PER·PBR·배당 | pykrx `get_index_fundamental` | 불가: KRX 로그인 필요 | F1 |
| 밸류에이션 | 지수 컨센서스 | Refinitiv `.KS200`·`.KS11` `TR.EPSMean` | 불가: 412 | 세션 초 probe |
| 밸류에이션 | (대안) 바텀업 PBR | 상위 30종목(KODEX200 비중 85.12%) `TR.PriceToBVPerShare` 월별 | 부분: 29/30종목(055550.KS 없음), 비중 83.89%. 2011-01 이전부터 이력이 있는 종목 비중 77.52% | R3 |
| 밸류에이션 | (대안) 바텀업 배당수익률 | 상위 30종목 `TR.DividendYield` | 부분: 30/30종목, 2011 이전 이력 비중 78.75% | R3 |
| 밸류에이션 | (대안) 바텀업 Fwd PER·ERP | 상위 30종목 `TR.EPSMean(NTM)` + `TR.CompanyMarketCap` + `KRTSY10Y=KQ` | 부분: 30/30종목, 2011 이전 이력 비중 76.54%. 생존편향 | R3, R1 |
| 펀더멘털 | Fwd EPS 1·3개월 변화율·수정 모멘텀 | 위 바텀업 | 부분(위와 같음) | R3 |
| 펀더멘털 | 이익수정비율(상향/하향 건수) | 9개 후보 필드(아래 주) | 불가: 수정 건수 필드 모두 실패 | R2 |
| 펀더멘털 | 통화 3개월 변화율 | `KRW=KFTC` | 가능 | R1 |

> **주: 시도한 수정 건수 계열 필드 9개**
> - 필드: `TR.NumEstRevisingUp/Down`, `TR.EPSNumUpRevisions`, `TR.EPSNumDownRevisions`, `TR.NumberOfUpRevisions`, `TR.EPSMeanChg`, `TR.EPSNumUp`, `TR.EPSNumDown`, `TR.EPSMeanPctChg`
> - 대상: `.SPX`에는 9개 모두 시도했고, `005930.KS`에는 Up/Down 2개만 시도했다.
> - 같은 시도에서 `TR.EPSNumIncEstimates`(포함 추정치 수)는 `.SPX` 201행으로 성공했다. 다만 이 필드는 수정 건수가 아니다.
> - 대체 후보: 바텀업 "1개월 전보다 NTM EPS가 오른 종목의 비중"(수정 확산 대리지표, 가정).

## 2. S&P500 (equity_index)
| 블록 | 지표 | 소스 | 상태 | 근거 |
|---|---|---|---|---|
| 가격 | 종가 | Refinitiv `.SPX` `TR.PriceClose` 일별(get_data) | 가능 4,386행 2009-12-31~ | R1 |
| 변동성 | VIX | Refinitiv `.VIX` `TR.PriceClose` | 불가: 0행(오류 문구 없음). 권한 없음은 RM 기록 | R1, RM |
| 변동성 | VIX (대체) | FRED `VIXCLS` | 가능 9,301행 1990~ | F1 |
| 변동성 | 기간구조 VIX3M/VIX | FRED `VXVCLS` | 가능 4,751행 2007-12-04~ | F2 |
| 변동성 | VIX9D | FRED `VIX9DCLS` | 불가: HTML 반환 | F2 |
| 심리 | 신용스프레드 | FRED `BAA10Y` | 가능 10,202행 1986-01-02~ | F3 |
| 심리 | Put/Call | CBOE | 미확인 | |
| 시장폭 | 구성종목 기반 | — | 미확인(S&P 구성종목은 호출하지 않음) | |
| 포지셔닝 | E-mini COT | CFTC Socrata 13874A | 가능 877주 2010-01-05~ | F1 |
| 밸류에이션 | 12M Fwd PER | `.SPX` `TR.PtoEPSMeanEst` 월별 | 가능 201행 2010-01-29~ | R2 |
| 밸류에이션 | PBR·배당수익률 | `.SPX` `TR.PriceToBVPerShare`·`TR.DividendYield`·`TR.IndexDividendYield` | 불가: 0행 | R2 |
| 밸류에이션 | ERP | Fwd 이익수익률 − `US10YT=RR` | 가능 | R1, R2 |
| 펀더멘털 | Fwd EPS 1·3개월 변화율 | `.SPX` `TR.EPSMean(NTM)` 월별 | 가능 201행 2010-01-17~ | R2 |
| 펀더멘털 | 이익수정비율 | 수정 건수 필드 | 불가(위 주) | R2 |

## 3. 금리 — KTB10Y, UST10Y (rates)
| 블록 | 지표 | 소스 | 상태 | 근거 |
|---|---|---|---|---|
| 가격 | KTB10Y | Refinitiv `KRTSY10Y=KQ` 4,149행 / ECOS 817Y002 국고채(10년) 4,152건 | 가능 2010~ | R1, F1 |
| 가격 | UST10Y | Refinitiv `US10YT=RR` 4,206행 / FRED `DGS10` | 가능 | R1, F1 |
| 포지셔닝 | UST10Y 선물 COT | CFTC 043602 | 가능 877주 | F1 |
| 포지셔닝 | KTB 선물 포지셔닝 | — | 미확인 | |
| 밸류에이션 | 미국 실질금리 | FRED `DFII10` | 가능 5,956행 2003~ | F1 |
| 밸류에이션 | 한국 실질금리 | ECOS 물가연동국채 | 부분: 항목코드 `817Y002/010230000`을 시도했으나 국고채 30년이 나옴(코드 오류, 미해결). 대리지표는 KTB10Y − CPI YoY(ECOS 901Y009, 가능 201건 2010-01~2026-09), 가정 | F1 |
| 밸류에이션 | 기준금리 대비 스프레드 | `KRBASE=BOKK` 4,142행 / ECOS 722Y001 / FRED `DFF` | 가능 | R1, F1 |
| 밸류에이션 | 기간프리미엄(미국) | FRED `THREEFYTP10` | 가능 9,184행 1990~2026-10-16 | F1 |
| 밸류에이션 | 기간프리미엄(한국) | — | 미확인 | |
| 펀더멘털 | 경기·물가 서프라이즈 | — | 미확인 | |
| (참고) | 금융여건 | FRED `NFCI`·`STLFSI4`, BEI `T10YIE` | 가능(프로파일 미편입) | F1 |

## 4. USDKRW (fx, 원화 매수 관점)
| 블록 | 지표 | 소스 | 상태 | 근거 |
|---|---|---|---|---|
| 가격 | 이격도·수익률 z | `KRW=KFTC` 4,147행 / ECOS 731Y001 4,152건 | 가능 | R1, F1 |
| 포지셔닝 | 투기적 포지셔닝 | CFTC 계약명 검색(KOREAN·KRW) | 불가: 검색 결과 0건 | F3 |
| 밸류에이션 | REER 괴리 | FRED `RBKRBIS`(BIS broad) | 가능 391행 1994-01~2026-07(월별) | F1 |
| 밸류에이션 | REER (ECOS) | `731Y005/0000003` | 불가: 달러/유로가 나옴(코드 오류) | F1 |
| 펀더멘털 | 금리차 3개월 변화 | KTB10Y − UST10Y | 가능 | R1 |
| 펀더멘털 | 경상수지 | ECOS 301Y013 | 가능 200건 2010-01~2026-08 | F1 |
| 펀더멘털 | 교역조건 | ECOS 403Y | 미확인 | |

## 5. 금·WTI (commodity)
| 블록 | 지표 | 소스 | 상태 | 근거 |
|---|---|---|---|---|
| 가격 | 1번째 월물 | `GCc1`·`CLc1` | 가능 4,234행 | R1 |
| 펀더멘털 | 커브 c1/c2 | `GCc2`(4,234행)·`CLc2`(4,233행) | 가능 | R1 |
| 포지셔닝 | COT | CFTC 088691·067651 | 가능 877주 | F1 |
| 포지셔닝 | COT (Refinitiv) | `1GC-NCL-NET=COT`·`GC-NCL-NET=COT` | 불가: Invalid RIC | R2 |
| 밸류에이션 | 실질가격 | FRED `CPIAUCSL` 디플레이트 | 가능 956행 1947~2026-09 | F1 |
| 펀더멘털 | 원유 재고 | FRED `WCESTUS1` | 불가: HTML 반환. EIA API는 미확인 | F1 |

## 6. 크레딧 — US HY, US IG, 국내 회사채 (credit)
| 지표 | 소스 | 상태 | 근거 |
|---|---|---|---|
| US HY OAS | FRED `BAMLH0A0HYM2` | 부분: 786행 2023-10-24부터만 | F1 |
| US IG OAS | FRED `BAMLC0A0CM` | 부분: 785행 2023-10-24부터만 | F1 |
| US HY·IG (Refinitiv ICE) | `.MERH0A0`·`.MERC0A0` (lseg-data `get_history`) | 불가: `UserNotPermission` | R4 |
| US HY (iBoxx USD Liquid HY) | `.IBLUS0004`: 지수 레벨 `TRDPRC_1`·`MOD_DURTN`·`YLDTOMAT`·자산스왑스프레드 `AST_SWPSPD` | 가능 2010-01-04~(4,352~4,383행). `ZSPREAD`·`OAS`는 2025년부터만 | R4, R5 |
| US IG (iBoxx USD Liquid IG) | `.IBLUS0005`: `TRDPRC_1`·`MOD_DURTN`·`YLDTOMAT` | 가능 2010-01-04~(4,280행). `AST_SWPSPD`는 2022-12~, `ZSPREAD`·`OAS`는 2025년부터만 | R5 |
| US HY·IG 2010~ 스프레드 구성안 | `YLDTOMAT` − 같은 듀레이션의 UST 수익률(G-스프레드, 커브 보간) | 계산 가능(원재료 확인). 보간용 UST 2·5·7·30년 RIC은 미확인, 가정 | R5 |
| US IG 장기 대리 | FRED `BAA10Y` / `AAA10Y` | 가능 10,202행 1986~ / 10,949행 1983~ | F3 |
| US HY 장기 대리 | — | 미확인(무료 소스 찾지 못함) | |
| 국내 회사채 스프레드 | ECOS AA-(3년) − 국고3년 / `KRGUCORP=KQ`(AA- 3년인지는 RM 기록) | 가능 2010~ | F1, R1, RM |
| 부도율·등급 변동 | — | 미확인. FRED `DRALACBN`(미국 은행 대손상각률, 166행 1985~2026-04 분기)은 부도율 자체가 아닌 대리지표 | F1 |

## 운송 관련 함정 (Phase 2 어댑터에 반영)
- **FRED**
  - 브라우저 UA(`Mozilla/5.0`)로 curl 요청하면 HTTP 000, 0바이트다. curl 기본 UA는 200이다(세션 실측).
  - F1 실행 때는 requests에 `curl/8` UA와 IPv4 강제를 함께 적용했다. 어느 쪽이 효과였는지는 분리되지 않았다.
  - fredgraph는 중단된 시리즈(`WCESTUS1`, `VIX9DCLS`)에 HTML을 돌려준다. `<!DOCTYPE`을 확인한 뒤 파싱한다.
- **ECOS**: 항목코드 오류 2건 — `731Y005/0000003`은 달러/유로, `817Y002/010230000`은 국고채 30년이다.
- **Refinitiv**
  - `.SPX`는 `get_data TR.PriceClose Frq=D`로 받는다(이번 R1에서 성공). `get_timeseries` 권한 없음은 RM 기록이다.
  - `KRW=`는 뉴욕 마감이고, KOSPI와 맞추려면 `KRW=KFTC`를 쓴다(RM).
