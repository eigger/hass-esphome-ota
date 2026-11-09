# 실환경 연결 진단과 문제 해결

**한국어** | [English](troubleshooting.md) | [README로 돌아가기](../README.ko.md)

자동 테스트는 Builder와의 네트워크 경계를 목(mock)으로 대체하므로, 실제 Home Assistant OS의 Builder 애드온과 기기 동작은 아래 절차로 확인합니다.

---

## 1. 연결 진단

통합을 설치한 뒤 Builder에 자동 연결되는지 확인하는 단계입니다.

### 사전 조건 (필수 확인)
1. ESPHome Device Builder 애드온이 설치 및 실행 중이어야 합니다 (`state == "started"`).
2. 애드온에 공개 포트나 로그인 토큰을 따로 설정하지 않은 기본 상태에서 확인합니다.
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

## 2. 엔드투엔드 확인 시나리오

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

## 3. 장애 유형별 원인 및 해결

| 증상 | 원인 | 해결 방법 |
|---|---|---|
| `Builder 시작 대기` 상태 유지 | ESPHome Builder 애드온 정지 또는 재시작 중 | 애드온이 정상 실행될 때까지 대기하거나 상단 `Builder 재연결` 버튼 클릭 |
| `Builder 선택 필요` 배너 표시 | 여러 개의 Builder가 감지되었으나 특정 Builder가 지정되지 않음 | 상단 배너 또는 통합 옵션(OptionsFlow)에서 원하는 Builder 선택 |
| `HTTP 403 Forbidden` 발생 | 루프백 주소가 아닌 외부 IP로 접속 시도 | 연결 주소가 `127.0.0.1`인지 확인 (Docker 브리지 IP 직접 사용 금지) |
| `인증 요구 (requires_auth=true)` | Builder에 사용자 로그인 암호가 설정됨 | Builder 설정에서 전용 로그인 비밀번호를 해제하고 trusted listener 환경 유지 |
| CAS 충돌 (`CAS_CONFLICT`) | 다른 사용자가 외부에서 YAML을 동시 수정함 | 기기 상세 화면에서 최신 YAML을 다시 불러온 후 변경 적용 |
| 칩셋 불일치 (`BinaryValidationError`) | 기기 설정 플랫폼과 빌드 결과 바이너리 칩 ID 불일치 | YAML의 `esp32: board:` 설정 확인 |


