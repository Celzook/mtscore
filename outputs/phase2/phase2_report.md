# Phase 2 보고 — 실데이터 수집과 지표 계산 (10개 자산)

- 작성: 2026-10-28, 브랜치 `phase2-data`(`feat/contrarian-oversold`에서 분기, 커밋하지 않음)
- 표본: 2010-01-01 ~ 2026-10-27(마지막 완결 거래일). 오늘(10-28) 장중 봉은 받지 않았다.
- 점수 기준일: 2026-10-27. 점수 이력은 워밍업 3년 뒤인 2013-01-04(SP500은 2012-12-31)부터 나온다.

## 개정 (2026-10-28 2차 — 독립 검증 반영·사용자 결정 A~F)
이 절이 아래 본문보다 우선한다. 본문의 옛 수치는 고쳤고, 바뀐 결정은 여기 적는다.

| 결정 | 적용 | 결과 |
|---|---|---|
| A. G-스프레드 평균만기 매칭 | US_IG·US_HY 모두 `AVG_LIFE` 만기의 UST 커브 수익률(선형 보간). 듀레이션 매칭판은 `spread_dur_matched`(점수 미사용) | ICE OAS 대비 수준·주간 변화 상관: IG 0.936·0.908(듀레이션판 0.772·0.894), HY 0.979·0.960(듀레이션판 0.979·0.964) — HY 는 사실상 같아 같은 방식 사용 |
| B. 금 활성월 백어저스트 | `GCc1..c4`(연속 4개 달). c1 계약월 = 그달 최종거래일(월말 3번째 영업일) 전이면 그달. 활성월 G·J·M·Q·V·Z 를 첫 통지일 5영업일 전에 교체. 실질가격은 `close_c1_raw`(`real_price_level_spot`) | c1 계약월 규칙 검증: 규칙상 c1 교체일 201개 중 68.7%가 c2/c1 스프레드 급변 상위 5%일(±1일 어긋나면 5%). 활성월 교체 101회, 2010 시점 누적 계수 1.457. 교체일 `gold_switch_dates.csv` |
| C. KOSPI200 민감도 | 주 점수는 시총가중 유지. `fwd_per_ew`·`fwd_eps_12m_ew`·`eps_up_share_ew`(동일가중), `*_ex2`(005930·000660 제외; 005935 우선주는 KODEX200 보유에 없음) — 프로파일에 없어 점수 미사용 | 10-27: fwd_per 시총 4.42 / 동일가중 8.07 / 두 종목 제외 8.14. eps_up_share 0.83 / 0.58 / 0.62 |
| D. 승인 4건 | 그대로. 추가: 근월물 0 이하 가격은 `close_c1_raw` 결측(WTI 2020-04-20 1일) → 그날 `_spot` 지표 N/A | |
| E. 미국 CPI as_of = ALFRED 최초 공표일 | 키 없이 `alfredgraph.csv?id=..&vintage_date=..`(요청당 12개 빈티지), 2007-01~ 평일마다 빈티지를 받아 관측이 처음 나온 날·값 | 238개월, 공표 지연 중앙 44일(기준월 1일 기준)·최대 61일. 실제 BLS 일정과 일치 확인: 2019-12분 2020-01-14, 2020-01분 2020-02-13, 2024-09분 2024-10-10, 셧다운 지연 2025-09분 2025-10-24·2025-11분 2025-12-18. **2025-10분은 공표되지 않아 결측** |
| F. NFCI·Kim-Wright 실시간 값 | 같은 방식, 최초 공표값. 첫 빈티지 이전은 N/A(수정치로 채우지 않음) | NFCI 첫 빈티지 2011-05-25, 805주, 지연 중앙 5일·최대 20일 → `financial_conditions` 첫 점수 2014-08-25. THREEFYTP10 첫 빈티지 2016-05-27, 2,643일, 지연 중앙 7일·95% 99일·최대 140일(옛 '+10일' 가정은 과소) → `term_premium` 첫 점수 2019-05-28 |

