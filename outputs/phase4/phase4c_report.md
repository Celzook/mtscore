# Phase 4 단계 C — 장기 반전(C1)·FX 캐리 수준(C2) 검증

- 기준: `docs/prereg_2026-10-29.md`(사전 등록, 결과를 보기 전에 고정)
- 브랜치: `phase4-wiki-c`(워크트리, 분기점 `20bc444`)
- 실행: `scripts/phase4c_collect.py` → `scripts/phase4c_build.py` → `scripts/phase4_c.py`(로그: `phase4c_run_log.txt`)
- 설정 파일(`config/profiles`·`universe.yaml`·`scoring.yaml`)은 바꾸지 않았다. 변형은 `config/variants/phase4c.yaml`의 지표를 설정 사본에 붙여 만들었다.

## 0. 결론

| 자산군 (자산) | 변형 | 블록 | 선택 IC 기준선→변형 | 확인 IC 기준선→변형 | 확인 플라시보 p 기준선→변형 | 판정 |
|---|---|---|---|---|---|---|
| 원자재 (GOLD·WTI) | C1 장기 반전 | 밸류 | 0.143 → **0.210** | 0.109 → **0.154** | 0.699 → 0.458 | **채택 조건 충족** |
| 환율 (USDKRW) | C1 장기 반전 | 밸류 | 0.106 → −0.131 | 0.025 → 0.040 | 0.931 → 0.870 | 기각(조건 1) |
| 환율 (USDKRW) | C2 금리차 수준 | 펀더멘털 | −0.012 → **0.094** | 0.038 → **0.070** | 0.892 → 0.730 | **채택 조건 충족** |
| 금리 (KTB10Y·UST10Y) | C1 장기 반전 | 밸류 | 0.230 → 0.128 | −0.021 → 0.009 | 0.896 → 0.956 | 기각(조건 1·3) |

- 시평 63일, 자산군 풀링 Spearman IC 기준이다(`phase4c_verdict.csv`).
- **채택 조건을 충족한 두 변형도 확인 구간에서 유의하지 않다**(p 0.46, 0.73).
  - 사전 등록 조건은 "기준선보다 나빠지지 않음"이라 통과했다.
  - "효과가 확인됐다"는 뜻은 아니다.
- **프로파일에는 반영하지 않았다.** 반영하려면 다음이 필요하다.
  - 별도 레인 검증과 사용자 결정
  - 장기 필드 빌드를 주 패널 파이프라인에 넣는 작업(§6)
- 중복 규칙: 상관 0.9를 넘는 쌍이 없다. 제외 후보도 없다(§3).
- 새 지표는 모든 자산에서 **2013-01부터 점수가 나온다**. 선택 구간 전체를 쓸 수 있다(§2).

## 1. 바꾼 것

- **C0 장기 이력 수집**
  - 2005-01-03~2009-12-31 구간을 Refinitiv `get_timeseries CLOSE`로 받았다. 대상은 `GCc1~4`·`CLc1`·`CLc2`·`KRTSY10Y=KQ`·`US10YT=RR`이다.
    - 저장 위치: `data/raw/phase4c_long/refinitiv/`
  - 2010년 이후는 Phase 2 원자료를 읽기만 했다.
  - REER(FRED `RBKRBIS`)는 Phase 2 캐시가 1994-01부터 있다. `data/raw/phase4c_long/fred/`로 복사만 했다.
- **장기 필드 패널** `data/processed/phase4c_long_panel.csv.gz`(39,193행)
  - 기존 필드와 이름을 분리했다.
    - GOLD·WTI: `close_long`, `close_long_m60`
    - USDKRW: `reer_long`, `reer_long_m60`
    - KTB10Y·UST10Y: `yield_long`, `yield_long_m60`
  - `*_m60` = 같은 장기 계열에서 t − 60 달력월 시점의 값이다.
    - 일별 필드: 그 시점 이전 마지막 관측. 5영업일 넘게 오래된 관측이면 결측이다.
    - REER: 기준월 − 60개월의 값. date와 as_of는 그대로 둔다.
  - 연속물은 Phase 2와 같은 함수를 같은 인자로 썼다.
    - 금: `gc_c1_month`·`gc_held_month(5)`·`continuous_from_nearbys`
    - WTI: `cl_roll_dates`·`back_adjust_ratio(5)`
  - 짝 함수 `lag_months_daily`·`lag_months_exact`를 `src/mtscore/data/build.py`에 추가했다.
