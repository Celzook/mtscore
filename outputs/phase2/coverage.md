# Phase 2 커버리지 — 자산별 지표 사용/제외와 사유 (기준일 2026-10-27)

`used` = 계산에 들어감, `available` = 기준일에 점수가 있음. 사유 원문은 `coverage.csv`.

## KOSPI200

| 블록 | 하위블록 | 지표 | 사용 | 첫 점수일 | 사유 |
|---|---|---|---|---|---|
| oversold | price | disparity_20 | O | 2013-01-29 |  |
| oversold | price | disparity_60 | O | 2013-04-01 |  |
| oversold | price | disparity_200 | O | 2013-10-21 |  |
| oversold | price | drawdown_52w_over_rv | O | 2013-10-21 |  |
| oversold | price | return_z_5 | O | 2013-10-28 |  |
| oversold | price | return_z_20 | O | 2013-11-18 |  |
| oversold | price | rsi_2 | O | 2013-01-07 |  |
| oversold | confluence | bb_pctb_20 | O | 2013-01-29 |  |
| oversold | confluence | rsi_14 | O | 2013-01-22 |  |
| oversold | breadth | pct_above_ma20 | O | 2013-01-29 |  |
| oversold | breadth | pct_above_ma200 | O | 2013-10-21 |  |
| oversold | breadth | pct_new_low_52w | O | 2014-01-03 |  |
| oversold | breadth | adr_20 | O | 2013-02-01 |  |
| oversold | vol_sentiment | vol_index_level | O | 2013-01-04 |  |
| oversold | vol_sentiment | vol_index_over_rv | O | 2013-01-28 |  |
| oversold | vol_sentiment | vol_term_inversion | — |  | missing_field:vol_index_3m — VKOSPI 기간구조(3개월물) 소스 없음 — vol_index_3m 미확보 |
| oversold | vol_sentiment | put_call | — |  | status:na_until_found — Put/Call 소스 미확인(KRX·KOFIA·CBOE) — na_until_found |
| oversold | vol_sentiment | home_ccy_shock_20 | O | 2013-02-01 |  |
| oversold | vol_sentiment | rv_ratio_20 | O | 2013-11-12 |  |
| oversold | flows | foreign_net_buy_intensity | — |  | missing_field:foreign_net_buy — 투자자별 순매수 소스 없음: pykrx 는 KRX_ID/KRX_PW 로그인 필요(계정 없음), KRX Open API(AUTH_KEY) 응답에 투자자별 매매 없음, naver HTTP 410 |
| oversold | flows | inst_net_buy_intensity | — |  | status:na_until_found — 위와 같음(기관 순매수) — na_until_found |
| oversold | flows | margin_debt_change | — |  | status:na_until_found — 신용잔고(KOFIA) 미확인 — na_until_found |
| oversold | flows | forced_liquidation | — |  | status:na_until_found — 반대매매(KOFIA) 미확인 — na_until_found |
| valuation | multiples | pbr_trailing | O | 2013-02-01 |  |
| valuation | multiples | per_fwd_12m | O | 2013-02-01 |  |
| valuation | multiples | dividend_yield | O | 2013-02-26 |  |
| valuation | multiples | erp | O | 2013-02-01 |  |
| fundamental | earnings | revision_ratio | — |  | status:na_until_found — 수정 건수 필드 실패(Phase 0) → revision_breadth(바텀업 상향 비중)로 대체 |
| fundamental | earnings | revision_breadth | O | 2013-02-26 |  |
| fundamental | earnings | fwd_eps_chg_1m | O | 2013-03-04 |  |
| fundamental | earnings | fwd_eps_chg_3m | O | 2013-05-03 |  |
| fundamental | earnings | revision_momentum | O | 2013-04-02 |  |
| fundamental | macro | home_ccy_trend_3m | O | 2013-04-05 |  |

## SP500

