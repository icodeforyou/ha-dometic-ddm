"""BLE transport against a fake bleak client."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from pyddm import DDM1_NOTIFY_UUID, DDM1_WRITE_UUID, DDM2_NOTIFY_UUID, Protocol
from pyddm.transport.base import TransportError
from pyddm.transport.ble import BleTransport


class FakeBleakClient:
    def __init__(self, *, connected: bool = False, fail_write: bool = False) -> None:
        self._connected = connected
        self.fail_write = fail_write
        self.mtu_size = 23
        self.notify_callbacks: dict[str, Callable[..., Any]] = {}
        self.writes: list[tuple[str, bytes, bool | None]] = []
        self.calls: list[str] = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self, **kwargs: Any) -> bool:
        self.calls.append("connect")
        self._connected = True
        return True

    async def disconnect(self) -> bool:
        self.calls.append("disconnect")
        self._connected = False
        return True

    async def start_notify(self, char: Any, callback: Callable[..., Any]) -> None:
        self.calls.append("start_notify")
        self.notify_callbacks[str(char)] = callback

    async def stop_notify(self, char: Any) -> None:
        self.calls.append("stop_notify")
        self.notify_callbacks.pop(str(char), None)

    async def write_gatt_char(self, char: Any, data: Any, response: bool | None = None) -> None:
        if self.fail_write:
            raise OSError("gatt write failed")
        self.writes.append((str(char), bytes(data), response))

    def emit(self, char: str, data: bytes) -> None:
        self.notify_callbacks[char](None, bytearray(data))


async def test_connect_starts_notify_on_protocol_characteristic() -> None:
    client = FakeBleakClient()
    transport = BleTransport(client, Protocol.DDM1)
    received: list[bytes] = []
    transport.on_notify(received.append)
    await transport.connect()
    assert client.calls == ["connect", "start_notify"]
    assert DDM1_NOTIFY_UUID in client.notify_callbacks
    assert transport.connected
    client.emit(DDM1_NOTIFY_UUID, b"\x04")
    assert received == [b"\x04"]
    await transport.write(b"\x03")
    assert client.writes == [(DDM1_WRITE_UUID, b"\x03", None)]
    await transport.disconnect()
    assert client.calls[-2:] == ["stop_notify", "disconnect"]
    assert not transport.connected


async def test_ddm2_uses_0400_characteristics() -> None:
    client = FakeBleakClient(connected=True)
    transport = BleTransport(client, Protocol.DDM2, owns_client=False, write_response=True)
    await transport.connect()
    assert client.calls == ["start_notify"]
    assert DDM2_NOTIFY_UUID in client.notify_callbacks
    await transport.write(b"\x12\x0a\x00\x02\x01")
    assert client.writes[0][0].startswith("537a0401")
    assert client.writes[0][2] is True
    await transport.disconnect()
    # not owned → never disconnects the client
    assert "disconnect" not in client.calls
    assert client.is_connected


async def test_link_drop_during_start_notify_is_explained() -> None:
    class Dropper(FakeBleakClient):
        async def start_notify(self, char: Any, callback: Callable[..., Any]) -> None:
            self._connected = False
            raise OSError("Not Connected")

    transport = BleTransport(Dropper(connected=True), Protocol.DDM2, owns_client=False)
    with pytest.raises(TransportError, match="dropped the link while notifications"):
        await transport.connect()


async def test_not_owned_and_not_connected_is_an_error() -> None:
    transport = BleTransport(FakeBleakClient(), Protocol.DDM1, owns_client=False)
    with pytest.raises(TransportError, match="not connected"):
        await transport.connect()


async def test_write_errors_wrapped() -> None:
    client = FakeBleakClient(connected=True, fail_write=True)
    transport = BleTransport(client, Protocol.DDM1, owns_client=False)
    await transport.connect()
    with pytest.raises(TransportError, match="BLE write failed"):
        await transport.write(b"\x03")
    client._connected = False
    with pytest.raises(TransportError, match="not connected"):
        await transport.write(b"\x03")


async def test_handle_disconnected_fires_callback() -> None:
    client = FakeBleakClient(connected=True)
    transport = BleTransport(client, Protocol.DDM1, owns_client=False)
    fired: list[bool] = []
    transport.on_disconnect(lambda: fired.append(True))
    await transport.connect()
    transport.handle_disconnected()
    assert fired == [True]
    assert not transport.connected
