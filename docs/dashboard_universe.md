# Stock_Dashboard 유니버스 ↔ mtscore 대응표 (2026-10-29)

- **원천**: Stock_Dashboard 홈 화면의 "유니버스 점수판"이다. 저장소 regime-council, 브랜치 `refinitiv-migration`, 커밋 `3943460`.
  - 주식 쪽: `universe/equity.json`의 `series` 가운데 `static/index.html`의 `SB_EQ_GROUPS` 6개 묶음에 속한 33개다. 묶음은 국내, 선진국, 신흥국, 스타일·팩터, 섹터·테마, 우선주다. 변동성 묶음(VIX, VXN, VKOSPI, VSTOXX)은 점수판에 나오지 않는다.
  - 정량 스캐너 쪽: `quant.py`의 `SCAN` 15개
  - 점수판 타일은 설정상 모두 48개다. 화면에는 기술 점수가 계산된 타일만 나오므로 실제 노출 수는 다를 수 있다. 이 가운데 7쌍은 두 목록에 같은 자산이 겹친다. 그래서 고유 자산은 **41개**다.
- **사용자 지시** (2026-10-29): "유니버스 목록은 Stock_Dashboard 프로젝트로부터 받아봐." 임계값 이벤트 방식은 보류 상태로 둔다. 대시보드에도 넣지 않는다.
- **이 표의 용도**: 3단계(대시보드 이식)의 범위를 잡는 것이다. 자산 추가는 설정 추가다(CLAUDE.md). 지표 자료를 구할 수 있는지는 자산마다 Phase 0 방식으로 확인한다. 아래 "필요 자료" 칸은 [추정]이다.

## 1. 이미 mtscore에 있는 자산 (7개)
| 대시보드 키 | 대시보드 이름 | mtscore asset_id | 비고 |
|---|---|---|---|
| kospi200 (주식) · kospi (주식·정량) | KOSPI200 · KOSPI | KOSPI200 | [설계 제안] 이식할 때 KOSPI 종합 타일에는 KOSPI200 점수를 대용으로 쓴다(대용 표기). 지금 대시보드 kospi 타일은 `^KS11` 자체 점수다. 대시보드 kospi200은 `069500.KS`(KODEX 200 ETF)이고, mtscore KOSPI200은 `.KS200TR` 총수익지수다. 같은 시장이지만 시리즈는 다르다 |
| sp500 (주식·정량) | S&P500 | SP500 | |
| ktb_10y (정량) | 국고10년 (가격 환산) | KTB10Y | |
| ust_10y_cmt (정량) | 미국채10년 (가격 환산) | UST10Y | |
| usdkrw (정량) | USD/KRW | USDKRW | mtscore는 원화 매수 관점이다. [설계 메모] 대시보드 표시 방향과 맞춰야 할 수 있다 |
| gold (정량) | 금 | GOLD | |
| wti (정량) | WTI | WTI | |

- **대시보드에 없는 mtscore 자산**: US_HY, US_IG, KR_CORP. 이식할 때 점수판에 "크레딧" 묶음을 새로 둘지는 사용자가 정한다.

## 2. 새로 넣어야 하는 자산 (33개)
| 묶음 | 대시보드 키 (티커) | mtscore 자산군 | 필요 자료 [추정] |
|---|---|---|---|
| 국내 | kosdaq (^KQ11) | equity_index | 밸류·이익: KOSDAQ PER·PBR·12M fwd EPS |
| 선진국 | ndx (^NDX) · 정량 nasdaq(종합) | equity_index | 밸류·이익: 지수 PER·EPS. 두 타일을 하나로 볼지 정한다 |
| 선진국 | sx5e (^STOXX50E) · 정량 stoxx50 | equity_index | 밸류·이익: 지수 PER·EPS. 유로 금리 |
| 선진국 | nikkei (^N225) · 정량 nikkei | equity_index | 밸류·이익: 지수 PER·EPS. 엔 금리 |
| 신흥국 | csi300 (510300.SS) | equity_index | ETF 가격. 밸류는 지수 기준 |
| 신흥국 | hsi (^HSI) | equity_index | |
| 신흥국 | nifty (^NSEI) | equity_index | |
| 신흥국 | taiex (^TWII) | equity_index | |
| 신흥국 | aaxj (AAXJ) | equity_index | ETF 밸류 |
| 신흥국 | eem (EEM) · 정량 eem | equity_index | ETF 밸류 |
| 스타일·팩터 | f_div SCHD · f_minvol USMV · f_quality QUAL · f_value VLUE · f_growth IWF · f_mom MTUM · kr_div 161510.KS | (새 자산군 후보) | ETF 밸류(가중 PER·PBR). 팩터 ETF에 맞는 "펀더멘털" 정의가 지금 프로필에는 없다 |
| 섹터·테마 | XLF · XLV · XLK · SOXX · XLE · ICLN · PAVE · 091170.KS · 091160.KS · 266420.KS | (새 자산군 후보) | ETF 밸류. 섹터 이익 수정 |
| 우선주 | samsung 005930.KS · samsung_pref 005935.KS · pff PFF | (새 자산군 후보) | 개별주는 지수 모델 범위 밖일 수 있다 [추정]. 우선주 괴리는 페어 칸이 이미 다룬다 |
| 환율 | usdjpy · eurusd · dxy | fx | 금리차(정책금리), 실질실효환율, 포지셔닝 |

- **세는 법**: 이 33개는 위 원천 설명의 "주식 쪽 33개"와 다른 집합이다. 여기서는 이미 있는 kospi200·sp500과 kospi를 빼고 환율 3개를 더했다. 국내 1 + 선진국 3 + 신흥국 6 + 팩터 7 + 섹터 10 + 우선주 3 + 환율 3 = **33개**다.
- **41개 맞추기**: 이미 있는 7개 + KOSPI 종합 1개(KOSPI200 대용) + 새 자산 33개 = 41개다.
  - KOSPI 종합을 대용이 아니라 별도 자산으로 보면 새 자산은 34개가 된다.
- **겹치는 7쌍**: kospi, kosdaq, sp500, nikkei, eem은 두 목록에서 키가 같다. ndx(나스닥100)와 nasdaq(나스닥 종합), sx5e와 stoxx50은 같은 시장의 지수다.

## 3. 설계상 열린 문제 (3단계 착수 전에 정한다)
1. **팩터·섹터·우선주 ETF의 블록 정의**: 지금 블록 구조(과매도·밸류·펀더멘털)는 지수·금리·환율·원자재·크레딧에 맞춰져 있다. 이 자산들은 과매도만 산출되고 나머지는 부분판정이 될 가능성이 크다 [추정]. 새 자산군 프로필을 둘지 정해야 한다. 프로필 추가는 설정이다. 코어 코드를 바꿔야 하면 설계 결함으로 보고한다.
2. **검증 범위**: 새 자산에는 Phase 3 방식의 IC·플라시보 검증이 없다. 검증 전에는 "검증 전" 표시를 붙여 보여 준다.
3. **겹치는 타일**: 나스닥 종합과 나스닥100처럼 같은 자산의 다른 지수가 두 번 나온다. 점수 하나를 쓸지 정한다.
4. **임계값 이벤트**: 보류 상태다. 대시보드에 넣지 않는다.