검증 지적 반영
- 두 종목 비중: 62%는 KODEX200 펀드 비중이었다. 계산에 쓰인 값은 **시총 54.5%, 선행이익 75.4%**(2026-10, 181종목).
- KOSPI200 바텀업 Fwd PER 연말 범위 **7.58(2011)~13.73(2020)**, 2026-10-27 4.42.
- 시총은 전체 시총(full cap)이다. KRX 코스피200 시총(유동주식 기준 아님, 지수 시총) 대비 +3.8%. KOSPI200 지수 자체는 유동시총 가중이라 바텀업 가중과 다르다(가정).
- 구성종목 커버리지 편향: 2010-01 에 EPS 가 있는 종목 47개, 삼성전자 EPS 는 2010-04 부터(하이닉스 2010-01). 초기 몇 달의 집계는 대형주 일부가 빠진 값이다.
- S&P eps_up_share 범위 **0.19~0.96**.
- 미국 +1영업일은 연방 공휴일·성금요일을 뺀 미국 영업일로 고쳤다(`fred.next_us_bday`). 정부 셧다운에 따른 H.15 공표 지연은 반영하지 못한다(가정).
- 패널 **149,597행**(금 연속물·민감도·ALFRED 반영 후).
- 원천 대조 **47/51 통과**(불통과: USDKRW 매매기준율 정의 차 1건, WTI 현물 vs 근월물 2건, 비교용 IG 듀레이션판 상관 1건).
- PIT 재현 60건 최대 차 5e-5(반올림), NaN 불일치 0. 테스트 **202 passed, 17 warnings**.

## 0. (1차) 사용자 결정에서 벗어났거나 덧붙인 점 — 2차에서 D 로 승인, 4·6 은 A·B 로 대체
1. **월별 컨센서스 as_of = 표본일**(월말·스냅숏일). NEXT_STEPS §1-3 은 '반환 날짜'였다. 반환 날짜가 마지막 변경일이라 다음 달에도 같은 날짜로 다른 값이 와서 바꿨다(더 보수적).
2. **WTI 교체일은 NYMEX 최종거래일 규칙**으로 정했다. c1/c2 관계는 백어저스트 계수와 검증에만 썼다(단독 신호는 연 104회 참). 그리고 **교체 5영업일 전에 갈아탄다**(2020-04-20 −37.63 회피).
3. **`universe.yaml` WTI overrides 추가**: `real_price_level`·`backwardation` 제외, 원 근월물판 `real_price_level_spot`·`backwardation_spot` 추가.
4. **G-스프레드를 액면가 국채 듀레이션 매칭으로 구현**('같은 듀레이션'의 문자 그대로 해석). 중간에 만기=듀레이션 근사에서 바꿨다. IG 는 그래도 대조 기준(수준 상관 0.8)에 못 미친다(0.77, 평균만기 매칭이면 0.94).
5. **`commodity.yaml` `inventory_change`의 `na_until_found` 해제**: EIA 재고를 lseg `PS-ESPR-EIA`로 확보했다.
6. GOLD 는 롤 조정하지 않았다(결정 범위 밖, §12).

## 1. 산출물 (`outputs/phase2/`)
| 파일 | 내용 |
|---|---|
| `coverage.csv` · `coverage.md` | 자산별 지표 사용/제외와 사유 |
| `latest_indicators.csv` · `latest.md` | 기준일 지표 원시값·백분위·점수·블록 비중, 블록 점수·국면 |
| `latest_scores.csv` · `result_2026-10-27.json` | 10개 자산 블록 점수·구간·국면(JSON 은 `docs/result_schema.md` 형식) |
| `score_history.csv.gz` | 자산 × 일별 블록 점수 이력(34,586행) |
| `field_map.csv` · `field_map.md` | 소스 → 필드 지도와 필드별 as_of 규칙·행 수·기간 |
| `crosscheck.csv` | 원천 대조 표본(49건) |
| `pit_recompute_check.csv` | PIT 재현 점검(과거 기준일로 잘라 다시 계산 = 이력값) |
| `wti_roll_dates.csv` · `gold_switch_dates.csv` · `build_info.json` | WTI 교체일 202개, 바텀업 종목 수·롤 검증·iBoxx 총수익 확인 |
| `manual_input_list.md` | 수동 입력 목록 갱신판(템플릿 `data/manual/templates/phase2_na_fields.csv`) |

