"""Async Session driving a fake transport."""

from __future__ import annotations

import asyncio
import logging

import pytest

from pyddm import Protocol, Session, SessionError, Update
from pyddm.session import DDM1_HANDSHAKE_WITH_PING
from pyddm.transport.base import TransportError

from .fakes import FakeTransport

ACK = b"\x04"


async def _complete_ddm1_handshake(transport: FakeTransport) -> None:
    await asyncio.sleep(0)  # let Session.start() register its notify callback
    transport.notify(ACK)
    await transport.wait_for_writes(1)  # HELLO
    transport.notify(ACK)


async def test_start_runs_handshake_and_becomes_ready() -> None:
    transport = FakeTransport()
    session = Session(Protocol.DDM1, transport)
    start = asyncio.create_task(session.start(ready_timeout=1.0))
    await asyncio.sleep(0)
    assert transport.connect_calls == 1
    assert not session.ready
    await _complete_ddm1_handshake(transport)
    await start
    assert session.ready
    assert transport.written == [b"\x03"]
    await session.close()
    assert transport.disconnect_calls == 1


async def test_ack_arriving_during_connect_is_not_lost() -> None:
    """A CFX3 may ACK as soon as notifications are enabled, before connect() returns."""

    class EagerTransport(FakeTransport):
        async def connect(self) -> None:
            await super().connect()
            self.notify(ACK)  # device speaks before we return from connect()

    transport = EagerTransport()
    session = Session(Protocol.DDM1, transport)
    start = asyncio.create_task(session.start(ready_timeout=1.0))
    await transport.wait_for_writes(1)
    assert transport.written == [b"\x03"]  # HELLO was queued and flushed
    transport.notify(ACK)
    await start
    assert session.ready
    await session.close()


async def test_connect_failure_leaves_session_restartable_state_closed() -> None:
    transport = FakeTransport()

    async def failing_connect() -> None:
        raise TransportError("no route")

    transport.connect = failing_connect  # type: ignore[method-assign]
    session = Session(Protocol.DDM1, transport)
    with pytest.raises(TransportError):
        await session.start()
    transport.notify(ACK)  # ignored, no callback registered any more
    assert not session.ready


async def test_start_times_out_without_device_ack() -> None:
    transport = FakeTransport()
    session = Session(Protocol.DDM1, transport)
    with pytest.raises(TimeoutError):
        await session.start(ready_timeout=0.05)
    await session.close()


async def test_ping_variant_writes_ping_first() -> None:
    transport = FakeTransport()
    session = Session(Protocol.DDM1, transport, handshake=DDM1_HANDSHAKE_WITH_PING)
    await session.start(ready_timeout=None)
    await transport.wait_for_writes(1)
    assert transport.written == [b"\x02"]
    await session.close()


async def test_subscribe_requires_ready() -> None:
    transport = FakeTransport()
    session = Session(Protocol.DDM1, transport)
    await session.start(ready_timeout=None)
    with pytest.raises(SessionError, match="not ready"):
        await session.subscribe(bytes([0x01, 0x00, 0x00, 0x81]))
    await session.close()


async def test_publish_updates_callback_and_is_acked() -> None:
    transport = FakeTransport()
    updates: list[Update] = []
    ready_calls: list[bool] = []
    session = Session(
        Protocol.DDM1,
        transport,
        on_update=updates.append,
        on_ready=lambda: ready_calls.append(True),
    )
    start = asyncio.create_task(session.start(ready_timeout=1.0))
    await _complete_ddm1_handshake(transport)
    await start
    assert ready_calls == [True]

    transport.notify(bytes([0x00, 0x00, 0x01, 0x01, 0x01, 0x0A, 0xFF]))
    await transport.wait_for_writes(2)
    assert transport.written[1] == ACK
    assert len(updates) == 1
    assert updates[0].name == "compartment.c0MeasuredTemperature"
    assert updates[0].value == -24.6
    assert session.values[bytes([0x00, 0x01, 0x01, 0x01])].value == -24.6
    await session.close()