| 블록 | 하위블록 | 지표 | 사용 | 첫 점수일 | 사유 |
|---|---|---|---|---|---|
| oversold | price | disparity_20 | O | 2013-01-29 |  |
| oversold | price | disparity_60 | O | 2013-04-01 |  |
| oversold | price | disparity_200 | O | 2013-10-15 |  |
| oversold | price | drawdown_52w_over_rv | O | 2013-10-18 |  |
| oversold | price | return_z_5 | O | 2013-10-25 |  |
| oversold | price | return_z_20 | O | 2013-11-15 |  |
| oversold | price | rsi_2 | O | 2013-01-07 |  |
| oversold | confluence | bb_pctb_20 | O | 2013-01-29 |  |
| oversold | confluence | rsi_14 | O | 2013-01-22 |  |
| oversold | breadth | pct_above_ma20 | — |  | override_exclude:breadth (universe.yaml) |
| oversold | breadth | pct_above_ma200 | — |  | override_exclude:breadth (universe.yaml) |
| oversold | breadth | pct_new_low_52w | — |  | override_exclude:breadth (universe.yaml) |
| oversold | breadth | adr_20 | — |  | override_exclude:breadth (universe.yaml) |
| oversold | vol_sentiment | vol_index_level | O | 2012-12-31 |  |
| oversold | vol_sentiment | vol_index_over_rv | O | 2013-01-28 |  |
| oversold | vol_sentiment | vol_term_inversion | O | 2012-12-31 |  |
| oversold | vol_sentiment | put_call | — |  | status:na_until_found — Put/Call 소스 미확인(KRX·KOFIA·CBOE) — na_until_found |
| oversold | vol_sentiment | home_ccy_shock_20 | — |  | override_exclude:home_ccy_shock_20 (universe.yaml) |
| oversold | vol_sentiment | rv_ratio_20 | O | 2013-11-11 |  |
| oversold | flows | foreign_net_buy_intensity | — |  | override_exclude:flows (universe.yaml) |
| oversold | flows | inst_net_buy_intensity | — |  | override_exclude:flows (universe.yaml) |
| oversold | flows | margin_debt_change | — |  | override_exclude:flows (universe.yaml) |
| oversold | flows | forced_liquidation | — |  | override_exclude:flows (universe.yaml) |
| valuation | multiples | pbr_trailing | — |  | override_exclude:pbr_trailing (universe.yaml) |
| valuation | multiples | per_fwd_12m | O | 2013-01-29 |  |
| valuation | multiples | dividend_yield | — |  | override_exclude:dividend_yield (universe.yaml) |
| valuation | multiples | erp | O | 2013-01-29 |  |
| fundamental | earnings | revision_ratio | — |  | status:na_until_found — 수정 건수 필드 실패(Phase 0) → revision_breadth(바텀업 상향 비중)로 대체 |
| fundamental | earnings | revision_breadth | O | 2013-03-01 |  |
| fundamental | earnings | fwd_eps_chg_1m | O | 2013-03-01 |  |
| fundamental | earnings | fwd_eps_chg_3m | O | 2013-04-29 |  |
| fundamental | earnings | revision_momentum | O | 2013-04-01 |  |
| fundamental | macro | home_ccy_trend_3m | — |  | override_exclude:home_ccy_trend_3m (universe.yaml) |

## KTB10Y

| 블록 | 하위블록 | 지표 | 사용 | 첫 점수일 | 사유 |
|---|---|---|---|---|---|
| oversold | price | yield_chg_z_20 | O | 2013-11-18 |  |
| oversold | price | yield_chg_z_60 | O | 2014-01-13 |  |
| oversold | price | yield_disparity_60 | O | 2013-04-01 |  |
| oversold | confluence | bb_pctb_20 | O | 2013-01-29 |  |
| oversold | confluence | rsi_14 | O | 2013-01-22 |  |
| oversold | volatility | level_rv_ratio_20 | O | 2013-11-12 |  |
| oversold | positioning | futures_net_spec | — |  | override_exclude:futures_net_spec (universe.yaml) |
| valuation | level | real_yield | O | 2013-01-04 |  |
| valuation | level | spread_to_policy | O | 2013-01-04 |  |
| valuation | level | term_premium | — |  | override_exclude:term_premium (universe.yaml) |
| fundamental | macro | macro_surprise | — |  | status:na_until_found — 경기·물가 서프라이즈 소스 미확인 — na_until_found |
| fundamental | macro | inflation_momentum | O | 2014-04-04 |  |
| fundamental | macro | policy_direction | O | 2013-07-05 |  |
| fundamental | macro | financial_conditions | — |  | override_exclude:financial_conditions (universe.yaml) |

## UST10Y

| 블록 | 하위블록 | 지표 | 사용 | 첫 점수일 | 사유 |
|---|---|---|---|---|---|
| oversold | price | yield_chg_z_20 | O | 2013-11-18 |  |
| oversold | price | yield_chg_z_60 | O | 2014-01-14 |  |
| oversold | price | yield_disparity_60 | O | 2013-04-01 |  |
| oversold | confluence | bb_pctb_20 | O | 2013-02-01 |  |
| oversold | confluence | rsi_14 | O | 2013-01-25 |  |
| oversold | volatility | level_rv_ratio_20 | O | 2013-11-12 |  |
| oversold | positioning | futures_net_spec | O | 2014-07-07 |  |
| valuation | level | real_yield | O | 2013-01-04 |  |
| valuation | level | spread_to_policy | O | 2013-01-04 |  |
| valuation | level | term_premium | O | 2019-05-28 |  |
| fundamental | macro | macro_surprise | — |  | status:na_until_found — 경기·물가 서프라이즈 소스 미확인 — na_until_found |
| fundamental | macro | inflation_momentum | O | 2014-04-04 |  |
| fundamental | macro | policy_direction | O | 2013-07-08 |  |
| fundamental | macro | financial_conditions | O | 2014-08-25 |  |

## USDKRW

