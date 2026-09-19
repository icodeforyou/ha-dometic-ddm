# ha-dometic-ddm

Home Assistant custom integration (HACS) for Dometic devices that speak Dometic's
**DDM** data model over BLE (and, for DDM2, optionally local WiFi-TCP).
First targets: **Dometic CFX3** compressor cooler (DDM1) and **Dometic FreshJet FJZ7 2600**
roof air conditioner (DDM2). Everything else in the DDM2 dictionary (CFX5, batteries,
inverters, heaters …) should be reachable through the same code path with only a device
profile added.

Protocol knowledge comes from decompiling the official *Dometic Power* app
(com.dometic.app 2.2.8, Expo/Hermes). It is documented in `docs/` — **read it before
touching protocol code**:

- `docs/dometic-power-protokoll.md` — frame format, actions, handshake, topic layout, codecs
- `docs/ddm1_cfx3_parameters.json` — full CFX3 (DDM1) parameter table, 86 params
- `docs/ddm2_parameters.json` — full DDM2 dictionary, 240 classes / 2 464 params

## Architecture decision (settled)

**Thin bridges, all logic in Python.** ESP32-C3 bridges run stock ESPHome
`bluetooth_proxy`; this integration talks BLE through Home Assistant's bluetooth stack
(`bleak` via `habluetooth`). No custom firmware unless bonding through the proxy proves
impossible (see Open questions).

Layout:

```
custom_components/dometic_ddm/   HA integration (config flow, coordinator, entities)
pyddm/                           transport-independent protocol package (no HA imports)
  frame.py                       encode/decode [action][topic4][value], handshake state machine
  ddm1.py / ddm2.py              codecs + parameter tables loaded from docs/*.json
  transport/ble.py, tcp.py       BLE (bleak) and WiFi-TCP (base64 lines, "\r") transports
tests/                           pytest, protocol tests run against captured frames, no hardware
esphome/                         example YAML for XIAO ESP32-C3 bluetooth proxy
docs/                            protocol docs + parameter tables (source of truth)
```

`pyddm` must stay importable and testable without Home Assistant. It is intended to become
a PyPI package later (HA rules want protocol code outside the integration).

## Protocol cheat sheet (details in docs/)

Both protocols: raw GATT payload `[action][topic b0..b3][value…]`; control frames are a
single action byte. No length, no CRC.

| | DDM1 (CFX3) | DDM2 (FJZ7, CFX5, …) |
|---|---|---|
| Service | `537a0300-0995-481f-926c-1604e23fd515` | `537a0400-0995-481f-926c-1604e23fd515` |
| Write / Notify | `…0301` / `…0302` | `…0401` / `…0402` |
| PUBLISH / SET / SUBSCRIBE | `0x00` / – (PUBLISH writes) / `0x01` | `0x10` / `0x11` / `0x12` |
| PING / HELLO / ACK / NAK / NOP | `0x02` / `0x03` / `0x04` / `0x05` / `0x06` | – / `0x03` / `0x04` / `0x05` / `0x06` |
| Topic layout | `[instance, param, class, group]` | `[param, instance, class, group]` |
| Values | 1–2 byte LE, °C·10 (int16), V·10 | int32 LE, ×1000 for °C/V/A/W |

Handshake (DDM1, from app code): device sends `04` → we send `03` → device `04` → subscribe.
Every PUBLISH we receive is answered with `04`. The app bonds (Android) and requests MTU 153.
Device identification at scan: local name starting `CFX3` → DDM1; manufacturer data with
company id `0x0845` → DDM2.

## Working method

- Observed reality > docs > logs > code > hypotheses. The docs in `docs/` are derived from
  app code, **not yet verified against hardware**. Mark anything hardware-dependent as
  "needs verification" in code comments and README until it has been seen on a real device.
- Change one thing at a time; every protocol claim should have a test with a concrete byte
  sequence.
- Read before write: get subscribe/decode stable on a device before implementing SET.
- Never guess protocol bytes. If a frame is unknown, log it hex-dumped and stop.

## Open questions (do not silently assume)

1. Does FJZ7 expose the `ac` class (class 2, group 1) over BLE, or only over WiFi/cloud?
2. Does bonding survive HA restart when going through an ESPHome bluetooth proxy?
3. Is topic `01 00 00 81` (DDM1 "subscribeAppSz") really a bulk subscription?
4. Exact DDM2 handshake (HELLO/ACK) — assumed same as DDM1, unverified.

## Prior art (don't reinvent, do read)

- github.com/philippe-a11y/home-assistant-dometic-cfx — BLE, DDM1+DDM2 for CFX; CFX5 verified
- github.com/JS-DE-Tech/hacs-dometic-cfx3 — CFX3 over local WiFi ("DDMP")
- No known public implementation for FreshJet FJZ/FJX.

## Tooling

Python ≥ 3.12 for the integration (match current HA). `ruff` + `mypy --strict` on `pyddm`,
`pytest` for everything, `pytest-homeassistant-custom-component` for the integration.
Commit messages in English, conventional-commits style.
