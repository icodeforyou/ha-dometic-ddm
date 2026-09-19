"""TCP transport line framing, with a loopback asyncio server (no hardware)."""

from __future__ import annotations

import asyncio
import base64

import pytest

from pyddm.transport.base import TransportError
from pyddm.transport.tcp import TcpTransport, decode_line, encode_line


def test_line_codec() -> None:
    frame = bytes([0x12, 0x0A, 0x00, 0x02, 0x01])
    line = encode_line(frame)
    assert line.endswith(b"\r")
    assert line[:-1] == base64.b64encode(frame)
    assert decode_line(line) == frame
    assert decode_line(b"  " + line[:-1] + b"\r\n") == frame
    with pytest.raises(TransportError):
        decode_line(b"!!!not base64\r")


async def test_loopback_round_trip(socket_enabled: None) -> None:
    received: list[bytes] = []
    got_frame = asyncio.Event()

    async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        line = await reader.readuntil(b"\r")
        received.append(decode_line(line))
        # echo a PUBLISH ac.itemp = 21.5 °C back
        writer.write(encode_line(bytes([0x10, 0x0A, 0x00, 0x02, 0x01, 0xFC, 0x53, 0x00, 0x00])))
        writer.write(b"garbage-line\r")  # must be dropped, not fatal
        await writer.drain()
        await got_frame.wait()
        writer.close()

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    frames: list[bytes] = []
    dropped = asyncio.Event()

    def on_frame(data: bytes) -> None:
        frames.append(data)
        got_frame.set()

    transport = TcpTransport("127.0.0.1", port)
    transport.on_notify(on_frame)
    transport.on_disconnect(dropped.set)
    async with server:
        await transport.connect()
        assert transport.connected
        await transport.write(bytes([0x12, 0x0A, 0x00, 0x02, 0x01]))
        async with asyncio.timeout(1):
            await got_frame.wait()
            await dropped.wait()
        assert received == [bytes([0x12, 0x0A, 0x00, 0x02, 0x01])]
        assert frames == [bytes([0x10, 0x0A, 0x00, 0x02, 0x01, 0xFC, 0x53, 0x00, 0x00])]
        assert not transport.connected
        with pytest.raises(TransportError):
            await transport.write(b"\x04")
        await transport.disconnect()
        await transport.disconnect()  # idempotent


async def test_connect_refused(socket_enabled: None) -> None:
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    transport = TcpTransport("127.0.0.1", port, connect_timeout=1)
    with pytest.raises(TransportError):
        await transport.connect()
