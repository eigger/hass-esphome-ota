# ESPHome OTA 기능 및 시스템 구조

**한국어** | [English](features.md) | [README로 돌아가기](../README.ko.md)

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
