# ha-dometic-ddm

Home Assistant custom integration (HACS) for Dometic devices that speak Dometic's **DDM**
data model over Bluetooth LE: the **CFX3** compressor cooler (DDM1) first, the
**FreshJet FJZ7 2600** roof air conditioner (DDM2) next, and eventually anything else in the
DDM2 dictionary (CFX5, batteries, inverters, heaters, …) by adding a device profile.

> **Status: pre-alpha, not hardware-verified.**
> Everything here is derived from decompiling the official *Dometic Power* app (v2.2.8).
> No frame in this repository has yet been observed on a real device. Anything that depends
> on device behaviour is marked *needs verification* in code comments. Do not expect it to
> work on your cooler yet; do expect it to be a solid, tested starting point.

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

## What works (in tests) and what is guessed

**CFX3 (DDM1).** Config flow via Bluetooth discovery (local name `CFX3*` or service
`537a0300-…`), a coordinator that connects with `bleak-retry-connector`, runs the handshake
`04 → 03 → 04`, subscribes to individual topics and ACKs every PUBLISH. Entities for
compartment 0 only: climate (target temperature, on/off), temperature and battery voltage
sensors, door and compressor binary sensors, battery protection select. Dual-zone (`c1…`)
entities are not created yet.

**FreshJet FJZ7 (DDM2).** Discovered (manufacturer id `0x0845` or service `537a0400-…`) and
connected in *probe mode*: it subscribes to a handful of gateway and AC topics and logs
every value it receives at INFO level. No entities. The point is to answer open question 1
(is the AC class reachable over BLE at all?) the first time a real unit is in range.

Things the code assumes but nobody has seen on a device yet, all marked
*needs verification* in comments:

- the DDM1 handshake order and that every PUBLISH must be ACKed (from app code);
- that a CFX3 needs a BLE bond; the integration asks `bleak-retry-connector` to pair on
  DDM1 connections and whether that survives an HA restart through an ESPHome proxy;
- the meaning of the bulk-subscription topic `01 00 00 81` (not used by default);
- DDM2 handshake: default is *none* (the hardware-verified CFX5 implementation does not
  do one), the HELLO/ACK variant exists as `DDM2_HANDSHAKE_LIKE_DDM1`;
- the DDM2 STRUCT byte layout, interpreted from the dictionary's `struct` field;
- enum names for DDM1 battery protection / power source (lifted from the DDM2 dictionary);
- the local WiFi TCP transport (base64 lines, `\r`), including its port, which the app
  source does not name.

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

HACS installs from GitHub releases. `hacs.json` sets `zip_release`, so each release must
carry `dometic_ddm.zip`; the `Release` workflow builds and attaches it when a `v*` tag is
pushed, after re-running lint, mypy, tests and HACS validation.

```sh
python scripts/release.py 0.2.0   # bumps manifest.json, commits, tags v0.2.0
git push && git push --tags
```

The workflow refuses tags that do not match `manifest.json` and releases whose vendored
`pyddm` copy is stale. Tags below `v1.0.0` or with a suffix (`-beta.1`) are marked
pre-release.

## Prior art

- [philippe-a11y/home-assistant-dometic-cfx](https://github.com/philippe-a11y/home-assistant-dometic-cfx): BLE, DDM1 + DDM2 for CFX; CFX5 verified on hardware.
- [JS-DE-Tech/hacs-dometic-cfx3](https://github.com/JS-DE-Tech/hacs-dometic-cfx3): CFX3 over local WiFi.

No public implementation of the FreshJet FJZ/FJX protocol is known; that is where this
project adds something new.

## License

MIT
