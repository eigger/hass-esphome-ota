# ESPHome OTA 커스텀 통합 구현 작업 지시서

## 요청과 작업 위치

`/Users/eigger/Documents/GitHub/hass-esphome-ota`에 Home Assistant 커스텀 통합 `esphome_ota`를 구현한다. 기존 ESPHome OTA Publisher 애드온을 이식하면서 **ESPHome Builder 자동 연결과 사용 편의성**을 중심으로 개편한다. 설계 설명에 그치지 않고 동작 가능한 코드·테스트·설치 문서를 작성하는 것이 담당 에이전트의 작업이다.

지시서 작성 시점(2026-10-09)에 대상 디렉터리는 비어 있고 `.git`은 없다. 이 지시서와 `docs/architecture.ko.md`는 인계용 문서다. 착수 시 실제 상태와 적용되는 `AGENTS.md`를 다시 확인하고 기존 변경을 보존한다. 구현에 필요하면 로컬 Git을 초기화한다. 새 브랜치는 기본적으로 `codex/` 접두사를 사용한다. 원격 저장소 생성·push·PR·배포는 이 지시서의 요구 사항에 포함하지 않는다.

## 제품 목표 — 가장 중요한 판단 기준

사용자는 공개 포트 매핑이나 `leave_front_door_open`, Builder 로그인 토큰을 설정하지 않고 **HA 안에서 ESPHome 빌드·게시를 실행**하려고 한다. 이 연결을 해결하지 못한 채 기존 애드온 UI만 컴포넌트로 포장하는 것은 목표 달성이 아니다.

기본 환경은 HA OS + ESPHome Device Builder 애드온이다. 컴포넌트 백엔드는 HA Core 프로세스에서 Builder의 trusted loopback listener로 연결한다. 브라우저에서 `127.0.0.1`에 연결하거나, 기존 애드온의 gateway/공개 포트 탐색 방식을 기본으로 사용하지 않는다.

완성될 기본 사용자 흐름:

```text
통합 추가 → Builder 자동 연결 → 기기 목록 자동 표시
→ 기기 선택 → OTA 설정 적용·검증 → 빌드·다운로드·게시
→ 필요 시 첫 설치 안내 → 이후 HTTP OTA 설치 상태 확인
```

자동 연결·자동 목록 동기화는 기본 기능이다. 기기 발견 자체로 YAML을 수정하거나 빌드를 시작하지 않는다. 사용자의 `OTA 준비` 또는 `빌드·게시` 선택 이후 필요한 단계를 이어서 실행한다. 게시와 실제 설치 성공을 구분한다.

## 먼저 읽을 자료

1. 이 저장소의 [상세 설계](docs/architecture.ko.md).
2. 원본 애드온: `/Users/eigger/Documents/GitHub/hassio-apps/esphome_ota/rootfs/opt/esphome_ota/`.
3. 기존 회귀 테스트: `/Users/eigger/Documents/GitHub/hassio-apps/tests/`의 `test_token_ota.py`, `test_version_ownership.py`, `test_build_time.py`.
4. ESL Manager 참조:
   - `/Users/eigger/Documents/GitHub/hass-ble-esl/custom_components/ble_esl/designer/__init__.py`
   - `/Users/eigger/Documents/GitHub/hass-ble-esl/custom_components/ble_esl/designer/frontend/manager.js`
   - `/Users/eigger/Documents/GitHub/hass-ble-esl/custom_components/ble_esl/__init__.py`, `config_flow.py`, `manifest.json`
5. HA 로컬 소스: `/Users/eigger/Documents/GitHub/core/homeassistant/components/esphome/{dashboard.py,coordinator.py,config_flow.py}`와 `components/hassio/`.
6. 최신 Builder 공식 API·trusted listener 구현: 상세 설계의 근거 링크. 로컬 HA 소스 버전과 실제 지원할 HA 버전의 차이를 확인한다.

원본 애드온·ESL Manager·HA Core 저장소는 참조 용도다. 이 작업의 구현은 대상 저장소에 작성한다. 기존 애드온을 삭제하거나 원본 파일을 직접 개편하지 않는다. 애드온 전용 export 변경이 필요하면 별도 후속 항목으로 명시한다.

## 설계 결정