재현: `scripts/phase2_collect_refinitiv.py` → `phase2_build.py` → `phase2_score.py` → `phase2_crosscheck.py` → `phase2_pit_check.py` → `phase2_tables.py`.
원자료(`data/raw/`)와 패널(`data/processed/panel.csv.gz`, 149,597행)은 `.gitignore` 대상이라 커밋되지 않는다.

## 2. 자산별 수집 결과
| 자산 | 필드(소스) | 사용 지표 / 전체 |
|---|---|---|
| KOSPI200 | close `.KS200`, close_tr `.KS200TR`(2011-01~), vol_index `.KSVKOSPI`, fwd_per·pbr·div_yield·fwd_eps_12m·eps_up_share(KODEX200 보유 201종목 바텀업, 월별), 시장폭 5필드(같은 201종목 일봉), refs KTB10Y.yield·USDKRW.close | 26 / 33 |
| SP500 | close `.SPX`(get_data 일별), fwd_per `TR.PtoEPSMeanEst`, fwd_eps_12m `TR.EPSMean NTM`(월별+10-27 스냅숏), eps_up_share(SPY 보유 503종목 바텀업), vol_index FRED `VIXCLS`, vol_index_3m `VXVCLS` | 19 / 33(14개는 universe 제외) |
| KTB10Y | yield `KRTSY10Y=KQ`, policy_rate `KRBASE=BOKK`, cpi ECOS 901Y009, real_yield = KTB10Y − CPI YoY(파생) | 10 / 14 |
| UST10Y | yield `US10YT=RR`, real_yield `DFII10`, policy_rate `DFF`, term_premium `THREEFYTP10`, cot_net CFTC 043602, cpi `CPIAUCSL`, nfci `NFCI` | 13 / 14 |
| USDKRW | close `KRW=KFTC`, reer `RBKRBIS`, rate_diff = KTB10Y − UST10Y(t−1, 파생), current_account_12m ECOS 301Y013 12개월 합 | 8 / 10 |
| GOLD | close(`GCc1..c4` 활성월 백어저스트, 2차), close_c1_raw `GCc1`, cot_net CFTC 088691, cpi(ALFRED), refs UST10Y.real_yield | 8 / 11 |
| WTI | close(`CLc1`/`CLc2` 비율 백어저스트), close_c1_raw `CLc1`, close_c2 `CLc2`, cot_net CFTC 067651, cpi, inventory EIA 주간 원유 재고 `PS-ESPR-EIA`(lseg) | 9 / 11 |
| US_HY | spread = iBoxx `.IBLUS0004` YLDTOMAT − 같은 듀레이션 UST, index_level `TRDPRC_1`(총수익지수) | 7 / 8 |
| US_IG | 위와 같음 `.IBLUS0005` | 7 / 8 |
| KR_CORP | spread = `KRGUCORP=KQ`(AA− 3년) − `KRTSY3Y=KQ`, spread_low_grade = `KRCORP=KQ`(BBB− 3년) − 국고3년, refs KOSPI200.fwd_eps_12m | 7 / 8 |

종목 일봉은 수정주가다: 삼성전자 50:1 분할(2018-05-04) 전후 2018-04-25 종가 50,400원, 카카오 5:1 분할(2021-04-15) 전 2021-04-08 종가 109,600원(분할 반영값).

바텀업 종목 수(`build_info.json`): KOSPI200 fwd_per·EPS 계열은 월 47개(2010 초)~181개(현재), 중앙 155개. PBR·배당은 중앙 169개.
S&P500 eps_up_share 는 월 403~501개(중앙 467개). 시장폭은 2010년 138종목, 현재 201종목.