- **C1 지표**: 이름은 `long_reversal_60m`이다. 기존 하위블록에 넣었다.
  - 원자재 `valuation.real_price`: `ratio_minus_one(close_long, close_long_m60)`, 방향 −
  - 환율 `valuation.reer`: `ratio_minus_one(reer_long, reer_long_m60)`, 방향 −
    - log 차분 대신 비율 − 1을 썼다. 단조 변환이라 백분위가 같다(테스트로 확인).
  - 금리 `valuation.level`: `spread(yield_long, yield_long_m60)`, 방향 +
- **C2 지표**: 환율 `fundamental.macro`에 `rate_diff_level`을 넣었다. `level(rate_diff)`, 방향 +.
- 기존 지표의 입력은 모두 2010년 이후 필드 그대로다. 장기 필드는 새 지표만 읽는다.

## 2. 커버리지 (`phase4c_coverage.csv`, `phase4c_coverage_fields.csv`, `phase4c_build_info.json`)

**원천별 시작일**
| 원천 | 원자료 시작 | 장기 필드 시작 | `_m60` 첫 값 |
|---|---|---|---|
| GCc1~c4 | 2005-01-03 | 2005-01-03 | 2010-01-04 |
| CLc1·CLc2 | 2005-01-03 | 2005-01-03 | 2010-01-04 |
| KRTSY10Y=KQ | 2005-01-03 | 2005-01-03 | 2010-01-04 |
| US10YT=RR | 2005-01-03 | 2005-01-03 | 2010-01-04 |
| RBKRBIS | 1994-01-01 | 2005-01(기준월) | 2005-01(짝 값은 2000-01 기준월) |

**새 지표 첫 점수일**
| 지표 | 자산 | 첫 원값 | 첫 점수 |
|---|---|---|---|
| C1 | GOLD·WTI·USDKRW·KTB10Y·UST10Y | 2010-01-04 | 2013-01-04 |
| C2 | USDKRW | 2010-01-05 | 2013-01-07 |

- 모두 2013년 이내라 선택 구간을 온전히 쓸 수 있다.
- **같은 규칙을 2005~2009에 적용해도 되는지 확인했다.**
  - 금: c1 교체일이 c2/c1 스프레드 급변일(상위 5%)과 겹치는 비율
    - 2005~2009: k=0에서 0.70(k=±1에서 0.0·0.2)
    - 2010년 이후: 0.69
  - WTI: c1/c2 신호의 참 비율
    - 2005~2009: k=0에서 0.80으로 최대
    - 2010년 이후: 0.59로 최대
  - 두 연속물 모두 규칙이 그대로 맞는다. N/A로 둘 구간이 없다.
- **2010년 이후 구간은 Phase 2와 같다.**
  - `close_long`과 Phase 2 `close`의 최대 상대 차는 2.2e-16이다(GOLD 4,234일, WTI 4,235일).
  - `yield_long`과 `reer_long`은 차가 0이다.
- 금 원자료에서 c1~c4 중 하나라도 빈 날 20일(2005~2009)은 Phase 2와 같은 `dropna` 규칙으로 연속물에서 빠졌다.

## 3. 중복 점검 (`phase4c_redundancy.csv`, 선택 구간 지표 점수 Pearson)

| 새 지표 | 기존 지표 | 풀링 상관 | 자산별 상관 | 63일 IC (새 / 기존) |
|---|---|---|---|---|
| 원자재 C1 | `real_price_level_spot` | 0.40 | GOLD 0.49, WTI 0.35 | 0.077 / 0.143 |
| 환율 C1 | `reer_level` | 0.60 | — | −0.263 / 0.106 |
| 금리 C1 | `real_yield` | 0.11 | KTB −0.20, UST 0.51 | −0.055 / 0.260 |
| 금리 C1 | `spread_to_policy` | 0.11 | KTB 0.56, UST 0.15 | −0.055 / 0.035 |
| 금리 C1 | `term_premium`(UST, 2019-05~ 150일) | 0.14 | — | −0.055 / 0.212 |
| 환율 C2 | `rate_diff_chg_3m` | 0.57 | — | 0.126 / 0.094 |

- 0.9를 넘는 쌍이 없다. 자산별로 봐도 없다. Phase 3 규칙을 적용하면 제외 후보가 없다.
- `real_price_level`은 GOLD·WTI 모두 `overrides`에서 빠져 있어 비교 대상이 없다.

## 4. 보조: 21·126·252일 IC (`phase4c_split_ic.csv`, 판정에 쓰지 않음)

