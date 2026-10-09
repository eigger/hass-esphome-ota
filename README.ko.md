# ESPHome OTA for Home Assistant (한국어 안내)

[![HACS Custom Integration](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-54%20Passed-brightgreen.svg)]()

[English Documentation (README.md)](README.md)

**ESPHome OTA**는 Home Assistant OS 환경에서 원격 HTTP OTA 펌웨어 빌드 및 배포를 자동화하는 커스텀 통합 구성요소입니다. 기존 애드온 방식에서 발생하던 공개 포트 매핑, `leave_front_door_open`, Builder 토큰 설정의 번거로움을 완전히 제거하고, HA Core 프로세스에서 **ESPHome Device Builder** 애드온의 신뢰 루프백(trusted loopback listener)으로 자동 연결됩니다.

---

## 주요 기능

- **Zero-Config 루프백 자동 탐색**: 공개 포트 설정이나 대시보드 로그인 토큰 없이, HA 내부 루프백 인터페이스를 통해 실행 중인 ESPHome Builder 애드온을 즉시 탐색·연결합니다.
- **기기 목록 실시간 동기화**: 로컬 YAML 파일을 수동으로 스캔하거나 별도 기기 등록 절차를 거치지 않고, Builder가 인식한 기기 목록을 실시간으로 가져와 표시합니다.
- **안전한 YAML OTA 준비 및 Diff 제공**: Compare-And-Swap(CAS)을 통해 `packages.esphome_ota` 관리 설정을 주입하며, 사용자가 작성한 기존 코드, 주석, `!secret`, `!include`를 원본 그대로 보존합니다.
- **신뢰할 수 있는 컴파일 & 게시 파이프라인**:
  - Builder 공식 API를 통해 컴파일을 요청하고 실시간 출력을 스트리밍합니다.
  - 명시적으로 `completed` 상태가 확인된 경우에만 성공으로 처리합니다 (`unknown` 및 비정상 종료 차단).
  - 일회용 다운로드 토큰을 발급받아 프라이빗 저장소에 안전하게 내려받습니다.
  - 칩셋(`esp_image_header_t`), GCC 빌드 시각, 프레임워크 및 부트 로그 프로젝트 버전을 철저히 검사하여 무결성을 보장합니다.
  - 캐시 방지 해시(`?v=<md5>`)를 포함하여 `/local/esphome_ota/` 경로에 원자적(Atomic)으로 배포합니다.
- **최초 1회 설치 안내**: 펌웨어 게시 성공과 실제 기기의 HTTP OTA 설치 상태를 엄격히 구분하여, 최초 1회 USB/로컬 OTA 설치가 필요한 기기를 직관적으로 안내합니다.
- **ESL Manager 스타일 전용 사이드바 패널**:
  - Home Assistant 테마 및 다크 모드에 완벽하게 대응하는 모던 웹 컴포넌트 대시보드.
  - WebSocket 실시간 구독을 통해 상태 변화, 컴파일 진행 로그, 기기 설치 완료 이벤트를 즉각 반영.
  - 실시간 터미널 로그 스트리밍 창 및 작업 취소 기능.
  - 다중 기기 선택 및 일괄 빌드·게시 지원.
- **기존 애드온 데이터 이전 (마이그레이션)**: 기존 ESPHome OTA Publisher 애드온의 `registered.json`, 기기 래퍼, 토큰, 바이너리를 보존하며 안전하게 이전합니다.
- **수동 펌웨어 업로드**: 사전 컴파일된 바이너리를 직접 업로드할 수 있는 관리자 전용 멀티파트 HTTP 엔드포인트 제공.
- **개인정보 보호 진단 데이터**: 시스템 진단 시 토큰, 외부 비밀 주소, 민감한 YAML 내용을 자동으로 마스킹 처리.

---

## 시스템 구조

```text
[ HA 사이드바 패널 ]
       │  HA 관리자 WebSocket API
       ▼
 [ OtaManager ] ──► [ BuilderResolver ] ──► 루프백 WS/HTTP (127.0.0.1:<port>)
       │                                     └─► ESPHome Device Builder
       ├──────────► [ DeviceManager ]
       ├──────────► [ JobRunner ]
       │                 └─► Compile -> Checkpoint -> Download -> Verify
       ├──────────► [ ArtifactPublisher ]
       │                 ├─► 프라이빗 보관소: /config/esphome_ota/firmware/
       │                 └─► 공개 배포 경로: /config/www/esphome_ota/
       └──────────► [ InstallationMonitor ] ◄── HA Update 엔티티 상태 감시
```

---

## 설치 방법

### 방법 1: HACS를 통한 설치 (권장)
1. Home Assistant 사이드바에서 **HACS** 진입.
2. 우측 상단 메뉴(점 3개) > **사용자 지정 저장소 (Custom repositories)** 선택.
3. 저장소 URL에 `https://github.com/eigger/hass-esphome-ota` 입력 및 범주로 **통합 구성요소 (Integration)** 선택.
4. **ESPHome OTA** 검색 후 **다운로드** 클릭.
5. Home Assistant 재시작.

### 방법 2: 수동 설치
1. 본 저장소를 다운로드합니다.
2. `custom_components/esphome_ota` 디렉터리를 Home Assistant의 `<config>/custom_components/` 경로로 복사합니다:
   ```bash
   cp -r custom_components/esphome_ota /config/custom_components/
   ```
3. Home Assistant를 재시작합니다.

---

## 기본 사용 흐름

1. **통합 구성요소 추가**:
   - **설정** > **기기 및 서비스** > **통합 구성요소 추가** > **ESPHome OTA** 검색.
   - 실행 중인 Builder가 자동으로 감지됩니다. 원격 기기가 접근할 외부 접속 URL(Base URL)을 확인하고 저장합니다.
2. **사이드바 패널 열기**:
   - 사이드바에서 **ESPHome OTA** 클릭.
   - Builder에 등록된 기기 목록이 자동으로 표시됩니다.
3. **기기 OTA 준비**:
   - 기기 카드의 **OTA 준비** 클릭.
   - 제안된 YAML Diff를 검토하고 **YAML에 적용** 클릭.
4. **빌드 및 게시**:
   - **빌드 및 게시** 클릭.
   - 팝업되는 터미널에서 컴파일 로그를 실시간으로 확인.
   - 빌드가 완료되면 자동으로 바이너리가 검증 및 게시됩니다.
5. **최초 설치 진행 (필요 시)**:
   - 기기에 아직 HTTP OTA 기능이 없다면, 첫 1회는 Builder 대시보드나 USB를 통해 설치합니다. 이후부터는 HA 대시보드의 Update 엔티티를 통해 원격 설치가 가능합니다.

---

## 레거시 애드온 데이터 이전

기존 ESPHome OTA Publisher 애드온에서 전환하는 경우:
1. **ESPHome OTA** 패널 우측 상단의 **기존 애드온 데이터 이전** 클릭.
2. 이전 대상 기기 및 바이너리 미리보기를 확인하고 실행.
3. 기존 토큰, 슬러그, 배포 바이너리가 안전하게 유지됩니다.
4. 이전이 완료된 후 기존 애드온을 중지하거나 삭제합니다.

---

## 검증 및 테스트

로컬 pytest 테스트 실행:
```bash
pytest tests/
```
실제 Home Assistant OS 환경에서의 진단 및 검증 절차는 [docs/validation.ko.md](docs/validation.ko.md)를 참조하세요.

---

## 라이선스

이 프로젝트는 MIT 라이선스에 따라 라이선스가 부여됩니다.