- 도메인 `esphome_ota`, 단일 config entry가 선택한 Builder 하나와 여러 OTA 기기를 관리한다.
- URL·포트·토큰 입력 화면 대신 자동 탐색을 먼저 수행한다. Builder가 여러 개면 선택 화면을 제공한다.
- discovery 우선순위: 저장된 Builder 선택, HA ESPHome dashboard 정보, Supervisor 서비스 discovery/Ingress 정보. 포트는 매번 발견·검증하고 하드코딩하지 않는다.
- 선택한 Builder가 정지해도 다른 Builder로 자동 전환하지 않는다. 시작 대기·재연결 상태를 표시한다.
- HA 내부 API 접점은 adapter에 격리한다. 애드온 `SUPERVISOR_TOKEN` 환경변수를 전제하지 않는다.
- 기기 목록은 Builder가 기준이다. 별도 기기 등록·로컬 YAML 스캔은 기본 흐름에서 제거한다.
- 기기용 외부 `base_url`과 Builder 내부 연결 주소를 구분한다. 외부 URL 누락 시 LAN 주소를 조용히 대신 사용하지 않는다.
- 패널은 ESL Manager처럼 `panel_custom` custom element와 HA `hass` 객체·테마·언어를 사용한다. 관리 API는 관리자 HA WebSocket, 로그는 구독 방식이다.
- 바이너리 수동 업로드는 관리자 HTTP multipart로 제공한다. 대형 base64 WS 전송을 사용하지 않는다.
- 파일 읽기/쓰기·바이너리 분석은 executor, runtime 변경·이벤트 발행은 HA loop에서 실행한다.
- 기존 공개 URL·slug·토큰·버전 소유권을 유지한다. private artifact는 HA config 디렉터리에 저장한다.
- 새로운 동일 용도의 Update 엔티티를 중복 생성하지 않고 기존 ESPHome 엔티티를 연결한다.

## 구현 순서

### 1. 자동 연결을 먼저 구현·실증

`manifest.json`, config flow, setup/unload, discovery adapter, resolver, 최소 Builder client를 작성한다. 먼저 읽기 전용 연결 진단으로 후보 탐색·handshake·기기 목록 조회를 확인한다.

그다음 지정된 검증용 기기에 대해 `compile → job_id 저장 → 명시적 완료 확인 → OTA artifact 조회 → 다운로드`를 검증한다. compile은 `firmware/compile`이며 실제 기기에 플래시하는 `firmware/install`을 기본 동작으로 호출하지 않는다.

필수 조건은 **공개 포트 미설정, leave_front_door_open 비활성, dashboard_token 없음**이다. `requires_auth=false`와 목록 조회 성공을 확인한다. 직접 loopback 접속에서 `ha_ingress=false`는 정상일 수 있다. handshake의 `port`를 trusted 포트로 오인하지 않는다.

Builder 재시작과 Ingress 포트 변경 후 자동 재탐색을 검증한다. HA/Builder 최소 지원 버전은 실제 사용 API와 검증 결과에 맞춰 결정한다.

실제 HA 런타임이 제공되지 않으면:

- 임의의 기기에 실제 빌드·설치·설정 변경을 수행하지 않는다.
- 모의 Builder/HA discovery fixture로 자동 연결·파이프라인 구현과 테스트를 계속 진행한다.
- 실제 HA 안에서 실행할 최소 연결 진단과 검증 절차를 제공한다.
- 연결 실증을 `미검증`으로 명시한다. mock 성공을 실환경 성공으로 표현하지 않는다.

실환경에서 trusted 연결이 거부되는 것이 확인되면 원인을 먼저 해결한다. 공개 포트나 수동 토큰 설정으로 요구 사항을 바꿔 성공 처리하지 않는다.

### 2. 작업 관리와 게시 기능

JobRunner, Store, 바이너리 검사, publisher를 이식한다. pipeline 단계와 Builder job_id를 checkpoint로 저장하고 중복 제출·재연결·HA 재시작을 처리한다. 실패 단계부터 재시도하되 compile 응답 유실 때 새 compile을 바로 재제출하지 않는다.

명시적 완료 상태만 성공으로 처리한다. 기존 `DashboardClient.compile()`의 unknown 허용을 유지하지 않는다. 다운로드 파일의 칩·버전·크기·구조를 검사하고 게시 버전은 실제 바이너리 값으로 확정한다.

검증된 private artifact가 있으면 빌드 없이 재게시할 수 있어야 한다. 실패 시 기존 공개 펌웨어를 보존한다. artifact의 configuration 기반 API 때문에 외부 동시 빌드와 결과 귀속이 불명확하면 자동 게시를 중단한다. 완전한 귀속을 보장하는 upstream API가 있는지도 확인한다.

### 3. OTA 준비와 YAML 변경

Builder API로 YAML을 읽고 CAS(`expected`)로 저장한다. OTA 준비 화면에 변경 diff를 제공한다. 주석·태그·사용자 project/version·기존 packages/OTA 인증을 보존한다. 통합이 소유하지 않은 `packages.ota` 등을 덮어쓰지 않는다.

새 기기는 관리 package `packages.esphome_ota`에 필요한 설정을 넣는 방식부터 검증한다. 기존 `ota_server/...` include 기기는 별도의 legacy 경로로 호환한다. 생성 로직과 파일 접근을 분리한다. 포함 파일 등으로 version 소유권을 확정할 수 없으면 자동 덮어쓰기하지 않는다.

자동 버전은 최초 1.0.0 이후 patch 증가를 기본으로 하되 동일 요청 재시도에는 예약 버전을 재사용한다. 사용자 version 소유 기기는 자동 증가하지 않는다. 게시만 재시도할 때는 버전을 올리지 않는다.

