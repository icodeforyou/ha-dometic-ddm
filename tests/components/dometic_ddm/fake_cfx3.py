"""A CFX3 simulator behind a bleak-like client, following docs/dometic-power-protokoll.md.

Behaviour (all "needs verification" against a real cooler, this encodes the docs):
* ACK (04) is notified as soon as notifications are enabled.
* HELLO (03) is answered with ACK (04).
* SUBSCRIBE (01 + topic) is answered with a PUBLISH of the current value for that topic.
* PUBLISH (00 + topic + value) from the client is treated as a write: the value is stored
  and echoed back as a PUBLISH, like a device confirming the new state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from pyddm.ddm1 import default_table

DDM1_NOTIFY = "537a0302-0995-481f-926c-1604e23fd515"
DDM1_WRITE = "537a0301-0995-481f-926c-1604e23fd515"

_T = default_table()


def _initial_state() -> dict[bytes, bytes]:
    def enc(group: str, name: str, value: Any) -> tuple[bytes, bytes]:
        p = _T.get(group, name)
        return p.topic, p.encode(value)

    return dict(
        [
            enc("productInformation", "productModelNumber", "CFX3 45"),
            enc("productInformation", "productSerialNumber", "SN123456"),
            enc("productInformation", "productType", 1),
            enc("deviceSpecific", "ccFirmwareVersion", "1.2.3"),
            enc("compartment", "c0Power", True),
            enc("compartment", "c0MeasuredTemperature", -24.6),
            enc("compartment", "c0SetTemperature", -18.0),
            enc("compartment", "c0DoorOpen", False),
            enc("compartment", "c0TemperatureRange", (-22.0, 10.0)),
            enc("power", "coolerPower", True),
            enc("power", "batteryVoltageLevel", 12.6),
            enc("power", "batteryProtectionLevel", 1),
            enc("power", "compressorPower", True),
            enc("power", "powerSource", 1),
        ]
    )


class FakeCfx3Client:
    """Just enough of bleak's BleakClient for BleTransport, plus CFX3 behaviour."""

    def __init__(self, address: str) -> None:
        self.address = address
        self.state: dict[bytes, bytes] = _initial_state()
        self.writes: list[bytes] = []
        self.acks_received = 0
        self.mtu_size = 153
        self.pair_requested = False
        self.disconnected_callback: Callable[[Any], None] | None = None
        self._connected = False
        self._notify: Callable[[Any, bytearray], None] | None = None
        self.hello_seen = asyncio.Event()

    # -- bleak API -----------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self, **kwargs: Any) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> bool:
        self._connected = False
        self._notify = None
        return True

    async def start_notify(self, char: Any, callback: Callable[[Any, bytearray], None]) -> None:
        assert str(char) == DDM1_NOTIFY
        self._notify = callback
        self._emit(b"\x04")  # device speaks first

    async def stop_notify(self, char: Any) -> None:
        self._notify = None

    async def write_gatt_char(self, char: Any, data: Any, response: bool | None = None) -> None:
        assert str(char) == DDM1_WRITE
        frame = bytes(data)
        self.writes.append(frame)
        action = frame[0]
        if action == 0x03:  # HELLO
            self.hello_seen.set()
            self._emit(b"\x04")
        elif action == 0x04:  # ACK for a publish
            self.acks_received += 1
        elif action == 0x01 and len(frame) == 5:  # SUBSCRIBE
            topic = frame[1:5]
            if topic in self.state:
                self._emit(b"\x00" + topic + self.state[topic])
        elif action == 0x00 and len(frame) >= 5:  # PUBLISH = write
            topic, value = frame[1:5], frame[5:]
            self.state[topic] = value
            self._emit(b"\x00" + topic + value)

    # -- test helpers ---------------------------------------------------------------

    def publish(self, group: str, name: str, value: Any) -> None:
        """Device-initiated value change."""
        p = _T.get(group, name)
        self.state[p.topic] = p.encode(value)
        self._emit(b"\x00" + p.topic + self.state[p.topic])

    def drop_link(self) -> None:
        """Simulate the cooler going out of range."""
        self._connected = False
        self._notify = None
        if self.disconnected_callback is not None:
            self.disconnected_callback(self)

    def _emit(self, frame: bytes) -> None:
        if self._notify is not None:
            self._notify(None, bytearray(frame))
