# 적용한 공통 규칙

- 표준: https://github.com/eigger/hass-repo-standards/tree/v1.0.0
- 참조 커밋 SHA: 44349ee5621eea5d80e5c427f7a2435d2c2491bb
- Standards release: v1.0.0
- Resolved standards SHA: 44349ee5621eea5d80e5c427f7a2435d2c2491bb
- 채택일: 2026-10-18 (채택 PR 병합 시 확정)
- profile: integration / ha
- 기본 브랜치: main; domain: esphome_ota
- 적용 점검표: [ADOPTION_CHECKLIST.md](ADOPTION_CHECKLIST.md)
- 중앙 현황표: https://github.com/eigger/hass-repo-standards/blob/main/docs/adoption-status.md (이번 작업에서는 중앙 리포를 수정하지 않았으며 반영할 내용은 체크리스트 '남은 작업'에 기록)
- 중앙 현황 갱신일: 미등록 (중앙 리포 미수정)
- 조율: 메인 에이전트; 독립 리뷰·검증: Opus 서브 에이전트
- 테스트 경로: `tests/components/esphome_ota/`
- 변경 전 지원 최소 HA / 선언 근거: `hacs.json` `homeassistant: 2024.1.0` (README에는 별도 선언 없음)
- 적용 후 지원 최소 HA: 변경 없음 (2024.1.0 유지). 상향은 별도 명시적 사용자 승인 필요
- current HA 테스트 환경: Python 3.14 / HA 2026.10.2 / pytest-homeassistant-custom-component 0.13.373 / pytest-timeout 2.4.0 (`requirements_test.txt`)
- 최소 HA 검증 환경: 구성하지 못함 — 아래 예외 참조
- 최소 package 검증: 해당 없음 (`manifest.requirements=[]`, 외부 Python 의존성 없음 → dependency-update 워크플로 미도입)
- 릴리스: GitHub Release 사용 중(`release: true`, 최신 1.1.0). 이번 적용으로 버전·태그·Release를 만들지 않음

## 예외

| 규칙 ID | 이유 | 담당자 | 재검토 조건 |
|---|---|---|---|
| TEST-04, HACS-01 | `hacs.json`이 선언한 최소 HA 2024.1.0에서 코드가 동작하지 않습니다. `panel.py`가 `homeassistant.components.http.StaticPathConfig`를 import하는데 HA 2024.1.2(해당 시점 플러그인 0.13.88, 정확한 2024.1.0용 플러그인 릴리스는 PyPI에 없음)에서 ImportError가 발생합니다. 따라서 별도 minimum-ha job을 만들지 않았고 선언 최소를 검증된 값으로 취급하지 않습니다. 최신화 요청만으로 최소를 상향하지 않습니다. | @eigger | 사용자가 지원 최소 상향(또는 하위 호환 코드 도입)을 승인하면 `hacs.json`·README·CI를 함께 변경하고 정확한 최소 환경 job을 추가 |
| GOV-05 | 사용자 지시에 따라 구현은 메인 에이전트가 직접 수행하고 독립 리뷰만 별도 Opus 서브 에이전트에 위임 | @eigger | 다음 재검토 또는 후속 채택 작업 |

## HACS brand

`custom_components/esphome_ota/brand/icon.png`가 이미 존재합니다. 이번 작업에서 이미지 내용·권리를 검증하지 않았고 기존 128×128을 256×256으로 업스케일했습니다(brand/README.md). 원본 아트워크 재export가 더 선명합니다., HACS brands 검사는 원격 CI 결과로 확인합니다.

## 규칙 범위 메모

