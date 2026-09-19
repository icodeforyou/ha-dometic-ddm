"""Protocol session: handshake state machine, auto-ACK, subscribe/write, decoded updates.

The core is :class:`ProtocolMachine`, a *sans-I/O* state machine: feed it received bytes,
get back a list of events (frames to send, decoded updates, ...). It has no knowledge of
asyncio or transports, so it can be tested byte-for-byte. :class:`Session` wraps a machine
and a :class:`~pyddm.transport.Transport` for real use.

DDM1 handshake (from the app's ``reportDDM1Data``; needs verification on a CFX3)::

    device  →  04 (ACK)           after notifications are enabled
    us      →  03 (HELLO)
    device  →  04 (ACK)           session ready, send SUBSCRIBEs
    device  →  00 tt tt tt tt vv  PUBLISH ...
    us      →  04 (ACK)           for every PUBLISH received

Prior art (philippe-a11y) opens with PING (``02``) and gets the same ACK/HELLO/ACK
sequence; :data:`DDM1_HANDSHAKE_WITH_PING` models that variant.

DDM2 handshake is **unverified** (open question 4 in CLAUDE.md). The default here is
"no handshake, no per-PUBLISH ACK" because that is what the hardware-verified CFX5
implementation does. :data:`DDM2_HANDSHAKE_LIKE_DDM1` models the docs' assumption.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
from dataclasses import dataclass, field, replace
from enum import Enum
import logging
from typing import Any

from . import ddm1, ddm2
from .const import Protocol
from .frame import DDM1Action, DDM2Action, Frame, FrameError, action_name, hexdump
from .transport.base import Transport, TransportError

__all__ = [
    "DDM1_HANDSHAKE",
    "DDM1_HANDSHAKE_WITH_PING",
    "DDM2_HANDSHAKE_LIKE_DDM1",
    "DDM2_HANDSHAKE_NONE",
    "Control",
    "Event",
    "HandshakeConfig",
    "HandshakeStep",
    "ProtocolMachine",
    "Ready",
    "Send",
    "Session",
    "SessionError",
    "SessionState",
    "Unknown",
    "Update",
    "default_handshake",
]

_LOGGER = logging.getLogger(__name__)


class SessionError(Exception):
    """Wrong state for the requested operation."""


class SessionState(Enum):
    """Life cycle of a :class:`ProtocolMachine`."""

    IDLE = "idle"
    HANDSHAKE = "handshake"
    READY = "ready"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class HandshakeStep:
    """Wait for control action ``expect`` from the device, then send ``send`` (if any)."""

    expect: int
    send: bytes | None = None


@dataclass(frozen=True, slots=True)
class HandshakeConfig:
    """Configurable handshake so unverified variants can be swapped without code changes."""

    steps: tuple[HandshakeStep, ...]
    ack_publishes: bool
    """Answer every incoming PUBLISH with a single ACK byte."""
    initial: tuple[bytes, ...] = ()
    """Frames sent immediately at :meth:`ProtocolMachine.start` (e.g. a PING nudge)."""


DDM1_HANDSHAKE = HandshakeConfig(
    steps=(
        HandshakeStep(expect=DDM1Action.ACK, send=Frame.control(DDM1Action.HELLO).encode()),
        HandshakeStep(expect=DDM1Action.ACK),
    ),
    ack_publishes=True,
)
DDM1_HANDSHAKE_WITH_PING = replace(
    DDM1_HANDSHAKE, initial=(Frame.control(DDM1Action.PING).encode(),)
)
DDM2_HANDSHAKE_NONE = HandshakeConfig(steps=(), ack_publishes=False)
DDM2_HANDSHAKE_LIKE_DDM1 = HandshakeConfig(
    steps=(
        HandshakeStep(expect=DDM2Action.ACK, send=Frame.control(DDM2Action.HELLO).encode()),
        HandshakeStep(expect=DDM2Action.ACK),
    ),
    ack_publishes=True,
)


def default_handshake(protocol: Protocol) -> HandshakeConfig:
    """Handshake used unless the caller overrides it."""
    return DDM1_HANDSHAKE if protocol is Protocol.DDM1 else DDM2_HANDSHAKE_NONE


@dataclass(frozen=True, slots=True)
class Send:
    """The machine wants these bytes written to the device."""

    data: bytes


@dataclass(frozen=True, slots=True)
class Ready:
    """Handshake complete; subscriptions may be sent."""


@dataclass(frozen=True, slots=True)
class Control:
    """A control frame received while READY (device ACK/NAK/NOP/PING)."""

    action: int


@dataclass(frozen=True, slots=True)
class Unknown:
    """Bytes we could not interpret. Logged hex-dumped by :class:`Session`; never acted on."""

    data: bytes
    reason: str


@dataclass(frozen=True, slots=True)
class Update:
    """A decoded (or undecodable-but-known-topic) PUBLISH from the device."""

    topic: bytes
    raw: bytes
    parameter: ddm1.DDM1Parameter | ddm2.DDM2Parameter | None = None
    instance: int | None = None
    value: Any = None
    error: str | None = None
    """Set when the topic is known but the value failed to decode."""

    @property
    def name(self) -> str:
        """``group.name`` / ``class.param`` or the hex topic when unknown."""
        if self.parameter is None:
            return hexdump(self.topic)
        return self.parameter.qualified_name


type Event = Send | Ready | Control | Unknown | Update


@dataclass
class _MachineCounters:
    received: int = 0
    published: int = 0
    unknown: int = 0
    acks_sent: int = 0


class ProtocolMachine:
    """Sans-I/O protocol state machine for one device connection."""

    def __init__(
        self,
        protocol: Protocol,
        *,
        handshake: HandshakeConfig | None = None,
        ddm1_table: ddm1.DDM1Table | None = None,
        ddm2_table: ddm2.DDM2Table | None = None,
    ) -> None:
        self.protocol = protocol
        self.handshake = handshake if handshake is not None else default_handshake(protocol)
        self._ddm1_table = ddm1_table
        self._ddm2_table = ddm2_table
        self.state = SessionState.IDLE
        self._step = 0
        self.values: dict[bytes, Update] = {}
        """Latest update per topic."""
        self.counters = _MachineCounters()

    # -- tables (lazy so importing the machine does not parse 470 kB of JSON) ----------

    @property
    def ddm1_table(self) -> ddm1.DDM1Table:
        if self._ddm1_table is None:
            self._ddm1_table = ddm1.default_table()
        return self._ddm1_table

    @property
    def ddm2_table(self) -> ddm2.DDM2Table:
        if self._ddm2_table is None:
            self._ddm2_table = ddm2.default_table()
        return self._ddm2_table

    # -- actions -------------------------------------------------------------------

    @property
    def _publish(self) -> int:
        return DDM1Action.PUBLISH if self.protocol is Protocol.DDM1 else DDM2Action.PUBLISH

    @property
    def _subscribe(self) -> int:
        return DDM1Action.SUBSCRIBE if self.protocol is Protocol.DDM1 else DDM2Action.SUBSCRIBE

    @property
    def _ack(self) -> int:
        return DDM1Action.ACK if self.protocol is Protocol.DDM1 else DDM2Action.ACK

    @property
    def ready(self) -> bool:
        """True once the handshake has completed."""
        return self.state is SessionState.READY

    # -- frame builders ------------------------------------------------------------

    def subscribe_frame(self, topic: bytes) -> bytes:
        """``[SUBSCRIBE, topic]``."""
        return Frame.data(self._subscribe, topic).encode()

    def write_frame(self, topic: bytes, value: Any) -> bytes:
        """Encode ``value`` with the table and wrap it in the protocol's write action.

        DDM1 writes with PUBLISH (there is no SET); DDM2 writes with SET.
        """
        topic = bytes(topic)
        if self.protocol is Protocol.DDM1:
            param1 = self.ddm1_table.lookup(topic)
            if param1 is None:
                raise KeyError(f"unknown DDM1 topic {hexdump(topic)}")
            return Frame.data(DDM1Action.PUBLISH, topic, param1.encode(value)).encode()
        found = self.ddm2_table.lookup(topic)
        if found is None:
            raise KeyError(f"unknown DDM2 topic {hexdump(topic)}")
        param2, _instance = found
        return Frame.data(DDM2Action.SET, topic, param2.encode(value)).encode()

    def raw_write_frame(self, topic: bytes, value: bytes) -> bytes:
        """Write pre-encoded bytes (for experiments; bypasses the table)."""
        action = DDM1Action.PUBLISH if self.protocol is Protocol.DDM1 else DDM2Action.SET
        return Frame.data(action, topic, value).encode()

    def ping_frame(self) -> bytes:
        """DDM1 PING. DDM2 has no PING in the app."""
        if self.protocol is not Protocol.DDM1:
            raise SessionError("DDM2 has no PING action")
        return Frame.control(DDM1Action.PING).encode()

    # -- state machine -------------------------------------------------------------

    def start(self) -> list[Event]:
        """Enter the handshake. Returns initial frames to send and possibly ``Ready``."""
        if self.state is not SessionState.IDLE:
            raise SessionError(f"cannot start in state {self.state.value}")
        events: list[Event] = [Send(data) for data in self.handshake.initial]
        self._step = 0
        if self.handshake.steps:
            self.state = SessionState.HANDSHAKE
        else:
            self.state = SessionState.READY
            events.append(Ready())
        return events

    def close(self) -> None:
        """Mark the machine closed; further input is ignored."""
        self.state = SessionState.CLOSED

    def receive(self, data: bytes) -> list[Event]:
        """Process one notification payload from the device."""
        data = bytes(data)
        self.counters.received += 1
        if self.state in (SessionState.IDLE, SessionState.CLOSED):
            self.counters.unknown += 1
            return [Unknown(data, f"received while {self.state.value}")]
        try:
            frame = Frame.decode(data, self.protocol)
        except FrameError as err:
            self.counters.unknown += 1
            return [Unknown(data, str(err))]

        if frame.action == self._publish and frame.topic is not None:
            return self._on_publish(frame)
        if frame.is_control:
            return self._on_control(frame)
        # SUBSCRIBE/SET coming *from* the device makes no sense; report, don't act.
        self.counters.unknown += 1
        return [Unknown(data, f"unexpected {action_name(self.protocol, frame.action)} from device")]

    def _on_control(self, frame: Frame) -> list[Event]:
        if self.state is SessionState.HANDSHAKE:
            step = self.handshake.steps[self._step]
            if frame.action != step.expect:
                # e.g. NAK during handshake: surface it, stay where we are.
                return [Control(frame.action)]
            events: list[Event] = []
            if step.send is not None:
                events.append(Send(step.send))
            self._step += 1
            if self._step >= len(self.handshake.steps):
                self.state = SessionState.READY
                events.append(Ready())
            return events
        return [Control(frame.action)]

    def _on_publish(self, frame: Frame) -> list[Event]:
        assert frame.topic is not None
        self.counters.published += 1
        update = self._decode_publish(frame.topic, frame.value)
        self.values[frame.topic] = update
        events: list[Event] = [update]
        if self.handshake.ack_publishes:
            self.counters.acks_sent += 1
            events.append(Send(Frame.control(self._ack).encode()))
        return events

    def _decode_publish(self, topic: bytes, raw: bytes) -> Update:
        if self.protocol is Protocol.DDM1:
            param1 = self.ddm1_table.lookup(topic)
            if param1 is None:
                return Update(topic=topic, raw=raw, error="unknown topic")
            try:
                return Update(topic=topic, raw=raw, parameter=param1, value=param1.decode(raw))
            except ddm1.CodecError as err:
                return Update(topic=topic, raw=raw, parameter=param1, error=str(err))
        found = self.ddm2_table.lookup(topic)
        if found is None:
            return Update(topic=topic, raw=raw, error="unknown topic")
        param2, instance = found
        try:
            return Update(
                topic=topic, raw=raw, parameter=param2, instance=instance, value=param2.decode(raw)
            )
        except ddm2.CodecError as err:
            return Update(topic=topic, raw=raw, parameter=param2, instance=instance, error=str(err))


type UpdateCallback = Callable[[Update], None]
type ErrorCallback = Callable[[Exception], None]


@dataclass
class _SessionCallbacks:
    on_update: UpdateCallback | None = None
    on_error: ErrorCallback | None = None
    on_ready: Callable[[], None] | None = None
    on_control: Callable[[int], None] | None = None
    extra: list[UpdateCallback] = field(default_factory=list)


class Session:
    """Asyncio driver around :class:`ProtocolMachine` and a :class:`Transport`.

    Outgoing frames generated by the machine (HELLO, ACKs) are queued and written in
    order by a background task, so a slow transport can never reorder the handshake.
    API writes (:meth:`subscribe`, :meth:`write`) go through the same lock and raise on
    transport failure so callers can report it.
    """

    def __init__(
        self,
        protocol: Protocol,
        transport: Transport,
        *,
        handshake: HandshakeConfig | None = None,
        on_update: UpdateCallback | None = None,
        on_error: ErrorCallback | None = None,
        on_ready: Callable[[], None] | None = None,
        on_control: Callable[[int], None] | None = None,
        ddm1_table: ddm1.DDM1Table | None = None,
        ddm2_table: ddm2.DDM2Table | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.protocol = protocol
        self.transport = transport
        self.machine = ProtocolMachine(
            protocol, handshake=handshake, ddm1_table=ddm1_table, ddm2_table=ddm2_table
        )
        self._callbacks = _SessionCallbacks(on_update, on_error, on_ready, on_control)
        self._log = logger or _LOGGER
        self._ready = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._outgoing: asyncio.Queue[bytes] = asyncio.Queue()
        self._writer_task: asyncio.Task[None] | None = None
        self._closed = False

    # -- properties ----------------------------------------------------------------

    @property
    def ready(self) -> bool:
        """True once the handshake completed."""
        return self.machine.ready

    @property
    def values(self) -> dict[bytes, Update]:
        """Latest decoded update per topic."""
        return self.machine.values

    def add_update_listener(self, callback: UpdateCallback) -> Callable[[], None]:
        """Register an extra update listener; returns an unsubscribe function."""
        self._callbacks.extra.append(callback)

        def _remove() -> None:
            if callback in self._callbacks.extra:
                self._callbacks.extra.remove(callback)

        return _remove

    # -- life cycle ----------------------------------------------------------------

    async def start(self, *, ready_timeout: float | None = 10.0) -> None:
        """Connect the transport (if needed), run the handshake, wait until READY.

        Raises ``TimeoutError`` if the device does not complete the handshake in
        ``ready_timeout`` seconds (pass ``None`` to return without waiting).
        """
        if self._closed:
            raise SessionError("session is closed")
        # Arm the machine *before* the transport connects: a CFX3 sends its first ACK as
        # soon as notifications are enabled, possibly before ``connect()`` returns. Frames
        # to send are only queued here; the writer task flushes them once connected.
        self.transport.on_notify(self._handle_notify)
        self._dispatch(self.machine.start())
        if not self.transport.connected:
            try:
                await self.transport.connect()
            except Exception:
                self.transport.on_notify(None)
                self.machine.close()
                raise
        self._writer_task = asyncio.create_task(self._writer_loop(), name="pyddm-writer")
        if ready_timeout is not None:
            await self.wait_ready(ready_timeout)

    async def wait_ready(self, ready_timeout: float) -> None:
        """Block until the handshake completes or ``ready_timeout`` seconds pass."""
        async with asyncio.timeout(ready_timeout):
            await self._ready.wait()

    async def close(self) -> None:
        """Stop the writer, detach from the transport and disconnect it."""
        self._closed = True
        self.machine.close()
        task, self._writer_task = self._writer_task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self.transport.on_notify(None)
        await self.transport.disconnect()

    # -- API writes ----------------------------------------------------------------

    async def subscribe(self, topic: bytes) -> None:
        """Send one SUBSCRIBE. Requires READY (the app subscribes only after the handshake)."""
        self._require_ready()
        await self._write(self.machine.subscribe_frame(topic))

    async def subscribe_many(self, topics: list[bytes] | tuple[bytes, ...]) -> None:
        """Send several SUBSCRIBEs in order."""
        for topic in topics:
            await self.subscribe(topic)

    async def write(self, topic: bytes, value: Any) -> None:
        """Write a decoded value (DDM1 PUBLISH / DDM2 SET), encoded via the parameter table."""
        self._require_ready()
        await self._write(self.machine.write_frame(topic, value))

    async def write_raw(self, topic: bytes, value: bytes) -> None:
        """Write pre-encoded bytes. For experiments only."""
        self._require_ready()
        await self._write(self.machine.raw_write_frame(topic, value))

    async def ping(self) -> None:
        """DDM1 PING (allowed in any non-closed state, e.g. to nudge the device)."""
        if self._closed:
            raise SessionError("session is closed")
        await self._write(self.machine.ping_frame())

    def _require_ready(self) -> None:
        if self._closed:
            raise SessionError("session is closed")
        if not self.machine.ready:
            raise SessionError(f"session not ready (state {self.machine.state.value})")

    # -- internals -----------------------------------------------------------------

    async def _write(self, data: bytes) -> None:
        async with self._write_lock:
            self._log.debug("%s TX %s", self.protocol.value, hexdump(data))
            await self.transport.write(data)

    async def _writer_loop(self) -> None:
        while True:
            data = await self._outgoing.get()
            try:
                await self._write(data)
            except TransportError as err:
                self._log.warning("%s: queued write failed: %s", self.protocol.value, err)
                self._report_error(err)
            finally:
                self._outgoing.task_done()

    def _handle_notify(self, data: bytes) -> None:
        self._log.debug("%s RX %s", self.protocol.value, hexdump(data))
        self._dispatch(self.machine.receive(data))

    def _dispatch(self, events: list[Event]) -> None:
        for event in events:
            match event:
                case Send(data):
                    self._outgoing.put_nowait(data)
                case Ready():
                    self._ready.set()
                    if self._callbacks.on_ready is not None:
                        self._callbacks.on_ready()
                case Update() as update:
                    if update.error is not None:
                        self._log.warning(
                            "%s: %s on %s (value %s): %s",
                            self.protocol.value,
                            update.error,
                            update.name,
                            hexdump(update.raw) or "<empty>",
                            "topic not in table" if update.parameter is None else "decode failed",
                        )
                    self._emit_update(update)
                case Unknown(data, reason):
                    self._log.warning(
                        "%s: ignoring unknown frame %s (%s)",
                        self.protocol.value,
                        hexdump(data),
                        reason,
                    )
                case Control(action):
                    self._log.debug(
                        "%s: control %s", self.protocol.value, action_name(self.protocol, action)
                    )
                    if self._callbacks.on_control is not None:
                        self._callbacks.on_control(action)

    def _emit_update(self, update: Update) -> None:
        for callback in (self._callbacks.on_update, *self._callbacks.extra):
            if callback is None:
                continue
            try:
                callback(update)
            except Exception as err:  # a bad listener must not kill the session
                self._log.exception("update listener failed")
                self._report_error(err)

    def _report_error(self, err: Exception) -> None:
        if self._callbacks.on_error is not None:
            self._callbacks.on_error(err)
