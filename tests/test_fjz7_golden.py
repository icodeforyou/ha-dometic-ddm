"""FreshJet FJZ7 golden frames captured from a real unit (docs/captures/2026-09-20_fjz7_*).

These are the first DDM2 bytes seen on hardware. They verify: DDM2 topic order
``[param, instance, class, group]``, SUBSCRIBE 0x12 answered by PUBLISH 0x10, int32 little
endian with factor 1000 for °C/A/W, plain strings, empty STRUCT for "no errors", and that
no handshake is needed after bonding (DDM2_HANDSHAKE_NONE).
"""

from __future__ import annotations

import pytest

from pyddm import Protocol
from pyddm.ddm2 import default_table
from pyddm.session import ProtocolMachine, Ready, Update

CAPTURED: list[tuple[str, str, object]] = [
    # (RX frame hex, parameter, decoded value)
    ("10 00 00 00 00 01 00 00 00", "gw.avl", 1),
    ("10 02 00 00 00 32 2E 32 2E 31", "gw.ver", "2.2.1"),
    ("10 13 00 00 00 04 00 00 00", "gw.ptype", 4),
    ("10 0E 00 00 00", "gw.dsn", ""),
    ("10 0F 00 00 00 39 36 30 30 30 35 31 30 30 30", "gw.sku", "9600051000"),
    ("10 00 00 02 01 01 00 00 00", "ac.avl", 1),
    ("10 09 00 02 01 12 00 00 00", "ac.mdl", 18),
    ("10 21 00 02 01 32 2E 32 2E 30", "ac.ver", "2.2.0"),
    ("10 01 00 02 01 01 00 00 00", "ac.on", 1),
    ("10 03 00 02 01 02 00 00 00", "ac.md", 2),
    ("10 04 00 02 01 F0 55 00 00", "ac.ttemp", 22.0),
    ("10 0A 00 02 01 90 65 00 00", "ac.itemp", 26.0),
    ("10 02 00 02 01 02 00 00 00", "ac.fspd", 2),
    ("10 0B 00 02 01 00 00 00 00", "ac.fs", 0),
    ("10 0C 00 02 01 00 00 00 00", "ac.fmd", 0),
    ("10 05 00 02 01 00 00 00 00", "ac.lgt", 0),
    ("10 06 00 02 01 64 00 00 00", "ac.dmr", 100),
    ("10 1B 00 02 01 00 00 00 00", "ac.sleep", 0),
    ("10 07 00 02 01 00 00 00 00", "ac.pwr", 0.0),
    ("10 2C 00 02 01 58 02 00 00", "ac.curr", 0.6),
    ("10 2D 00 02 01 07 00 00 00", "ac.currlim", 7),
    ("10 1A 00 02 01", "ac.status", {"error": []}),
    ("10 1E 00 02 01 10 00 00 00", "ac.actext", 16),
]


@pytest.mark.parametrize(("hex_frame", "name", "value"), CAPTURED)
def test_captured_publish_decodes(hex_frame: str, name: str, value: object) -> None:
    machine = ProtocolMachine(Protocol.DDM2)
    assert machine.start() == [Ready()]  # no handshake needed on a bonded link
    events = machine.receive(bytes.fromhex(hex_frame))
    assert len(events) == 1  # and no ACK is sent for DDM2 publishes
    update = events[0]
    assert isinstance(update, Update)
    assert update.error is None, update.error
    assert update.name == name
    assert update.instance == 0
    assert update.value == value


def test_captured_enum_names() -> None:
    table = default_table()
    assert table.get("gw", "ptype").enum_name(4) == "Dometic DICM Gateway"
    assert table.get("ac", "mdl").enum_name(18) == "Dometic FJZ7000 series"
    assert table.get("ac", "md").enum_name(2) == "Fan"
    assert table.get("ac", "fmd").enum_name(0) == "Auto"
    assert table.get("ac", "currlim").enum_name(7) == "Unlimited"
    assert table.get("ac", "actext").enum_name(16) == "Inverter"


def test_subscribe_frames_as_sent() -> None:
    machine = ProtocolMachine(Protocol.DDM2)
    table = default_table()
    assert machine.subscribe_frame(table.topic_for("gw", "avl")) == bytes.fromhex("12 00 00 00 00")
    assert machine.subscribe_frame(table.topic_for("ac", "itemp")) == bytes.fromhex(
        "12 0A 00 02 01"
    )
    assert machine.subscribe_frame(table.topic_for("ac", "actext")) == bytes.fromhex(
        "12 1E 00 02 01"
    )
