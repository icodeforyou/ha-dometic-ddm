"""Frame encode/decode, byte exact."""

from __future__ import annotations

import pytest

from pyddm import DDM1Action, DDM2Action, Frame, FrameError, Protocol
from pyddm.frame import action_name, hexdump, is_control_action, is_data_action


def test_action_values_match_docs() -> None:
    assert [a.value for a in DDM1Action] == [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06]
    assert DDM2Action.PUBLISH == 0x10
    assert DDM2Action.SET == 0x11
    assert DDM2Action.SUBSCRIBE == 0x12
    assert DDM2Action.HELLO == 0x03
    assert DDM2Action.ACK == 0x04
    assert DDM2Action.NAK == 0x05
    assert DDM2Action.NOP == 0x06
    assert DDM2Action.FRAGMENT == 0x14


def test_control_frame_is_single_byte() -> None:
    assert Frame.control(DDM1Action.ACK).encode() == b"\x04"
    assert Frame.control(DDM1Action.HELLO).encode() == b"\x03"
    assert Frame.decode(b"\x04", Protocol.DDM1) == Frame(0x04)
    assert Frame.decode(b"\x04", Protocol.DDM1).is_control


def test_ddm1_subscribe_frame_bytes() -> None:
    frame = Frame.data(DDM1Action.SUBSCRIBE, bytes([0x01, 0x00, 0x00, 0x81]))
    assert frame.encode() == bytes([0x01, 0x01, 0x00, 0x00, 0x81])


def test_ddm1_publish_round_trip() -> None:
    raw = bytes([0x00, 0x00, 0x01, 0x01, 0x01, 0x0A, 0xFF])
    frame = Frame.decode(raw, Protocol.DDM1)
    assert frame.action == DDM1Action.PUBLISH
    assert frame.topic == bytes([0x00, 0x01, 0x01, 0x01])
    assert frame.value == bytes([0x0A, 0xFF])
    assert frame.encode() == raw


def test_ddm2_set_round_trip() -> None:
    raw = bytes([0x11, 0x04, 0x00, 0x02, 0x01, 0xFC, 0x53, 0x00, 0x00])
    frame = Frame.decode(raw, Protocol.DDM2)
    assert frame.action == DDM2Action.SET
    assert frame.topic == bytes([0x04, 0x00, 0x02, 0x01])
    assert frame.value == bytes([0xFC, 0x53, 0x00, 0x00])
    assert frame.encode() == raw


def test_ddm2_subscribe_without_value() -> None:
    raw = bytes([0x12, 0x0A, 0x00, 0x02, 0x01])
    frame = Frame.decode(raw, Protocol.DDM2)
    assert frame == Frame(0x12, bytes([0x0A, 0x00, 0x02, 0x01]), b"")
    assert frame.encode() == raw


def test_empty_value_publish_is_valid() -> None:
    frame = Frame.decode(bytes([0x00, 0x00, 0x04, 0x03, 0x01]), Protocol.DDM1)
    assert frame.value == b""


@pytest.mark.parametrize(
    ("data", "protocol"),
    [
        (b"", Protocol.DDM1),
        (bytes([0x00, 0x01, 0x02]), Protocol.DDM1),  # PUBLISH too short
        (bytes([0x10, 0x01]), Protocol.DDM2),  # PUBLISH too short
        (bytes([0x04, 0x00]), Protocol.DDM1),  # ACK with trailing byte
        (bytes([0x10, 0, 0, 0, 0]), Protocol.DDM1),  # 0x10 is not a DDM1 action
        (bytes([0x02]), Protocol.DDM2),  # PING does not exist in DDM2
        (bytes([0x14, 0, 0, 0, 0, 1]), Protocol.DDM2),  # FRAGMENT unsupported
        (bytes([0x7F]), Protocol.DDM1),
    ],
)
def test_decode_rejects_unknown_or_malformed(data: bytes, protocol: Protocol) -> None:
    with pytest.raises(FrameError):
        Frame.decode(data, protocol)


def test_frame_error_contains_hexdump() -> None:
    with pytest.raises(FrameError, match="7F 01 02"):
        Frame.decode(bytes([0x7F, 0x01, 0x02]), Protocol.DDM1)


def test_frame_validation() -> None:
    with pytest.raises(FrameError):
        Frame(0x00, b"\x00\x01")  # topic must be 4 bytes
    with pytest.raises(FrameError):
        Frame(0x04, None, b"\x01")  # control frame cannot carry a value
    with pytest.raises(FrameError):
        Frame(0x100)


def test_helpers() -> None:
    assert hexdump(bytes([0x00, 0x0A, 0xFF])) == "00 0A FF"
    assert action_name(Protocol.DDM1, 0x03) == "HELLO"
    assert action_name(Protocol.DDM2, 0x12) == "SUBSCRIBE"
    assert action_name(Protocol.DDM2, 0x99) == "UNKNOWN(0x99)"
    assert is_data_action(Protocol.DDM1, 0x00)
    assert not is_control_action(Protocol.DDM1, 0x00)
    assert is_control_action(Protocol.DDM2, 0x04)
    assert not is_data_action(Protocol.DDM2, 0x04)
    assert Frame.decode(b"\x00\x00\x01\x01\x01\x0a\xff", Protocol.DDM1).describe(Protocol.DDM1) == (
        "PUBLISH 00 01 01 01 = 0A FF"
    )
    assert Frame.control(0x04).describe(Protocol.DDM1) == "ACK"