| 자산군 / 변형 | 구간 | 기준선 21·63·126·252 | 변형 21·63·126·252 |
|---|---|---|---|
| 원자재 C1 | 선택 | 0.09·0.14·0.11·0.15 | 0.16·0.21·0.17·0.21 |
| 원자재 C1 | 확인 | 0.04·0.11·0.13·0.16 | 0.10·0.15·0.17·0.10 |
| 환율 C1 | 선택 | 0.12·0.11·0.02·0.30 | −0.04·−0.13·−0.24·0.07 |
| 환율 C1 | 확인 | 0.09·0.03·0.08·0.24 | 0.09·0.04·0.12·0.23 |
| 환율 C2 | 선택 | −0.04·−0.01·0.11·0.13 | 0.05·0.09·0.15·0.11 |
| 환율 C2 | 확인 | 0.03·0.04·−0.09·−0.22 | 0.05·0.07·−0.05·−0.23 |
| 금리 C1 | 선택 | 0.15·0.23·0.35·0.54 | 0.09·0.13·0.26·0.45 |
| 금리 C1 | 확인 | 0.01·−0.02·−0.01·0.07 | 0.02·0.01·0.04·0.12 |

- 원자재 C1은 확인 구간 252일에서 기준선보다 낮다(0.16 → 0.10).
- 환율 C2는 확인 구간 252일 IC가 기준선과 변형 모두 음수다(−0.22·−0.23).
- 이벤트 통계는 `phase4c_events_aux.csv`에 있다. 전체 표본 기준이며 판정에 쓰지 않았다.

## 5. 검증

**기본 설정 재현** (`phase4c_reproduce_diff.csv`)
- 비교 대상은 두 가지다.
  - `outputs/phase2/score_history.csv.gz`(4자리 반올림)
  - `data/processed/phase3_forward_returns.csv.gz`의 블록 점수(6자리 반올림)
- 입력을 Phase 2 패널만 썼을 때와 패널+장기 필드를 썼을 때 모두 불일치 0이다.
  - Phase 2와 비교: 34,573행 모두 일치, 한쪽에만 있는 행 0
  - Phase 3와 비교: 42,118행 모두 일치

**변형의 불변성** (`phase4c_invariance.csv`)
- 변형을 넣어도 기존 지표의 점수 열과 대상이 아닌 블록이 모든 자산에서 비트 단위로 같다.

**테스트**
- 전체 `pytest` 결과는 **224 passed**(기존 217 + 신규 7)다. 경고 17개는 기존과 같다(`phase4c_pytest_run.txt`).
- 신규 테스트 파일은 `tests/test_phase4c.py`다. 확인하는 내용은 다음과 같다.
  - `lag_months_daily`가 코어 `lag_months`와 같다.
  - 일별 공백이 5영업일을 넘으면 결측이다.
  - REER 정확월 짝 함수가 as_of를 유지한다.
  - 비율 − 1과 로그 차분의 백분위가 같다.
  - 앞 구간을 붙여도 백어저스트 연속물의 겹치는 구간 값이 같다.
  - 변형 YAML이 실제 설정에서 빌드되고, 하위블록 위치가 맞다.
  - 엔진 수준: 장기 필드를 추가해도 점수가 불변이다. 새 지표는 2010년부터 원값을 갖는다.
- TODO와 skip은 없다.

**플라시보 설정**
- 2,000회, 이동 범위 [252, n−252), 모든 자산에 같은 이동을 준다(Phase 3 설정).
- 시드 = 11 + 4000 + 10·자산군 순번 + 구간 순번이다.
- **기준선과 변형에 같은 이동 배열을 썼다.** 몬테카를로 잡음(Phase 3 실측 ±0.03)이 판정을 가르지 않게 하기 위해서다.

## 6. 설계 결함 보고

**엔진은 자산 달력 이전 이력을 쓸 수 없다**
- 원인
  - 자산 달력은 `close`·`yield`의 관측일이다. 그래서 2010-01부터 시작한다.
  - `to_calendar`는 달력 첫날 이전 관측을 버린다. 유지 한도 안의 마지막 값 하나만 남는다.
  - 그 결과 장기 필드만 넣어서는 `pct_change_months(·, 60)`가 2015년부터만 계산된다.
- 이번 대응: 코어를 고치지 않았다.
  - 빌더가 같은 장기 계열에서 60개월 전 값 짝 필드(`*_m60`)를 만든다.
  - 지표는 기존 계산 함수(`ratio_minus_one`, `spread`)로 설정만 바꿔 계산한다.
