# ScoreResult JSON 스키마 (schema_version 1.1)

`ScoringEngine.score(...).to_json()`이 내는 문서 구조다. 필드를 추가하면 minor 버전(1.x)을 올리고(1.1: `staged_entry`·`trend` 추가, 2026-10-29), 필드의 의미나 형식을 바꾸면 major 버전을 올린다. 결측값은 모두 `null`이다(NaN을 쓰지 않는다).

```json
{
  "schema_version": "1.1",
  "engine_version": "0.1.0",
  "as_of": "YYYY-MM-DD",
  "note": "블록 점수는 자산별 자기 과거 분포 대비 백분위(0~100, 클수록 매수 매력)",
  "assets": [
    {
      "asset_id": "KOSPI200",
      "date": "YYYY-MM-DD",
      "stale": true|false,
      "blocks": {"oversold": 0-100|null, "valuation": 0-100|null, "fundamental": 0-100|null},
      "bands":  {"oversold": "극단|경계|중립|반대경계|반대극단"|null, "...": "..."},
      "regime": {"label": "최우선 매수|...|축약:O高·F低"|null, "display": "<label> (부분판정)"|"<label>"|null,
                 "partial": true|false,
                 "states": {"o": "high|low"|null, "v": "...", "f": "..."}},
      "staged_entry": {"flag": true|false|null, "oversold": 0-100|null, "vol_ratio": float|null,
                       "vol_indicator": "rv_ratio_20"|null,
                       "reason": ""|"staged_entry 설정 없음"|"unavailable_at_as_of"|"no_vol_indicator"|
                                 "multiple_vol_indicators:<a,b>"|"oversold_na"|"vol_ratio_na"},
      "trend": {"sign": 1|-1|0|null, "value": float|null, "months": 12|null,
                "reason": ""|"trend 설정 없음"|"missing_field:<f>"|"return_index:<사유>"|"insufficient_history"|
                          "unavailable_at_as_of"},
      "contributions": [
        {"block": "oversold", "sub_block": "price", "indicator": "disparity_20",
         "raw": float|null, "percentile": 0-100|null, "score": 0-100|null,
         "weight_in_block": float, "contribution": float|null}
      ],
      "coverage": [
        {"indicator": "put_call", "block": "oversold", "sub_block": "vol_sentiment", "function": "level",
         "fields": "put_call", "direction": "+|-", "used": true|false, "available": true|false,
         "reason": ""|"status:na_until_found"|"missing_field:<f>"|"override_exclude:<k>"|
                   "insufficient_history"|"currency_variant:<v>"|"asset_class:<c> 미적용"|"unavailable_at_as_of",
         "first_score_date": "YYYY-MM-DD"|null}
      ]
    }
  ]
}
```

## 필드 설명
| 필드 | 뜻 |
|---|---|
| `as_of` | 요청한 기준일. 이 날 알려진 값(`as_of` ≤ 기준일)만 썼다 |
| `assets[].date` | 그 자산이 실제로 쓴 날. 자산 달력(자기 가격 필드가 공표된 거래일) 중 기준일 이전 마지막 날이다 |
| `assets[].stale` | 그 날이 기준일보다 `daily_ffill_max_bdays` 영업일 넘게 오래됐다는 뜻(피드 중단). 참이면 블록·국면은 N/A, coverage는 `unavailable_at_as_of`, 순위에서 빠진다 |
| `coverage.used` / `available` | `used`: 이력 어딘가에서 점수가 계산됐는지. `available`: 기준일에 점수가 있었는지. 사용했지만 기준일에 없으면 reason이 `unavailable_at_as_of`(데이터 끊김·유지 한도 초과)다 |
| `percentile` | 원시값의 자기 과거 분포 내 백분위 |
| `score` | 방향을 반영한 값. (+) 지표는 percentile 그대로, (−) 지표는 100 − percentile이다 |
| `weight_in_block` | 그날 가용한 지표·하위블록만으로 가중치를 다시 맞춘 블록 내 비중. 한 블록의 `contribution` 합은 블록 점수와 같다. `scoring.yaml sub_block_agg`가 `min`인 하위블록은 최솟값을 낸 지표(동점이면 정의 순서상 첫 지표)가 하위블록 비중 전체를 갖고, 나머지 지표는 비중 0·기여도 0이다. 그 하위블록이 그날 결측이면 모든 지표가 비중 0·기여도 `null`이다 |
| `regime.partial` | N/A 블록이 있어 부분판정이라는 뜻 |
| `regime.label` | N/A 블록이 있으면 그 블록에 high·low를 모두 넣어 본다. 판정이 하나로 모이면 그 라벨, 갈리면 축약 라벨(`축약:O高·F低`)이다 |
| `regime.display` | 부분판정이면 라벨 뒤에 `scoring.yaml regime.partial_label`을 붙인 표시용 문자열이다 |
| `staged_entry` | 분할 진입 표시(1.1 추가, 사전 등록 B2). `flag`는 과매도 블록 점수 ≥ `scoring.yaml staged_entry.oversold_min`이고 변동성비 원시값 ≥ `vol_ratio_min`일 때 참이다. 변동성비는 계산 함수가 `staged_entry.vol_functions`에 있는 이 자산의 사용 지표(정확히 1개, 이름은 `vol_indicator`)의 원시값이다. 판정할 수 없으면 `flag`가 null이고 `reason`에 사유가 있다. **점수·국면에 영향이 없다**(표시 전용) |
| `trend` | 추세 표시(1.1 추가, 사전 등록 B3). `value` = 수익 지수(백테스트 수익률 규칙: `close_tr`·`close`·`duration_approx`·USDKRW 역수)의 `trend.months` 달력월 수익 − 같은 구간 현금 수익(`trend.cash_field` 정책금리, 없는 자산은 `universe.yaml refs`, 직전일 금리/100/`cash_days_per_year` 복리, 가정). `sign`은 그 부호(±1, 정확히 0이면 0). 구간 안에 금리 결측일이 있거나 이력이 짧으면 null. **점수·국면 판정에 쓰지 않는다** |

자산 간 순위(`ScoreResult.ranking`)는 JSON에 넣지 않는다. 블록 점수가 자기 역사 대비 백분위이므로, 순위는 자기 역사 대비 극단성을 비교한 것이다.