- GOV-05: 구현은 메인 에이전트가 수행하고 독립 리뷰만 별도 Opus 서브 에이전트에 위임했습니다(사용자 지시). 구현 자체를 서브 에이전트에 위임하지 않은 점은 표준 AGENTS.md와 다릅니다.
- `ruff format`을 저장소 전체에 적용했습니다(포맷 전용 변경, 38개 파일). Ruff 규칙 선택은 기존 `ruff.toml`(E/F, E501 제외)을 유지합니다.
- 기존 CI의 `scripts/ha_component_requirements.py`는 공통 python-environment 액션의 `ha-components` 입력으로 대체되어 삭제했습니다.
- 실물 ESPHome Builder/기기 검증은 수행하지 않았습니다.
## 2026-10-23 ZIP release and Downloads update

Base commit: `655107c7af12c50058ebba7a7677aead84cc957e`. HACS remains Custom. `hacs.json` now selects `esphome_ota.zip`; publishing the next release builds and attaches that integration ZIP through the pinned central action. Analytics Usage is replaced by Downloads. The archive contains tracked integration files at its root. No existing release/tag/assets are modified.

Implementation and review: root; generated release caller reuses the independently reviewed central ZIP contract. Support minimum, manifest, code, dependencies, README body and prior adoption exceptions are preserved. Verification evidence is recorded in ADOPTION_CHECKLIST.md; this scoped update does not establish full standards compliance.

## 2026-10-25 중앙 검사기 갱신

- 검토한 중앙 main: `1863343638014adb8a4001afc8fddc1a27dc500f` (git ls-remote 확인). 이전 기본 기준 `ba9f3fad8b635c163fb44a4e91b1833cc4ab47b4`의 채택 이력은 위 기록을 보존합니다.
- 모든 중앙 workflow/action pin과 reusable workflow의 standards-ref를 같은 검토 SHA로 맞춥니다. HACS-04는 actions/*의 full SHA 고정을 유지하면서 SHA 값 차이를 허용합니다.
- Validate에 중앙 템플릿의 무조건 실행 standards job을 추가합니다. 기존 HACS/Hassfest와 HA test job 이름·입력은 보존하며, 기본 브랜치를 사용하는 중앙 실행 조건을 적용합니다.
- 통합 코드·런타임 의존성·지원 최소·배포 버전은 이번 변경 대상이 아닙니다. 기존 채택 범위를 전체 완료로 바꾸지 않으며 실제 검증 결과와 남은 항목은 ADOPTION_CHECKLIST.md의 같은 날짜 기록을 참조합니다.

### 2026-10-25 CI 미충족 보완

PR #37의 실제 실패 항목인 README 관리 영역·categories 검토 근거·공통 test scaffold를 보완했습니다. 기존 README 본문, 실제 HA lifecycle/Builder 테스트와 지원 정책을 보존합니다. 로컬 검증과 원격 확인 범위는 ADOPTION_CHECKLIST.md의 CI 실패 수정 기록을 참조합니다.


### 2026-10-25 Standards 파일·표시 이름 분리

- 기존 Validate의 중앙 검사 job을 `standards.yml`로 옮기고 workflow/job 표시 이름을 `Standards`로 줄였습니다. Validate의 HACS/Hassfest, 검사 항목·통과 기준·실행 단계·조건·권한은 유지합니다.
- 위치 인식과 중앙 명명 안내를 맞춘 검토 소스: `ca740d88b32fa5dcbc94c41fce2908450c76ed50` ([중앙 PR #24](https://github.com/eigger/hass-repo-standards/pull/24), 현재 이 PR의 의존 변경). 이전 기준 `1863343638014adb8a4001afc8fddc1a27dc500f`의 검증 이력은 앞 기록으로 보존합니다. 모든 중앙 pin·standards-ref는 같은 새 검토 소스로 맞춥니다.
### 2026-10-25 immutable central release reference migration

- User-requested partial migration: current central caller references use immutable `v1.0.0` resolved to `44349ee5621eea5d80e5c427f7a2435d2c2491bb`. Prior scoped ZIP SHA evidence is retained here: `ca740d88b32fa5dcbc94c41fce2908450c76ed50`. Runtime code, dependencies, support minimum, manifest and integration version are unchanged.
