# ESPHome OTA for Home Assistant

<!-- hass-standards:badges:start -->
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat-square)](#설치)
[![Release](https://img.shields.io/github/v/release/eigger/hass-esphome-ota?style=flat-square)](https://github.com/eigger/hass-esphome-ota/releases)
[![Home Assistant minimum](https://img.shields.io/badge/HA-%E2%89%A5%202024.1.0-41BDF5?style=flat-square)](hacs.json)
[![Tests](https://img.shields.io/github/actions/workflow/status/eigger/hass-esphome-ota/tests.yml?branch=main&style=flat-square&label=Tests)](https://github.com/eigger/hass-esphome-ota/actions/workflows/tests.yml)
[![Validate](https://img.shields.io/github/actions/workflow/status/eigger/hass-esphome-ota/validate.yml?branch=main&style=flat-square&label=Validate)](https://github.com/eigger/hass-esphome-ota/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/eigger/hass-esphome-ota?style=flat-square)](LICENSE)
[![Analytics reporting installs](https://img.shields.io/badge/dynamic/json?style=flat-square&color=41BDF5&label=Usage&query=%24.esphome_ota.total&url=https%3A%2F%2Fanalytics.home-assistant.io%2Fcustom_integrations.json)](https://analytics.home-assistant.io/)
<!-- hass-standards:badges:end -->

[English](README.md) | **한국어**

**ESPHome OTA**는 ESPHome 펌웨어를 HTTP OTA로 빌드·게시하는 Home Assistant 커스텀 통합(HACS)입니다. HA OS 안에서 **ESPHome Device Builder** 애드온의 신뢰 루프백(trusted loopback listener)에 자동 연결하므로 공개 포트 매핑, `leave_front_door_open`, 로그인 토큰이 필요 없습니다. HACS 커스텀 통합이며 Home Assistant Core 공식 통합이 아닙니다.

## 지원 기능

- Builder 애드온 Zero-Config 자동 탐색과 기기 목록 실시간 동기화.
- `!secret`, `!include`, 주석을 보존하는 Diff 기반 YAML OTA 준비(`packages.esphome_ota`).
- 실시간 로그, 바이너리 무결성 검사, `/local/esphome_ota/` 원자적 게시를 포함한 컴파일·게시 파이프라인.
- 일괄 빌드·작업 취소·최초 설치 안내 사이드바 패널, 수동 펌웨어 업로드, 기존 애드온 데이터 이전.

상세 기능과 시스템 구조: [docs/features.ko.md](docs/features.ko.md).

## 요구사항

- ESPHome Device Builder 애드온이 있는 Home Assistant(HA OS / Supervised).
- `hacs.json`의 최소 HA는 2024.1.0으로 선언되어 있으나 현재 코드는 더 새로운 버전이 필요합니다([docs/development.md](docs/development.md#verified-environments), 영문). CI는 HA 2026.10.2에서 검증합니다.
- ESPHome 기기가 접근할 수 있는 Base URL.

## 설치

1. HACS의 **사용자 지정 저장소**에 `https://github.com/eigger/hass-esphome-ota`를 범주 **Integration**으로 추가합니다.
2. **ESPHome OTA**를 다운로드하고 Home Assistant를 재시작합니다.
3. **설정** > **기기 및 서비스** > **통합 구성요소 추가**에서 **ESPHome OTA**를 선택합니다.

수동 설치: `custom_components/esphome_ota`를 `<config>/custom_components/`로 복사하고 재시작합니다. 제거하려면 통합 항목을 삭제한 뒤 해당 폴더(게시한 펌웨어가 불필요하면 `www/esphome_ota/`도)를 삭제합니다.

## 빠른 시작

1. 사이드바의 **ESPHome OTA**를 열면 Builder의 기기 목록이 표시됩니다.
2. 기기 카드의 **OTA 준비**로 YAML Diff를 검토하고 **YAML에 적용**을 누릅니다.
3. **빌드 및 게시**를 누르고 실시간 로그를 확인하면 매니페스트와 바이너리가 `/local/esphome_ota/`에 게시됩니다.
4. HTTP OTA가 아직 없는 기기는 최초 1회 USB 또는 로컬 OTA로 설치하며, 이후부터 HTTP OTA로 업데이트합니다.

## 중요 제한사항

- 펌웨어 게시와 기기 설치는 다르며 패널에서 구분해 표시합니다.
- 기기 발견만으로 YAML을 수정하거나 빌드를 시작하지 않습니다.
- 실제 Home Assistant 대상 자동 테스트로 검증했으며, 실물 기기·실제 Builder 동작은 [docs/validation.ko.md](docs/validation.ko.md)의 수동 절차로만 확인합니다.

## 레거시 애드온 데이터 이전

기존 ESPHome OTA Publisher 애드온에서 전환하는 경우 패널의 **기존 애드온 데이터 이전**을 사용합니다. 이전 대상 기기와 바이너리 미리보기를 확인한 뒤 실행하면 `registered.json`, `www/esphome_ota/`의 바이너리, 토큰, 슬러그가 유지됩니다. 완료 후 기존 애드온을 중지하거나 삭제합니다.

## 문서

- [기능 및 시스템 구조](docs/features.ko.md)
- [개발 및 테스트](docs/development.md) (영문)
- [상세 설계](docs/architecture.ko.md)
- [HA OS 실환경 검증](docs/validation.ko.md)

## 지원

버그 보고와 기능 제안은 [GitHub Issues](https://github.com/eigger/hass-esphome-ota/issues)를 이용하세요. 이 저장소는 GitHub Discussions를 사용하지 않습니다.

## 라이선스

[MIT 라이선스](LICENSE)로 배포됩니다.
