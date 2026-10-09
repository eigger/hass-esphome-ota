# ESPHome OTA 검증 및 실환경 진단 가이드

작성일: 2026-10-10  
상태: 자동화 테스트 88개(기존 82개 + 4차 리뷰 결함 검증 6개) 전체 통과, 실환경 런타임 검증 대기 (미검증 명시)

본 문서는 `WORK_ORDER.md` 및 `docs/architecture.ko.md`에 정의된 검증 기준과 수용 기준에 따라, 자동화 테스트로 검증된 항목과 실제 Home Assistant OS + ESPHome Device Builder 애드온 환경에서 수행해야 할 실환경 진단 절차를 정리합니다.

---

## 1. 검증 현황 요약

| 구분 | 검증 방식 | 결과 | 비고 |
|---|---|---|---|
| Builder 루프백 자동 탐색 | 모의 Discovery Adapter | **통과 (100%)** | Dashboard 및 Supervisor 서비스/애드온 탐색 검증 |
| WebSocket 핸드셰이크 & 다중화 | MockBuilderServer | **통과 (100%)** | 인증 요구(`requires_auth=true`) 차단 및 403 예외 처리 |
| 명시적 컴파일 완료 검증 | MockBuilderServer | **통과 (100%)** | `completed`만 성공 처리 (`unknown`/`failed` 거부) |
| 단일 사용 토큰 다운로드 | MockBuilderServer HTTP | **통과 (100%)** | 토큰 만료/불일치 시 401 거부 및 예외 처리 |
| 바이너리 분석 및 검증 | 정밀 바이너리 신서사이저 | **통과 (100%)** | chip_id, esp_app_desc_t, 부트 로그 버전 추출, 칩 불일치 거부 |
| YAML CAS 및 버전 소유권 | 유닛 테스트 | **통과 (100%)** | `esphome.project.version` vs `esp32.framework.version` 구분 및 CAS 충돌 검증 |
| 원자적 게시 & 숨김 | 파일시스템 테스트 | **통과 (100%)** | Manifest-last 순서, 캐시버스터(`?v=`), 프라이빗 보존 |
| 기기 상태 전이 & 잠금 | asyncio 동시성 테스트 | **통과 (100%)** | `needs_initial_install` 구분, 기기별 동시 빌드 직렬화 |
| Update 엔티티 감시 & 만료 | HA State 머신 테스트 | **통과 (100%)** | `installed_version` 일치 감시, unavailable 제외, 만료 타이머 |
| 레거시 애드온 데이터 이전 | 스토리지 마이그레이션 | **통과 (100%)** | 토큰·슬러그 보존, 바이너리 이전, 멱등성 검증 |
| 웹소켓 API & 수동 업로드 | HA WS/HTTP 클라이언트 | **통과 (100%)** | 관리자 권한 확인, 스냅샷+델타 구독, 16MB 업로드 제한 |
| **8대 P1 1차 결함 회귀 테스트** | [test_p1_bugfixes.py](file:///Users/eigger/Documents/GitHub/hass-esphome-ota/tests/components/esphome_ota/test_p1_bugfixes.py) | **통과 (100%)** | 파일명 확장자, 문자열 작업 ID, YAML 들여쓰기, 스냅샷 이벤트, 자동 재연결, 검증 스트림, 버전 반영, CAS expected |
| **2ba3cab 리뷰 결함 8건 회귀 테스트** | [test_p1_p2_review_fixes.py](file:///Users/eigger/Documents/GitHub/hass-esphome-ota/tests/components/esphome_ota/test_p1_p2_review_fixes.py) | **통과 (100%)** | Builder 미선택 ingress 포트, 다이얼로그 DOM 보존, 치환문자열 버전, XSS 방지, 소켓 중단 복구, 락 내부 버전 할당, Update 엔티티 동적 감시, 자동 정리 타이머 복원 |
| **00d085d 2차 리뷰 결함 7건 회귀 테스트** | [test_00d085d_review_fixes.py](file:///Users/eigger/Documents/GitHub/hass-esphome-ota/tests/components/esphome_ota/test_00d085d_review_fixes.py) | **통과 (100%)** | 취소 빌드 게시 차단, dev Builder 하이재킹 방지, !include 관리버전 보존/검토, Update 엔티티 정밀 매칭, 컴파일 유실 복구, 기기 카드 갱신, 수동 업로드 정리 스케줄링 |
| **ffe378c 3차 리뷰 결함 4건 회귀 테스트** | [test_ffe378c_review_fixes.py](file:///Users/eigger/Documents/GitHub/hass-esphome-ota/tests/components/esphome_ota/test_ffe378c_review_fixes.py) | **통과 (100%)** | `firmware/get_jobs` 공식 API 규격, 과거 이력/업로드 오연결 방지, 원격 패키지 소유권 보호, ESPHome 플랫폼 엔티티 검증 |
| **e2369ce 4차 리뷰 결함 4건 회귀 테스트** | [test_e2369ce_review_fixes.py](file:///Users/eigger/Documents/GitHub/hass-esphome-ota/tests/components/esphome_ota/test_e2369ce_review_fixes.py) | **통과 (100%)** | 직전 완료 컴파일 오연결 차단(P1), recovery_required 화면 해제/취소/재확인(P2), ESP8266 firmware.bin 다운로드(P2), 4칸 들여쓰기 YAML 패치 교정(P2) |
| **실제 HA OS 런타임 실증** | 실제 하드웨어/애드온 | **미검증** | 개발 환경에 실행 중인 HA OS 인스턴스 부재 |

> [!IMPORTANT]
> **실환경 연결 실증 미검증 안내**:
> 작업 지시서의 원칙에 따라, 본 개발 환경(macOS 로컬)에는 활성 Home Assistant 프로세스 및 실제 ESPHome Builder 애드온이 구동되지 않으므로, **모의 환경 성공을 실환경 성공으로 표현하지 않으며 '실환경 미검증' 상태로 명시**합니다. 실제 HA OS에 설치 후 아래의 최소 진단 절차를 수행해야 합니다.

---

## 2. 실사용 전 8대 P1 결함 조치 내역

1. **[P1-1] Builder 파일명 확장자 분리**:
   - `device_id`("livingroom")와 Builder 전달용 원본 `configuration`("livingroom.yaml")을 엄격히 분리하여 Builder API가 파일 미발견 오류를 내지 않도록 조치.
2. **[P1-2] 빌드 작업 ID 문자열 유지**:
   - Builder가 반환하는 12자리 hex 작업 ID(`uuid4().hex[:12]`)를 `int()` 변환하지 않고 모델/API/스트림 전반에서 문자열로 유지.
3. **[P1-3] 생성 YAML 들여쓰기 교정**:
   - `packages.esphome_ota` 생성 시 `esphome.project` 블록을 4칸 들여쓰기로 수정하여 별도 최상위 패키지로 오해석되는 YAML 구조 결함 제거.
4. **[P1-4] 패널 첫 진입 시 초기 스냅샷 이벤트 발행**:
   - HA JS 웹소켓의 `subscribeMessage()`가 `send_result()` 페이로드를 콜백에 전달하지 않는 동작에 대응하여, 구독 즉시 `snapshot` 이벤트를 송출하고 프런트엔드 연결 시 상태 조회 보완.
5. **[P1-5] 자동 재연결 루프 구현**:
   - 초기 연결 실패 시 지연 재시도 루프 가동, WS 끊김 감지 시 `on_disconnect` 콜백을 통해 지터 백오프로 자동 재탐색 및 재연결 수행.
6. **[P1-6] YAML 검증 스트리밍 완료 및 종료 코드 검사**:
   - `devices/validate`가 첫 출력 프레임에서 단일 응답으로 끝나지 않고 전체 스트림을 소비한 뒤 최종 `exit_code == 0` 및 `success == True`를 확인하도록 수정.
7. **[P1-7] 자동 증가 버전 컴파일 전 YAML 반영 및 검증**:
   - 빌드 시작 전 관리 대상 기기의 버전을 `apply_ota_patch`로 YAML에 기록(CAS)한 후 컴파일하며, 다운로드된 바이너리의 버전이 일치하는지 검증.
8. **[P1-8] UI YAML CAS expected 원본 전달**:
   - `esphome_ota/prepare_ota` 응답에 `expected`/`original` 원본 YAML을 포함하고 `device-dialog.js`가 `apply_ota` 호출 시 필수 전달하도록 연동.

---

## 3. 2ba3cab 리뷰 결함 8건 조치 내역 (P1 5건, P2 3건)

1. **[P1-1] Builder 미선택 상태 보존 및 동적 ingress 포트 우선 해석**:
   - Builder 없이 설치 시 slug를 임의로 `"esphome"`으로 저장하지 않고 `slug=None` 미선택 상태를 유지.
   - 사후에 실제 애드온(`5c53de3b_esphome`)이 발견되면 fallback 힌트(6052) 대신 발견된 ingress 포트를 최우선 채택하여 자동 연결.
2. **[P1-2] 빌드 이벤트 수신 시 열린 진행창 DOM 보존**:
   - `manager.js`에서 `handleEvent()`가 매번 shadowRoot 전체를 덮어쓰지 않도록 DOM 셸을 최초 1회만 초기화(`_initDom()`).
   - `job_updated`, `devices_updated` 시 진행창 및 설정창 요소를 그대로 유지하고 목록 및 로그만 갱신하여 모달이 닫히는 현상 제거.
3. **[P1-3] 사용자 프로젝트 버전 치환 및 소유권 보호**:
   - YAML의 `substitutions:` 정의를 읽어 `${version}` 등 로컬 치환 변수를 선해석.
   - 미해결 치환자(`$`, `{}` 포함) 또는 외부 include 등으로 소유권이 불명확하거나 사용자 관리 버전인 경우, 자동 YAML 덮어쓰기를 건너뛰고 컴파일된 바이너리의 app_desc 버전을 권위(authoritative)로 인정.
4. **[P1-4] 프런트엔드 XSS 방지 (YAML diff, 로그, 기기 정보)**:
   - `device-dialog.js`, `job-dialog.js`, `manager.js`에서 YAML diff 라인, 기기명, 모달 타이틀에 `escapeHtml()` 적용.
   - 빌드 로그 뷰어는 innerHTML 대신 `textContent = logs`로 변경하여 악의적 스크립트 실행 벡터 완전 차단.
5. **[P1-5] 소켓 단절 시 대기 큐 즉시 해제 및 작업 재추적/복구**:
   - `connection.py`에서 WebSocket 종료 감지 시 대기 중인 모든 요청 큐를 `BuilderConnectionError`로 깨워 타임아웃 지연 제거.
   - HA 재시작 또는 재연결 시 `async_resume_jobs()`를 실행하여 저장된 `builder_job_id`를 기반으로 원격 작업 상태를 조회하고 파이프라인(다운로드/검증/게시)을 자동 복구.
6. **[P2-6] 기기 Lock 내부 동적 버전 할당 및 중복 동시 빌드 차단**:
   - 동일 기기에 대한 중복 빌드 요청을 즉시 거부(`BuilderConflictError`).
   - 버전 번호 증가를 요청 접수 시점이 아닌 기기 Lock(`async with lock:`) 획득 내부에서 최신 게시 버전을 기준으로 계산하여 버전 충돌 원천 차단.
7. **[P2-7] Update 엔티티 동적 감시 갱신**:
   - `er.EVENT_ENTITY_REGISTRY_UPDATED` 이벤트를 구독하고 최초 설치/기기 등록 시 `async_refresh_monitoring()`을 호출하여, 최초 배포 후 새로 등록된 Update 엔티티도 누락 없이 감시 목록에 편입.
8. **[P2-8] 자동 정리(Auto-cleanup) 스케줄링 및 재시작 후 복원**:
   - 펌웨어 게시(`async_publish`) 및 재게시(`republish`) 시점에 `monitor.schedule_cleanup()`을 호출하여 만료 타이머 등록.
   - HA 재시작 시 `monitor.async_setup()`에서 활성 공개 아티팩트의 남은 만료 시간을 계산하여 타이머를 자동 복원.

---

## 4. 00d085d 2차 리뷰 결함 7건 조치 내역 (P1 3건, P2 4건)

1. **[P1-1] 복구 중 취소(cancelled)된 빌드 게시 차단**:
   - `_resume_pipeline()`에서 Builder 상태 조회 시 `status == "cancelled"`인 경우 다운로드/게시로 넘어가지 않고 즉시 `STAGE_CANCELLED`로 종결.
   - `completed` 상태만 정상 다운로드·게시 경로를 허용하고, 그 외 비정상 상태는 예외 발생 처리.
2. **[P1-2] 저장된 운영 Builder 대기 유지 (개발 Builder 자동 전환 차단)**:
   - `resolver.py`에서 `saved_selection.slug`가 지정된 경우, 오직 해당 슬러그(또는 표준 코어 별칭인 `esphome`과 `5c53de3b_esphome`)만 매칭.
   - 운영 Builder 미발견 시 `esphome-dev` 등 다른 후보로 임의 전환하지 않고 `STATUS_WAITING` 대기 상태를 유지.
3. **[P1-3] 단순 컴포넌트 !include 관리 버전 유지 및 모호한 프로젝트 include 검토 요구**:
   - `sensor: !include sensors.yaml` 등 일반 컴포넌트 include는 프로젝트 소유권을 침해하지 않으므로 정상적으로 `packages.esphome_ota`를 주입하고 관리 버전 증가.
   - `packages:` 또는 `esphome:` 블록에 외부 include가 있거나 미해결 `${...}` 치환자가 있는 경우에만 소유권 모호로 판단하고, 임의 빌드 대신 수동 검토를 요구(`BuilderError`). Builder의 `current_version`을 프로젝트 버전으로 오인하는 결함 차단.
4. **[P2-4] Update 엔티티 정밀 매칭 (부분문자열 오매칭 방지)**:
   - `dev_name in entity.entity_id` 단순 부분문자열 검색 대신, HA Device Registry 식별자 매칭 및 `update.{name}_firmware` 등 정밀 토큰/접두사 패턴으로 매핑.
   - `room` 기기가 `update.bedroom_firmware`를 가로채지 않도록 격리.
5. **[P2-5] 컴파일 제출 응답 유실 시 `recovery_required` 상태 분리 및 재추적**:
   - `client.start_compile()` 도중 소켓이 끊긴 경우 즉시 `failed`로 버리지 않고 `STAGE_RECOVERY_REQUIRED`로 기록.
   - Builder 재연결 시 `client.list_jobs()`로 원격 접수 여부를 대조하여, 실제 수락된 작업은 `builder_job_id`를 복구해 이어서 빌드 완료.
6. **[P2-6] 펌웨어 게시 및 설치 검증 시 기기 카드 데이터 즉시 동기화**:
   - `jobs.py` 게시 완료 및 `monitor.py` 설치 검증 시 `devices_updated` 이벤트를 송출.
   - `manager.js`에서 `job_updated` 및 `installation_verified` 수신 시 기기 카드의 게시/설치 버전(1.0.1)을 즉각 갱신하도록 처리.
7. **[P2-7] 수동 HTTP 업로드 시 만료 타이머 재스케줄링**:
   - `FirmwareUploadView.post()` 경로에서도 `monitor.schedule_cleanup()`을 호출하여 이전 타이머를 취소하고 신규 만료 타이머 등록.
   - 업로드 즉시 `devices_updated` 이벤트를 발행하여 UI 카드 동기화.

---

## 5. ffe378c 3차 리뷰 결함 4건 조치 내역 (P1 2건, P2 2건)

1. **[P1-1] 공식 작업 목록 조회 API(`firmware/get_jobs`) 규격 준수 및 복구 오류 처리 정상화**:
   - 코드가 비공식 명령(`firmware/list_jobs`) 대신 공식 API 명세인 `firmware/get_jobs`를 호출하도록 수정 (`client.py:155`).
   - API 호출 실패나 네트워크 오류 발생 시 빈 목록(`[]`)으로 삼키지 않고 예외를 전파하며, 복구 대기 중인 작업을 섣불리 `STAGE_FAILED`("접수되지 않음")로 종결하지 않고 `STAGE_RECOVERY_REQUIRED` 상태를 안전하게 보존.
   - 테스트 모의 서버(`MockBuilderServer`)도 공식 명령 `firmware/get_jobs`만 지원하도록 엄격화하여 API 규격 불일치 재발 방지.
2. **[P1-2] 복구 시 과거 이력/타 종류 작업 오연결 방지 및 고유 일치 검증**:
   - Builder 작업 조회 결과에서 파일명뿐 아니라 **작업 종류**(`job_type == "compile"`)와 **제출 시각**(`created_at >= job.created_at - 60s`)을 엄격히 대조 (`jobs.py:388`).
   - 과거 세션의 완료된 `upload` 작업이나 이전의 완료 컴파일 작업이 현재 컴파일의 `builder_job_id`로 오연결되는 현상 원천 차단.
   - 일치하는 작업 후보가 유일(단 1개)하지 않거나 모호한 경우(0개 또는 2개 이상) 즉각 실패로 떨구지 않고 `STAGE_RECOVERY_REQUIRED`를 유지하여 안정적 재시도 보장.
3. **[P2-3] 원격 패키지 참조 감지 및 최상위 프로젝트 버전 우선순위 반영**:
   - `github://...` 단축 표기나 `url:`/`files:` 딕셔너리 형태의 원격 패키지 참조를 정확히 감지하여, 최상위 명시 설정이 없는 제3자 프로젝트의 소유권을 함부로 침해하거나 관리 버전을 주입하지 않도록 보호 (`config_patch.py:86`).
   - 반대로 최상위 YAML에 명시적 `esphome.project.version`이 정의된 경우 최상위 우선순위를 적용하여, 레거시 패키지의 `!include`가 존재하더라도 빌드를 부당하게 차단하지 않고 정상 진행.
4. **[P2-4] ESPHome 외 타 플랫폼 엔티티/기기 연결 오인 차단**:
   - Update 엔티티 감시 매칭 시 `entity.domain == "update"`뿐 아니라 반드시 `entity.platform == "esphome"`인지 엄격히 검증 (`monitor.py:89`).
   - MQTT 등 타 통합구성요소의 기기/엔티티(`update.room_firmware`)가 동명이라는 이유로 ESPHome 기기의 설치 감시 대상으로 오연결되는 결함 해결.
   - HA Device Registry의 기기 식별자가 `domain == "esphome"`에 속하는지 실제 연결 관계를 확인.

---

## 6. e2369ce 4차 리뷰 결함 4건 조치 내역 (P1 1건, P2 3건)

1. **[P1-1] 제출 직전 완료된 과거 컴파일 오연결 차단 및 고유 확정 실패 시 recovery_required 유지**:
   - 컴파일 요청 직전 Builder의 기존 작업 목록을 사전 스냅샷(`prior_job_ids`)하여, 새 요청 이전에 이미 존재했던 모든 작업 ID를 복구 대상에서 명시적으로 제외 (`jobs.py:274, 442`).
   - 기존 60초 여유 판정(`bj_ts < job_ts - 60`)을 제거하고, 요청 제출 시각보다 과거에 시작된 작업(`bj_ts < ref_ts`)은 모두 거부하도록 엄격화.
   - 타임스탬프가 누락되었거나 고유한 1:1 연결을 확정할 수 없는 경우 임의 연결을 중단하고 `STAGE_RECOVERY_REQUIRED` 상태를 안전하게 유지.
2. **[P2-2] UI에서 recovery_required 작업 해제/재확인/취소 제공 및 빌드 차단 해제**:
   - `job-dialog.js`에서 `recovery_required` 상태일 때 숨겨져 있던 취소(Cancel) 버튼을 노출하고, Builder 연결 및 작업을 즉시 재조회할 수 있는 재확인(Recheck) 버튼(`btn-recheck`)을 추가.
   - 사용자가 취소 클릭 시 `async_cancel_job`을 통해 작업을 `STAGE_CANCELLED`로 종결하여 기기 빌드 락/진행 차단을 해제하고, 기기 카드에서 즉시 새 빌드를 재시도할 수 있도록 개선 (`manager.js`).
3. **[P2-3] ESP8266 빌드 다운로드 시 firmware.bin 자동 선택**:
   - ESPHome의 ESP8266 컴포넌트 공식 규격에 따라, ESP8266은 `firmware.ota.bin` 대신 `firmware.bin`을 OTA 이미지로 생성함을 반영.
   - `resolve_ota_binary_file`을 도입하여 Builder의 `firmware/get_binaries` 목록과 `platform_hint`를 대조: explicit type="ota"를 최우선 확인하고, ESP8266인 경우 `firmware.bin`을 자동 선택하여 다운로드 실패 해결 (`client.py:220`).
4. **[P2-4] 4칸 들여쓰기 기존 OTA package의 인플레이스 교체 및 중첩 방지**:
   - `config_patch.py`에서 기존 2칸 하드코딩 매칭(`^  esphome_ota:`)을 제거하고, YAML `packages:` 하위의 실제 들여쓰기 깊이(2칸 또는 4칸)를 동적으로 감지.
   - 주입할 패키지 스니펫을 감지된 들여쓰기에 맞게 정밀 재들여쓰기(`reindent_yaml_snippet`)하여, 유효한 4칸 들여쓰기 YAML에서도 기존 `esphome_ota` 블록이 새 블록 내부에 중첩되지 않고 정확히 제자리에서 교체되도록 수정.

---

## 7. 실환경 최소 연결 진단 절차

실제 Home Assistant OS 환경에 설치 후 Builder 자동 연결을 검증하는 단계입니다.

### 사전 조건 (필수 확인)
1. ESPHome Device Builder 애드온이 설치 및 실행 중이어야 합니다 (`state == "started"`).
2. 애드온 설정에서 **공개 포트 매핑 없음**, **`leave_front_door_open` 비활성**, **`dashboard_token` 없음** 상태를 유지합니다.
3. Home Assistant Core 프로세스에서 loopback(`127.0.0.1:<ingress_port>`)으로 Builder trusted listener에 접속 가능한 기본 HA OS 환경이어야 합니다.

### 진단 스크립트 실행 (HA 런타임 내부)

HA Core 컨테이너 또는 SSH 터미널에서 다음 명령으로 연결 진단을 수행합니다.

```bash
# 1. Builder 애드온 ingress 포트 확인 (Supervisor API)
curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/addons/5c53de3b_esphome/info | jq '.data.ingress_port'

# 2. HA Core 내부에서 루프백 연결 및 WS 핸드셰이크 테스트 (Python 원라이너)
python3 -c "
import asyncio, aiohttp, json

async def test_connect(port):
    async with aiohttp.ClientSession() as session:
        url = f'ws://127.0.0.1:{port}/ws'
        print(f'Connecting to {url}...')
        async with session.ws_connect(url) as ws:
            msg = await ws.receive_str()
            info = json.loads(msg)
            print('Received server info:', info)
            assert info.get('requires_auth') is False, 'Error: Builder requires auth!'
            print('SUCCESS: Trusted loopback connection verified without credentials.')

asyncio.run(test_connect(<INGRESS_PORT>))
"
```

### 정상 통과 기준
- `requires_auth`가 `false`여야 합니다.
- HTTP 403 거부(Peer Guard)가 발생하지 않아야 합니다.
- `devices/list` 명령 전송 시 설정된 기기 목록 JSON이 반환되어야 합니다.

---

## 8. 실환경 엔드투엔드 파이프라인 검증 시나리오

1. **통합 구성요소 추가**
   - HA 설정 → 기기 및 서비스 → 통합 구성요소 추가 → `ESPHome OTA` 선택.
   - 포트나 토큰 입력 없이 단일 실행 중인 Builder가 자동 탐지되고, 외부 접속 URL(Base URL) 확인 폼만 표시되는지 확인.
2. **사이드바 패널 진입**
   - 사이드바 `ESPHome OTA` 메뉴 클릭.
   - 상단 Builder 배지가 `정상 연결됨` (초록색)으로 표시되고 기기 카드가 자동 노출되는지 확인.
3. **OTA 준비 (YAML 변경 확인)**
   - 기기 카드의 `OTA 준비` 클릭.
   - `packages.esphome_ota` 블록이 기존 사용자 주석/설정을 보존하며 추가되는 Diff 확인.
   - `YAML에 적용` 클릭 후 CAS 충돌 없이 저장되는지 확인.
4. **빌드 및 게시**
   - `빌드 및 게시` 클릭.
   - 실시간 터미널 로그 팝업에 컴파일 로그 스트리밍 확인.
   - 컴파일 완료 후 자동으로 바이너리 다운로드 및 무결성 검증, `/local/esphome_ota/`에 게시되는지 확인.
   - 기기 상태가 `첫 설치 필요`로 전환되는지 확인.
5. **최초 1회 설치**
   - ESPHome Builder 화면에서 기존 OTA 또는 USB를 통해 해당 펌웨어 1회 설치.
6. **후속 업데이트 확인**
   - HA 대시보드에 기기의 Update 엔티티가 새 버전 업데이트를 감지하는지 확인.

---

## 9. 장애 유형별 원인 및 해결 가이드

| 증상 | 원인 | 해결 방법 |
|---|---|---|
| `Builder 시작 대기` 상태 유지 | ESPHome Builder 애드온 정지 또는 재시작 중 | 애드온이 정상 실행될 때까지 대기하거나 상단 `Builder 재연결` 버튼 클릭 |
| `HTTP 403 Forbidden` 발생 | 루프백 주소가 아닌 외부 IP로 접속 시도 | 연결 주소가 `127.0.0.1`인지 확인 (Docker 브리지 IP 직접 사용 금지) |
| `인증 요구 (requires_auth=true)` | Builder에 사용자 로그인 암호가 설정됨 | Builder 설정에서 전용 로그인 비밀번호를 해제하고 trusted listener 환경 유지 |
| CAS 충돌 (`CAS_CONFLICT`) | 다른 사용자가 외부에서 YAML을 동시 수정함 | 기기 상세 화면에서 최신 YAML을 다시 불러온 후 변경 적용 |
| 칩셋 불일치 (`BinaryValidationError`) | 기기 설정 플랫폼과 빌드 결과 바이너리 칩 ID 불일치 | YAML의 `esp32: board:` 설정 확인 |
