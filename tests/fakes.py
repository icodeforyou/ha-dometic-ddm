"""Test doubles shared by the pyddm tests."""

from __future__ import annotations

import asyncio

from pyddm.transport.base import Transport, TransportError


class FakeTransport(Transport):
    """In-memory transport: records writes, lets tests inject notifications."""

    def __init__(self, *, fail_writes: bool = False) -> None:
        super().__init__()
        self.written: list[bytes] = []
        self.write_event = asyncio.Event()
        self._connected = False
        self.fail_writes = fail_writes
        self.connect_calls = 0
        self.disconnect_calls = 0

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self.connect_calls += 1
        self._connected = True

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._connected = False

    async def write(self, data: bytes) -> None:
        if not self._connected:
            raise TransportError("not connected")
        if self.fail_writes:
            raise TransportError("simulated write failure")
        self.written.append(bytes(data))
        self.write_event.set()

    def notify(self, data: bytes) -> None:
        """Simulate a GATT notification from the device."""
        self._deliver(bytes(data))

    async def wait_for_writes(self, count: int, within: float = 1.0) -> list[bytes]:
        """Wait until at least ``count`` frames were written (or ``within`` seconds pass)."""
        async with asyncio.timeout(within):
            while len(self.written) < count:
                self.write_event.clear()
                await self.write_event.wait()
        return list(self.written)

    def drop_link(self) -> None:
        """Simulate the device disconnecting."""
        self._connected = False
        self._notify_disconnect()
