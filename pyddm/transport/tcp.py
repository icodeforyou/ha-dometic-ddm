"""DDM2 over local WiFi TCP.

From the app: frames are base64 encoded, one per line, lines terminated by ``"\\r"``.
The same topics/actions are used as over BLE.

**Untested.** The app source names no default port, so ``port`` is mandatory; do not
guess one. Needs verification against a real device before use.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import logging

from .base import Transport, TransportError

_LOGGER = logging.getLogger(__name__)

LINE_TERMINATOR = b"\r"


def encode_line(frame: bytes) -> bytes:
    """Wire form of one frame: base64 + ``\\r``."""
    return base64.b64encode(frame) + LINE_TERMINATOR


def decode_line(line: bytes) -> bytes:
    """Frame bytes from one wire line (terminator and surrounding whitespace ignored)."""
    try:
        return base64.b64decode(line.strip(), validate=True)
    except (binascii.Error, ValueError) as err:
        raise TransportError(f"invalid base64 line {line!r}: {err}") from err


class TcpTransport(Transport):
    """Line-oriented TCP transport for DDM2 devices on the local network."""

    def __init__(self, host: str, port: int, *, connect_timeout: float = 10.0) -> None:
        super().__init__()
        self._host = host
        self._port = port
        self._connect_timeout = connect_timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        try:
            async with asyncio.timeout(self._connect_timeout):
                self._reader, self._writer = await asyncio.open_connection(self._host, self._port)
        except (OSError, TimeoutError) as err:
            raise TransportError(f"TCP connect to {self._host}:{self._port} failed: {err}") from err
        self._reader_task = asyncio.create_task(self._read_loop(), name="pyddm-tcp-reader")

    async def disconnect(self) -> None:
        task, self._reader_task = self._reader_task, None
        writer, self._writer = self._writer, None
        self._reader = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def write(self, data: bytes) -> None:
        if self._writer is None or self._writer.is_closing():
            raise TransportError("not connected")
        try:
            self._writer.write(encode_line(bytes(data)))
            await self._writer.drain()
        except OSError as err:
            raise TransportError(f"TCP write failed: {err}") from err

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                line = await self._reader.readuntil(LINE_TERMINATOR)
                try:
                    frame = decode_line(line)
                except TransportError:
                    _LOGGER.warning("dropping undecodable line %r", line)
                    continue
                self._deliver(frame)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            _LOGGER.debug("TCP link to %s:%s closed", self._host, self._port)
        except asyncio.CancelledError:
            raise
        finally:
            if self._writer is not None:
                self._writer.close()
                self._writer = None
                self._notify_disconnect()
