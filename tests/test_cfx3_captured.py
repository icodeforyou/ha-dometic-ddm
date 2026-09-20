"""CFX3 frames captured from a real CFX335 (docs/captures/2026-09-20_cfx3_first-session.*).

Verifies on real bytes: the PING-first handshake, that device PINGs are ACKed, DDM1 topic
layout, int16 LE deci-values, INT16_ARRAY, zero-terminated strings with leftover bytes after
the terminator, the bulk-subscription frame, and history arrays with the 0x8000 sentinel.
"""

from __future__ import annotations

import pytest

from pyddm import Protocol
from pyddm.ddm1 import HistoryData, default_table
from pyddm.session import DDM1_HANDSHAKE_WITH_PING, Control, ProtocolMachine, Ready, Send, Update

ACK = bytes([0x04])

CAPTURED: list[tuple[str, str, object]] = [
    ("00 00 C4 00 00 01", "productInformation.productType", 1),
    (
        "00 00 C1 00 80 56 33 2E 35 31 30 2B 44 44 32 2E 32 00",
        "deviceSpecific.ccFirmwareVersion",
        "V3.510+DD2.2",
    ),
    ("00 00 00 01 01 01", "compartment.c0Power", True),
    ("00 00 01 01 01 B4 00", "compartment.c0MeasuredTemperature", 18.0),
    ("00 00 01 01 01 BE 00", "compartment.c0MeasuredTemperature", 19.0),
    ("00 00 02 01 01 14 00", "compartment.c0SetTemperature", 2.0),
    ("00 10 02 01 01 6A FF", "compartment.c1SetTemperature", -15.0),
    ("00 00 08 01 01 00", "compartment.c0DoorOpen", False),
    ("00 00 80 01 01 24 FF C8 00", "compartment.c0TemperatureRange", (-22.0, 20.0)),
    ("00 00 00 03 01 01", "power.coolerPower", True),
    ("00 00 01 03 01 84 00", "power.batteryVoltageLevel", 13.2),
    ("00 00 02 03 01 01", "power.batteryProtectionLevel", 1),
    ("00 00 03 03 01 00", "power.compressorPower", False),
    ("00 00 05 03 01 01", "power.powerSource", 1),
    # "CFX335\0" followed by leftover bytes "5 DZ", cut at the first NUL.
    (
        "00 00 C0 00 00 43 46 58 33 33 35 00 35 20 44 5A 00 00 00 00",
        "productInformation.productModelNumber",
        "CFX335",
    ),
    (
        "00 00 C1 00 00 34 34 33 30 34 33 34 35 00 00 00 00 00 00 00",
        "productInformation.productSerialNumber",
        "44304345",
    ),
    ("00 00 00 06 01 43 46 58 33 5F 61 39 30 62 66 38", "communication.deviceName", "CFX3_a90bf8"),
    ("00 00 03 04 01 00", "errors.connectionError", False),
    ("00 00 03 05 01 00", "alerts.temperatureAlertDcm", False),
    ("00 00 08 06 01 01", "communication.wifiApConnected", True),
    ("00 00 00 02 01 00", "presentation.presentedTemperatureUnit", 0),
    ("00 01 00 07 01", "wiFiSettings.stationSsid1", ""),
    (
        "00 00 40 01 01 A8 00 87 00 9B 00 00 80 00 80 00 80 00 80 B3",
        "compartment.c0TemperatureHistoryHour",
        HistoryData((16.8, 13.5, 15.5, None, None, None, None), 179),
    ),
    (
        "00 00 40 03 01 04 00 00 00 19 00 00 80 00 80 00 80 00 80 B3",
        "power.dcCurrentHistoryHour",
        HistoryData((0.4, 0.0, 2.5, None, None, None, None), 179),
    ),
]


def _ready_machine() -> ProtocolMachine:
    m = ProtocolMachine(Protocol.DDM1)
    m.start()
    m.receive(ACK)
    m.receive(ACK)
    return m


def test_handshake_as_captured_ping_first() -> None:
    """12:17:50 / 12:35:28: we 02, cooler 04, we 03, cooler 04, READY."""

    m = ProtocolMachine(Protocol.DDM1, handshake=DDM1_HANDSHAKE_WITH_PING)
    assert m.start() == [Send(bytes([0x02]))]
    assert m.receive(ACK) == [Send(bytes([0x03]))]
    assert m.receive(ACK) == [Ready()]


def test_device_pings_are_acked() -> None:
    """The cooler pings every 2 s and publishes nothing until the pings are ACKed."""
    m = _ready_machine()
    assert m.receive(bytes([0x02])) == [Control(0x02), Send(ACK)]


@pytest.mark.parametrize(("hex_frame", "name", "value"), CAPTURED)
def test_captured_publish_decodes(hex_frame: str, name: str, value: object) -> None:
    m = _ready_machine()
    events = m.receive(bytes.fromhex(hex_frame))
    update, ack = events
    assert isinstance(update, Update)
    assert update.error is None, update.error
    assert update.name == name
    if isinstance(value, float):
        assert update.value == pytest.approx(value)
    else:
        assert update.value == value
    assert ack == Send(ACK)  # every PUBLISH is ACKed


def test_bulk_subscription_frames() -> None:
    table = default_table()
    m = _ready_machine()
    assert m.subscribe_frame(table.topic_for("multiSubscriptionParameters", "subscribeAppSz")) == (
        bytes.fromhex("01 01 00 00 81")
    )
    assert m.subscribe_frame(table.topic_for("multiSubscriptionParameters", "subscribeAppDz")) == (
        bytes.fromhex("01 03 00 00 81")
    )