## 3. N/A 와 사유 (날조·대리 없음)
| 자산 | 지표 | 사유 |
|---|---|---|
| KOSPI200 | foreign_net_buy_intensity, inst_net_buy_intensity | pykrx 는 KRX_ID/KRX_PW 로그인이 필요한데 계정이 없다. `~/.config/krx_key`는 KRX Open API AUTH_KEY 였고(아래 §8), 투자자별 매매 응답이 없다. naver HTTP 410 |
| KOSPI200 | vol_term_inversion | VKOSPI 3개월물 소스 없음(`vol_index_3m` 미확보) |
| KOSPI200·SP500 | put_call, margin_debt_change, forced_liquidation, revision_ratio | `na_until_found` 유지(소스 미확인 / 수정 건수 필드 실패). revision_ratio 는 `revision_breadth`(eps_up_share)가 대신한다 |
| KTB10Y·UST10Y | macro_surprise | 소스 미확인 |
| USDKRW | terms_of_trade_trend | ECOS 403Y 항목코드 미확인 |
| US_HY·US_IG·KR_CORP | default_trend | 부도율 소스 미확인 |

universe 제외(설정)는 `coverage.md`에 `override_exclude`로 적었다. 수동 입력 템플릿은 `data/manual/templates/phase2_na_fields.csv`.

## 4. 적용한 결정 (사용자 결정 2026-10-28, `CLAUDE.md` "확정 결정 (2026-10-28) — Phase 2 데이터")
1. **KOSPI200 컨센서스·시장폭**: 현재 구성종목 바텀업. `0#.KS200` 체인은 412 라 KODEX200(`069500.KS`) 보유종목 201개를 썼다. 가정: 생존편향.
2. **S&P500 eps_up_share**: SPY 보유종목 전체 503개, 월별 `TR.EPSMean NTM` + `TR.CompanyMarketCap`, `{"SDate","EDate","Frq":"M"}` 파라미터, 50 RIC/호출, 디스크 캐시·재개 가능.
   정의 = 1개월 전보다 NTM EPS 가 오른 종목의 시총 비중(가중치 = 전월 표본일 시총). 가정: 생존편향.
   수집은 예상보다 짧았다(미국 281초, 한국 261초) — 시간이 오래 걸린 것은 KOSPI200 종목 일봉(804건, 546초)이었고 그것을 백그라운드로 돌렸다.
3. **WTI 연속물**: 비율 백어저스트.
   - 교체일은 NYMEX 최종거래일 규칙(인도월 전월 25일의 3영업일 전) 다음 거래일로 정했다. 202개, 연 12.0회.
   - c1/c2 관계 신호(|c1_t−c2_{t−1}|<|c1_t−c1_{t−1}|)만으로는 잡음 때문에 연 104회 참이라 쓸 수 없었다. 대신 검증에 썼다.
     규칙 교체일에서 k일 어긋난 날의 참 비율이 k=0 에서 0.586 으로 가장 높다(k=±1: 0.40·0.41).
   - 교체일 5영업일 전에 다음 월물로 갈아탄다(2020-04-20 근월물 −37.63 회피, 연속물 최저 6.87).
   - **결정 3에 덧붙인 설정 변경(확인 필요)**: 연속물 `close`는 과거 수준이 누적 롤 계수(2010년 시점 1.98배)만큼 왜곡돼 실질가격·커브(c1/c2) 비교에 맞지 않는다.
     그래서 WTI 만 `real_price_level`·`backwardation`을 빼고 원 근월물 `close_c1_raw`판 `real_price_level_spot`·`backwardation_spot`을 `universe.yaml`에 추가했다(코어 변경 없음).
4. **기본값 수용**: 듀레이션 KTB·UST 8.5, KR_CORP 2.7(Phase 2 에서는 쓰지 않음 — Phase 3 수익률용). CPI 공표 시차 미국 = 다음 달 1일+14일, 한국 = 다음 달 5일.
   **iBoxx `TRDPRC_1`은 총수익지수다**: 39개 열 중 `TRTN_PRICE`(총수익 가격)와 전 구간 차 0.0(HY 4,359행, IG 3,915행). 월간 회귀에서 캐리 항의 회귀 계수가 HY 0.67, IG 1.10 이다(t 값은 계산하지 않음). 쿠폰을 더하지 않았다.

