"""Sans-I/O state machine: handshake, auto-ACK, decode, unknown frames."""

from __future__ import annotations

import pytest

from pyddm import DDM1Action, DDM2Action, Protocol
from pyddm.session import (
    DDM1_HANDSHAKE,
    DDM1_HANDSHAKE_WITH_PING,
    DDM2_HANDSHAKE_LIKE_DDM1,
    DDM2_HANDSHAKE_NONE,
    Control,
    HandshakeConfig,
    HandshakeStep,
    ProtocolMachine,
    Ready,
    Send,
    SessionError,
    SessionState,
    Unknown,
    Update,
    default_handshake,
)

ACK = b"\x04"
HELLO = b"\x03"
PING = b"\x02"


def test_default_handshakes() -> None:
    assert default_handshake(Protocol.DDM1) is DDM1_HANDSHAKE
    assert default_handshake(Protocol.DDM2) is DDM2_HANDSHAKE_NONE
    assert DDM1_HANDSHAKE.ack_publishes is True
    assert DDM2_HANDSHAKE_NONE.ack_publishes is False


def test_ddm1_handshake_ack_hello_ack() -> None:
    m = ProtocolMachine(Protocol.DDM1)
    assert m.state is SessionState.IDLE
    assert m.start() == []
    assert m.state is SessionState.HANDSHAKE
    # device → 04 ; we → 03
    assert m.receive(ACK) == [Send(HELLO)]
    assert m.state is SessionState.HANDSHAKE
    assert not m.ready
    # device → 04 ; ready
    assert m.receive(ACK) == [Ready()]
    assert m.ready


def test_ddm1_handshake_with_ping_variant() -> None:
    m = ProtocolMachine(Protocol.DDM1, handshake=DDM1_HANDSHAKE_WITH_PING)
    assert m.start() == [Send(PING)]
    assert m.receive(ACK) == [Send(HELLO)]
    assert m.receive(ACK) == [Ready()]


def test_ddm2_default_has_no_handshake() -> None:
    m = ProtocolMachine(Protocol.DDM2)
    assert m.start() == [Ready()]
    assert m.ready


def test_ddm2_optional_hello_handshake() -> None:
    m = ProtocolMachine(Protocol.DDM2, handshake=DDM2_HANDSHAKE_LIKE_DDM1)
    assert m.start() == []
    assert m.receive(ACK) == [Send(HELLO)]
    assert m.receive(ACK) == [Ready()]


def test_custom_handshake_steps() -> None:
    cfg = HandshakeConfig(
        steps=(HandshakeStep(expect=DDM1Action.NOP, send=b"\x02"),), ack_publishes=False
    )
    m = ProtocolMachine(Protocol.DDM1, handshake=cfg)
    m.start()
    assert m.receive(b"\x06") == [Send(b"\x02"), Ready()]


def test_unexpected_control_during_handshake_does_not_advance() -> None:
    m = ProtocolMachine(Protocol.DDM1)
    m.start()
    assert m.receive(b"\x05") == [Control(DDM1Action.NAK)]
    assert m.state is SessionState.HANDSHAKE
    assert m.receive(ACK) == [Send(HELLO)]


def test_publish_during_handshake_is_decoded_and_acked() -> None:
    m = ProtocolMachine(Protocol.DDM1)
    m.start()
    events = m.receive(bytes([0x00, 0x00, 0x08, 0x01, 0x01, 0x01]))
    assert isinstance(events[0], Update)
    assert events[0].name == "compartment.c0DoorOpen"
    assert events[0].value is True
    assert events[1] == Send(ACK)
    assert m.state is SessionState.HANDSHAKE


def _ready_ddm1() -> ProtocolMachine:
    m = ProtocolMachine(Protocol.DDM1)
    m.start()
    m.receive(ACK)
    m.receive(ACK)
    return m


def test_publish_decoded_and_acked() -> None:
    m = _ready_ddm1()
    events = m.receive(bytes([0x00, 0x00, 0x01, 0x03, 0x01, 0x7E, 0x00]))
    update, ack = events
    assert isinstance(update, Update)
    assert update.name == "power.batteryVoltageLevel"
    assert update.value == 12.6
    assert update.raw == bytes([0x7E, 0x00])
    assert update.error is None
    assert ack == Send(ACK)
    assert m.values[bytes([0x00, 0x01, 0x03, 0x01])] is update
    assert m.counters.published == 1
    assert m.counters.acks_sent == 1


