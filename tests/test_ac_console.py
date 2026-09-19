"""The local test console must speak exactly the frames the integration speaks."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer
import pytest

from pyddm import Protocol
from pyddm.ddm1 import default_table as ddm1_table
from pyddm.ddm2 import default_table as ddm2_table
from pyddm.transport.base import Transport
from tools.ac_console.server import (
    AC_DASHBOARD,
    CFX3_DASHBOARD,
    Console,
    TappedTransport,
    coerce_write_value,
    create_app,
    describe_frame,
    display_value,
    json_value,
)

from .fakes import FakeTransport

# ---------------------------------------------------------------- pure helpers


def test_describe_frame_ddm2_publish() -> None:
    text = describe_frame(
        Protocol.DDM2, bytes([0x10, 0x0A, 0x00, 0x02, 0x01, 0xFC, 0x53, 0x00, 0x00])
    )
    assert text == "PUBLISH 0A 00 02 01 = FC 53 00 00  ac.itemp = 21.5 °C"


def test_describe_frame_ddm2_enum_and_control() -> None:
    assert describe_frame(
        Protocol.DDM2, bytes([0x10, 0x03, 0x00, 0x02, 0x01, 3, 0, 0, 0])
    ).endswith("ac.md = 3 (Auto)")
    assert describe_frame(Protocol.DDM2, b"\x04") == "ACK"
    assert describe_frame(Protocol.DDM2, bytes([0x12, 0x0A, 0x00, 0x02, 0x01])) == (
        "SUBSCRIBE 0A 00 02 01  ac.itemp"
    )


def test_describe_frame_ddm1_and_unknown() -> None:
    assert describe_frame(Protocol.DDM1, bytes([0x00, 0x00, 0x01, 0x01, 0x01, 0x0A, 0xFF])) == (
        "PUBLISH 00 01 01 01 = 0A FF  compartment.c0MeasuredTemperature = -24.6 °C"
    )
    assert "(unknown topic)" in describe_frame(
        Protocol.DDM1, bytes([0x00, 0xEE, 0xEE, 0xEE, 0xEE, 1])
    )
    assert describe_frame(Protocol.DDM1, bytes([0x7F, 0x01])).startswith("??")
    assert "[decode failed" in describe_frame(
        Protocol.DDM1, bytes([0x00, 0x00, 0x01, 0x01, 0x01, 0x0A])
    )


def test_display_value() -> None:
    ac = ddm2_table()
    assert display_value(ac.get("ac", "on"), 1) == "on"
    assert display_value(ac.get("ac", "itemp"), 21.5) == "21.5 °C"
    assert display_value(ac.get("ac", "actext"), 0x12) == "18 (Compressor, Inverter)"
    assert display_value(ac.get("ac", "status"), {"error": [1]}) == '{"error": [1]}'
    cfx = ddm1_table()
    assert display_value(cfx.get("compartment", "c0DoorOpen"), True) == "yes"
    assert (
        display_value(cfx.get("compartment", "c0TemperatureRange"), (-22.0, 10.0)) == "-22.0 … 10.0"
    )
    assert display_value(None, None) == "—"


def test_json_value() -> None:
    assert json_value(b"\x01\x02") == "01 02"
    assert json_value((1.0, 2.0)) == [1.0, 2.0]
    assert json_value({"a": (b"\x00",)}) == {"a": ["00"]}


def test_coerce_write_value() -> None:
    ac = ddm2_table()
    assert coerce_write_value(ac.get("ac", "md"), "Auto") == 3
    assert coerce_write_value(ac.get("ac", "ttemp"), "21.5") == 21.5
    assert coerce_write_value(ac.get("ac", "on"), "0x1") == 1
    assert coerce_write_value(ac.get("mccc", "csettemp"), [4.0]) == {"temp": [4.0]}
    cfx = ddm1_table()
    assert coerce_write_value(cfx.get("compartment", "c0Power"), "on") is True
    assert coerce_write_value(cfx.get("compartment", "c0SetTemperature"), "-18") == -18.0
    assert coerce_write_value(cfx.get("power", "batteryProtectionLevel"), "2") == 2


def test_dashboards_reference_real_parameters() -> None:
    for cls, name in AC_DASHBOARD:
        ddm2_table().get(cls, name)
    for cls, name in CFX3_DASHBOARD:
        ddm1_table().get(cls, name)
    assert ("ac", "itemp") in AC_DASHBOARD
    assert ("ac", "ttemp") in AC_DASHBOARD


async def test_tapped_transport_reports_both_directions() -> None:
    inner = FakeTransport()
    seen: list[tuple[str, bytes]] = []
    tapped = TappedTransport(inner, lambda d, b: seen.append((d, b)))
    delivered: list[bytes] = []
    tapped.on_notify(delivered.append)
    await tapped.connect()
    await tapped.write(b"\x03")
    inner.notify(b"\x04")
    assert seen == [("tx", b"\x03"), ("rx", b"\x04")]
    assert delivered == [b"\x04"]
    assert inner.written == [b"\x03"]


# ---------------------------------------------------------------- websocket round trip


class FakeFreshJet(FakeTransport):
    """Answers SUBSCRIBE ac.itemp with a PUBLISH and echoes SETs (per docs, unverified)."""

    async def write(self, data: bytes) -> None:
        await super().write(data)
        if data[0] == 0x12 and data[1:5] == bytes([0x0A, 0x00, 0x02, 0x01]):
            self.notify(bytes([0x10, 0x0A, 0x00, 0x02, 0x01, 0xFC, 0x53, 0x00, 0x00]))
        elif data[0] == 0x11:
            self.notify(bytes([0x10]) + data[1:])


async def _recv_until(ws: Any, predicate: Any, within: float = 2.0) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    async with asyncio.timeout(within):
        while True:
            msg = await ws.receive()
            assert msg.type is WSMsgType.TEXT, msg
            payload = json.loads(msg.data)
            seen.append(payload)
            if predicate(payload):
                return seen


@pytest.fixture
async def console_client(socket_enabled: None) -> Any:
    device = FakeFreshJet()

    async def connector(address: str, protocol: Protocol, console: Console) -> Transport:
        assert protocol is Protocol.DDM2
        connector.addresses.append(address)  # type: ignore[attr-defined]
        return device

    connector.addresses = []  # type: ignore[attr-defined]

    async def scanner(seconds: float) -> list[dict[str, Any]]:
        return [
            {
                "address": "AA:BB:CC:DD:EE:02",
                "name": "SHE-2600",
                "rssi": -50,
                "protocol": "ddm2",
                "service_uuids": [],
                "manufacturer_ids": ["0x0845"],
                "manufacturer_data": {"0x0845": "01 02"},
            },
        ]

    console = Console(connector=connector, scanner=scanner)
    app = create_app(console)
    async with TestClient(TestServer(app)) as client:
        yield client, device, console


async def test_ws_full_flow(console_client: Any) -> None:
    client, device, console = console_client
    ws = await client.ws_connect("/ws")
    first = await _recv_until(ws, lambda m: m["type"] == "state")
    assert first[-1]["connected"] is False

    await ws.send_json({"cmd": "scan"})
    seen = await _recv_until(ws, lambda m: m["type"] == "scan")
    assert seen[-1]["devices"][0]["protocol"] == "ddm2"

    await ws.send_json({"cmd": "connect", "address": "AA:BB:CC:DD:EE:02", "protocol": "ddm2"})
    seen = await _recv_until(ws, lambda m: m["type"] == "state" and m["ready"])
    assert device.connect_calls == 1
    assert console.state.protocol == "ddm2"

    # Read path: dashboard subscribe → SUBSCRIBE frames logged, PUBLISH decoded to an update.
    await ws.send_json({"cmd": "subscribe", "params": [["ac", "itemp"]]})
    seen = await _recv_until(ws, lambda m: m["type"] == "update")
    frames = [m for m in seen if m["type"] == "frame"]
    assert frames[0]["dir"] == "tx"
    assert frames[0]["hex"] == "12 0A 00 02 01"
    assert frames[1]["dir"] == "rx"
    assert frames[1]["text"].endswith("ac.itemp = 21.5 °C")
    update = seen[-1]
    assert update["name"] == "ac.itemp"
    assert update["value"] == 21.5
    assert update["display"] == "21.5 °C"

    # Writes are refused until explicitly enabled.
    await ws.send_json({"cmd": "write", "class": "ac", "param": "ttemp", "value": 22})
    seen = await _recv_until(ws, lambda m: m["type"] == "log" and m["level"] == "error")
    assert "writes are disabled" in seen[-1]["msg"]
    assert all(w[0] != 0x11 for w in device.written)

    await ws.send_json({"cmd": "enable_writes", "on": True})
    await _recv_until(ws, lambda m: m["type"] == "state" and m["writes_enabled"])
    await ws.send_json({"cmd": "write", "class": "ac", "param": "ttemp", "value": 22})
    seen = await _recv_until(ws, lambda m: m["type"] == "update" and m["name"] == "ac.ttemp")
    # DDM2 SET, int32 LE x1000, exactly what the integration would send.
    assert device.written[-1] == bytes([0x11, 0x04, 0x00, 0x02, 0x01, 0xF0, 0x55, 0x00, 0x00])
    assert seen[-1]["value"] == 22.0

    await ws.send_json({"cmd": "raw", "hex": "12 00 00 00 00"})
    seen = await _recv_until(ws, lambda m: m["type"] == "frame" and m["hex"] == "12 00 00 00 00")
    assert seen[-1]["text"] == "SUBSCRIBE 00 00 00 00  gw.avl"

    await ws.send_json({"cmd": "disconnect"})
    seen = await _recv_until(ws, lambda m: m["type"] == "state" and not m["connected"])
    assert device.disconnect_calls == 1
    await ws.close()


async def test_params_endpoint(console_client: Any) -> None:
    client, _device, _console = console_client
    resp = await client.get("/api/params?protocol=ddm2")
    rows = await resp.json()
    assert len(rows) == 2464
    md = next(r for r in rows if r["class"] == "ac" and r["name"] == "md")
    assert md["enum"]["Auto"] == 3
    assert md["topic"] == "03 00 02 01"
    resp = await client.get("/api/params?protocol=ddm1")
    assert len(await resp.json()) == 85


async def test_index_served(console_client: Any) -> None:
    client, _device, _console = console_client
    resp = await client.get("/")
    assert resp.status == 200
    assert "Dometic DDM Console" in await resp.text()
