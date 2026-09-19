"""CFX3 parameter table loading and lookup."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyddm.ddm1 import DDM1Table, DDM1Type, default_table

DOCS = Path(__file__).resolve().parents[1] / "docs" / "ddm1_cfx3_parameters.json"


def test_table_loads_all_addressable_parameters() -> None:
    table = default_table()
    raw = json.loads(DOCS.read_text())
    total = sum(len(v) for v in raw.values())
    assert total == 86
    # appConnectParameters has a null instance byte and is not addressable.
    assert len(table) == 85


@pytest.mark.parametrize(
    ("group", "name", "topic", "kind"),
    [
        ("compartment", "c0Power", "00 00 01 01", DDM1Type.INT8_BOOLEAN),
        ("compartment", "c0MeasuredTemperature", "00 01 01 01", DDM1Type.INT16_DECIDEGREE_CELSIUS),
        ("compartment", "c0SetTemperature", "00 02 01 01", DDM1Type.INT16_DECIDEGREE_CELSIUS),
        ("compartment", "c1SetTemperature", "10 02 01 01", DDM1Type.INT16_DECIDEGREE_CELSIUS),
        ("compartment", "c0DoorOpen", "00 08 01 01", DDM1Type.INT8_BOOLEAN),
        ("compartment", "c0TemperatureRange", "00 80 01 01", DDM1Type.INT16_ARRAY),
        ("compartment", "c0TemperatureHistoryHour", "00 40 01 01", DDM1Type.HISTORY_DATA_ARRAY),
        ("power", "coolerPower", "00 00 03 01", DDM1Type.INT8_BOOLEAN),
        ("power", "batteryVoltageLevel", "00 01 03 01", DDM1Type.INT16_DECICURRENT_VOLT),
        ("power", "batteryProtectionLevel", "00 02 03 01", DDM1Type.INT8_NUMBER),
        ("power", "compressorPower", "00 03 03 01", DDM1Type.INT8_BOOLEAN),
        ("power", "powerSource", "00 05 03 01", DDM1Type.INT8_NUMBER),
        ("communication", "deviceName", "00 00 06 01", DDM1Type.UTF8_STRING),
        ("productInformation", "productModelNumber", "00 C0 00 00", DDM1Type.UTF8_STRING),
        ("deviceSpecific", "ccFirmwareVersion", "00 C1 00 80", DDM1Type.UTF8_STRING),
        ("multiSubscriptionParameters", "subscribeAppSz", "01 00 00 81", DDM1Type.EMPTY),
        ("multiSubscriptionParameters", "subscribeAppDz", "03 00 00 81", DDM1Type.EMPTY),
        ("factoryReset", "factoryReset", "00 00 01 00", DDM1Type.EMPTY),
    ],
)
def test_topic_for_matches_docs(group: str, name: str, topic: str, kind: DDM1Type) -> None:
    table = default_table()
    param = table.get(group, name)
    assert table.topic_for(group, name) == bytes.fromhex(topic)
    assert param.type is kind
    assert table.lookup(bytes.fromhex(topic)) is param


def test_lookup_unknown_topic() -> None:
    assert default_table().lookup(bytes([0xEE, 0xEE, 0xEE, 0xEE])) is None
    assert bytes([0x00, 0x01, 0x01, 0x01]) in default_table()
    assert b"\xee\xee\xee\xee" not in default_table()


def test_get_unknown_name() -> None:
    with pytest.raises(KeyError, match=r"compartment\.nope"):
        default_table().get("compartment", "nope")


def test_topic_byte_accessors() -> None:
    param = default_table().get("compartment", "c1MeasuredTemperature")
    assert param.instance == 0x10
    assert param.param_id == 0x01
    assert param.class_id == 0x01
    assert param.group_id == 0x01
    assert param.qualified_name == "compartment.c1MeasuredTemperature"


def test_parameter_encode_decode_uses_type() -> None:
    param = default_table().get("compartment", "c0SetTemperature")
    assert param.encode(-18) == bytes([0x4C, 0xFF])
    assert param.decode(bytes([0x4C, 0xFF])) == -18.0


def test_duplicate_topics_rejected() -> None:
    raw = {
        "a": {"x": {"topic_bytes": [0, 0, 0, 0], "type": "EMPTY", "unit": "-", "writable": 1}},
        "b": {"y": {"topic_bytes": [0, 0, 0, 0], "type": "EMPTY", "unit": "-", "writable": 1}},
    }
    with pytest.raises(ValueError, match="topic 00 00 00 00"):
        DDM1Table.from_json(raw)
