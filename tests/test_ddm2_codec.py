"""DDM2 codec: int32 LE with factor, strings, structs, enums, table lookups."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyddm.ddm2 import (
    CodecError,
    DDM2Parameter,
    DDM2Table,
    DDM2Type,
    StructField,
    default_table,
    parse_struct_spec,
)

DOCS = Path(__file__).resolve().parents[1] / "docs" / "ddm2_parameters.json"


@pytest.fixture(scope="module")
def table() -> DDM2Table:
    return default_table()


def test_dictionary_size(table: DDM2Table) -> None:
    raw = json.loads(DOCS.read_text())
    assert len(raw) == 240
    assert len(table) == 2464
    assert len(table.class_names()) == 240


@pytest.mark.parametrize(
    ("cls", "name", "topic"),
    [
        ("ac", "avl", "00 00 02 01"),
        ("ac", "on", "01 00 02 01"),
        ("ac", "md", "03 00 02 01"),
        ("ac", "ttemp", "04 00 02 01"),
        ("ac", "itemp", "0A 00 02 01"),
        ("ac", "status", "1A 00 02 01"),
        ("ac", "etemp", "27 00 02 01"),
        ("gw", "avl", "00 00 00 00"),
        ("gw", "ver", "02 00 00 00"),
        ("mccc", "ctemp", "04 00 00 1A"),
        ("mccc", "batprotlvl", "0D 00 00 1A"),
    ],
)
def test_topic_layout_param_instance_class_group(
    table: DDM2Table, cls: str, name: str, topic: str
) -> None:
    assert table.topic_for(cls, name) == bytes.fromhex(topic)
    found = table.lookup(bytes.fromhex(topic))
    assert found is not None
    param, instance = found
    assert param.qualified_name == f"{cls}.{name}"
    assert instance == 0


def test_instance_is_topic_byte_1(table: DDM2Table) -> None:
    assert table.topic_for("ac", "itemp", instance=2) == bytes([0x0A, 0x02, 0x02, 0x01])
    found = table.lookup(bytes([0x0A, 0x07, 0x02, 0x01]))
    assert found is not None
    assert found[1] == 7
    with pytest.raises(ValueError, match="instance"):
        table.topic_for("ac", "itemp", instance=256)


def test_lookup_unknown(table: DDM2Table) -> None:
    assert table.lookup(bytes([0xFF, 0x00, 0xFF, 0xFF])) is None
    assert table.lookup(b"\x00") is None
    with pytest.raises(KeyError):
        table.get("ac", "nope")


def test_int32_temperature_factor_1000(table: DDM2Table) -> None:
    itemp = table.get("ac", "itemp")
    assert itemp.out_type is DDM2Type.INT32
    assert itemp.factor == 1000
    # 21500 = 0x000053FC little-endian
    assert itemp.decode(bytes([0xFC, 0x53, 0x00, 0x00])) == 21.5
    # -5000 = 0xFFFFEC78
    assert itemp.decode(bytes([0x78, 0xEC, 0xFF, 0xFF])) == -5.0
    ttemp = table.get("ac", "ttemp")
    assert ttemp.encode(21.5) == bytes([0xFC, 0x53, 0x00, 0x00])
    assert ttemp.encode(-5) == bytes([0x78, 0xEC, 0xFF, 0xFF])


def test_int32_unscaled_stays_int(table: DDM2Table) -> None:
    on = table.get("ac", "on")
    assert on.factor == 1
    assert on.decode(bytes([0x01, 0x00, 0x00, 0x00])) == 1
    assert isinstance(on.decode(b"\x01\x00\x00\x00"), int)
    assert on.encode(True) == b"\x01\x00\x00\x00"
    assert on.encode(0) == b"\x00\x00\x00\x00"
    with pytest.raises(CodecError):
        on.encode(1.5)


def test_int32_wrong_length(table: DDM2Table) -> None:
    with pytest.raises(CodecError, match="expects 4 bytes"):
        table.get("ac", "itemp").decode(b"\x01\x02")


def test_uint32_bitfield(table: DDM2Table) -> None:
    actext = table.get("ac", "actext")
    assert actext.out_type is DDM2Type.UINT32
    assert actext.decode(bytes([0xFF, 0xFF, 0xFF, 0xFF])) == 0xFFFFFFFF
    assert actext.enum == {
        "Heater": 1,
        "Compressor": 2,
        "Inverter": 0x10,
        "FanEvap": 0x20,
        "ForceLoadShed": 0x40,
    }
    with pytest.raises(CodecError):
        actext.encode(-1)


def test_enum_names(table: DDM2Table) -> None:
    md = table.get("ac", "md")
    assert md.enum == {"Cool": 0, "Heat": 1, "Fan": 2, "Auto": 3, "Dry": 4, "Turbo": 5}
    assert md.enum_name(3) == "Auto"
    assert md.enum_name(99) is None
    assert md.enum_value("Dry") == 4
    with pytest.raises(KeyError):
        md.enum_value("Sauna")
    mdl = table.get("ac", "mdl")
    assert mdl.enum_name(18) == "Dometic FJZ7000 series"
    assert table.get("ac", "itemp").enum_name(1) is None
    flaps = table.get("ac", "flaps")
    assert flaps.enum_value("Flaps Active") == 15
    currlim = table.get("ac", "currlim")
    assert currlim.enum_value("Unlimited") == 7
    ptype = table.get("gw", "ptype")
    assert ptype.enum_value("Rubicon CFX3 Dual Zone") == 3  # parsed from "0x03"


def test_string(table: DDM2Table) -> None:
    ver = table.get("ac", "ver")
    assert ver.out_type is DDM2Type.STRING
    assert ver.decode(b"1.2.3") == "1.2.3"
    assert ver.decode(b"1.2.3\x00\x00") == "1.2.3"
    with pytest.raises(CodecError, match="not writable"):
        ver.encode("x")
    dsn = table.get("gw", "dsn")
    assert dsn.encode("ABC123") == b"ABC123"


def test_other_is_opaque_bytes(table: DDM2Table) -> None:
    mac = table.get("gw", "mac")
    assert mac.out_type is DDM2Type.OTHER
    assert mac.decode(bytes(range(6))) == bytes(range(6))


def test_void_command(table: DDM2Table) -> None:
    del_ = table.get("btwl", "del")
    assert del_.in_type is DDM2Type.VOID
    assert del_.encode(None) == b""
    with pytest.raises(CodecError):
        del_.encode(1)


def test_struct_error_array_x16(table: DDM2Table) -> None:
    status = table.get("ac", "status")
    assert status.struct == (StructField(name="error", kind="x16", count=0, unit="error"),)
    assert status.decode(b"") == {"error": []}
    assert status.decode(bytes([0x01, 0x00, 0x10, 0x02])) == {"error": [1, 0x0210]}
    assert status.encode({"error": [1, 0x0210]}) == bytes([0x01, 0x00, 0x10, 0x02])
    with pytest.raises(CodecError, match="multiple"):
        status.decode(bytes([0x01, 0x00, 0x10]))


def test_struct_temp_array_scaled_by_parameter_factor(table: DDM2Table) -> None:
    ctemp = table.get("mccc", "ctemp")
    assert ctemp.factor == 1000
    raw = bytes([0x78, 0xEC, 0xFF, 0xFF, 0xA0, 0x0F, 0x00, 0x00])  # -5000, 4000
    assert ctemp.decode(raw) == {"temp": [-5.0, 4.0]}
    csettemp = table.get("mccc", "csettemp")
    assert csettemp.encode({"temp": [-5.0, 4.0]}) == raw


def test_struct_bool_array_not_scaled(table: DDM2Table) -> None:
    cdoor = table.get("mccc", "cdoor")
    assert cdoor.decode(bytes([1, 0, 0, 0, 0, 0, 0, 0])) == {"bool_arr": [1, 0]}


def test_struct_nested_variable_array(table: DDM2Table) -> None:
    rng = table.get("mccc", "ctemprng")
    raw = bytes.fromhex("d0b9ffff 10270000 e8e3ffff 10270000")  # (-18.0, 10.0), (-7.192, 10.0)
    assert rng.decode(raw) == {
        "temp_range": [
            {"mintemp": -17.968, "maxtemp": 10.0},
            {"mintemp": -7.192, "maxtemp": 10.0},
        ]
    }
    assert rng.decode(b"") == {"temp_range": []}


def test_struct_fixed_and_variable_fields() -> None:
    fields = parse_struct_spec('{"time":["i32"],"interval":["i32"],"data":["i32",0]}')
    param = DDM2Parameter(
        class_name="t",
        name="bindata",
        param_id=1,
        class_id=1,
        group_id=1,
        in_type=DDM2Type.STRUCT,
        out_type=DDM2Type.STRUCT,
        unit="-",
        factor=1,
        writable=True,
        struct=fields,
    )
    raw = bytes.fromhex("01000000 3c000000 0a000000 0b000000")
    assert param.decode(raw) == {"time": 1, "interval": 60, "data": [10, 11]}
    assert param.encode({"time": 1, "interval": 60, "data": [10, 11]}) == raw
    with pytest.raises(CodecError, match="needs 4 bytes"):
        param.decode(b"\x01\x00\x00\x00\x3c\x00")
    with pytest.raises(CodecError, match="missing struct field"):
        param.encode({"time": 1})
    with pytest.raises(CodecError, match="unknown struct fields"):
        param.encode({"time": 1, "interval": 2, "data": [], "bogus": 1})


def test_struct_strings_and_bytes() -> None:
    fields = parse_struct_spec('{"rssi":["s",4],"name":["s",8],"addr":["x8",6]}')
    param = DDM2Parameter(
        class_name="t",
        name="s",
        param_id=1,
        class_id=1,
        group_id=1,
        in_type=DDM2Type.STRUCT,
        out_type=DDM2Type.STRUCT,
        unit="-",
        factor=1,
        writable=True,
        struct=fields,
    )
    raw = b"-70\x00" + b"CFX\x00\x00\x00\x00\x00" + bytes([1, 2, 3, 4, 5, 6])
    assert param.decode(raw) == {"rssi": "-70", "name": "CFX", "addr": [1, 2, 3, 4, 5, 6]}
    assert param.encode({"rssi": "-70", "name": "CFX", "addr": [1, 2, 3, 4, 5, 6]}) == raw
    with pytest.raises(CodecError, match="trailing"):
        param.decode(raw + b"\x00")


def test_parse_struct_spec_rules() -> None:
    fields = parse_struct_spec('{"temp":["i32",0,"^C"]}')
    assert fields[0].is_variable
    assert fields[0].unit == "^C"
    nested = parse_struct_spec(
        '{"temp_range":[{"mintemp":["i32",1,"^C"],"maxtemp":["i32",1,"^C"]},0]}'
    )
    assert nested[0].nested is not None
    assert nested[0].element_size() == 8
    with pytest.raises(CodecError, match="must be last"):
        parse_struct_spec('{"a":["i32",0],"b":["i32"]}')
    with pytest.raises(CodecError, match="unknown element type"):
        parse_struct_spec('{"a":["f64"]}')
    with pytest.raises(CodecError):
        parse_struct_spec("[1,2]")


def test_every_struct_spec_in_dictionary_parses(table: DDM2Table) -> None:
    structs = [p for p in table if p.out_type is DDM2Type.STRUCT]
    assert len(structs) == 47
    assert all(p.struct is not None for p in structs)
    # Four parameters are STRUCT on input only and carry no struct spec; they cannot be
    # encoded until the app's layout for them is known.
    in_only = [p for p in table if p.in_type is DDM2Type.STRUCT and p.struct is None]
    assert len(in_only) == 4
    with pytest.raises(CodecError, match="without a struct spec"):
        in_only[0].encode({})


def test_every_enum_in_dictionary_parses(table: DDM2Table) -> None:
    enums = [p for p in table if p.enum is not None]
    assert len(enums) == 280
    assert all(isinstance(v, int) for p in enums for v in (p.enum or {}).values())


def test_class_ids_unique(table: DDM2Table) -> None:
    seen: dict[tuple[int, int], str] = {}
    for name in table.class_names():
        params = table.parameters(name)
        ids = {(p.class_id, p.group_id) for p in params}
        assert len(ids) == 1, name
        cid = ids.pop()
        assert cid not in seen, (name, seen.get(cid))
        seen[cid] = name


def test_factor_parsing() -> None:
    raw = {
        "c": {
            "a": {
                "param_id": 0,
                "class_id": 1,
                "group_id": 2,
                "in": "-",
                "out": "INT32_T",
                "unit": "-",
                "factor": "",
                "writeable": 0,
            },
            "b": {
                "param_id": 1,
                "class_id": 1,
                "group_id": 2,
                "in": "-",
                "out": "INT32_T",
                "unit": "V",
                "factor": 100,
                "writeable": 0,
            },
        }
    }
    table = DDM2Table.from_json(raw)
    assert table.get("c", "a").factor == 1
    assert table.get("c", "b").decode(bytes([0xE8, 0x03, 0x00, 0x00])) == 10.0