## 5. 가정 목록
- **바텀업 생존편향**: KOSPI200·S&P500 모두 현재 구성종목. 과거 구성은 Refinitiv 가 주지 않는다(`SDate`를 줘도 현재 구성).
- **최신 빈티지**는 2차에서 미국 CPI·NFCI·THREEFYTP10 을 ALFRED 최초 공표값으로 바꿨다. 나머지 FRED·ECOS 는 수정치.
- **NTM 상향 편향**: NTM 창이 매달 앞으로 굴러가 이익 성장 종목은 수정 없이도 EPS 가 오른다 → eps_up_share 수준이 구조적으로 높다(KOSPI200 0.58~0.94, S&P 0.19~0.96). 자기 역사 백분위로만 쓴다.
- **월별 컨센서스 as_of = 표본일**(월말·스냅숏일): 반환 날짜는 마지막 변경일이라 다음 달에도 같은 날짜가 다른 값으로 온다(KR 1,756건, US 4,965건). NEXT_STEPS 의 "반환 날짜" 규칙보다 보수적이다.
- **KOSPI200 fwd_eps_12m**: 같은 종목 집합의 합산 선행이익 증가율 연쇄지수(첫 달 100). 수준은 임의 단위.
- **G-스프레드**: 국채 = 액면가 반기 이표채, 듀레이션 → 만기 → 수익률 선형 보간, 커브 1·2·3·5·7·10·30년.
- **KTB10Y 실질금리**: 명목 − 그날까지 공표된 CPI 전년비(사후 물가로 기대인플레이션 대신).
- **as_of 지연**(공표 시차): DFII10·DFF +1 미국 영업일(공휴일 제외, 셧다운 지연 미반영), CPI·NFCI·THREEFYTP10 은 ALFRED 실제 공표일(2차), RBKRBIS 기준월+3개월, ECOS 경상수지 기준월+2개월 10일, COT 화요일+3일(공휴일 지연 미반영).
- **최신 빈티지**: FRED·ECOS 값은 수정치다(공표 당시 값이 아니다).
- **WTI**: 영업일 = 관측 거래일, 교체 5영업일 전 갈아탐.
- **GOLD**: 2차에서 활성월 비율 백어저스트로 바꿨다(결정 B). 가정: 첫 통지일 5영업일 전 교체, 영업일 = 관측 거래일.

## 6. 원천 대조 (`crosscheck.csv`, 47/51 통과 — 2차)
| 대조 | 결과 |
|---|---|
| UST10Y `US10YT=RR` vs FRED `DGS10`(3일) | 차 0.3~1.2bp |
| KTB10Y·KTB3Y·AA−3Y `=KQ` vs ECOS 817Y002(각 3일) | 9건 모두 0.000 |
| KOSPI200 `.KS200` vs KRX Open API(3일) | 3건 모두 0.00 |
| S&P500 `.SPX` vs FRED `SP500`(3일) | 3건 모두 0.00 |
| EIA 재고 `PS-ESPR-EIA` 주간 변화 vs `USOILC=ECI`(3주) | 차 0.000~0.007 백만 배럴(같은 EIA 원천의 다른 Refinitiv 계열) |
| COT Socrata vs CFTC 연간 파일 `deacot2026.zip`(3계약 × 2일) | 6건 모두 0 |
| 한국 CPI 전년비 ECOS vs FRED OECD `KORCPIALLMINMEI`(3개월, 2023) | 차 0.02~0.04%p |
| USDKRW `KRW=KFTC` vs FRED `DEXKOUS`(3일) | 차 0.1~2.8원 |
| USDKRW `KRW=KFTC` vs ECOS 731Y001 매매기준율(3일) | **1건 불통과**: 09-15 19.3원. 매매기준율은 전일 시장평균환율이라 정의가 다르다(나머지 4.4·1.6원) |
| WTI `CLc1` vs FRED `DCOILWTICO`(6일) | 2025년 3일은 0.25~0.86달러. **2026-10 2건 불통과**(6.7·6.1달러): EIA 현물 vs 근월 선물, 급한 백워데이션 구간의 정의 차 |
| 바텀업 201종목 시총 합 vs KRX 코스피200 시총(10-27) | 4,459조 vs 4,295조(+3.8%, 우선주·시총 정의 차 허용 5% 안) |
| US_HY G-스프레드 vs ICE OAS(2023-10~) | 수준 상관 0.979, 주간 변화 상관 0.964, 평균 차 +0.33%p |
| US_IG G-스프레드 vs ICE OAS(2023-10~) | **불통과**: 수준 상관 0.772(기준 0.8), 주간 변화 0.894. 만기=듀레이션 단순판은 0.40 이었다. 평균만기(`AVG_LIFE`) 매칭이면 0.936 — **결정 필요**(사용자 결정은 '같은 듀레이션') |

