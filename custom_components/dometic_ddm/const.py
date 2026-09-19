"""Constants for the Dometic DDM integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "dometic_ddm"

CONF_PROTOCOL: Final = "protocol"
CONF_PAIR: Final = "pair"

MANUFACTURER: Final = "Dometic"

# The coordinator's periodic update is only a connection watchdog; all values are pushed.
UPDATE_INTERVAL_SECONDS: Final = 60
# The app-derived DDM1 handshake is two round trips; a CFX3 should be well under this.
HANDSHAKE_TIMEOUT_SECONDS: Final = 15
CONNECT_MAX_ATTEMPTS: Final = 3

# CFX3 (DDM1) topics subscribed one by one, as (table section, parameter name).
# These are the parameters the entities read plus product identification. The bulk
# subscription topic ``01 00 00 81`` (subscribeAppSz) is deliberately NOT used by default:
# open question 3 in CLAUDE.md (is it really a bulk subscription?) needs a device.
CFX3_SUBSCRIPTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("productInformation", "productModelNumber"),
    ("productInformation", "productSerialNumber"),
    ("productInformation", "productType"),
    ("deviceSpecific", "ccFirmwareVersion"),
    ("compartment", "c0Power"),
    ("compartment", "c0MeasuredTemperature"),
    ("compartment", "c0SetTemperature"),
    ("compartment", "c0DoorOpen"),
    ("compartment", "c0TemperatureRange"),
    ("power", "coolerPower"),
    ("power", "batteryVoltageLevel"),
    ("power", "batteryProtectionLevel"),
    ("power", "compressorPower"),
    ("power", "powerSource"),
)

# DDM2 "probe" subscriptions. No FJZ7 entities exist yet (open question 1: does the AC
# class come over BLE?). Subscribing to these and logging what comes back is how that
# question gets answered on real hardware.
DDM2_PROBE_SUBSCRIPTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("gw", "avl"),
    ("gw", "ver"),
    ("gw", "ptype"),
    ("ac", "avl"),
    ("ac", "mdl"),
    ("ac", "itemp"),
)

# UI fallback for the climate entity until the device has reported c0TemperatureRange.
# Not a protocol constant; CFX3 marketing range is roughly -22 °C to +10 °C.
FALLBACK_MIN_TEMP_C: Final = -22.0
FALLBACK_MAX_TEMP_C: Final = 10.0