- 남는 문제
  - 창 길이(60)가 계산 함수 params가 아니라 빌더 입력(`config/variants/phase4c.yaml long_months`)에 있다.
  - 창을 바꾸려면 패널을 다시 빌드해야 한다.
  - 해결하려면 코어에서 필드별 달력 이전 이력을 허용해야 한다(코어 변경).
- 채택한 변형을 반영하려면 할 일
  - `phase4c_build.py` 단계를 주 빌드 순서에 넣는다.
  - 패널에 장기 필드를 합친다.
  - 백어저스트 기준점이 같아야 하므로 `close_long`과 `close_long_m60`은 같은 빌드에서 만든다.

**공유 venv의 editable 설치**
- `.venv`의 `mtscore` editable 설치가 주 체크아웃의 `src`를 가리킨다. 그래서 워크트리에서 `pytest`를 실행하면 다른 체크아웃의 코드를 시험하게 된다.
- `pyproject.toml`의 `[tool.pytest.ini_options]`에 `pythonpath = ["src"]`를 추가했다.
- 스크립트는 원래 `ROOT/src`를 맨 앞에 넣으므로 영향이 없다.

## 7. 가정

- C1을 기존 하위블록에 넣었다(원자재 `real_price`, 환율 `reer`, 금리 `level`).
  - 사전 등록 C2의 "기존 블록 구조 그대로"를 C1에도 적용했고, 결과를 보기 전에 고정했다.
  - 새 하위블록에 넣으면 블록 내 비중이 달라진다. 이 변형은 돌리지 않았다(튜닝 금지).
- 금리 C1의 하위블록 비중은 하위블록 내 동일가중이라 지표 수에 따라 달라진다.
  - UST는 1/4이다.
  - KTB는 `term_premium`이 빠져 1/3이다.
- 2005~2009 연속물의 교체 규칙은 Phase 2 가정을 그대로 따른다.
  - 영업일 = 관측 거래일
  - 교체는 5영업일 전
  - GCc1 = 그달 계약, c1~c4는 연속한 4개월
  - 이 규칙들은 2005~2009에서도 교체일 검증 지표로 확인했다(§2).
- REER는 최신 빈티지(수정치)이고, as_of = 기준월 + 3개월이다(Phase 2와 같다). `_m60` 짝 값은 공표 시차가 고정이라는 가정 아래 엔진의 `lag_months`와 같다.
- 구간은 관측 시작일 기준으로 나눴다. 63일 수익이 2020년에 걸쳐도 시작일이 2019년이면 선택 구간이다.
- 환율 풀링은 USDKRW 1개 자산이라 단일 자산 IC와 같다.

## 8. 파일

- **수정**
  - `src/mtscore/data/build.py`(끝에 함수 2개 추가)
  - `pyproject.toml`(pytest `pythonpath`)
- **추가**
  - 설정: `config/variants/phase4c.yaml`
  - 스크립트: `scripts/phase4c_collect.py`, `scripts/phase4c_build.py`, `scripts/phase4_c.py`
  - 테스트: `tests/test_phase4c.py`
  - 보고서와 로그: `outputs/phase4/phase4c_report.md`, `phase4c_run_log.txt`, `phase4c_pytest_run.txt`
  - CSV: `phase4c_verdict.csv`, `phase4c_split_ic.csv`, `phase4c_redundancy.csv`, `phase4c_indicator_ic_selection.csv`, `phase4c_coverage.csv`, `phase4c_coverage_fields.csv`, `phase4c_reproduce_diff.csv`, `phase4c_invariance.csv`, `phase4c_events_aux.csv`
  - JSON: `phase4c_build_info.json`, `phase4c_run_info.json`
- **데이터**(gitignore, 커밋 대상 아님)
  - `data/raw/phase4c_long/`
  - `data/processed/phase4c_long_panel.csv.gz`
- **커밋 주의**: 이 워크트리의 `.venv`·`data/raw`·`data/processed`는 심볼릭 링크다.
  - `.gitignore`의 `data/raw/` 같은 패턴은 끝에 `/`가 있어서 링크를 거르지 못한다. 그래서 `git status`에 `??`로 나온다.
  - `git add -A`를 쓰지 말고, 위 파일만 경로를 지정해 추가한다.
- **재현 순서**
  ```
  .venv/bin/python scripts/phase4c_collect.py   # Refinitiv(Windows python.exe 워커, 키 stdin) — 받은 파일은 건너뜀
  .venv/bin/python scripts/phase4c_build.py
  .venv/bin/python scripts/phase4_c.py          # 약 90초
  .venv/bin/python -m pytest -q
  ```
