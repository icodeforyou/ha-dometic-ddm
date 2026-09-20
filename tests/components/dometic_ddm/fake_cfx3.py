"""A CFX3 simulator behind a bleak-like client, behaving like the real CFX335 did on
2026-09-20 (docs/captures/2026-09-20_cfx3_first-session.md):

* The cooler says nothing after notifications are enabled. The client must send PING (02);
  the cooler answers ACK (04). HELLO (03) is answered with ACK.
* Once the session is up the cooler PINGs the client; it only answers SUBSCRIBEs with a
  PUBLISH after the client has ACKed at least one of those PINGs.
* A PUBLISH from the client (a write) is ACKed and applied but NOT echoed; a later
  SUBSCRIBE returns the new value.
"""

from __future__ import annotations

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
            enc("productInformation", "productModelNumber", "CFX335"),
            enc("productInformation", "productSerialNumber", "44304345"),
            enc("productInformation", "productType", 1),
            enc("deviceSpecific", "ccFirmwareVersion", "V3.510+DD2.2"),
            enc("compartment", "c0Power", True),
            enc("compartment", "c0MeasuredTemperature", 18.0),
            enc("compartment", "c0SetTemperature", 2.0),
            enc("compartment", "c0DoorOpen", False),
            enc("compartment", "c0TemperatureRange", (-22.0, 20.0)),
            enc("power", "coolerPower", True),
            enc("power", "batteryVoltageLevel", 13.2),
            enc("power", "batteryProtectionLevel", 1),
            enc("power", "compressorPower", False),
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
        self.mtu_size = 23
        self.pair_requested = False
        self.disconnected_callback: Callable[[Any], None] | None = None
        self._connected = False
        self._notify: Callable[[Any, bytearray], None] | None = None
        self._hello_done = False
        self._pinged_client = False

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
        self._hello_done = False
        self._pinged_client = False
        self.acks_received = 0
        return True

    async def start_notify(self, char: Any, callback: Callable[[Any, bytearray], None]) -> None:
        assert str(char) == DDM1_NOTIFY
        self._notify = callback  # the real cooler stays silent here

    async def stop_notify(self, char: Any) -> None:
        self._notify = None

    async def write_gatt_char(self, char: Any, data: Any, response: bool | None = None) -> None:
        assert str(char) == DDM1_WRITE
        frame = bytes(data)
        self.writes.append(frame)
        action = frame[0]
        if action == 0x02:  # PING from the client
            self._emit(b"\x04")
        elif action == 0x03:  # HELLO
            self._hello_done = True
            self._emit(b"\x04")
            # session up: the cooler starts its 2 s keepalive; first one right away
            self._emit(b"\x02")
            self._pinged_client = True
        elif action == 0x04:  # ACK (for our PING or PUBLISH)
            self.acks_received += 1
        elif action == 0x01 and len(frame) == 5:  # SUBSCRIBE
            self._emit(b"\x04")
            if self._pinged_client and self.acks_received == 0:
                return  # real cooler: silent until its PINGs are ACKed
            topic = frame[1:5]
            if topic in self.state:
                self._emit(b"\x00" + topic + self.state[topic])
        elif action == 0x00 and len(frame) >= 5:  # PUBLISH = write: ACK + apply, no echo
            self.state[frame[1:5]] = frame[5:]
            self._emit(b"\x04")

    # -- test helpers ---------------------------------------------------------------

    def publish(self, group: str, name: str, value: Any) -> None:
        """Device-initiated value change."""
        p = _T.get(group, name)
        self.state[p.topic] = p.encode(value)
        self._emit(b"\x00" + p.topic + self.state[p.topic])

    def ping(self) -> None:
        """Keepalive PING from the cooler."""
        self._emit(b"\x02")

    def drop_link(self) -> None:
        """Simulate the cooler going out of range."""
        self._connected = False
        self._notify = None
        if self.disconnected_callback is not None:
            self.disconnected_callback(self)

    def _emit(self, frame: bytes) -> None:
        if self._notify is not None:
            self._notify(None, bytearray(frame))