def test_publish_unknown_topic_still_acked() -> None:
    m = _ready_ddm1()
    events = m.receive(bytes([0x00, 0xEE, 0xEE, 0xEE, 0xEE, 0x01]))
    update = events[0]
    assert isinstance(update, Update)
    assert update.parameter is None
    assert update.error == "unknown topic"
    assert update.name == "EE EE EE EE"
    assert events[1] == Send(ACK)


def test_publish_with_bad_length_reports_error_not_exception() -> None:
    m = _ready_ddm1()
    events = m.receive(bytes([0x00, 0x00, 0x01, 0x01, 0x01, 0x0A]))  # 1 byte for int16
    update = events[0]
    assert isinstance(update, Update)
    assert update.parameter is not None
    assert update.value is None
    assert update.error is not None
    assert "expects 2 byte" in update.error


def test_unknown_frames_surface_as_unknown() -> None:
    m = _ready_ddm1()
    [event] = m.receive(bytes([0x7F, 0x01]))
    assert isinstance(event, Unknown)
    assert "7F 01" in event.reason
    [event] = m.receive(bytes([0x01, 0x00, 0x00, 0x01, 0x01]))  # SUBSCRIBE from device
    assert isinstance(event, Unknown)
    assert "SUBSCRIBE" in event.reason
    assert m.counters.unknown == 2


def test_control_frames_when_ready() -> None:
    m = _ready_ddm1()
    assert m.receive(ACK) == [Control(DDM1Action.ACK)]
    assert m.receive(b"\x02") == [Control(DDM1Action.PING)]


def test_receive_before_start_or_after_close() -> None:
    m = ProtocolMachine(Protocol.DDM1)
    [event] = m.receive(ACK)
    assert isinstance(event, Unknown)
    m.start()
    m.close()
    [event] = m.receive(ACK)
    assert isinstance(event, Unknown)
    with pytest.raises(SessionError):
        m.start()


def test_frame_builders_ddm1() -> None:
    m = _ready_ddm1()
    topic = bytes([0x00, 0x02, 0x01, 0x01])
    assert m.subscribe_frame(topic) == bytes([0x01, 0x00, 0x02, 0x01, 0x01])
    # DDM1 writes with PUBLISH
    assert m.write_frame(topic, -18.0) == bytes([0x00, 0x00, 0x02, 0x01, 0x01, 0x4C, 0xFF])
    assert m.raw_write_frame(topic, b"\x4c\xff") == bytes(
        [0x00, 0x00, 0x02, 0x01, 0x01, 0x4C, 0xFF]
    )
    assert m.ping_frame() == PING
    with pytest.raises(KeyError):
        m.write_frame(b"\xee\xee\xee\xee", 1)


def test_frame_builders_ddm2() -> None:
    m = ProtocolMachine(Protocol.DDM2)
    m.start()
    topic = m.ddm2_table.topic_for("ac", "ttemp")
    assert m.subscribe_frame(topic) == bytes([0x12, 0x04, 0x00, 0x02, 0x01])
    # DDM2 writes with SET, int32 LE x1000
    assert m.write_frame(topic, 21.5) == bytes(
        [0x11, 0x04, 0x00, 0x02, 0x01, 0xFC, 0x53, 0x00, 0x00]
    )
    with pytest.raises(SessionError):
        m.ping_frame()


def test_ddm2_publish_decoded_with_instance_and_no_ack() -> None:
    m = ProtocolMachine(Protocol.DDM2)
    m.start()
    events = m.receive(bytes([0x10, 0x0A, 0x03, 0x02, 0x01, 0xFC, 0x53, 0x00, 0x00]))
    assert len(events) == 1
    update = events[0]
    assert isinstance(update, Update)
    assert update.name == "ac.itemp"
    assert update.instance == 3
    assert update.value == 21.5


def test_ddm2_with_ack_handshake_acks_publishes() -> None:
    m = ProtocolMachine(Protocol.DDM2, handshake=DDM2_HANDSHAKE_LIKE_DDM1)
    m.start()
    m.receive(ACK)
    m.receive(ACK)
    events = m.receive(bytes([0x10, 0x00, 0x00, 0x02, 0x01, 0x01, 0x00, 0x00, 0x00]))
    assert events[-1] == Send(bytes([DDM2Action.ACK]))
