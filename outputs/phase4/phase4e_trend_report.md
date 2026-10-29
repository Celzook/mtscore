# Phase 4 E (TREND) — KR_CORP 추세 표시 현금 차감 면제 + 변동성 가점·confluence 표기

날짜 2026-10-29 · 브랜치 `phase4-wiki` · 근거: CLAUDE.md "확정 결정 (2026-10-29) — Phase 4 종합 판단 후" 결정 4·결정 2. 커밋·푸시는 하지 않았다.

## 설계 결함 보고 (core/api 변경)
- **결함**: 추세 표시(`trend`)는 모든 자산에서 수익 지수의 12개월 수익에서 현금 수익을 뺐다. KR_CORP의 수익 지수(`duration_approx`, 스프레드 기준)는 이미 같은 듀레이션 국고 대비 초과수익 근사라서 현금을 또 빼면 이중 차감이다. 그 결과 부호가 구조적으로 음(-)쪽으로 치우쳤다.
- **영향 범위**: 표시 필드 `trend`뿐이다. 점수·국면 경로는 건드리지 않았다. `core/` 코드는 바꾸지 않았다(`api.trend_history`가 현금 시리즈를 0으로 넘겨 기존 `bt.tsmom_excess`를 그대로 쓴다).
- **조치**: 자산별 설정으로 현금 차감을 면제하고, 결과에 부호의 기준(`trend.basis`)을 싣는다. 스키마 1.1 -> 1.2(필드 추가이므로 minor).

## 설계 선택
- 위치: `config/universe.yaml` 자산 키 `trend: {cash: none, basis: 국고 대비}`. 면제는 자산의 성질(수익 지수의 정의)이라 `return_yield_field` 가정과 같은 자리에 둔다. `scoring.yaml trend`의 "키를 모두 적어야 한다" 규칙을 건드리지 않는다.
- 검증(알 수 없는 키는 `ConfigError`): `trend` 하위 키는 `cash`·`basis`만. `cash` 값은 `subtract`(기본)·`none`. `cash: none`이면 `basis`(비어 있지 않은 문자열)가 필수다. `cash: subtract`에 `basis`를 적으면 거부한다(현금을 빼면서 라벨만 바꾸는 것을 막는다). `trend`가 매핑이 아니어도 거부한다.
- 출력: `trend.basis` = 기본 `"현금 대비"`, KR_CORP `"국고 대비"`, `scoring.yaml`에 `trend` 설정이 없으면 null.

## 변경 파일
| 파일 | 내용 |
|---|---|
| `src/mtscore/config.py` | `AssetSpec.trend_cash`·`trend_basis`, `_parse_asset_trend` 검증, `KNOWN_ASSET_KEYS`에 `trend` 추가 |
| `src/mtscore/api.py` | `SCHEMA_VERSION` 1.2, `trend_history`의 면제 분기, `score()`의 `trend.basis` 열, docstring |
| `config/universe.yaml` | KR_CORP `trend: {cash: none, basis: 국고 대비}`, 키 설명 주석 |
| `docs/result_schema.md` | 1.2, `trend.basis` 필드·설명 |
| `config/profiles/{commodity,credit,equity_index,fx,rates}.yaml` | 결정 2: 주석만(아래) |
| `tests/test_engine.py` | 스키마 테스트 1.2·`basis` 키·"현금 대비" 단언 |
| `tests/test_phase4b.py` | 면제 동작·금리 필드 유무 무관·기본 자산 "현금 대비"·점수 불변·`trend` 설정 없음 시 basis null·검증 오류 8건·실제 유니버스에서 KR_CORP만 면제 |
| `scripts/phase4e_trend_check.py` (신규) | 전후 점검 스크립트 |
| `outputs/phase4/phase4e_trend_{check_run.txt,check.json,kr_corp.csv,report.md}` (신규) | 점검 산출 |

## 결정 2 표기 (주석만, 동작 불변)
- `rv_ratio_20`(equity_index·fx·commodity)·`level_rv_ratio_20`(rates·credit) 행과 5개 프로파일의 `confluence:` 헤더에 `효과 미확인(Phase 3 §6-5, Phase 4 B — 2026-10-29 유지 결정)`을 덧붙였다(프로파일당 2곳, 총 10곳).
- 주석만 바꿨으므로 동작은 같다. 점수 동일성은 아래 증거 1이 함께 보여 준다.

## 증거 (`.venv/bin/python scripts/phase4e_trend_check.py`, 로그 `phase4e_trend_check_run.txt`)
1. **점수 불변**: `score_history` 34,573행이 `outputs/phase2/score_history.csv.gz`와 `check_exact=True`로 정확히 같다. 다르면 스크립트가 중단된다.
2. **result JSON**: Phase 2 `result_2026-10-27.json`과 `trend`·`staged_entry`·`schema_version`을 뺀 나머지가 같다(블록·밴드·국면·기여도·커버리지).
3. **KR_CORP 외 9개 자산**: `trend` 양(+)인 날 비율·유효 일수가 `phase4b_trend_coverage.csv`와 같다.
4. **KR_CORP 전후** (유효 3,809일, 2011-05-18~): 

| | 이전(현금 차감) | 이후(면제) |
|---|---|---|
| 양(+)인 날 비율 | 7.6% | 84.0% |
| 기준일 2026-10-27 value / sign | -0.0272 / -1 | -0.0016 / -1 (`basis` "국고 대비") |

- 부호가 바뀐 날은 2,897일(76.1%). 날마다 `value` 차이 평균 +0.0208(범위 +0.0050~+0.0350)이다. 일별은 `phase4e_trend_kr_corp.csv`.
- `phase4b_trend_coverage.csv`·`phase4b_display_latest.csv`는 재생성하지 않았다. 따라서 이 두 파일의 KR_CORP 행(`share_pos` 0.0759)은 이전 동작 기준이다.
- 기준일 값이 -0.0016으로 0에 가깝다. 부호만 보지 말고 크기도 함께 읽어야 한다.

## 테스트
`.venv/bin/python -m pytest -q` -> 278 passed (경고 77건은 기존 DeprecationWarning).

## 남은 일 (이 에이전트 범위 밖)
- `CLAUDE.md`·대시보드 이식 문서에 "KR_CORP 부호 = 국고 대비" 반영, `phase4b_*` 산출물 재생성 여부는 사용자·메인 결정.
- `trend.basis`가 1.2에서 새로 생겼으므로 1.1 소비자는 이 키를 무시하면 된다(필드 추가라 하위 호환).
