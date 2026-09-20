# ha-dometic-ddm

Home Assistant custom integration (HACS) for Dometic devices that speak Dometic's **DDM**
data model over Bluetooth LE: the **CFX3** compressor cooler (DDM1) first, the
**FreshJet FJZ7 2600** roof air conditioner (DDM2) next, and eventually anything else in the
DDM2 dictionary (CFX5, batteries, inverters, heaters, …) by adding a device profile.

> **Status: alpha, hardware-tested once.** Read and write paths were verified against a
> real FreshJet FJZ7 2600 and a CFX3 (CFX335) on 2026-09-20 from a laptop; see
> `docs/captures/`. Not yet tested on a Raspberry Pi or through an ESPHome proxy, not yet
> tested over days. Anything still guessed is marked *needs verification* in the code.

## What is in the repo

| Path | Purpose |
|---|---|
| `pyddm/` | Transport-independent protocol package (frames, DDM1/DDM2 codecs, parameter tables, session state machine, BLE and TCP transports). No Home Assistant imports; intended to become a PyPI package. |
| `custom_components/dometic_ddm/` | The Home Assistant integration (config flow, coordinator, entities). Ships a vendored copy of `pyddm` until it is on PyPI. |
| `tests/` | pytest suite. Byte-exact codec tests, frame round-trips, handshake state machine against a fake transport, CFX3 golden sequence, HA config-flow tests. Runs without hardware. |
| `esphome/` | Example ESPHome YAML for a Seeed XIAO ESP32-C3 acting as a Bluetooth proxy. |
| `docs/` | Protocol documentation and parameter tables. **Source of truth.** |

Read `docs/dometic-power-protokoll.md` before touching protocol code.

## Architecture

Thin bridges, all logic in Python: ESP32-C3 boards run stock ESPHome `bluetooth_proxy`, and
this integration talks BLE through Home Assistant's Bluetooth stack. The `pyddm` package
knows nothing about Home Assistant or Bluetooth libraries beyond an abstract transport, so
the protocol can be unit-tested with captured byte sequences.

```
custom_components/dometic_ddm/   HA integration (config flow, coordinator, entities)
  pyddm/                         vendored copy of ../../pyddm (HACS only ships this folder)
pyddm/                           the protocol package, source of truth for the copy
  const.py                       UUIDs, company id, advertisement → protocol classification
  frame.py                       [action][topic4][value] encode/decode, action enums
  ddm1.py / ddm2.py              codecs + parameter tables (JSON bundled under pyddm/data)
  session.py                     sans-I/O ProtocolMachine + asyncio Session
  transport/                     abstract Transport, bleak BLE, base64-line TCP (untested)
```

Keep the vendored copy current with `python scripts/sync_vendored.py`; a test fails if it
is stale. Once `pyddm` is on PyPI the copy goes away and `manifest.json` lists it under
`requirements`.

## Supported devices and entities

One integration, one config entry per device. The protocol (DDM1 or DDM2) is detected at
discovery and selects the device profile.

| Device | Protocol | Entities |
|---|---|---|
| **FreshJet FJZ7 2600** (and other `SHE_…` FreshJet units, untested) | DDM2 | climate (off / cool / heat / fan only / auto / dry, target temperature, fan speed 0–5), light with dimmer, sleep switch, sensors: inside temperature, power, current, operating state; binary sensors: compressor running, error |
| **CFX3** single zone (CFX335 tested; other CFX3 sizes should behave the same) | DDM1 | climate for the compartment (on / off, target temperature), sensors: temperature, battery voltage; binary sensors: door, compressor; battery protection select |

Dual-zone CFX3 (`c1…` topics) and other DDM2 devices (CFX5, batteries, …) are not exposed
yet; the protocol layer already decodes them.

## Pairing (read this before adding a device)

Both devices refuse any Bluetooth client they are not bonded with and drop the link within
a few seconds. Bonding is only possible while the device is in its pairing mode:

- **FreshJet**: press the pairing button combination on the unit (see the unit's manual;
  the AC is only pairable for a short window).
- **CFX3**: open the cooler's menu and start Bluetooth pairing; the Bluetooth icon blinks
  for about a minute.

Then add the integration (or reload it) while the window is open. Home Assistant bonds
during connection setup. Afterwards the bond is reused. Only one client can be connected at
a time, so close the Dometic app on any phone nearby. After a disconnect a CFX3 stays
invisible for about a minute before it can be found again.

## Verified behaviour and remaining guesses

Verified on hardware (2026-09-20): frame format and codecs for both protocols; DDM2 needs no
handshake and echoes every write; DDM1 is opened by the client with PING, the cooler pings
every two seconds and publishes only while those pings are acknowledged, and it applies
writes without echoing them (the integration re-reads after each write); bulk subscription
topics work; changes made on the remote or the cooler's own buttons are pushed.

Still to verify: bond persistence across HA restarts and through an ESPHome proxy; the
FreshJet power reading (`ac.pwr`, looks 10× too small); the meaning of fan speed levels
0–5; whether the dimmer really dims; the battery protection and power source enum names on
the CFX3 (borrowed from the DDM2 dictionary).

## Hardware bring-up plan

1. Flash `esphome/xiao-esp32c3-proxy.yaml` (stock ESPHome, `bluetooth_proxy: active: true`).
2. Put the CFX3 in pairing mode, add the integration from HA's discovered-devices list.
3. Read the debug log (`custom_components.dometic_ddm` and `pyddm` at DEBUG): every frame
   is hex-dumped as `TX`/`RX`, unknown frames are logged and ignored, never acted on.
4. Compare the decoded compartment temperature against the cooler's display before
   trusting any write.

## Development

```sh
uv sync --group dev          # Python 3.14 .venv with HA test harness, ruff, mypy, pytest (from uv.lock)
uv run ruff check . && uv run ruff format --check .
uv run mypy                  # strict, pyddm only
uv run pytest -q
```

## Releasing

HACS installs from GitHub releases, and `hacs.json` sets `zip_release`, so each release
carries `dometic_ddm.zip`. Releases are cut automatically: on every push to `main` the
`Release` workflow reads `manifest.json`; if that version has no release yet it re-runs
lint, mypy, tests and HACS validation, tags the commit `v<version>`, and publishes the
release with the zip attached. Pushes that do not change the version release nothing.

```sh
python scripts/release.py 0.2.0   # bumps manifest.json and commits
git push                          # → release v0.2.0
```

Versions below 1.0.0 or with a suffix (`0.3.0-beta.1`) are marked pre-release.

## Prior art

- [philippe-a11y/home-assistant-dometic-cfx](https://github.com/philippe-a11y/home-assistant-dometic-cfx): BLE, DDM1 + DDM2 for CFX; CFX5 verified on hardware.
- [JS-DE-Tech/hacs-dometic-cfx3](https://github.com/JS-DE-Tech/hacs-dometic-cfx3): CFX3 over local WiFi.

No public implementation of the FreshJet FJZ/FJX protocol is known; that is where this
project adds something new.

## License

MIT
