"""aiohttp server: serves the console page and bridges a WebSocket to a pyddm Session.

Messages (JSON), browser → server::

    {"cmd": "scan", "seconds": 6}
    {"cmd": "connect", "address": "AA:..", "protocol": "ddm2", "handshake": "none"}
    {"cmd": "disconnect"}
    {"cmd": "pair"}
    {"cmd": "ping"}
    {"cmd": "subscribe", "params": [["ac", "itemp"], ...]}     # omitted → dashboard set
    {"cmd": "enable_writes", "on": true}
    {"cmd": "write", "class": "ac", "param": "ttemp", "value": 21}
    {"cmd": "raw", "hex": "12 0A 00 02 01"}
    {"cmd": "state"}

server → browser::

    {"type": "scan", "devices": [...]}
    {"type": "state", ...}
    {"type": "frame", "dir": "tx"|"rx", "hex": "..", "text": "PUBLISH ac.itemp = 21.5", "ts": ..}
    {"type": "update", "name": "ac.itemp", "value": 21.5, "display": "21.5 °C", ...}
    {"type": "log", "level": "info"|"warning"|"error", "msg": ".."}

Writes (``write``/``raw``) are refused until ``enable_writes`` was sent: read first, write
later (CLAUDE.md working method).
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import time
from typing import Any

from aiohttp import WSMsgType, web

from pyddm import (
    Frame,
    FrameError,
    Protocol,
    Session,
    SessionError,
    hexdump,
    protocol_from_advertisement,
)
from pyddm.ddm1 import CodecError as Ddm1CodecError
from pyddm.ddm1 import DDM1Parameter, HistoryData
from pyddm.ddm1 import default_table as ddm1_table
from pyddm.ddm2 import CodecError as Ddm2CodecError
from pyddm.ddm2 import DDM2Parameter
from pyddm.ddm2 import default_table as ddm2_table
from pyddm.session import (
    DDM1_HANDSHAKE,
    DDM1_HANDSHAKE_WITH_PING,
    DDM2_HANDSHAKE_LIKE_DDM1,
    DDM2_HANDSHAKE_NONE,
    HandshakeConfig,
    Update,
)
from pyddm.transport.base import NotifyCallback, Transport, TransportError

_LOGGER = logging.getLogger("ac_console")
STATIC = Path(__file__).parent / "static"

# FreshJet (DDM2 ``ac`` class, plus gateway identity). Order = order of SUBSCRIBE frames.
AC_DASHBOARD: tuple[tuple[str, str], ...] = (
    ("gw", "avl"),
    ("gw", "ver"),
    ("gw", "ptype"),
    ("gw", "dsn"),
    ("gw", "sku"),
    ("ac", "avl"),
    ("ac", "mdl"),
    ("ac", "ver"),
    ("ac", "on"),
    ("ac", "md"),
    ("ac", "operst"),
    ("ac", "ttemp"),
    ("ac", "itemp"),
    ("ac", "etemp"),
    ("ac", "fspd"),
    ("ac", "fs"),
    ("ac", "fmd"),
    ("ac", "lgt"),
    ("ac", "dmr"),
    ("ac", "sleep"),
    ("ac", "eco"),
    ("ac", "flaps"),
    ("ac", "pwr"),
    ("ac", "curr"),
    ("ac", "currlim"),
    ("ac", "status"),
    ("ac", "actext"),
)
# CFX3 (DDM1). Same set as the integration's CFX3_SUBSCRIPTIONS.
CFX3_DASHBOARD: tuple[tuple[str, str], ...] = (
    ("productInformation", "productModelNumber"),
    ("productInformation", "productSerialNumber"),
    ("productInformation", "productType"),
    ("deviceSpecific", "ccFirmwareVersion"),
    ("compartment", "c0Power"),
    ("compartment", "c0MeasuredTemperature"),
    ("compartment", "c0SetTemperature"),
    ("compartment", "c0DoorOpen"),
    ("compartment", "c0TemperatureRange"),
    ("power", "coolerPower"),
    ("power", "batteryVoltageLevel"),
    ("power", "batteryProtectionLevel"),
    ("power", "compressorPower"),
    ("power", "powerSource"),
)

HANDSHAKES: dict[str, dict[Protocol, HandshakeConfig]] = {
    "default": {Protocol.DDM1: DDM1_HANDSHAKE, Protocol.DDM2: DDM2_HANDSHAKE_NONE},
    "none": {Protocol.DDM1: DDM2_HANDSHAKE_NONE, Protocol.DDM2: DDM2_HANDSHAKE_NONE},
    "hello": {Protocol.DDM1: DDM1_HANDSHAKE, Protocol.DDM2: DDM2_HANDSHAKE_LIKE_DDM1},
    "ping": {Protocol.DDM1: DDM1_HANDSHAKE_WITH_PING, Protocol.DDM2: DDM2_HANDSHAKE_LIKE_DDM1},
}

UNITS = {"^C": "°C", "%%": "%"}
_UNITLESS = frozenset({"-", "enum", "error", "instance", "inventory", "class", "parameter"})


# ---------------------------------------------------------------------------- helpers


def json_value(value: Any) -> Any:
    """Make a decoded value JSON serialisable."""
    if isinstance(value, bytes | bytearray):
        return hexdump(bytes(value))
    if isinstance(value, HistoryData):
        return {"values": list(value.values), "trailer": value.trailer}
    if isinstance(value, tuple):
        return [json_value(v) for v in value]
    if isinstance(value, list):
        return [json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    return value


def display_value(param: DDM1Parameter | DDM2Parameter | None, value: Any) -> str:
    """Human readable value with unit / enum name."""
    if value is None:
        return "—"
    if isinstance(param, DDM2Parameter):
        if param.enum is not None and isinstance(value, int):
            name = param.enum_name(value)
            if param.unit == "bitfield":
                names = [n for n, v in param.enum.items() if v and value & v == v]
                return f"{value} ({', '.join(names) or 'none'})"
            return f"{value} ({name})" if name is not None else str(value)
        unit = UNITS.get(param.unit, param.unit)
        if param.unit == "bool":
            return "on" if value else "off"
        if unit and unit not in _UNITLESS:
            return f"{value} {unit}"
    if isinstance(param, DDM1Parameter):
        if isinstance(value, bool):
            return "yes" if value else "no"
        unit = UNITS.get(param.unit, param.unit)
        if isinstance(value, int | float) and unit not in ("-", "enum"):
            return f"{value} {unit}"
        if isinstance(value, tuple):
            return " … ".join(str(v) for v in value)
    if isinstance(value, dict | list):
        return json.dumps(json_value(value))
    return str(value)


def describe_frame(protocol: Protocol, data: bytes) -> str:
    """One line for the frame log: action, parameter name, decoded value."""
    try:
        frame = Frame.decode(data, protocol)
    except FrameError as err:
        return f"?? {err}"
    text = frame.describe(protocol)
    if frame.topic is None:
        return text
    if protocol is Protocol.DDM1:
        param1 = ddm1_table().lookup(frame.topic)
        if param1 is None:
            return text + "  (unknown topic)"
        text += f"  {param1.qualified_name}"
        if frame.value:
            try:
                text += f" = {display_value(param1, param1.decode(frame.value))}"
            except Ddm1CodecError as err:
                text += f"  [decode failed: {err}]"
        return text
    found = ddm2_table().lookup(frame.topic)
    if found is None:
        return text + "  (unknown topic)"
    param2, instance = found
    text += f"  {param2.qualified_name}" + (f"[{instance}]" if instance else "")
    if frame.value:
        try:
            text += f" = {display_value(param2, param2.decode(frame.value))}"
        except Ddm2CodecError as err:
            text += f"  [decode failed: {err}]"
    return text


def update_message(update: Update) -> dict[str, Any]:
    return {
        "type": "update",
        "name": update.name,
        "topic": hexdump(update.topic),
        "raw": hexdump(update.raw),
        "instance": update.instance,
        "value": json_value(update.value),
        "display": display_value(update.parameter, update.value)
        if update.error is None
        else f"⚠ {update.error}",
        "unit": getattr(update.parameter, "unit", None),
        "error": update.error,
        "ts": time.time(),
    }


def coerce_write_value(param: DDM1Parameter | DDM2Parameter, value: Any) -> Any:
    """Accept enum names / strings from the browser and turn them into codec input."""
    if isinstance(param, DDM2Parameter):
        if isinstance(value, str) and param.enum is not None and value in param.enum:
            return param.enum_value(value)
        if isinstance(value, str) and param.in_type.value in ("INT32_T", "UINT32_T"):
            return float(value) if "." in value else int(value, 0)
        if isinstance(value, str) and param.in_type.value == "VOID":
            return None
        if isinstance(value, list) and param.in_type.value == "STRUCT":
            # convenience: a bare list → single-field struct
            assert param.struct is not None
            return {param.struct[0].name: value}
        return value
    kind = param.type.value
    if isinstance(value, str):
        if kind == "INT8_BOOLEAN":
            return value.strip().lower() in ("1", "true", "on", "yes")
        if kind in ("INT8_NUMBER", "UINT8_NUMBER"):
            return int(value, 0)
        if kind in ("INT16_DECIDEGREE_CELSIUS", "INT16_DECICURRENT_VOLT"):
            return float(value)
        if kind == "EMPTY":
            return None
    return value


class TappedTransport(Transport):
    """Wraps a transport and reports every frame in both directions."""

    def __init__(self, inner: Transport, tap: Callable[[str, bytes], None]) -> None:
        super().__init__()
        self._inner = inner
        self._tap = tap
        inner.on_notify(self._on_inner_notify)
        inner.on_disconnect(self._notify_disconnect)

    @property
    def inner(self) -> Transport:
        return self._inner

    @property
    def connected(self) -> bool:
        return self._inner.connected

    async def connect(self) -> None:
        await self._inner.connect()

    async def disconnect(self) -> None:
        await self._inner.disconnect()

    async def write(self, data: bytes) -> None:
        self._tap("tx", bytes(data))
        await self._inner.write(data)

    def on_notify(self, callback: NotifyCallback | None) -> None:
        # Keep our own hook on the inner transport; store the outer callback.
        self._notify_callback = callback

    def _on_inner_notify(self, data: bytes) -> None:
        self._tap("rx", bytes(data))
        self._deliver(data)


# ---------------------------------------------------------------------------- BLE glue

type Connector = Callable[[str, Protocol, "Console"], Awaitable[Transport]]


async def ble_connector(address: str, protocol: Protocol, console: Console) -> Transport:
    """Real BLE via bleak over BlueZ. Imported lazily so tests need no bleak backend."""
    from bleak import BleakClient  # noqa: PLC0415

    from pyddm.transport.ble import BleTransport  # noqa: PLC0415

    def _disconnected(_client: Any) -> None:
        console.loop.call_soon_threadsafe(console.on_link_lost)

    client = BleakClient(address, disconnected_callback=_disconnected, timeout=30.0)
    console.log("info", f"Connecting to {address} …")
    await client.connect()
    console.log("info", f"Link up, MTU {client.mtu_size}; enabling notifications")
    console.bleak_client = client
    return BleTransport(client, protocol, owns_client=True)


async def ble_scan(seconds: float) -> list[dict[str, Any]]:
    from bleak import BleakScanner  # noqa: PLC0415

    found = await BleakScanner.discover(timeout=seconds, return_adv=True)
    devices: list[dict[str, Any]] = []
    for address, (device, adv) in found.items():
        protocol = protocol_from_advertisement(
            adv.local_name, adv.service_uuids, adv.manufacturer_data.keys()
        )
        devices.append(
            {
                "address": address,
                "name": adv.local_name or device.name,
                "rssi": adv.rssi,
                "protocol": protocol.value if protocol else None,
                "service_uuids": list(adv.service_uuids),
                "manufacturer_ids": [f"0x{m:04X}" for m in adv.manufacturer_data],
                "manufacturer_data": {
                    f"0x{m:04X}": hexdump(bytes(v)) for m, v in adv.manufacturer_data.items()
                },
            }
        )
    devices.sort(key=lambda d: (d["protocol"] is None, -(d["rssi"] or -999)))
    return devices


# ---------------------------------------------------------------------------- console


@dataclass
class ConsoleState:
    address: str | None = None
    protocol: str | None = None
    connected: bool = False
    ready: bool = False
    handshake: str = "default"
    writes_enabled: bool = False


class Console:
    """One shared device connection, any number of browser tabs."""

    def __init__(self, connector: Connector | None = None, scanner: Any = None) -> None:
        self._connector: Connector = connector or ble_connector
        self._scanner = scanner or ble_scan
        self.clients: set[web.WebSocketResponse] = set()
        self.session: Session | None = None
        self.bleak_client: Any = None
        self.state = ConsoleState()
        self.values: dict[str, dict[str, Any]] = {}
        self.frames: list[dict[str, Any]] = []
        self.loop = asyncio.get_event_loop()
        self._send_tasks: set[asyncio.Task[None]] = set()

    # -- fan-out ---------------------------------------------------------------------

    def broadcast(self, message: dict[str, Any]) -> None:
        text = json.dumps(message)
        for ws in list(self.clients):
            if ws.closed:
                self.clients.discard(ws)
                continue
            task = asyncio.ensure_future(ws.send_str(text))
            self._send_tasks.add(task)
            task.add_done_callback(self._send_tasks.discard)

    def log(self, level: str, msg: str) -> None:
        getattr(_LOGGER, level if level != "warning" else "warning")(msg)
        self.broadcast({"type": "log", "level": level, "msg": msg, "ts": time.time()})

    def state_message(self) -> dict[str, Any]:
        self.state.connected = bool(self.session and self.session.transport.connected)
        self.state.ready = bool(self.session and self.session.ready)
        return {"type": "state", **self.state.__dict__, "values": list(self.values.values())}

    def push_state(self) -> None:
        self.broadcast(self.state_message())

    # -- session callbacks ---------------------------------------------------------------

    def _on_frame(self, direction: str, data: bytes) -> None:
        protocol = Protocol(self.state.protocol) if self.state.protocol else Protocol.DDM2
        entry = {
            "type": "frame",
            "dir": direction,
            "hex": hexdump(data),
            "text": describe_frame(protocol, data),
            "ts": time.time(),
        }
        self.frames.append(entry)
        del self.frames[:-500]
        self.broadcast(entry)

    def _on_update(self, update: Update) -> None:
        message = update_message(update)
        self.values[update.name] = message
        self.broadcast(message)

    def _on_ready(self) -> None:
        self.log("info", "Handshake complete, session READY")
        self.push_state()

    def _on_control(self, action: int) -> None:
        self.broadcast({"type": "control", "action": action, "ts": time.time()})

    def on_link_lost(self) -> None:
        self.log("warning", "BLE link lost")
        if self.session is not None:
            transport = self.session.transport
            inner = transport.inner if isinstance(transport, TappedTransport) else transport
            handle = getattr(inner, "handle_disconnected", None)
            if handle is not None:
                handle()
        self.push_state()

    # -- commands -----------------------------------------------------------------------

    async def handle(self, ws: web.WebSocketResponse, msg: dict[str, Any]) -> None:
        cmd = msg.get("cmd")
        try:
            match cmd:
                case "state":
                    await ws.send_json(self.state_message())
                    for frame in self.frames[-200:]:
                        await ws.send_json(frame)
                case "scan":
                    await self.scan(float(msg.get("seconds", 6)))
                case "connect":
                    await self.connect(
                        str(msg["address"]),
                        Protocol(msg.get("protocol") or "ddm2"),
                        str(msg.get("handshake") or "default"),
                    )
                case "disconnect":
                    await self.disconnect()
                case "pair":
                    await self.pair()
                case "ping":
                    await self.ping()
                case "subscribe":
                    params = msg.get("params")
                    await self.subscribe([(str(c), str(p)) for c, p in params] if params else None)
                case "enable_writes":
                    self.state.writes_enabled = bool(msg.get("on"))
                    self.log(
                        "warning" if self.state.writes_enabled else "info",
                        "Writes ENABLED — every write goes to the device"
                        if self.state.writes_enabled
                        else "Writes disabled (read-only)",
                    )
                    self.push_state()
                case "write":
                    await self.write(str(msg["class"]), str(msg["param"]), msg.get("value"))
                case "raw":
                    await self.raw(str(msg["hex"]))
                case _:
                    self.log("error", f"unknown command {cmd!r}")
        except (TransportError, SessionError, KeyError, ValueError) as err:
            self.log("error", f"{cmd}: {err}")
            self.push_state()

    async def scan(self, seconds: float) -> None:
        self.log("info", f"Scanning for {seconds:g}s …")
        devices = await self._scanner(seconds)
        ddm = [d for d in devices if d["protocol"]]
        self.log("info", f"Scan done: {len(devices)} devices, {len(ddm)} speak DDM")
        self.broadcast({"type": "scan", "devices": devices})

    async def connect(self, address: str, protocol: Protocol, handshake: str) -> None:
        await self.disconnect()
        if handshake not in HANDSHAKES:
            raise ValueError(f"unknown handshake {handshake!r}")
        self.state.address = address
        self.state.protocol = protocol.value
        self.state.handshake = handshake
        self.values.clear()
        self.frames.clear()
        self.push_state()
        inner = await self._connector(address, protocol, self)
        transport = TappedTransport(inner, self._on_frame)
        self.session = Session(
            protocol,
            transport,
            handshake=HANDSHAKES[handshake][protocol],
            on_update=self._on_update,
            on_ready=self._on_ready,
            on_control=self._on_control,
            on_error=lambda err: self.log("error", f"session: {err}"),
        )
        try:
            await self.session.start(ready_timeout=15.0)
        except TimeoutError:
            self.log(
                "warning",
                "No handshake completion within 15s. The device did not send the expected "
                "ACK. Try 'Send PING', another handshake variant, or check bonding.",
            )
            self.push_state()
            return
        except (TransportError, SessionError):
            await self.disconnect()
            raise
        self.push_state()
        if handshake == "none" or (protocol is Protocol.DDM2 and handshake == "default"):
            self.log("info", "No handshake configured for this protocol; session is READY")

    async def disconnect(self) -> None:
        session, self.session = self.session, None
        self.bleak_client = None
        if session is not None:
            try:
                await session.close()
            except Exception as err:  # teardown must not raise
                _LOGGER.debug("close failed: %s", err)
            self.log("info", "Disconnected")
        self.push_state()

    async def pair(self) -> None:
        if self.bleak_client is None:
            raise SessionError("not connected via BLE")
        self.log("info", "Requesting BLE pairing/bonding …")
        try:
            await self.bleak_client.pair()
        except Exception as err:
            raise TransportError(f"pairing failed: {err}") from err
        self.log("info", "Pairing call returned without error")

    async def ping(self) -> None:
        if self.session is None:
            raise SessionError("not connected")
        await self.session.ping()

    def _require_session(self) -> Session:
        if self.session is None:
            raise SessionError("not connected")
        if not self.session.ready:
            raise SessionError("session not READY (handshake incomplete)")
        return self.session

    def _param(self, class_name: str, name: str) -> DDM1Parameter | DDM2Parameter:
        if self.state.protocol == Protocol.DDM1.value:
            return ddm1_table().get(class_name, name)
        return ddm2_table().get(class_name, name)

    def _topic(self, class_name: str, name: str) -> bytes:
        param = self._param(class_name, name)
        return param.topic if isinstance(param, DDM1Parameter) else param.topic(0)

    def dashboard(self) -> tuple[tuple[str, str], ...]:
        return CFX3_DASHBOARD if self.state.protocol == Protocol.DDM1.value else AC_DASHBOARD

    async def subscribe(self, params: list[tuple[str, str]] | None) -> None:
        session = self._require_session()
        params = params or list(self.dashboard())
        self.log("info", f"Subscribing to {len(params)} parameter(s)")
        for class_name, name in params:
            await session.subscribe(self._topic(class_name, name))
            await asyncio.sleep(0.05)  # be gentle with the device's write queue

    async def write(self, class_name: str, name: str, value: Any) -> None:
        session = self._require_session()
        if not self.state.writes_enabled:
            raise SessionError("writes are disabled; flip 'Enable writes' first")
        param = self._param(class_name, name)
        coerced = coerce_write_value(param, value)
        self.log("warning", f"WRITE {param.qualified_name} ← {coerced!r}")
        try:
            await session.write(self._topic(class_name, name), coerced)
        except (Ddm1CodecError, Ddm2CodecError) as err:
            raise ValueError(str(err)) from err

    async def raw(self, hex_text: str) -> None:
        session = self._require_session()
        if not self.state.writes_enabled:
            raise SessionError("writes are disabled; flip 'Enable writes' first")
        data = bytes.fromhex(hex_text.replace(" ", "").replace(":", ""))
        if not data:
            raise ValueError("empty frame")
        self.log("warning", f"RAW FRAME {hexdump(data)}")
        await session.transport.write(data)


# ---------------------------------------------------------------------------- web app


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    console: Console = request.app["console"]
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    console.clients.add(ws)
    try:
        await console.handle(ws, {"cmd": "state"})
        async for msg in ws:
            if msg.type is WSMsgType.TEXT:
                try:
                    payload = json.loads(msg.data)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "log", "level": "error", "msg": "bad JSON"})
                    continue
                await console.handle(ws, payload)
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break
    finally:
        console.clients.discard(ws)
    return ws


async def params_handler(request: web.Request) -> web.Response:
    protocol = Protocol(request.query.get("protocol", "ddm2"))
    if protocol is Protocol.DDM1:
        rows = [
            {
                "class": p.group,
                "name": p.name,
                "type": p.type.value,
                "unit": p.unit,
                "writable": True,
                "topic": hexdump(p.topic),
            }
            for p in ddm1_table()
        ]
    else:
        rows = [
            {
                "class": p.class_name,
                "name": p.name,
                "type": p.out_type.value,
                "in": p.in_type.value,
                "unit": p.unit,
                "writable": p.writable and p.in_type.value != "-",
                "enum": p.enum,
                "topic": hexdump(p.topic(0)),
            }
            for p in ddm2_table()
        ]
    return web.json_response(rows)


async def index_handler(_request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC / "index.html")


def create_app(console: Console | None = None) -> web.Application:
    app = web.Application()
    app["console"] = console or Console()
    app.router.add_get("/", index_handler)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/params", params_handler)
    app.router.add_static("/static/", STATIC)
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dometic DDM test console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging incl. pyddm")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    if not args.verbose:
        logging.getLogger("pyddm").setLevel(logging.INFO)

    async def _run() -> None:
        app = create_app(Console())
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, args.host, args.port)
        await site.start()
        _LOGGER.info("Console at http://%s:%d/  (Ctrl+C to stop)", args.host, args.port)
        try:
            await asyncio.Event().wait()
        finally:
            await app["console"].disconnect()
            await runner.cleanup()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run())
    return 0
