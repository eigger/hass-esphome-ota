# 공통 규칙 적용 체크리스트

[사용법과 판정 기준](https://github.com/eigger/hass-repo-standards/blob/ba9f3fad8b635c163fb44a4e91b1833cc4ab47b4/docs/checklist.md). 상태: `TODO` 미확인·미충족, `PASS` 근거 확인, `EXCEPTION` 기록된 예외, `N/A` 해당 없음.

## 검토 대상

| 항목 | 값 |
|---|---|
| 통합 리포 / 기본 브랜치 | eigger/hass-esphome-ota / main |
| domain / 구현 경로 | esphome_ota / custom_components/esphome_ota |
| 검토 대상 통합 커밋 | main `c2d6f90` 기준 작업 브랜치 (채택 PR 생성 시 갱신) |
| 검토한 표준 SHA | `ba9f3fad8b635c163fb44a4e91b1833cc4ab47b4` (STANDARDS.md와 일치) |
| 검토일 / 조율 | 2026-10-18 / 메인 에이전트 |
| 구현 / 독립 리뷰 | 메인 에이전트 / Opus 서브 에이전트 |
| 변경 전 지원 최소 HA | 2024.1.0 (`hacs.json`) |
| 유지·변경할 지원 최소 | 유지 (변경 없음) |
| current 테스트 HA / Python / 플러그인 | 2026.10.2 / 3.14 / 0.13.373 |
| 최소 테스트 HA | 구성 불가 — EXCEPTION 참조 |
| profile / 테스트 경로 | integration / ha, `tests/components/esphome_ota/` |
| 이전 검토 기록 | 최초 검토 |
| 채택 판정 | **예외가 있는 채택 진행 중** (원격 CI·PR·중앙 표 대기) |

## 항목별 결과

| 규칙 ID | 확인 항목 | 상태 | 근거 / 남은 작업 |
|---|---|---|---|
| GOV-01, GOV-02 | `STANDARDS.md`에 SHA·profile·기본 브랜치·예외 기록, workflow는 전체 SHA 고정 | PASS | STANDARDS.md, `.github/workflows/*.yml`(`@ba9f3fad…`) |
| GOV-03 | 명시적 채택 PR | TODO | PR 생성 후 링크 기록 |
| GOV-04 | 중앙 현황표 갱신 | TODO | 중앙 리포 미수정 — 행을 `진행 중`(PR 열림)으로 갱신 필요 |
| GOV-05 | 독립 리뷰 서브 에이전트 | PASS(부분) | Opus 리뷰 결과는 아래 '리뷰 기록'. 구현은 메인 에이전트가 직접 수행 |
| HA-01, HA-13 | `custom_components/esphome_ota/` = domain | PASS | manifest `domain: esphome_ota` |
| HA-02 | manifest 필드 확인 | PASS | dependencies·after_dependencies·config_flow·iot_class 선언. hassfest는 CI로 확인 |
| HA-04, HA-05, HA-06, HA-07, HA-08, HA-11, HA-12 | 구현 동작 규칙 | N/A(변경 없음) | 이번 작업은 구현 코드를 변경하지 않음(포맷 전용). 기존 회귀 테스트로 동작 유지 확인 |
| HA-09, HA-10, DOC-07 | Bluetooth | N/A | blesession/Bluetooth 미사용 |
| TEST-08, TEST-02, TEST-03, TEST-09 | `tests/components/esphome_ota/`, 실제 HA fixture·config entry 로딩 | PASS | conftest.py(`enable_custom_integrations`), 167 passed (아래 검증) |
| TEST-01, TEST-06, TEST-07 | 회귀 범위·외부 경계만 mock | PASS | 기존 테스트 유지, 삭제 없음 |
| TEST-04, HACS-01 | 지원 최소와 current 분리, 정확한 최소 검증 | EXCEPTION | STANDARDS.md 예외: 2024.1.0 선언이 코드와 불일치. 최소 상향은 하지 않음 |
| TEST-05, DEP-02, DEP-03, DEP-04, DEP-05, DEP-08 | 최소/현재 라이브러리 환경 | N/A | `manifest.requirements=[]` |
| DEP-01, DEP-06, DEP-07, CI-06 | runtime/test/lint 선언 분리, HA 구성요소 requirements | PASS | `requirements_test.txt`, `requirements_lint.txt`, `ha-components: frontend panel_custom websocket_api http`; pip check는 CI |
| HACS-02 | 배포 구조 | PASS | `custom_components/esphome_ota`, `content_in_root: false` |
| HACS-03, HACS-05 | brand 아이콘, HACS·Hassfest 실행 | TODO | 원격 CI 실행 후 기록 (icon.png 존재만 확인) |
| HACS-06 | 설명·topics | TODO | 원격 메타데이터 미확인 |
| CI-01, CI-02 | Validate/Tests 공통 caller, PR·main push·dispatch·schedule | PASS | tests.yml, validate.yml (main) |
| CI-03, CI-05, CI-08 | 최소 권한·concurrency·SHA 고정 | PASS | `permissions: contents: read`, caller 입력은 리포 상수 |
| CI-04, CI-07, CI-12 | 실제 ha 테스트·Ruff, required checks 이름 | TODO | 원격 CI 후 기록. branch protection 미조회 |
| CI-09, CI-10 | 의존성 updater | N/A | 외부 Python 의존성 없음. Dependabot(actions, pip HA 묶음)만 도입 |
| DOC-01, DOC-02, DOC-06 | README.md(영어)/README.ko.md 상호 링크, 간결화·docs 분리, Issues·LICENSE | PASS | README*.md, docs/features*.md, docs/development.md. Discussions 비활성(`gh repo view`)이라 Issues만 안내 |
| DOC-03, DOC-04, DOC-05 | 관리 배지·Usage·정적 Tests 배지 제거 | PASS | `sync_badges.py --check` OK |
| REL-01~03, CI-11, HACS-04 | 릴리스 | N/A | 이번 적용으로 릴리스하지 않음 |
| REL-04, REL-05 | 이전/분리 | N/A / 권장 | 포맷 변경과 표준 채택을 한 PR에 포함(포맷 전용 커밋 분리 가능) |

## 검증 기록

| 검증 축 / 상태 | Python / HA / 플러그인 | 명령·결과 | 범위 |
|---|---|---|---|
| 현재 환경 / PASS(로컬) | 3.14.x / 2026.10.2 / 0.13.373, ruff 0.17.1 | `ruff check .`, `ruff format --check .` 통과; `pytest tests/components/esphome_ota/ --timeout 120` → 167 passed, 12 subtests passed | 로컬 venv. 원격 CI는 TODO |
| 정확한 최소 HA / EXCEPTION | 3.12 / 2024.1.2(2024.1.0용 플러그인 없음) / 0.13.88 | conftest import 중 `ImportError: cannot import name 'StaticPathConfig' from 'homeassistant.components.http'` | 선언 최소가 코드와 불일치 |
| 정확한 최소 라이브러리 / N/A | — | — | 외부 의존성 없음 |

## 남은 작업

| 항목 | 작업 | 완료 근거 |
|---|---|---|
| 지원 최소 결정 | 사용자 결정: 최소를 코드가 실제 요구하는 버전으로 상향하거나 호환 코드 도입 | 별도 승인 후 hacs.json·README·CI 동시 변경 |
| 원격 검증 | PR의 Tests·Validate(HACS·Hassfest, brand) 실행 결과 기록 | CI run 링크 |
| 중앙 현황표 | 중앙 리포의 hass-esphome-ota 행 갱신 | 중앙 커밋 |

## 리뷰 기록

(독립 리뷰 결과·수정·재검증은 아래에 추가)
