<!-- hass-standards:header:start -->
# ESPHome OTA for Home Assistant

ESPHome Device Builder 애드온에 연결해 펌웨어를 빌드하고, Home Assistant가 HTTP OTA로 기기에 제공하는 커스텀 통합입니다. 애드온에는 별도 설정이 필요 없습니다.

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
- **애드온:** Home Assistant OS 또는 Supervised에 설치되어 실행 중인 ESPHome Device Builder 애드온. 통합은 Supervisor를 통해 애드온을 찾으며, Container/Core 설치와 외부 Builder는 지원하지 않습니다.
- **기본 URL:** ESPHome 기기가 펌웨어를 내려받을 Home Assistant의 외부 접속 주소. 외부에서 OTA를 받으려면 인터넷에서 접근 가능해야 합니다(도메인과 HTTPS).

## 설치

<!-- hass-standards:installation:start -->
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=eigger&repository=hass-esphome-ota&category=integration)
<!-- hass-standards:installation:end -->

1. 위 배지를 클릭해 마켓플레이스에서 저장소를 엽니다.
2. 저장소를 직접 추가하려면 **설정 → 마켓플레이스 → 링크에서 추가**에서 <https://github.com/eigger/hass-esphome-ota>을 입력합니다. 안내가 표시되면 GitHub 계정을 연결합니다.
3. **설치**를 선택합니다. 재시작 안내가 표시되면 Home Assistant를 재시작합니다. 설치가 끝나면 [설정](#설정)으로 이동합니다.

## 설정

**설정 → 기기 및 서비스 → 통합 추가 → ESPHome OTA**를 선택합니다.

1. ESPHome Builder가 여러 개 발견되면 사용할 Builder를 고릅니다. 하나뿐이면 자동으로 선택됩니다.
2. **외부 접속 URL (Base URL)**을 입력합니다. 기기가 펌웨어를 가져올 Home Assistant의 외부 주소입니다(예: `https://ha.example.com`).

이후 통합 항목의 **구성**에서 Base URL, Builder, **기본 자동 비공개 시간(시간)**(0 = 자동 비공개 안 함)을 바꿀 수 있습니다. 게시하기 전에 [중요 제한사항](#중요-제한사항)을 읽어 주세요.

### 제거

기기 YAML에서 `packages.esphome_ota` 블록도 지우려면, 통합을 제거하기 전에 패널의 각 기기 카드에서 **OTA 설정 제거**를 누르세요. 통합 항목을 삭제해도 YAML은 수정되지 않습니다. 그다음 통합 항목을 삭제하고 마켓플레이스에서 제거합니다. 게시한 펌웨어(`www/esphome_ota/`)와 프라이빗 보관본(`/config/esphome_ota/firmware/`)은 유지됩니다. 필요 없는 경우에만 해당 파일을 삭제하세요.

## 빠른 시작

1. 통합을 추가하면 Builder가 자동 감지되며 Base URL을 확인·저장합니다. 이후 사이드바의 **ESPHome OTA**를 열면 Builder의 기기 목록이 표시됩니다.
2. 기기 카드의 **OTA 준비**로 YAML Diff를 검토하고 **YAML에 적용**을 누릅니다.
3. **빌드 및 게시**를 누르고 실시간 로그를 확인하면 매니페스트와 바이너리가 `/local/esphome_ota/`에 게시됩니다.
4. HTTP OTA가 아직 없는 기기는 최초 1회 USB 또는 로컬 OTA로 설치하며, 이후부터 HA의 Update 엔티티로 HTTP OTA 원격 설치가 가능합니다.

## 중요 제한사항

- 펌웨어 게시와 기기 설치는 다르며 패널에서 구분해 표시합니다.
> [!WARNING]
> **게시된 펌웨어에는 기기의 비밀값이 들어 있으며 인증 없이 제공됩니다.**
>
> - 이 통합은 Home Assistant가 OTA 펌웨어를 제공(서빙)하도록 할 뿐, 누가 접근할 수 있는지는 통제하지 않습니다. 파일을 인터넷에서 접근 가능하게 둘지(공개 OTA), 어느 범위로 얼마나 오래 둘지는 사용자 책임이므로 필요한 만큼만 노출하세요.
> - ESPHome은 `!secret` 값을 컴파일할 때 실제 값으로 치환하므로, 빌드된 `.ota.bin`에는 Wi-Fi SSID·비밀번호, API 암호화 키, OTA 비밀번호가 평문으로 들어 있습니다. 파일을 내려받은 누구나 읽을 수 있습니다.
> - 파일은 Home Assistant 로그인 없이 `/local/esphome_ota/`에서 제공됩니다. 보호 수단은 URL에 포함된 16진수 32자 이상의 무작위 토큰뿐이며 모든 기기에 필수입니다. URL을 비밀번호처럼 다루고, 이슈·스크린샷·로그에 붙여 넣거나 공유하지 마세요.
> - 노출 시간을 짧게 유지하세요. 펌웨어는 설치가 확인되면 자동으로 비공개되며(기본 켜짐), **자동 비공개 시간**(기본 12시간)이 지나도 비공개됩니다. 필요 없으면 직접 비공개하세요.
> - 비공개는 공개 파일을 지울 뿐 이미 진행 중인 다운로드나 리버스 프록시·CDN에 캐시된 사본을 취소하지는 않습니다. URL 유출이 의심되면 Wi-Fi 비밀번호, API 키, OTA 비밀번호를 교체하세요.

- 기기 발견만으로 YAML을 수정하거나 빌드를 시작하지 않습니다.
- 실제 Home Assistant 대상 자동 테스트로 검증했으며, 실물 기기·실제 Builder 동작은 [docs/troubleshooting.ko.md](docs/troubleshooting.ko.md)의 수동 절차로만 확인합니다.

## 문서

- [기능 및 시스템 구조](docs/features.ko.md)
- [상세 설계](docs/architecture.ko.md)
- [실환경 연결 진단과 문제 해결](docs/troubleshooting.ko.md)

<!-- hass-standards:support:start -->
## 지원

- [Issues](https://github.com/eigger/hass-esphome-ota/issues): 버그를 신고하거나 기능을 요청하세요.
- [Discussions](https://github.com/eigger/hass-esphome-ota/discussions): 질문하고 사용 경험을 공유하세요.
<!-- hass-standards:support:end -->

<!-- hass-standards:related-projects:start -->
<!-- hass-standards:related-projects:end -->

<!-- hass-standards:license:start -->
## 라이선스

[MIT License](LICENSE) 라이선스로 배포됩니다.
<!-- hass-standards:license:end -->
