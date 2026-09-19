"""Frame format shared by DDM1 and DDM2.

Raw GATT payload::

    byte 0     action
    byte 1..4  topic (4 bytes)
    byte 5..n  value (type dependent, may be empty)

Control frames are a single action byte with no topic. There is no length field and no
CRC. See ``docs/dometic-power-protokoll.md`` section 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from .const import TOPIC_LENGTH, Protocol

__all__ = [
    "DDM1Action",
    "DDM2Action",
    "Frame",
    "FrameError",
    "action_name",
    "hexdump",
]


class DDM1Action(IntEnum):
    """Action byte for DDM1 (CFX3). DDM1 writes values with PUBLISH; there is no SET."""

    PUBLISH = 0x00
    SUBSCRIBE = 0x01
    PING = 0x02
    HELLO = 0x03
    ACK = 0x04
    NAK = 0x05
    NOP = 0x06


class DDM2Action(IntEnum):
    """Action byte for DDM2 (FreshJet FJZ/FJX, CFX5, gateways, ...)."""

    HELLO = 0x03
    ACK = 0x04
    NAK = 0x05
    NOP = 0x06
    PUBLISH = 0x10
    SET = 0x11
    SUBSCRIBE = 0x12
    # Only used for jumbo transfers (TLS certificates). Not supported here.
    FRAGMENT = 0x14


# Actions that carry a topic (and optionally a value).
_DATA_ACTIONS: dict[Protocol, frozenset[int]] = {
    Protocol.DDM1: frozenset({DDM1Action.PUBLISH, DDM1Action.SUBSCRIBE}),
    Protocol.DDM2: frozenset({DDM2Action.PUBLISH, DDM2Action.SET, DDM2Action.SUBSCRIBE}),
}
# Actions that are a bare single byte.
_CONTROL_ACTIONS: dict[Protocol, frozenset[int]] = {
    Protocol.DDM1: frozenset(
        {DDM1Action.PING, DDM1Action.HELLO, DDM1Action.ACK, DDM1Action.NAK, DDM1Action.NOP}
    ),
    Protocol.DDM2: frozenset({DDM2Action.HELLO, DDM2Action.ACK, DDM2Action.NAK, DDM2Action.NOP}),
}
_ACTION_ENUMS: dict[Protocol, type[IntEnum]] = {
    Protocol.DDM1: DDM1Action,
    Protocol.DDM2: DDM2Action,
}


class FrameError(ValueError):
    """Raised when bytes cannot be interpreted as a frame of the given protocol."""


def hexdump(data: bytes) -> str:
    """Render bytes as space separated upper-case hex, e.g. ``"00 01 01 01 0A FF"``."""
    return data.hex(" ").upper()


def action_name(protocol: Protocol, action: int) -> str:
    """Human readable action name, or ``UNKNOWN(0x..)`` for undocumented bytes."""
    try:
        return _ACTION_ENUMS[protocol](action).name
    except ValueError:
        return f"UNKNOWN(0x{action:02X})"


def is_data_action(protocol: Protocol, action: int) -> bool:
    """True if ``action`` carries a topic in ``protocol``."""
    return action in _DATA_ACTIONS[protocol]


def is_control_action(protocol: Protocol, action: int) -> bool:
    """True if ``action`` is a bare single-byte control frame in ``protocol``."""
    return action in _CONTROL_ACTIONS[protocol]


@dataclass(frozen=True, slots=True)
class Frame:
    """One protocol frame. ``topic is None`` marks a single-byte control frame."""

    action: int
    topic: bytes | None = None
    value: bytes = b""

    def __post_init__(self) -> None:
        if not 0 <= self.action <= 0xFF:
            raise FrameError(f"action {self.action!r} does not fit in one byte")
        if self.topic is None:
            if self.value:
                raise FrameError("a control frame cannot carry a value")
        elif len(self.topic) != TOPIC_LENGTH:
            raise FrameError(f"topic must be {TOPIC_LENGTH} bytes, got {len(self.topic)}")

    @property
    def is_control(self) -> bool:
        """True for single-byte control frames (ACK, HELLO, ...)."""
        return self.topic is None

    @classmethod
    def control(cls, action: int) -> Frame:
        """Build a control frame."""
        return cls(int(action))

    @classmethod
    def data(cls, action: int, topic: bytes, value: bytes = b"") -> Frame:
        """Build a data frame."""
        return cls(int(action), bytes(topic), bytes(value))

    def encode(self) -> bytes:
        """Serialize to the raw GATT payload."""
        if self.topic is None:
            return bytes((self.action,))
        return bytes((self.action,)) + self.topic + self.value

    @classmethod
    def decode(cls, data: bytes, protocol: Protocol) -> Frame:
        """Parse a raw GATT payload.

        Raises :class:`FrameError` for empty input, unknown actions, data frames shorter
        than five bytes, control frames with trailing bytes and DDM2 FRAGMENT frames.
        Callers should log the hex dump of the rejected bytes and carry on.
        """
        data = bytes(data)
        if not data:
            raise FrameError("empty frame")
        action = data[0]
        if is_data_action(protocol, action):
            if len(data) < 1 + TOPIC_LENGTH:
                raise FrameError(
                    f"{action_name(protocol, action)} frame too short: {hexdump(data)}"
                )
            return cls(action, data[1 : 1 + TOPIC_LENGTH], data[1 + TOPIC_LENGTH :])
        if is_control_action(protocol, action):
            if len(data) != 1:
                raise FrameError(
                    f"{action_name(protocol, action)} control frame with trailing bytes: "
                    f"{hexdump(data)}"
                )
            return cls(action)
        if protocol is Protocol.DDM2 and action == DDM2Action.FRAGMENT:
            raise FrameError(f"DDM2 FRAGMENT frames are not supported: {hexdump(data)}")
        raise FrameError(f"unknown {protocol.value} action 0x{action:02X}: {hexdump(data)}")

    def describe(self, protocol: Protocol) -> str:
        """Short human readable form for logs, e.g. ``PUBLISH 00 01 01 01 = 0A FF``."""
        name = action_name(protocol, self.action)
        if self.topic is None:
            return name
        text = f"{name} {hexdump(self.topic)}"
        if self.value:
            text += f" = {hexdump(self.value)}"
        return text
