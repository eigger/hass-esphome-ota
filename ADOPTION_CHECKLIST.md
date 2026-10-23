# 공통 규칙 적용 체크리스트

이 파일은 eigger/hass-esphome-ota의 채택 기록입니다(템플릿 기반). [사용법과 판정 기준](https://github.com/eigger/hass-repo-standards/blob/main/docs/checklist.md)을 읽고, 아래 규칙은 `STANDARDS.md`에 기록한 표준 커밋에서 확인합니다. 태그·릴리스 대신 `main`의 검토 커밋을 기준으로 하며, 위 사용법 링크의 `main`은 채택 시 검토한 커밋 SHA로 바꿉니다.

## 검토 대상

| 항목 | 값 |
|---|---|
| 통합 리포 / 실제 기본 브랜치 | eigger/hass-esphome-ota / main |
| domain / 구현 경로 | esphome_ota / custom_components/esphome_ota |
| 검토 대상 통합 커밋 / 채택 PR | main `c2d6f90` 기준 브랜치 chore/adopt-hass-repo-standards / [PR #29](https://github.com/eigger/hass-esphome-ota/pull/29) (HA 동작 결함 수정은 [PR #30](https://github.com/eigger/hass-esphome-ota/pull/30)으로 같은 브랜치에 스쿼시 병합) |
| 검토한 표준 전체 커밋 SHA | `ba9f3fad8b635c163fb44a4e91b1833cc4ab47b4` (STANDARDS.md와 일치) |
| 검토일 / 조율 담당 | 2026-10-18 / 메인 에이전트 |
| 구현 서브 에이전트 / 독립 리뷰·검증 서브 에이전트 | 없음(메인 직접 구현, 예외) / Opus 서브 에이전트 |
| 중앙 현황표 반영일 / 기록 | 2026-10-18 / [중앙 현황표 행](https://github.com/eigger/hass-repo-standards/blob/main/docs/adoption-status.md) (#29 병합 직후 갱신) |
| 변경 전 지원 최소 HA / 근거 파일 | 2024.1.0 / hacs.json |
| 유지·변경할 지원 최소 / 근거·승인 | 유지(변경 없음). 상향은 별도 승인 필요 |
| current 테스트 HA / 호환 Python·플러그인 | 2026.10.2 / 3.14 / 0.13.373 |
| 최소 테스트 HA / 호환 Python·플러그인 | 구성 불가 — TEST-04 예외 |
| profile / 테스트 경로 | integration / ha, `tests/components/esphome_ota/` |
| 이전 검토 기록 | 최초 검토 |
| 채택 판정 | **예외 포함** (필수 EXCEPTION 2건: GOV-05, TEST-04/HACS-01; 권장 HA-03 일부 미채택 — 후속) |

상태: `TODO` = 미확인·미충족, `PASS` = 근거로 확인, `EXCEPTION` = 적용 대상의 기록된 예외, `N/A` = 적용 조건에 해당 없음. 모든 항목은 미확인으로 시작합니다. `TODO`를 해당 없음으로 처리하지 않습니다. 묶은 규칙의 결과가 다르면 행을 나눕니다. 권장 항목은 별도로 표시했으며 미채택 이유를 기록합니다.

## 채택·구조·사용자 데이터

| 규칙 ID | 확인 항목 | 상태 | 근거 / 남은 작업 |
|---|---|---|---|
| GOV-01, GOV-02 | `STANDARDS.md`에 표준 SHA·profile·실제 기본 브랜치·예외 기록, workflow/action은 검토 SHA로 고정 | PASS | STANDARDS.md, workflow `@ba9f3fad…` 전체 SHA 고정 |
| GOV-03 | 새 표준 채택 변경의 영향·이관 방법과 명시적 채택 PR 확인. 규칙 자체를 변경하면 공통 CHANGELOG 기록 | PASS | 명시적 채택 [PR #29](https://github.com/eigger/hass-esphome-ota/pull/29); 표준 규칙 자체 변경 없음(CHANGELOG 기록 불필요) |
| GOV-04 | 중앙 표에 작업 시작·단계 변경·종료 상태, 담당·적용 내용·검증/리뷰 근거·남은 작업 갱신, 타 리포 기록 보존 | PASS | 중앙 `docs/adoption-status.md`의 hass-esphome-ota 행만 갱신(타 행 보존), #29 병합 후 `예외 포함`으로 기록 |
| GOV-05 | 구현과 독립 리뷰·검증을 별도 서브 에이전트에게 위임, 지적 수정·재검증 및 결과 취합 | EXCEPTION | 사용자 지시로 구현은 메인 에이전트, 리뷰만 Opus 서브 에이전트(STANDARDS.md 예외). 리뷰 지적 수정 후 재검증은 아래 기록 |
| HA-01, HA-13 | `custom_components/<domain>/`와 domain 일치, 필요한 모듈·공개 API·생명주기는 Core 대응 구조 | PASS | `custom_components/esphome_ota/`, manifest `domain: esphome_ota` |
| HA-02 | manifest 필드·정렬·동작 선언 확인, 공식 품질 등급 자가 표기 없음 | PASS | manifest 필드(dependencies, after_dependencies, config_flow, iot_class) 확인; 품질 등급 자가 표기 없음. Hassfest 결과는 CI 대기 |
| HA-03 (권장) | 공통 상수·설정·갱신·플랫폼 역할 및 프로토콜 경계에 맞게 모듈 구성 | PARTIAL | builder_host/builder_port를 const.py 상수로 이전, 업로드 view는 `async_setup`에서 1회 등록. 미채택(권장): websocket.py/http.py 게시·롤백 로직 중복, 타 모듈 private 속성 접근(`_managed_devices`, `_cleanup_timers`, `_get_slug_lock`) 정리는 리팩터링 범위라 후속 PR |
| HA-04, HA-08 | UI 설정·중복·안정적 식별 및 기능별 options/reauth/reconfigure, entity 의미·registry 영향 확인 | PASS | HA-08은 엔티티 없음 N/A. base_url http(s)·query/userinfo 거부 검증 + `invalid_url`(config/options flow, strings/en/ko), manifest `single_config_entry: true`, options builder_slug 선택기 번역. 연결 확인 단계는 추가하지 않음(Builder 미기동 상태에서도 설정 허용이 의도). 테스트: test_ha_rule_audit_fixes.py |
| HA-01, HA-04, HA-08, REL-01, REL-03 | domain·unique ID·entry schema·상태/통계 계약 변경 시 migration 테스트와 사용자 조치 안내 | N/A | domain·unique ID·entry schema·통계 계약을 변경하지 않음(AST 동일) → migration 불필요 |
| HA-05, HA-06 | setup 실패 구분, unload/reload·부분 실패의 task/listener/연결 정리, async·timeout·취소 처리 | PASS | 업로드 view 1회 등록 + 요청 시 현재 manager 조회(미로딩/미준비 503), 부분 setup 실패 시 `async_unload` 후 `hass.data` 정리, `entry.async_create_background_task` + unload 시 reconnect task await, CancelledError 재전파, ws_connect 15s timeout, monitor `_unloaded`·추적 task 취소, Auth/selection_required/403 장기 재시도(600s), websocket/http/monitor/migration 파일 검사·삭제를 executor로 이동. 남은 항목: `DeviceManager.list_all()`의 기기별 `is_file()`(후속) |
| HA-07 | 중복 polling·property I/O 방지, push 보존, unavailable/unknown·실패 후 복구 | PASS | 엔티티·polling 없음, push 유지(builder/connection.py:152, monitor.py:491), 재연결 backoff (감사 확인)
| HA-11, HA-12 | 번역·action/schema 일치, 로그/diagnostics/fixture 비식별화와 제공 시 redaction 테스트 | PASS | diagnostics allowlist·테스트 PASS(diagnostics.py:24-41). 로그의 시크릿 slug 토큰은 `redaction.py`(mask_slug + 로거 필터: 파일명/traceback 포함)로 마스킹, caplog 테스트(32hex·임의 토큰·OSError). builder_slug 라벨·"Auto-detect" 번역(selector) 추가 |

## 실제 HA 테스트·호환성·의존성

| 규칙 ID | 확인 항목 | 상태 | 근거 / 남은 작업 |
|---|---|---|---|
| TEST-08 | `tests/components/<domain>/`에 구현과 대응하는 테스트·domain fixture 배치, discovery·CI 경로 일치 | PASS | `tests/components/esphome_ota/`, CI 경로 일치 |
| TEST-02, TEST-03, DEP-07 | 실제 HA·호환 플러그인과 `hass`/`enable_custom_integrations` fixture 사용, HA core stub/복사본/`--no-deps`로 대체하지 않음 | PASS | 실제 HA 2026.10.2·플러그인 0.13.373, `enable_custom_integrations`(conftest.py). test_builder_discovery.py의 `sys.modules` 가짜 모듈을 실제 `esphome.dashboard.async_get_dashboard` 패치로 교체(ha-components에 esphome 추가) |
| TEST-09 | 실제 loader·config entry manager로 setup/플랫폼 로딩, HA 상태·registry·service/action으로 결과 검증 | PASS | config_entries.async_setup/async_setup_component를 쓰는 테스트 9개 파일, 167 passed |
| TEST-01, TEST-06, TEST-07 | 구현 기능별 성공·실패·중복·migration·unload·복구 회귀 검증, 외부 통신 경계만 mock, skip 사유 | PASS | 기존 테스트 삭제 없음, 외부 Builder 경계 mock |
| TEST-04, HACS-01 | 변경 전 지원 최소·current·각 Python/플러그인 분리, 선언한 정확한 최소 검증, 상향 시 비호환 근거·명시적 승인 확인 | EXCEPTION | STANDARDS.md 예외: 선언 최소 2024.1.0이 코드와 불일치. 최소 상향 안 함 |
| TEST-05, HA-10, DEP-02, DEP-05 | imagespec·blesession 등 최소/현재 라이브러리 별도 환경, 실제 HA 테스트·정확한 설치값·API 경계 검증 | N/A | 외부 Python 라이브러리 없음(`requirements: []`), Bluetooth 미사용 |
| DEP-01, DEP-06 | Python runtime은 manifest requirements, HA domain은 dependencies/after_dependencies, 테스트·린트 requirements는 별도 | PASS | requirements_test.txt / requirements_lint.txt 분리, manifest는 dependencies 사용 |
| DEP-07, CI-06 | 실제 사용하는 HA 구성요소의 requirements·필수 재귀 의존성·선택 로딩 경로 설치, resolver·`pip check` 통과 | PASS | `ha-components: frontend panel_custom websocket_api http esphome`; 로컬 `pip check` No broken requirements(리뷰 에이전트 확인). CI 설치 결과는 대기 |
| DEP-02, DEP-03, DEP-08 | 의존성 추가/변경의 버전·extras·marker·선언 위치·지원 플랫폼·라이선스 검토, 실제 HA 테스트와 문서 갱신 | N/A | 이번 변경에서 의존성 추가·변경 없음(requirements_test.txt의 pytest-timeout 별도 핀 제거 포함) |

독립 리뷰는 변경 전후 지원 최소와 current를 비교하고, 봇 PR이 과거 최소 requirements·constraints까지 갱신하거나 expected-ha-version·Python을 누락하지 않았는지 확인합니다. 최신 테스트 실패는 호환 수정 대상으로 처리합니다.

환경마다 아래 행을 복사합니다. 최소 HA와 최소 라이브러리 검증을 혼동하지 않고, marker가 활성인 환경에서 대상 패키지 설치값을 확인합니다. 실행하지 않은 조합은 `TODO` 또는 근거가 있는 `EXCEPTION`으로 남깁니다.

| 검증 축 / 상태 | 통합 커밋 | Python / HA / 플러그인 실제 버전 | 대상 패키지 | 명령·결과·pip check | skip·제외·미검증 |
|---|---|---|---|---|---|
| 현재 환경 / PASS(로컬) | 3ffb095 (+리뷰 수정 후 재실행 결과는 아래 리뷰 기록) | 3.14.5 / 2026.10.2 / 0.13.373 (ruff 0.17.1) | 해당 없음(외부 의존성 없음) | `ruff check .`·`ruff format --check .` 통과; `pytest tests/components/esphome_ota/ --timeout 120` 167 passed, 12 subtests; `pip check` No broken requirements | 원격 CI 미실행; 실물 Builder/기기 미검증 |
| 정확한 최소 HA / EXCEPTION | 3ffb095 | 3.12 / 2024.1.2(2024.1.0용 플러그인 없음) / 0.13.88 | — | conftest import 단계 `ImportError: StaticPathConfig` | 선언 최소와 코드 불일치 |
| 정확한 최소 라이브러리 / N/A | — | — | — | — | `requirements: []` |

## HACS·CI·의존성 업데이트

| 규칙 ID | 확인 항목 | 상태 | 근거 / 남은 작업 |
|---|---|---|---|
| HACS-01, HACS-02 | 루트 README/LICENSE/hacs.json, 검증한 최소 HA, 실제 배포 구조와 필요한 옵션 일치 | PASS | 루트 README/LICENSE/hacs.json, `custom_components/esphome_ota`, `content_in_root: false` (최소 HA 값은 예외) |
| HACS-03, HACS-05 | Default 여부는 목록 근거로 확인, [로컬 brand/icon.png 또는 원격 brands 근거](https://github.com/eigger/hass-repo-standards/blob/main/docs/hacs.md)와 HACS/Hassfest 실제 실행, ignore는 이유·해제 조건 기록 | PASS | brand/icon.png를 256×256으로 교체(기존 128px를 LANCZOS 업스케일, brand/README.md 기록; 원본 재export 권장). 원격 [Validate](https://github.com/eigger/hass-esphome-ota/actions/runs/39096290040) 성공(HACS·Hassfest) |
| HACS-06 (권장) | description·topics·issue 경로·brands 및 사용하는 HACS 필드 지원 확인 | PASS | `gh repo view`: description·topics·Issues 설정 확인 |
| CI-01, CI-02 | Validate/Python Tests 공통화, 확장 job 유지, PR·실제 기본 브랜치 push·dispatch 및 필요한 schedule | PASS | tests.yml/validate.yml: PR, main push, dispatch, validate schedule |
| CI-03, CI-05, CI-08 | 최소 권한·checkout 자격증명 비보존·timeout·concurrency, full SHA·갱신 관리, 비신뢰 입력·secrets 경계 | PASS | `permissions: contents: read`, concurrency, 공통 workflow가 checkout 자격증명 비보존·timeout 설정, SHA 고정, 비신뢰 입력 없음 |
| CI-04, CI-07, CI-12 | 실패를 숨기지 않는 실제 `ha` 필수 테스트, 버전별 환경·cache·Ruff 설정과 required checks 이름 확인 | PASS | 원격 [Tests](https://github.com/eigger/hass-esphome-ota/actions/runs/39096289938)(current Python 3.14, 실제 `ha` 테스트)·[Validate](https://github.com/eigger/hass-esphome-ota/actions/runs/39096290040) 성공(PR #29 head `6463244`). main은 branch protection·ruleset 없음(404/0건) — required checks 미설정, 설정 변경은 하지 않음 |
| DEP-03, DEP-04, CI-09 | updater의 선택 package·연산자/extras/marker 보존, 안정 버전·major 정책, 실제 기본 브랜치·단일 bot branch·PR만 제안 | N/A | 외부 의존성 없어 update_dependencies.yml 미도입; Dependabot(actions, pip HA 묶음)만 사용 |
| CI-09, CI-10, DEP-08 | 변경 tree의 새 하한·실제 HA 검증 후 PR 동기화, 실패 시 중단·변경 없음 시 기존 PR 정리, 후속 required checks 충족 방식 확인 | N/A | updater 미도입 |

## README·Bluetooth·유지보수

| 규칙 ID | 확인 항목 | 상태 | 근거 / 남은 작업 |
|---|---|---|---|
| DOC-01, DOC-02, DOC-06 | 영어 README.md·한국어 README.ko.md·상호 링크·기존 내용 보존, 간결한 제목/소개/핵심지원/최소요구/빠른설치·설정/짧은예제/중요제한/문서목록, 상세옵션·긴YAML·참조·개발/실HA테스트·의존성/검증범위를 docs·examples 등으로 보존·분리하고 유효한 링크 제공, 실제 활성 Issues·Discussions 또는 대체 지원 경로·실제 LICENSE 링크 | PASS | README.md/README.ko.md 상호 링크·간결화, 이전 내용은 docs/features*.md 보존, docs/development.md(개발·의존성 추가·환경), Issues 안내(Discussions 비활성), LICENSE 링크 |
| DOC-03, DOC-04, DOC-05 | 제목 아래 관리 블록, flat-square·순서·실제 조건별 배지, CI 실제 기본 브랜치, 필수 동적 Usage·Analytics 참여 설치 의미·미집계/조회 실패와 0 설치 구분·이전 안내 보존 | PASS | `sync_badges.py --check` OK, 정적 Tests 배지 제거, Usage 배지 포함 |
| HA-09, HA-10 | BLE 사용 시 HA Bluetooth API·라이브러리 공개 경계, 지원한 proxy 경로·재연결·취소·서비스 변경 검증 | N/A | BLE 미사용 |
| DOC-07 | blesession/proxy 통합 README의 핵심조건·상세문서 링크, 공통 Bluetooth 설정·추천기기·active 스캔/GATT 차이, 통합별 troubleshooting 또는 공통 링크+모델고유조건·실제진단·민감정보 제거 제보 안내 | N/A | blesession/Bluetooth proxy 미사용 |
| DOC-07, HA-12 | 기기별 깨우기·인증·타 앱 연결·전송 제약, 실제 검증 경로와 미검증 범위, 공개 문제 로그 비식별화 | N/A | BLE 기기 미사용(HA-12 로그 비식별화는 위 HA-11 행에서 TODO) |
| HACS-04, REL-01, REL-02, REL-03, CI-11 | 통합 릴리스 시 같은 검증 commit/tag·manifest 버전·산출물·권한, 사용자 영향·지원 변경·제한 안내 | N/A | 이번 적용으로 릴리스하지 않음 |
| REL-04 | 이전/중단 시 README 상단 경로·유지보수 상태·재등록 여부, 자동 이전으로 오인하지 않는 안내 | N/A | 이전·중단 상태 아님 |
| REL-05 (권장) | 의존성/HA API 변경과 기능 변경 분리, 표준 변경은 명시적 채택 PR로 반영 | PASS | 표준 채택은 PR #29로 명시, 포맷 변경은 AST 동일, HA 동작 결함 수정은 별도 PR #30으로 분리 |

## 예외와 남은 작업

예외 원본은 [STANDARDS.md](STANDARDS.md#예외)입니다.

| 규칙 ID | 예외 위치 / 이유 | 담당자 | 재검토 조건 |
|---|---|---|---|
| TEST-04, HACS-01 | STANDARDS.md 예외: 선언 최소 2024.1.0 미동작 | @eigger | 최소 상향 승인 또는 호환 코드 도입 시 |
| GOV-05 | STANDARDS.md 예외: 구현을 서브 에이전트에 위임하지 않음 | @eigger | 다음 재검토 |

| 규칙 ID / TODO | 남은 작업 | 완료 근거 |
|---|---|---|
| TEST-04 | 지원 최소 결정(상향 또는 호환 코드) 후 정확한 최소 job 추가 | 사용자 승인 + CI |
| HA-03 (권장) | websocket/http 게시·롤백 로직 중복 및 모듈 간 private 속성 접근 정리, `DeviceManager.list_all()`의 기기별 `is_file()`(이벤트 루프) 제거 | 후속 PR·테스트 |

CI 성공만으로 실물 기기 검증을 주장하지 않습니다. 실물 검증은 수행하지 않았습니다.

## 리뷰 기록

Opus 서브 에이전트 독립 리뷰(3ffb095): CI/배선·포맷 전용 변경(AST 동일 38개 파일)·삭제 스크립트 미참조·지원 최소 예외 처리는 적정. 필수 지적(상태 오용·템플릿 행 누락)과 Low/Nit 16건을 이 커밋에서 모두 반영했습니다. 반영 후 재검증 결과는 최종 커밋의 독립 재검토 시 추가합니다.


## 2026-10-23 HACS ZIP and Downloads (scoped)

- Target base: `655107c7af12c50058ebba7a7677aead84cc957e`; reviewed release central: `fd4162c0b93fbe8e109f99c787773ae09ba157e1`.
- Scope: HACS-04/CI-11 release ZIP and DOC-03/05 Downloads replacing Analytics Usage. No release is created during this update.
- Local scoped validation: PASS — canonical badge check, no Analytics Usage, release metadata/caller contract, actionlint 1.7.12, native git diff --check, unchanged tracked integration/manifest/dependencies/tests.
- Actual archive build: PASS at `48ac7f38e0a1e0008d77666e365e5ef424cf5e04`; `esphome_ota.zip`, 39 files, SHA256 `3d19cc7adce8fd2f45bc8d5a3603f2526bb9a9604cfbbd3a62bbdddded7fbd4b`. All archive members matched checkout bytes; manifest.json and __init__.py are at ZIP root. Final documentation-only follow-up preserves this integration tree. Windows Python 3.14.6; validation WSL Python 3.14.4/PyYAML 6.0.3/packaging 26.0.
- Full central integration checker: FAIL (pre-existing or unadopted contracts outside this scoped update; not treated as PASS). Findings:

```text
DOC-01 README.md: Exactly one ordered header marker pair required
DOC-01 README.ko.md: Exactly one ordered header marker pair required
HA-02 custom_components/esphome_ota/manifest.json: categories requires 1–3 actual product categories (HA-02 project policy)
HA-13 custom_components/__init__.py: Required contract file is missing
GOV-02 .github/workflows/tests.yml: standards-ref must equal the reviewed reusable workflow SHA
TEST-08 tests/__init__.py: must exist and be empty
TEST-08 tests/components/__init__.py: must exist and be empty
TEST-08 tests/components/esphome_ota/__init__.py: must exist and be empty
TEST-03 tests/conftest.py: must match the central template exactly
TEST-08 tests/components/esphome_ota/conftest.py: Exactly one ordered domain-fixtures marker pair required
CI-01 .github/workflows/validate.yml: central standards composite action pinned to full SHA required
```

- Existing CI workflows are preserved, except hass-kocom-smarthome where matching reviewed central references are synchronized. Existing support minimum and prior exceptions remain.
- Independent review and remote CI: tracked in this branch's pull request; merge requires resolved actionable findings and successful applicable checks. No real release upload, device or new real HA runtime validation is claimed by these local packaging checks.
