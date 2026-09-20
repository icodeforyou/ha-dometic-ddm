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

# FreshJet (DDM2 ``ac`` class + gateway identity). Every one of these was answered by a
# FJZ7 2600 (fw 2.2.0) on 2026-09-20, see docs/captures/2026-09-20_fjz7_first-session.log.
# ``etemp``, ``eco`` and ``flaps`` never answered on that unit and are left out; ``operst``
# only publishes on change and is kept because the climate entity uses it.
FJZ7_SUBSCRIPTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("gw", "avl"),
    ("gw", "ver"),
    ("gw", "sku"),
    ("ac", "avl"),
    ("ac", "mdl"),
    ("ac", "ver"),
    ("ac", "on"),
    ("ac", "md"),
    ("ac", "operst"),
    ("ac", "ttemp"),
    ("ac", "itemp"),
    ("ac", "fspd"),
    ("ac", "fs"),
    ("ac", "fmd"),
    ("ac", "lgt"),
    ("ac", "dmr"),
    ("ac", "sleep"),
    ("ac", "pwr"),
    ("ac", "curr"),
    ("ac", "currlim"),
    ("ac", "status"),
    ("ac", "actext"),
)

# ac.actext bitfield (dictionary): 1 Heater, 2 Compressor, 0x10 Inverter, 0x20 FanEvap.
# Observed: 0x10 idle, 0x12 while cooling.
AC_ACTEXT_HEATER: Final = 0x01
AC_ACTEXT_COMPRESSOR: Final = 0x02

# ac.fspd is an enum without names in the dictionary. Observed values on the FJZ7: 0 (Dry
# mode), 2 (Fan mode), 5 (Auto mode with fan "On"). Exposed verbatim as fan modes; the
# meaning of each level needs verification.
AC_FAN_SPEEDS: Final[tuple[str, ...]] = ("0", "1", "2", "3", "4", "5")

# UI fallback for the CFX3 climate entity until the device has reported c0TemperatureRange.
# Not a protocol constant; CFX3 marketing range is roughly -22 °C to +10 °C.
FALLBACK_MIN_TEMP_C: Final = -22.0
FALLBACK_MAX_TEMP_C: Final = 10.0
# UI range for the FreshJet target temperature. Not from the protocol (the dictionary has
# no range for ac.ttemp); typical for the product class. Needs verification.
FJZ7_MIN_TEMP_C: Final = 16.0
FJZ7_MAX_TEMP_C: Final = 31.0
