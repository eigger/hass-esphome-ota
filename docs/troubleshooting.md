# Connection diagnostics and troubleshooting

[한국어](troubleshooting.ko.md) | **English** | [Back to README](../README.md)

Automated tests replace the network boundary to the Builder with a mock, so the real Builder add-on on Home Assistant OS and real device behavior can only be checked with the steps below.

---

## 1. Connection diagnostics

Use these steps after installing the integration to confirm that it connects to the Builder automatically.

### Prerequisites

1. The ESPHome Device Builder add-on is installed and running (`state == "started"`).
2. Check with the add-on in its default state: no public port and no login token configured on it.
3. Home Assistant Core can reach the Builder's trusted listener over loopback (`127.0.0.1:<ingress_port>`), as on a standard Home Assistant OS install.

### Running the diagnostic (inside the Home Assistant runtime)

From the HA Core container or an SSH terminal:

```bash
# 1. Find the Builder add-on's ingress port (Supervisor API)
curl -s -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/addons/5c53de3b_esphome/info | jq '.data.ingress_port'

# 2. Test the loopback connection and WebSocket handshake from inside HA Core (Python one-liner)
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

### Expected result

- `requires_auth` is `false`.
- No HTTP 403 rejection (Peer Guard).
- Sending a `devices/list` command returns the JSON list of configured devices.

---

## 2. End-to-end check

1. **Add the integration**
   - Go to Settings → Devices & services → Add integration → `ESPHome OTA`.
   - Confirm that a single running Builder is detected without asking for a port or token, and that only the Public Base URL form is shown.
2. **Open the sidebar panel**
   - Click `ESPHome OTA` in the sidebar.
   - Confirm that the Builder badge at the top shows `Connected` (green) and the device cards appear automatically.
3. **Prepare OTA (review the YAML change)**
   - Click `Prepare OTA` on a device card.
   - Review the diff: the `packages.esphome_ota` block is added while your existing comments and settings are preserved.
   - Click `Apply to YAML` and confirm it saves without a CAS conflict.
4. **Build and publish**
   - Click `Build & Publish`.
   - Confirm that the compile log streams live in the log dialog.
   - After the compile, confirm that the binary is downloaded and verified automatically and published to `/local/esphome_ota/`.
   - Confirm that the device status changes to `First Install Needed`.
5. **First install (once)**
   - Install this firmware once from ESPHome Builder, using the existing OTA or USB.
6. **Follow-up update**
   - Confirm that the device's Update entity in Home Assistant detects the new version.

---

## 3. Common problems

| Symptom | Cause | Fix |
|---|---|---|
| Status stays at `Waiting for Builder` | The ESPHome Builder add-on is stopped or restarting | Wait until the add-on is running, or click `Reconnect Builder` at the top |
| `Selection Required` banner | Several Builders were found and none is selected | Pick the Builder in the banner or in the integration options (OptionsFlow) |
| `HTTP 403 Forbidden` | The connection came from a non-loopback address | Make sure the connection address is `127.0.0.1` (do not use the Docker bridge IP directly) |
| `requires_auth=true` | A login password is set on the Builder | Remove the dedicated login password in the Builder settings and keep the trusted listener |
| CAS conflict (`CAS_CONFLICT`) | The YAML was changed elsewhere at the same time | Reload the latest YAML in the device detail view, then apply your change again |
| Chip mismatch (`BinaryValidationError`) | The device's configured platform and the built binary's chip ID differ | Check the `esp32: board:` setting in the YAML |
