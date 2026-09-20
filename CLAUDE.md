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

Handshake (DDM1, **verified**): we send `02` (PING) → device `04` → we `03` → device `04` →
subscribe. Every PUBLISH *and every PING* we receive is answered with `04`. The app bonds (Android) and requests MTU 153.
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

## Hardware testing without HA

`uv run python -m tools.ac_console` → http://127.0.0.1:8765/ drives a pyddm Session over the
laptop's BlueZ adapter: scan, connect, subscribe, hex frame log, gated writes. Use it for
every protocol experiment before touching the integration; save frame logs under
`docs/captures/`. It must keep using pyddm's Session/codecs, never its own byte handling.

## Verified on hardware (2026-09-20, laptop BlueZ, captures in docs/captures/)

- **Bonding is mandatory** for both devices. Pairing only succeeds while the device is in
  its pairing mode (FreshJet: button combination on the unit; CFX3: Bluetooth pairing menu).
  Unbonded centrals are dropped within ~1–4 s. Use `bluetoothctl` (has an agent) to bond.
- **FJZ7 (DDM2)**: no handshake; SUBSCRIBE → PUBLISH immediately; SET confirmed by PUBLISH;
  `ac` class reachable over BLE (open question 1: yes); state pushed on change and on remote
  use; Turbo mode refused; `etemp/eco/flaps` never answer; `pwr` looks 10× too small.
- **CFX3 (DDM1)**: **client opens with PING** `02` → `04` → `03` → `04` (docs had the order
  wrong). Cooler PINGs every 2 s and **publishes nothing until each PING is ACKed** (pyddm
  does this by default now). Individual SUBSCRIBEs then answer immediately; bulk topics
  `01/02/03 00 00 81` work too (open question 3: yes). Cooler is silent for ~1 min after a
  disconnect before advertising again; bleak must be given BlueZ's device object, not a
  string address, or connects time out.

## Open questions (do not silently assume)

1. ~~Does FJZ7 expose the `ac` class over BLE?~~ Yes.
2. Does bonding survive HA restart when going through an ESPHome bluetooth proxy?
3. ~~Is `01 00 00 81` a bulk subscription?~~ Yes (Sz); `02`/`03` = Szi/Dz variants.
4. ~~Exact DDM2 handshake?~~ None needed.
5. `ac.pwr` scaling (factor 1000 gives ~29 W at 1.6 A; probably 100). Check with a meter.
6. `ac.fspd` level meaning (0/2/5 observed) and whether `ac.dmr` really dims the light.
7. HISTORY_DATA_ARRAY: `0x8000` = no sample (decode as None), trailer byte = counter.

## Prior art (don't reinvent, do read)

- github.com/philippe-a11y/home-assistant-dometic-cfx — BLE, DDM1+DDM2 for CFX; CFX5 verified
- github.com/JS-DE-Tech/hacs-dometic-cfx3 — CFX3 over local WiFi ("DDMP")
- No known public implementation for FreshJet FJZ/FJX.

## Tooling

Python 3.14 for the dev environment (current HA needs ≥ 3.14.2; `pyddm` itself supports ≥ 3.13). `ruff` + `mypy --strict` on `pyddm`,
`pytest` for everything, `pytest-homeassistant-custom-component` for the integration.
Commit messages in English, conventional-commits style.

## Releasing (HACS)

Releases are automatic. Never create tags or GitHub releases by hand.

1. `python scripts/release.py <version>` bumps `custom_components/dometic_ddm/manifest.json`
   and commits `chore(release): v<version>` (refuses a dirty tree or an already-released
   version). Versions below 1.0.0 or with a suffix become pre-releases.
2. `git push` to `main`. The `Release` workflow (`.github/workflows/release.yml`) sees a
   manifest version without a `v<version>` tag, runs ruff + mypy + pytest + HACS validation,
   tags the commit and publishes a GitHub release with `dometic_ddm.zip` attached.
   `hacs.json` has `zip_release: true`, so HACS installs from that zip.
3. Pushes that do not change the manifest version release nothing.

Prerequisites that live on GitHub, not in the repo: HACS validation requires the repository
to have a description and topics (`gh repo edit --description … --add-topic …`); they were
set on 2026-09-19. Watch runs with `gh run list` / `gh run watch <id>`.

The `pyddm` version in `pyproject.toml` is separate and only matters for a future PyPI release.