## 7. PIT 점검
- 패널 전 행 as_of ≥ date(`validate_panel`), as_of 최댓값 2026-10-27.
- 2020-03-23·2024-08-05 로 잘라 다시 계산한 블록 점수 60건 = 이력값(최대 차 5e-5 = 이력 파일 소수 4자리 반올림, NaN 불일치 0).
- 시장 간 시차: 미국 값을 한국 자산에 쓰는 파생은 USDKRW `rate_diff` 하나이고, t−1일 이전 뉴욕 종가만 쓴다(테스트 `test_rate_diff_uses_prior_us_close`).
  나머지 refs 는 같은 시장 안이다(KOSPI200 ← KTB10Y·USDKRW, KR_CORP ← KOSPI200, SP500·US_HY·US_IG ← UST10Y·SP500, GOLD ← UST10Y).

## 8. 기준일 점수·국면 (2026-10-27)
| 자산 | 과매도 | 밸류에이션 | 펀더멘털 | 국면 |
|---|---|---|---|---|
| KOSPI200 | 73.9 | 55.5 | 40.0 | 저평가 패닉 분할 진입 |
| SP500 | 62.6 | 16.8 | 78.9 | 단기 반등 트레이드 |
| KTB10Y | 24.2 | 62.5 | 37.4 | 고점 경계 |
| UST10Y | 55.3 | 80.1 | 45.6 | 저평가 패닉 분할 진입 |
| USDKRW | 10.3 | 97.7 | 51.2 | 보유 분할 매수 |
| GOLD | 55.3 | 6.1 | 22.6 | 가치함정 경계 |
| WTI | 31.9 | 34.7 | 89.6 | 비중 축소 |
| US_HY | 78.3 | 16.9 | 57.8 | 단기 반등 트레이드 |
| US_IG | 70.0 | 16.8 | 57.8 | 단기 반등 트레이드 |
| KR_CORP | 56.6 | 66.7 | 62.7 | 최우선 매수 |

stale·부분판정 자산은 없다. 점수는 자산별 자기 역사 대비 백분위다(자산 간 기대수익 비교가 아니다).
눈에 띄는 값: KOSPI200 바텀업 Fwd PER 이 4.4(2010~2025 연말 7.58~13.73)이다. 삼성전자(10-27 NTM EPS 66,470원, 주가 222,000원)·SK하이닉스(446,073원, 1,341,000원)의 NTM PER 이 3배 안팎이고 둘의 비중이 시총 54.5%·선행이익 75.4%라서다. 집계식 오류가 아니라 원자료 그대로다. 이 때문에 per_fwd_12m·erp 백분위가 극단(99.99)이다.