HTTP OTA가 아직 설치되지 않은 기기는 `첫 설치 필요`로 표시한다. YAML 적용과 빌드·게시만으로 기기에 새 OTA 기능이 적용되었다고 표시하지 않는다. 최초 설치는 기존 OTA/USB 등 Builder가 제공하는 설치 경로로 안내한다.

### 4. 편의 패널과 설치 감시

자동 기기 목록, 준비 상태, 설치/게시 버전, 빌드 진행 단계, 상세 로그, 실패 재시도, 취소, 일괄 빌드·게시를 구현한다. 연결·목록·job subscription은 bounded snapshot/event 구조로 만들고 패널을 닫아도 작업은 유지한다.

Update 엔티티는 registry·소스 URL 등의 근거로 매칭한다. 이름 추측만으로 자동 설치/숨김을 수행하지 않는다. 확정할 수 없으면 한 번 선택하게 한다. unavailable과 동일 버전 재게시를 새 설치 성공으로 오인하지 않는다. expiry를 재시작 후 복구한다.

### 5. 데이터 이전과 배포 구성

legacy registered.json·wrapper·공개 manifest 가져오기를 구현한다. 토큰/URL을 보존하고 반복 가져오기를 idempotent하게 처리한다. 애드온 `/data/firmware`는 통합에서 직접 읽을 수 있다고 가정하지 않는다. 공개 파일 복사 또는 애드온 export 결과 가져오기 경로를 제공한다.

애드온과 통합이 같은 공개 파일을 동시에 쓰지 않게 이전 절차를 문서화한다. 실패 시 원본 데이터가 남아 있어야 한다. 원본 애드온의 export 구현이 필요한 경우 이 저장소에서 제공할 수 있는 import와 필요한 export 계약을 구분한다.

README 한국어/영어, HACS 메타데이터, 의존성·최소 HA 버전, 설치·재연결·최초 플래시·데이터 이전·문제 해결 문서를 작성한다. 외부 서비스·원격 Builder 지원은 후속 범위다.

## 산출물 구조

```text
custom_components/esphome_ota/
  __init__.py, manifest.json, config_flow.py, const.py, models.py
  manager.py
  builder/{ha_discovery,resolver,connection,client,capabilities}.py
  devices.py, config_patch.py, packages.py, jobs.py
  firmware.py, publisher.py, monitor.py, storage.py, migration.py
  panel.py, websocket.py, http.py, diagnostics.py
  strings.json, translations/, frontend/
tests/components/esphome_ota/
docs/architecture.ko.md
docs/validation.ko.md
README.md, README.ko.md, hacs.json
```

위 책임 분리를 유지하되 파일명과 세부 분할은 구현 판단에 따라 조정해도 된다.

## 테스트와 수용 기준

아래 실패 사례와 상태 전이를 실제로 검증하는 테스트를 작성한다.

- discovery 지연·복수 후보·연결 주소 변경·403·인증 요구·미지원 API 구분.
- WS 끊김과 reader 종료, HA 공유 session 소유권, reload/unload의 route/task/subscription 중복 방지.
- compile 실패·unknown·응답 유실·job 소실에서 잘못된 성공과 이중 실행 방지.
- YAML CAS 충돌·project 소유권·기존 package·rollback 경쟁 편집.
- binary 칩/버전 불일치·download token 만료·외부 동시 빌드.
- 게시 중 실패 시 이전 공개본 보존, MD5/cache-buster, expiry 복원, 동일 버전 재게시.
- 관리자 API와 upload 제한, migration token/slug 보존, 첫 설치 상태.

기존 token/version ownership/build time 테스트에서 필요한 회귀 사례를 이식한다. HA 테스트 기반에 맞는 pytest와 mock Builder로 네트워크를 격리한다. 실제 ESPHome compile smoke test와 실HA 연결 테스트는 유닛 테스트와 분리한다.

수용 기준:

1. 단일 Builder이면 URL/port/token 입력 없이 연결과 기기 목록 표시.
2. 기기 선택부터 OTA 준비·빌드·게시까지 이어지는 기본 흐름.
3. Builder 재시작이나 HA reload 후 수동 연결 설정 불필요.
4. 게시 성공과 기기 설치 성공을 구분하고 최초 설치 필요성을 안내.
5. 기존 URL/token/사용자 version과 실패 시 이전 공개 펌웨어 보존.
6. 동작 가능한 통합·필요한 테스트·설치/이전 문서를 대상 저장소에 작성.
7. 실환경 미검증이 남으면 실행 절차와 확인하지 못한 항목 명시.

## 최종 보고

구현한 흐름, 실행한 테스트와 결과, 실제 HA에서 확인한 범위, 미검증/미완료 사항, 필요한 환경 정보를 간결하게 보고한다. 실증하지 않은 무인증 연결이나 OTA 설치를 성공했다고 보고하지 않는다. 실환경이 없어도 완성할 수 있는 코드와 테스트는 진행하고, 환경 부재만을 이유로 설계 문서 재작성에서 끝내지 않는다.
