<!-- hass-standards:header:start -->
# ESPHome OTA for Home Assistant

ESPHome Device Builder 애드온의 신뢰 루프백 리스너를 사용해 펌웨어를 HTTP OTA로 빌드·게시하는 Home Assistant 커스텀 통합입니다. 공개 포트, `leave_front_door_open` 설정, 로그인 토큰 없이 연결합니다.

[English](README.md) | **한국어**

<!-- hass-standards:badges:start -->
[![Release](https://img.shields.io/github/v/release/eigger/hass-esphome-ota?style=flat)](https://github.com/eigger/hass-esphome-ota/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat)](#설치)
[![Home Assistant minimum](https://img.shields.io/badge/HA-%E2%89%A5%202024.11.0-41BDF5?style=flat)](hacs.json)
[![Tests](https://img.shields.io/github/actions/workflow/status/eigger/hass-esphome-ota/tests.yml?branch=main&style=flat&label=Tests)](https://github.com/eigger/hass-esphome-ota/actions/workflows/tests.yml)
[![Validate](https://img.shields.io/github/actions/workflow/status/eigger/hass-esphome-ota/validate.yml?branch=main&style=flat&label=Validate)](https://github.com/eigger/hass-esphome-ota/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/eigger/hass-esphome-ota?style=flat)](LICENSE)
[![Downloads](https://img.shields.io/github/downloads/eigger/hass-esphome-ota/latest/total?style=flat&color=41BDF5&label=Downloads)](https://github.com/eigger/hass-esphome-ota/releases)
<!-- hass-standards:badges:end -->
<!-- hass-standards:header:end -->

![ESPHome OTA](custom_components/esphome_ota/brand/logo.png)

## 지원 기능

- Builder 애드온 Zero-Config 자동 탐색과 기기 목록 실시간 동기화.
- `!secret`, `!include`, 주석을 보존하는 Diff 기반 YAML OTA 준비(`packages.esphome_ota`).
- 실시간 로그, 바이너리 무결성 검사, `/local/esphome_ota/` 원자적 게시를 포함한 컴파일·게시 파이프라인.
- 지원 대상: ESP32 계열과 ESP8266. RP2040/RP2350은 검증 가능한 펌웨어 헤더가 없어 지원하지 않으며 빌드 시작 전에 거부됩니다.
- 일괄 빌드·작업 취소·최초 설치 안내 사이드바 패널, 수동 펌웨어 업로드.

상세 기능과 시스템 구조: [docs/features.ko.md](docs/features.ko.md).

## 요구사항

- **Home Assistant:** 2024.11.0 이상.
- **애드온:** Home Assistant OS 또는 Supervised의 ESPHome Device Builder.
- **기본 URL:** ESPHome 기기가 접속할 수 있는 주소. [검증 환경](docs/development.md#verified-environments) 참고(영어).

## 설치

<!-- hass-standards:installation:start -->
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eigger&repository=hass-esphome-ota&category=integration)
<!-- hass-standards:installation:end -->

1. 위 배지를 클릭해 마켓플레이스에서 저장소를 엽니다.
2. 저장소를 직접 추가하려면 **설정 → 마켓플레이스 → 링크에서 추가**에서 <https://github.com/eigger/hass-esphome-ota>을 입력합니다. 안내가 표시되면 GitHub 계정을 연결합니다.
3. **설치**를 선택합니다. 재시작 안내가 표시되면 Home Assistant를 재시작합니다. 설치가 끝나면 [설정](#설정)으로 이동합니다.

## 설정

**설정 → 기기 및 서비스 → 통합 추가 → ESPHome OTA**를 선택합니다.

### 제거

통합 항목을 삭제하고 마켓플레이스에서 제거합니다. 게시한 펌웨어(`www/esphome_ota/`)와 프라이빗 보관본(`/config/esphome_ota/firmware/`)은 유지됩니다. 필요 없는 경우에만 해당 파일을 삭제하세요.

## 빠른 시작

1. 통합을 추가하면 Builder가 자동 감지되며 Base URL을 확인·저장합니다. 이후 사이드바의 **ESPHome OTA**를 열면 Builder의 기기 목록이 표시됩니다.
2. 기기 카드의 **OTA 준비**로 YAML Diff를 검토하고 **YAML에 적용**을 누릅니다.
3. **빌드 및 게시**를 누르고 실시간 로그를 확인하면 매니페스트와 바이너리가 `/local/esphome_ota/`에 게시됩니다.
4. HTTP OTA가 아직 없는 기기는 최초 1회 USB 또는 로컬 OTA로 설치하며, 이후부터 HA의 Update 엔티티로 HTTP OTA 원격 설치가 가능합니다.

## 중요 제한사항

- 펌웨어 게시와 기기 설치는 다르며 패널에서 구분해 표시합니다.
- 게시된 펌웨어는 `/local/`에서 인증 없이 제공되며 기기의 Wi-Fi·API·OTA 비밀값을 포함합니다. URL은 모든 기기에 필수인 16진수 32자 이상의 무작위 토큰으로만 보호되므로 외부에 공유하지 마세요.
- 기기 발견만으로 YAML을 수정하거나 빌드를 시작하지 않습니다.
- 실제 Home Assistant 대상 자동 테스트로 검증했으며, 실물 기기·실제 Builder 동작은 [docs/validation.ko.md](docs/validation.ko.md)의 수동 절차로만 확인합니다.

## 기존 애드온 사용자

ESPHome OTA Publisher 애드온 데이터 가져오기 기능은 제거되었습니다. 애드온을 중지하거나 삭제하고, `www/esphome_ota/`에 남은 애드온 파일도 삭제합니다(애드온을 삭제해도 남으며, 인증 없이 제공되고 기기 비밀값을 포함합니다). 그다음 이 통합에서 **OTA 준비**, **빌드 및 게시**, ESPHome Builder로 1회 설치 순서로 기기를 다시 설정합니다. 이전 버전에서 가져온 기기는 계속 동작하며, 그중 강한 토큰이 없는 기기는 시작 시 새 토큰을 받으므로 마찬가지로 1회 설치가 필요합니다. 추측 가능한 URL에 남은 공개 펌웨어가 있으면 시작 시 경고 로그를 남깁니다.

## 문서

- [기능 및 시스템 구조](docs/features.ko.md)
- [개발 및 테스트](docs/development.md) (영문)
- [상세 설계](docs/architecture.ko.md)
- [HA OS 실환경 검증](docs/validation.ko.md)

<!-- hass-standards:support:start -->
## 지원

- [Issues](https://github.com/eigger/hass-esphome-ota/issues): 버그를 신고하거나 기능을 요청하세요.
<!-- hass-standards:support:end -->

<!-- hass-standards:related-projects:start -->
<!-- hass-standards:related-projects:end -->

<!-- hass-standards:license:start -->
## 라이선스

[MIT License](LICENSE) 라이선스로 배포됩니다.
<!-- hass-standards:license:end -->
