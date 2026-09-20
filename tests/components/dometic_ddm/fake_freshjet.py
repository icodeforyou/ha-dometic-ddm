"""A FreshJet FJZ7 simulator behind a bleak-like client, behaving like the real unit did on
2026-09-20 (docs/captures/2026-09-20_fjz7_*):

* No handshake. SUBSCRIBE (12 + topic) is answered with a PUBLISH (10 + topic + int32/str).
* SET (11 + topic + value) is applied and echoed as a PUBLISH; Turbo mode (md 5) is refused
  and the current mode is re-published instead.
* Values are the ones captured (AC in Fan mode, 26 °C inside, target 22 °C, ...).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyddm.ddm2 import default_table

DDM2_NOTIFY = "537a0402-0995-481f-926c-1604e23fd515"
DDM2_WRITE = "537a0401-0995-481f-926c-1604e23fd515"

_T = default_table()


def _initial_state() -> dict[bytes, bytes]:
    def enc(cls: str, name: str, value: Any) -> tuple[bytes, bytes]:
        p = _T.get(cls, name)
        return p.topic(0), p.encode(value) if p.in_type.value != "-" else _raw(p, value)

    def _raw(p: Any, value: Any) -> bytes:
        # read-only parameters have no `in` codec; build the bytes with the out type
        if p.out_type.value == "STRING":
            return str(value).encode()
        from pyddm.ddm2 import DDM2Parameter, DDM2Type, encode  # noqa: PLC0415

        tmp = DDM2Parameter(
            class_name=p.class_name,
            name=p.name,
            param_id=p.param_id,
            class_id=p.class_id,
            group_id=p.group_id,
            in_type=DDM2Type(p.out_type.value),
            out_type=p.out_type,
            unit=p.unit,
            factor=p.factor,
            writable=True,
            enum=p.enum,
            struct=p.struct,
        )
        return encode(tmp, value)

    return dict(
        [
            enc("gw", "avl", 1),
            enc("gw", "ver", "2.2.1"),
            enc("gw", "sku", "9600051000"),
            enc("ac", "avl", 1),
            enc("ac", "mdl", 18),
            enc("ac", "ver", "2.2.0"),
            enc("ac", "on", 1),
            enc("ac", "md", 2),
            enc("ac", "ttemp", 22.0),
            enc("ac", "itemp", 26.0),
            enc("ac", "fspd", 2),
            enc("ac", "fs", 0),
            enc("ac", "fmd", 0),
            enc("ac", "lgt", 0),
            enc("ac", "dmr", 100),
            enc("ac", "sleep", 0),
            enc("ac", "pwr", 0.0),
            enc("ac", "curr", 0.6),
            enc("ac", "currlim", 7),
            enc("ac", "status", {"error": []}),
            enc("ac", "actext", 0x10),
        ]
    )


class FakeFreshJetClient:
    """Just enough of bleak's BleakClient for BleTransport, plus FreshJet behaviour."""

    def __init__(self, address: str) -> None:
        self.address = address
        self.state: dict[bytes, bytes] = _initial_state()
        self.writes: list[bytes] = []
        self.mtu_size = 23
        self.pair_requested = False
        self.disconnected_callback: Callable[[Any], None] | None = None
        self._connected = False
        self._notify: Callable[[Any, bytearray], None] | None = None

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
        assert str(char) == DDM2_NOTIFY
        self._notify = callback

    async def stop_notify(self, char: Any) -> None:
        self._notify = None

    async def write_gatt_char(self, char: Any, data: Any, response: bool | None = None) -> None:
        assert str(char) == DDM2_WRITE
        frame = bytes(data)
        self.writes.append(frame)
        action, topic, value = frame[0], frame[1:5], frame[5:]
        if action == 0x12:  # SUBSCRIBE
            if topic in self.state:
                self._emit(b"\x10" + topic + self.state[topic])
        elif action == 0x11:  # SET
            if topic == _T.topic_for("ac", "md") and value == (5).to_bytes(4, "little"):
                self._emit(b"\x10" + topic + self.state[topic])  # Turbo refused
                return
            self.state[topic] = value
            self._emit(b"\x10" + topic + value)

    def publish(self, cls: str, name: str, value: Any) -> None:
        """Device-initiated change (remote control, compressor start, ...)."""
        p = _T.get(cls, name)
        topic = p.topic(0)
        from pyddm.ddm2 import DDM2Parameter, DDM2Type, encode  # noqa: PLC0415

        tmp = DDM2Parameter(
            class_name=p.class_name,
            name=p.name,
            param_id=p.param_id,
            class_id=p.class_id,
            group_id=p.group_id,
            in_type=DDM2Type(p.out_type.value),
            out_type=p.out_type,
            unit=p.unit,
            factor=p.factor,
            writable=True,
            enum=p.enum,
            struct=p.struct,
        )
        self.state[topic] = encode(tmp, value)
        self._emit(b"\x10" + topic + self.state[topic])

    def drop_link(self) -> None:
        self._connected = False
        self._notify = None
        if self.disconnected_callback is not None:
            self.disconnected_callback(self)

    def _emit(self, frame: bytes) -> None:
        if self._notify is not None:
            self._notify(None, bytearray(frame))