## 9. 실행 시간
| 단계 | 시간 |
|---|---|
| Refinitiv 보유종목 2건 | 7초 |
| Refinitiv 일별 19 RIC × 4구간(76건) | 44초 |
| `.SPX` 8건 | 13초 |
| S&P 바텀업 22건(503종목 × 월별+스냅숏) | 281초 |
| KOSPI200 바텀업 10건(201종목) | 261초 |
| KOSPI200 종목 일봉 804건(백그라운드) | 546초(733건 성공, 71건은 상장 전 구간 "No data") |
| lseg iBoxx 4건 | 측정하지 않음(추정 1분 안팎) |
| lseg EIA 재고 2건 | 6초 |
| FRED 13 + ECOS 6 + CFTC 3 | 55초(+ ECOS 접속 timeout 1회 재시도) |
| 패널 구성 / 점수 | 10초 / 4.5초 |

## 10. 자격 증명·권한
- Refinitiv(eikon, `python.exe`)와 lseg-data(`lsegvenv`) 모두 정상. 키는 워커 stdin 으로만 넘겼다. 프로젝트 파일에서 두 키 문자열을 검색해 0건임을 확인했다.
- `.SPX`·`.VIX` 권한 제약은 Phase 0 그대로(`.SPX`는 get_data 로, VIX 는 FRED).
- ECOS 는 sample 키 10건 페이징으로 받았다(총건수 일치 확인). 정식 키는 없다.
- KRX `~/.config/krx_key`(40자)는 **KRX Open API AUTH_KEY** 다. 지수·종목·ETF 일별 시세는 되고, 파생상품(`idx/drvprod_dd_trd`)은 401 이다.
  mtscore 에 필요한 지수 PER·PBR·배당, 투자자별 순매수, 과거 구성종목은 이 API 에 없다. pykrx 용 KRX_ID/KRX_PW 는 없다. 우회하지 않았다.
- KRX probe 응답은 `data/raw/krx/probe_openapi.json`(무시 대상 폴더, 키 없음)에 있다.
- `~/.config/mtscore/env`는 없고 만들지 않았다.

### .gitignore
- 무시: `data/raw/`(원자료·워커 로그), `data/processed/`(패널), `.venv/`, `__pycache__/`, `*.pyc`, `.omc/`, `*.egg-info/`, `*:Zone.Identifier`.
- 커밋 대상인데 원천 값이 들어 있는 것: `tests/fixtures/phase2/`(녹화 fixture — Refinitiv 3개 파일 6~11행, FRED·ECOS·CFTC·KRX 몇 행), `outputs/phase2/crosscheck.csv`(대조 표본 값), `latest_indicators.csv`(기준일 지표 원시값). 전체 이력은 없다. `score_history.csv.gz`는 파생 점수다.

## 11. 코드
- EIA 재고·iBoxx 는 `scripts/phase2_collect_refinitiv.py eia iboxx`(lseg 워커).
- 어댑터(`src/mtscore/data/adapters/`): `refinitiv.py`(WSL → `python.exe -I refinitiv_worker.py`), `lseg_worker.py`, `fred.py`, `ecos.py`, `cftc.py`, `krx.py`. 모두 출력이 `validate_panel`을 통과한다.
  `-I`가 필요한 이유: 어댑터 폴더의 `csv.py`가 Windows 파이썬의 표준 `csv`를 가려 pandas import 가 죽었다.
- 파생 필드: `src/mtscore/data/build.py`(순수 함수 — 코어 밖 데이터 층). 코어(`src/mtscore/core/`)는 고치지 않았다.
- 설정: `config/universe.yaml` WTI overrides(§4-3)·주석 갱신, `config/profiles/commodity.yaml` `inventory_change`의 `na_until_found` 해제(소스 확인).
- 테스트: `tests/test_phase2_adapters.py`(11개), `tests/test_phase2_build.py`(15개). 녹화 fixture 는 `tests/fixtures/phase2/`(행 몇 개씩), 네트워크 없음.
  전체 `pytest` **202 passed, 17 warnings**(2차; 1차 195, 시작 시 169 passed, 1 warning). 늘어난 경고는 numpy 의 timedelta 'generic' 단위 DeprecationWarning(`pd.Timedelta`·오프셋 연산)이다.

## 12. 결정이 필요한 것
- 1차의 1~5는 2차 사용자 결정 A~D 로 정리됐다. 남은 결정 없음(Phase 3 에서 민감도 필드 비교).
