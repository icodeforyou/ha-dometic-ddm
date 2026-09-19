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

## Development

```sh
uv sync --group dev          # creates .venv with HA test harness, ruff, mypy, pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy                  # strict, pyddm only
uv run pytest -q
```

## Prior art

- [philippe-a11y/home-assistant-dometic-cfx](https://github.com/philippe-a11y/home-assistant-dometic-cfx): BLE, DDM1 + DDM2 for CFX; CFX5 verified on hardware.
- [JS-DE-Tech/hacs-dometic-cfx3](https://github.com/JS-DE-Tech/hacs-dometic-cfx3): CFX3 over local WiFi.

No public implementation of the FreshJet FJZ/FJX protocol is known; that is where this
project adds something new.

## License

MIT