async def test_extra_listener_and_bad_listener_isolation() -> None:
    transport = FakeTransport()
    errors: list[Exception] = []
    seen: list[str] = []

    def bad(_update: Update) -> None:
        raise RuntimeError("boom")

    session = Session(Protocol.DDM2, transport, on_update=bad, on_error=errors.append)
    remove = session.add_update_listener(lambda u: seen.append(u.name))
    await session.start(ready_timeout=1.0)  # DDM2: ready immediately
    transport.notify(bytes([0x10, 0x0A, 0x00, 0x02, 0x01, 0xFC, 0x53, 0x00, 0x00]))
    assert seen == ["ac.itemp"]
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    remove()
    transport.notify(bytes([0x10, 0x0A, 0x00, 0x02, 0x01, 0xFC, 0x53, 0x00, 0x00]))
    assert seen == ["ac.itemp"]
    # DDM2 default: no ACKs written
    await asyncio.sleep(0)
    assert transport.written == []
    await session.close()


async def test_write_encodes_via_table() -> None:
    transport = FakeTransport()
    session = Session(Protocol.DDM1, transport)
    start = asyncio.create_task(session.start(ready_timeout=1.0))
    await _complete_ddm1_handshake(transport)
    await start
    topic = bytes([0x00, 0x02, 0x01, 0x01])
    await session.write(topic, -18)
    await session.subscribe_many([bytes([0x00, 0x01, 0x01, 0x01]), bytes([0x00, 0x08, 0x01, 0x01])])
    await session.write_raw(topic, b"\x28\x00")
    assert transport.written[1:] == [
        bytes([0x00, 0x00, 0x02, 0x01, 0x01, 0x4C, 0xFF]),
        bytes([0x01, 0x00, 0x01, 0x01, 0x01]),
        bytes([0x01, 0x00, 0x08, 0x01, 0x01]),
        bytes([0x00, 0x00, 0x02, 0x01, 0x01, 0x28, 0x00]),
    ]
    await session.close()


async def test_api_write_failure_propagates() -> None:
    transport = FakeTransport()
    session = Session(Protocol.DDM2, transport)
    await session.start(ready_timeout=1.0)
    transport.fail_writes = True
    with pytest.raises(TransportError):
        await session.subscribe(bytes([0x0A, 0x00, 0x02, 0x01]))
    await session.close()


async def test_queued_write_failure_reported_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    transport = FakeTransport(fail_writes=True)
    errors: list[Exception] = []
    session = Session(Protocol.DDM1, transport, on_error=errors.append)
    await session.start(ready_timeout=None)
    with caplog.at_level(logging.WARNING, logger="pyddm.session"):
        transport.notify(ACK)  # machine queues HELLO, write fails
        for _ in range(5):
            await asyncio.sleep(0)
    assert len(errors) == 1
    assert isinstance(errors[0], TransportError)
    assert "queued write failed" in caplog.text
    await session.close()


async def test_unknown_frame_is_logged_hexdumped(caplog: pytest.LogCaptureFixture) -> None:
    transport = FakeTransport()
    session = Session(Protocol.DDM2, transport)
    await session.start(ready_timeout=1.0)
    with caplog.at_level(logging.WARNING, logger="pyddm.session"):
        transport.notify(bytes([0x7F, 0xAB, 0xCD]))
    assert "7F AB CD" in caplog.text
    assert "ignoring unknown frame" in caplog.text
    await session.close()


async def test_closed_session_rejects_operations() -> None:
    transport = FakeTransport()
    session = Session(Protocol.DDM2, transport)
    await session.start(ready_timeout=1.0)
    await session.close()
    with pytest.raises(SessionError):
        await session.subscribe(b"\x00\x00\x00\x00")
    with pytest.raises(SessionError):
        await session.start()
    # notifications after close are ignored without error
    transport.notify(bytes([0x10, 0x0A, 0x00, 0x02, 0x01, 0xFC, 0x53, 0x00, 0x00]))
