# Kickoff prompt for Claude Code (copy into the first session)

Read CLAUDE.md and everything in docs/ first. Then scaffold the repository — no hardware
is available yet, so everything must be verifiable with pytest alone.

Deliver, in this order, each as its own commit:

1. **Tooling skeleton**: `pyproject.toml` (pyddm as an installable package, ruff, mypy,
   pytest config), `hacs.json`, `.github/workflows/ci.yml` running ruff + mypy + pytest,
   `README.md` (short: what it is, status "pre-alpha, not hardware-verified", link to docs).

2. **`pyddm` core**:
   - `frame.py`: `Frame(action, topic: bytes[4], value: bytes)` with `encode()`/`decode()`,
     control frames as single bytes, `DDM1Action`/`DDM2Action` enums exactly as in CLAUDE.md.
   - `ddm1.py`: codec for the DDM1 data types (INT8_BOOLEAN, INT8_NUMBER, UINT8_NUMBER,
     INT16_DECIDEGREE_CELSIUS, INT16_DECICURRENT_VOLT, INT16_ARRAY, HISTORY_DATA_ARRAY,
     UTF8_STRING, EMPTY) matching `ddm1Encoder`/`ddm1Decoder` semantics in
     docs/dometic-power-protokoll.md (little-endian int16, ×10; strings ≤15 bytes,
     zero-terminated when shorter). Load the parameter table from
     docs/ddm1_cfx3_parameters.json and expose `topic_for("compartment","c0SetTemperature")`
     and `lookup(topic_bytes)`.
   - `ddm2.py`: same for DDM2 (int32 LE with `factor`, STRING, STRUCT per the `struct`
     field, enums). Load docs/ddm2_parameters.json; topic = `[param_id, instance, class_id,
     group_id]`.
   - `session.py`: transport-independent state machine for the DDM1 handshake
     (WAIT_ACK → send HELLO → WAIT_ACK → READY), auto-ACK of incoming PUBLISH,
     subscribe(topic), set/publish(topic, value), and a callback for decoded updates.
     Model DDM2 the same way but keep the handshake steps configurable — it is unverified.
   - `transport/base.py` with an abstract `write(bytes)` / `on_notify(callback)`;
     `transport/ble.py` using `bleak` (service/char UUIDs from CLAUDE.md, request MTU 153
     where the backend allows); `transport/tcp.py` for DDM2 over WiFi (base64 frames,
     `\r`-separated) — implement but mark untested.

3. **Tests** (`tests/`): byte-exact tests for every codec type, frame round-trips,
   the handshake state machine driven by a fake transport, and a CFX3 "golden" sequence:
   device `04` → we `03` → device `04` → we `01 01 00 00 81` → device
   `00 00 01 01 01 0A FF` decodes to c0MeasuredTemperature = -24.6 °C
   (verify that value against the codec — if the sign handling says otherwise, the test
   must follow the codec, and note the discrepancy in a comment).

4. **HA integration skeleton** `custom_components/dometic_ddm/`: `manifest.json` with
   `bluetooth` matchers for both service UUIDs and `local_name: "CFX3*"`, config flow that
   discovers via bluetooth and stores address + protocol (DDM1/DDM2), a
   `DataUpdateCoordinator` wrapping a `pyddm` session, and entities for CFX3 only:
   sensor (measured temp, battery voltage), climate (set temp, power), binary_sensor
   (door, compressor), select (battery protection). Use `bluetooth_proxy`-compatible APIs
   (`async_ble_device_from_address`, `establish_connection` from `bleak-retry-connector`).
   FJZ7 entities come later, once open question 1 in CLAUDE.md is answered.

5. `esphome/xiao-esp32c3-proxy.yaml`: minimal bluetooth proxy config with
   `active: true`, for Seeed XIAO ESP32-C3.

Constraints: do not invent protocol bytes not present in docs/. Where the docs say
"needs verification", say so in a code comment. Keep `pyddm` free of Home Assistant
imports. Ask before adding dependencies beyond bleak, bleak-retry-connector and the
HA test harness.