| 블록 | 하위블록 | 지표 | 사용 | 첫 점수일 | 사유 |
|---|---|---|---|---|---|
| oversold | price | disparity_60 | O | 2013-04-01 |  |
| oversold | price | return_z_20 | O | 2013-11-18 |  |
| oversold | confluence | bb_pctb_20 | O | 2013-01-29 |  |
| oversold | confluence | rsi_14 | O | 2013-01-22 |  |
| oversold | volatility | rv_ratio_20 | O | 2013-11-12 |  |
| oversold | positioning | spec_positioning | — |  | override_exclude:spec_positioning (universe.yaml) |
| valuation | reer | reer_level | O | 2013-01-04 |  |
| fundamental | macro | rate_diff_chg_3m | O | 2013-04-05 |  |
| fundamental | macro | current_account_trend | O | 2013-04-05 |  |
| fundamental | macro | terms_of_trade_trend | — |  | status:na_until_found — 교역조건(ECOS 403Y) 미확인 — na_until_found |

## GOLD

| 블록 | 하위블록 | 지표 | 사용 | 첫 점수일 | 사유 |
|---|---|---|---|---|---|
| oversold | price | disparity_60 | O | 2013-04-01 |  |
| oversold | price | return_z_20 | O | 2013-11-18 |  |
| oversold | confluence | bb_pctb_20 | O | 2013-02-01 |  |
| oversold | confluence | rsi_14 | O | 2013-01-25 |  |
| oversold | volatility | rv_ratio_20 | O | 2013-11-11 |  |
| oversold | positioning | spec_positioning | O | 2014-07-07 |  |
| valuation | real_price | real_price_level | — |  | override_exclude:real_price_level (universe.yaml) |
| valuation | real_price | real_price_level_spot | O | 2013-01-04 |  |
| fundamental | curve | backwardation | — |  | override_exclude:backwardation (universe.yaml) |
| fundamental | inventory | inventory_change | — |  | override_exclude:inventory_change (universe.yaml) |
| fundamental | real_rate | real_rate_change | O | 2013-04-05 |  |

## WTI

| 블록 | 하위블록 | 지표 | 사용 | 첫 점수일 | 사유 |
|---|---|---|---|---|---|
| oversold | price | disparity_60 | O | 2013-04-01 |  |
| oversold | price | return_z_20 | O | 2013-11-18 |  |
| oversold | confluence | bb_pctb_20 | O | 2013-02-01 |  |
| oversold | confluence | rsi_14 | O | 2013-01-25 |  |
| oversold | volatility | rv_ratio_20 | O | 2013-11-11 |  |
| oversold | positioning | spec_positioning | O | 2014-07-01 |  |
| valuation | real_price | real_price_level | — |  | override_exclude:real_price_level (universe.yaml) |
| valuation | real_price | real_price_level_spot | O | 2013-01-04 |  |
| fundamental | curve | backwardation | — |  | override_exclude:backwardation (universe.yaml) |
| fundamental | curve | backwardation_spot | O | 2013-01-04 |  |
| fundamental | inventory | inventory_change | O | 2013-02-04 |  |

## US_HY

| 블록 | 하위블록 | 지표 | 사용 | 첫 점수일 | 사유 |
|---|---|---|---|---|---|
| oversold | spread | spread_chg_z_20 | O | 2013-11-11 |  |
| oversold | confluence | bb_pctb_20 | O | 2013-01-31 |  |
| oversold | confluence | rsi_14 | O | 2013-01-25 |  |
| oversold | volatility | level_rv_ratio_20 | O | 2013-11-04 |  |
| valuation | level | spread_level | O | 2013-01-04 |  |
| fundamental | defaults | default_trend | — |  | status:na_until_found — 부도율 소스 미확인 — na_until_found |
| fundamental | cycle | equity_eps_momentum | O | 2013-04-29 |  |
| fundamental | cycle | quality_gap_trend | O | 2013-04-05 |  |

## US_IG

| 블록 | 하위블록 | 지표 | 사용 | 첫 점수일 | 사유 |
|---|---|---|---|---|---|
| oversold | spread | spread_chg_z_20 | O | 2013-11-12 |  |
| oversold | confluence | bb_pctb_20 | O | 2013-01-31 |  |
| oversold | confluence | rsi_14 | O | 2013-01-25 |  |
| oversold | volatility | level_rv_ratio_20 | O | 2013-11-04 |  |
| valuation | level | spread_level | O | 2013-01-04 |  |
| fundamental | defaults | default_trend | — |  | status:na_until_found — 부도율 소스 미확인 — na_until_found |
| fundamental | cycle | equity_eps_momentum | O | 2013-04-29 |  |
| fundamental | cycle | quality_gap_trend | O | 2013-04-05 |  |

## KR_CORP

| 블록 | 하위블록 | 지표 | 사용 | 첫 점수일 | 사유 |
|---|---|---|---|---|---|
| oversold | spread | spread_chg_z_20 | O | 2013-11-18 |  |
| oversold | confluence | bb_pctb_20 | O | 2013-01-29 |  |
| oversold | confluence | rsi_14 | O | 2013-01-22 |  |
| oversold | volatility | level_rv_ratio_20 | O | 2013-11-12 |  |
| valuation | level | spread_level | O | 2013-01-04 |  |
| fundamental | defaults | default_trend | — |  | status:na_until_found — 부도율 소스 미확인 — na_until_found |
| fundamental | cycle | equity_eps_momentum | O | 2013-05-03 |  |
| fundamental | cycle | quality_gap_trend | O | 2013-04-05 |  |
