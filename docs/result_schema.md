# ScoreResult JSON 스키마 (schema_version 1.0)

`ScoringEngine.score(...).to_json()`이 내는 문서 구조다. 필드를 추가하면 minor 버전(1.x)을 올리고, 필드의 의미나 형식을 바꾸면 major 버전을 올린다. 결측값은 모두 `null`이다(NaN을 쓰지 않는다).

```json
{
  "schema_version": "1.0",
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

자산 간 순위(`ScoreResult.ranking`)는 JSON에 넣지 않는다. 블록 점수가 자기 역사 대비 백분위이므로, 순위는 자기 역사 대비 극단성을 비교한 것이다.
