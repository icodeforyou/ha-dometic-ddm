"""DDM2 codec and parameter dictionary (FreshJet FJZ/FJX, CFX5, gateways, ...).

Semantics follow ``ddm2Encoder``/``ddm2Decoder`` in the decompiled Dometic Power app as
documented in ``docs/dometic-power-protokoll.md`` section 4. Topic layout is
``[param_id, instance, class_id, group_id]``. Note the different order from DDM1.

Needs verification on hardware: everything. The STRUCT byte layout in particular is an
interpretation of the ``struct`` field in the dictionary (see :func:`parse_struct_spec`);
the docs only give examples, not a formal grammar.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
import json
from pathlib import Path
import struct
from typing import Any, Final

from .const import TOPIC_LENGTH

__all__ = [
    "CodecError",
    "DDM2Parameter",
    "DDM2Table",
    "DDM2Type",
    "DDM2Value",
    "StructField",
    "decode",
    "default_table",
    "encode",
    "parse_struct_spec",
]

DEFAULT_TABLE_PATH: Final = Path(__file__).parent / "data" / "ddm2_parameters.json"

_INT32 = struct.Struct("<i")
_UINT32 = struct.Struct("<I")


class CodecError(ValueError):
    """Raised when a value cannot be encoded/decoded for a DDM2 parameter."""


class DDM2Type(StrEnum):
    """``in``/``out`` types used by the DDM2 dictionary."""

    INT32 = "INT32_T"
    UINT32 = "UINT32_T"
    STRING = "STRING"
    STRUCT = "STRUCT"
    OTHER = "OTHER"  # opaque bytes (e.g. gw.mac)
    JUMBO = "JUMBO"  # fragmented transfer, not supported
    VOID = "VOID"  # command without a value
    NONE = "-"  # direction not available (read-only / write-only)


type DDM2Scalar = int | float | str | bytes | None
type DDM2Value = DDM2Scalar | Mapping[str, Any]


# Element type → (struct format, size in bytes). ``s`` (fixed-length string) is special.
_ELEMENT_FORMATS: Final[Mapping[str, tuple[str, int]]] = {
    "i8": ("<b", 1),
    "u8": ("<B", 1),
    "x8": ("<B", 1),  # hex-rendered byte in the app, plain unsigned here
    "x16": ("<H", 2),  # little-endian unsigned 16 (used by error arrays)
    "i32": ("<i", 4),
    "x32": ("<I", 4),  # little-endian unsigned 32
}
_UNITLESS: Final = frozenset({None, "", "-", "bool", "enum", "bitfield", "error", "instance"})


@dataclass(frozen=True, slots=True)
class StructField:
    """One field of a STRUCT parameter.

    ``count`` semantics (interpretation of the dictionary, needs verification):
    ``1`` scalar, ``0`` variable-length array consuming the rest of the buffer (only
    allowed as the last field), ``n > 1`` fixed-length array. For ``kind == "s"`` the
    count is the fixed byte length of the string.
    """

    name: str
    kind: str
    count: int = 1
    unit: str | None = None
    enum_ref: str | None = None
    nested: tuple[StructField, ...] | None = None

    @property
    def is_variable(self) -> bool:
        """True for a variable-length array field."""
        return self.count == 0

    def element_size(self) -> int:
        """Size in bytes of one element."""
        if self.nested is not None:
            return fixed_size(self.nested)
        if self.kind == "s":
            return 1
        try:
            return _ELEMENT_FORMATS[self.kind][1]
        except KeyError:
            raise CodecError(f"unknown struct element type {self.kind!r}") from None


def fixed_size(fields: tuple[StructField, ...]) -> int:
    """Total size of a struct with no variable-length fields."""
    total = 0
    for field in fields:
        if field.is_variable:
            raise CodecError(f"field {field.name!r} is variable-length; struct has no fixed size")
        total += field.element_size() * field.count
    return total


def _parse_field(name: str, spec: Any) -> StructField:
    if not isinstance(spec, list) or not spec:
        raise CodecError(f"struct field {name!r}: bad spec {spec!r}")
    head = spec[0]
    if isinstance(head, dict):
        nested = tuple(_parse_field(k, v) for k, v in head.items())
        count = int(spec[1]) if len(spec) > 1 else 1
        if any(f.is_variable for f in nested):
            raise CodecError(f"struct field {name!r}: nested variable-length fields unsupported")
        return StructField(name=name, kind="struct", count=count, nested=nested)
    if not isinstance(head, str):
        raise CodecError(f"struct field {name!r}: bad element type {head!r}")
    if head != "s" and head not in _ELEMENT_FORMATS:
        raise CodecError(f"struct field {name!r}: unknown element type {head!r}")
    count = int(spec[1]) if len(spec) > 1 else 1
    unit = str(spec[2]) if len(spec) > 2 and spec[2] is not None else None
    enum_ref = str(spec[3]) if len(spec) > 3 and spec[3] is not None else None
    return StructField(name=name, kind=head, count=count, unit=unit, enum_ref=enum_ref)


def parse_struct_spec(text: str) -> tuple[StructField, ...]:
    """Parse the JSON ``struct`` field of a dictionary entry.

    Grammar as observed in the dictionary::

        {"<field>": ["<type>", <count>?, "<unit>"?, "<enum ref>"?], ...}
        {"<field>": [{ ...nested fields... }, <count>]}

    A variable-length field (count 0) must be the last field.
    """
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise CodecError(f"struct spec must be an object: {text!r}")
    fields = tuple(_parse_field(str(k), v) for k, v in raw.items())
    for field in fields[:-1]:
        if field.is_variable:
            raise CodecError(f"variable-length field {field.name!r} must be last: {text!r}")
    return fields


def _parse_enum_value(text: str) -> int:
    text = text.strip()
    if text.lower().startswith(("0x", "-0x")):
        return int(text, 16)
    return int(text, 10)


def _parse_factor(raw: Any) -> int:
    # The dictionary uses "" for "no factor"; treat it and 0 as 1.
    if raw in ("", None, 0):
        return 1
    factor = int(raw)
    if factor <= 0:
        raise CodecError(f"invalid factor {raw!r}")
    return factor


@dataclass(frozen=True, slots=True)
class DDM2Parameter:
    """One entry of the DDM2 dictionary."""

    class_name: str
    name: str
    param_id: int
    class_id: int
    group_id: int
    in_type: DDM2Type
    out_type: DDM2Type
    unit: str
    factor: int
    writable: bool
    enum: Mapping[str, int] | None = None
    struct: tuple[StructField, ...] | None = None

    @property
    def qualified_name(self) -> str:
        """``class.param`` for logs, e.g. ``ac.itemp``."""
        return f"{self.class_name}.{self.name}"

    @property
    def is_scaled(self) -> bool:
        """True when raw integers are ``value * factor`` (e.g. °C·1000)."""
        return self.factor != 1

    def topic(self, instance: int = 0) -> bytes:
        """Topic bytes ``[param_id, instance, class_id, group_id]``."""
        if not 0 <= instance <= 0xFF:
            raise ValueError(f"instance {instance} does not fit in one byte")
        return bytes((self.param_id, instance, self.class_id, self.group_id))

    def enum_name(self, value: int) -> str | None:
        """Name for an enum value, or ``None`` if unknown / not an enum."""
        if self.enum is None:
            return None
        for name, val in self.enum.items():
            if val == value:
                return name
        return None

    def enum_value(self, name: str) -> int:
        """Raw value for an enum name."""
        if self.enum is None or name not in self.enum:
            raise KeyError(f"{self.qualified_name} has no enum member {name!r}")
        return self.enum[name]

    def encode(self, value: DDM2Value) -> bytes:
        """Encode a value for SET."""
        return encode(self, value)

    def decode(self, data: bytes) -> DDM2Value:
        """Decode a PUBLISH value."""
        return decode(self, data)


def _scale_out(param: DDM2Parameter, raw: int, unit: str | None) -> int | float:
    if param.is_scaled and unit == param.unit and unit not in _UNITLESS:
        return raw / param.factor
    return raw


def _scale_in(param: DDM2Parameter, value: Any, unit: str | None, what: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if not isinstance(value, int | float):
        raise CodecError(f"{what} needs a number, got {value!r}")
    if param.is_scaled and unit == param.unit and unit not in _UNITLESS:
        return round(value * param.factor)
    if isinstance(value, float) and not value.is_integer():
        raise CodecError(f"{what} is unscaled; got non-integer {value!r}")
    return int(value)


def _decode_scalar(param: DDM2Parameter, field: StructField, data: bytes) -> Any:
    if field.nested is not None:
        return _decode_struct(param, field.nested, data)
    if field.kind == "s":
        return data.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    fmt, _size = _ELEMENT_FORMATS[field.kind]
    raw = struct.unpack(fmt, data)[0]
    return _scale_out(param, int(raw), field.unit)


def _decode_struct(
    param: DDM2Parameter, fields: tuple[StructField, ...], data: bytes
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    offset = 0
    for field in fields:
        size = field.element_size()
        if field.kind == "s":
            if field.is_variable:
                result[field.name] = _decode_scalar(param, field, data[offset:])
                offset = len(data)
            else:
                chunk = data[offset : offset + field.count]
                if len(chunk) != field.count:
                    raise CodecError(f"{param.qualified_name}: short string field {field.name!r}")
                result[field.name] = _decode_scalar(param, field, chunk)
                offset += field.count
            continue
        if field.is_variable:
            rest = data[offset:]
            if len(rest) % size:
                raise CodecError(
                    f"{param.qualified_name}: {len(rest)} trailing bytes not a multiple of "
                    f"{size} for {field.name!r}: {data.hex(' ').upper()}"
                )
            result[field.name] = [
                _decode_scalar(param, field, rest[i : i + size]) for i in range(0, len(rest), size)
            ]
            offset = len(data)
            continue
        needed = size * field.count
        chunk = data[offset : offset + needed]
        if len(chunk) != needed:
            raise CodecError(
                f"{param.qualified_name}: field {field.name!r} needs {needed} bytes, "
                f"{len(chunk)} left: {data.hex(' ').upper()}"
            )
        if field.count == 1:
            result[field.name] = _decode_scalar(param, field, chunk)
        else:
            result[field.name] = [
                _decode_scalar(param, field, chunk[i : i + size]) for i in range(0, needed, size)
            ]
        offset += needed
    if offset != len(data):
        raise CodecError(
            f"{param.qualified_name}: {len(data) - offset} unexpected trailing byte(s): "
            f"{data.hex(' ').upper()}"
        )
    return result


def _encode_scalar(param: DDM2Parameter, field: StructField, value: Any) -> bytes:
    if field.nested is not None:
        if not isinstance(value, Mapping):
            raise CodecError(f"{param.qualified_name}: field {field.name!r} needs a mapping")
        return _encode_struct(param, field.nested, value)
    if field.kind == "s":
        if not isinstance(value, str):
            raise CodecError(f"{param.qualified_name}: field {field.name!r} needs a str")
        raw = value.encode("utf-8")
        if field.is_variable:
            return raw
        if len(raw) > field.count:
            raise CodecError(f"{param.qualified_name}: string {field.name!r} too long")
        return raw.ljust(field.count, b"\x00")
    fmt, _size = _ELEMENT_FORMATS[field.kind]
    raw_int = _scale_in(param, value, field.unit, f"{param.qualified_name}.{field.name}")
    try:
        return struct.pack(fmt, raw_int)
    except struct.error as err:
        raise CodecError(f"{param.qualified_name}.{field.name}: {err}") from None


def _encode_struct(
    param: DDM2Parameter, fields: tuple[StructField, ...], value: Mapping[str, Any]
) -> bytes:
    unknown = set(value) - {f.name for f in fields}
    if unknown:
        raise CodecError(f"{param.qualified_name}: unknown struct fields {sorted(unknown)}")
    out = bytearray()
    for field in fields:
        if field.name not in value:
            raise CodecError(f"{param.qualified_name}: missing struct field {field.name!r}")
        item = value[field.name]
        if field.kind == "s" or (field.count == 1 and not field.is_variable):
            out += _encode_scalar(param, field, item)
            continue
        if not isinstance(item, list | tuple):
            raise CodecError(f"{param.qualified_name}: field {field.name!r} needs a list")
        if not field.is_variable and len(item) != field.count:
            raise CodecError(
                f"{param.qualified_name}: field {field.name!r} needs {field.count} items"
            )
        for element in item:
            out += _encode_scalar(param, field, element)
    return bytes(out)


def encode(param: DDM2Parameter, value: DDM2Value) -> bytes:
    """Encode ``value`` for a SET of ``param`` according to its ``in`` type."""
    kind = param.in_type
    match kind:
        case DDM2Type.INT32 | DDM2Type.UINT32:
            raw = _scale_in(param, value, param.unit, param.qualified_name)
            packer = _INT32 if kind is DDM2Type.INT32 else _UINT32
            try:
                return packer.pack(raw)
            except struct.error:
                raise CodecError(
                    f"{param.qualified_name}: {raw} out of {kind.value} range"
                ) from None
        case DDM2Type.STRING:
            if not isinstance(value, str):
                raise CodecError(f"{param.qualified_name} needs a str, got {value!r}")
            return value.encode("utf-8")
        case DDM2Type.STRUCT:
            if param.struct is None:
                raise CodecError(f"{param.qualified_name} is STRUCT without a struct spec")
            if not isinstance(value, Mapping):
                raise CodecError(f"{param.qualified_name} needs a mapping, got {value!r}")
            return _encode_struct(param, param.struct, value)
        case DDM2Type.VOID:
            if value is not None:
                raise CodecError(f"{param.qualified_name} is VOID and takes no value")
            return b""
        case DDM2Type.OTHER:
            if not isinstance(value, bytes | bytearray):
                raise CodecError(f"{param.qualified_name} (OTHER) needs raw bytes")
            return bytes(value)
        case DDM2Type.NONE:
            raise CodecError(f"{param.qualified_name} is not writable")
        case DDM2Type.JUMBO:
            raise CodecError(f"{param.qualified_name} needs JUMBO/FRAGMENT transfer (unsupported)")
    raise CodecError(f"unsupported DDM2 type {kind!r}")  # pragma: no cover


def decode(param: DDM2Parameter, data: bytes) -> DDM2Value:
    """Decode a PUBLISH value of ``param`` according to its ``out`` type."""
    data = bytes(data)
    kind = param.out_type
    match kind:
        case DDM2Type.INT32 | DDM2Type.UINT32:
            if len(data) != 4:
                raise CodecError(
                    f"{param.qualified_name} ({kind.value}) expects 4 bytes, got {len(data)}: "
                    f"{data.hex(' ').upper()}"
                )
            unpacker = _INT32 if kind is DDM2Type.INT32 else _UINT32
            return _scale_out(param, int(unpacker.unpack(data)[0]), param.unit)
        case DDM2Type.STRING:
            return data.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        case DDM2Type.STRUCT:
            if param.struct is None:
                raise CodecError(f"{param.qualified_name} is STRUCT without a struct spec")
            return _decode_struct(param, param.struct, data)
        case DDM2Type.VOID | DDM2Type.NONE:
            if data:
                raise CodecError(f"{param.qualified_name} ({kind.value}) carries unexpected bytes")
            return None
        case DDM2Type.OTHER | DDM2Type.JUMBO:
            return data
    raise CodecError(f"unsupported DDM2 type {kind!r}")  # pragma: no cover


class DDM2Table:
    """Lookup structure over the DDM2 dictionary."""

    def __init__(self, parameters: Iterable[DDM2Parameter]) -> None:
        self._by_name: dict[tuple[str, str], DDM2Parameter] = {}
        self._by_id: dict[tuple[int, int, int], DDM2Parameter] = {}
        self._classes: dict[str, tuple[int, int]] = {}
        for param in parameters:
            key = (param.class_name, param.name)
            if key in self._by_name:
                raise ValueError(f"duplicate parameter {param.qualified_name}")
            ident = (param.class_id, param.group_id, param.param_id)
            if ident in self._by_id:
                raise ValueError(
                    f"class {param.class_id}/group {param.group_id}/param {param.param_id} "
                    f"used by both {self._by_id[ident].qualified_name} and {param.qualified_name}"
                )
            self._by_name[key] = param
            self._by_id[ident] = param
            self._classes.setdefault(param.class_name, (param.class_id, param.group_id))

    @classmethod
    def from_json(cls, raw: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> DDM2Table:
        """Build from the ``ddm2_parameters.json`` structure."""
        params: list[DDM2Parameter] = []
        for class_name, entries in raw.items():
            for name, entry in entries.items():
                enum_raw = entry.get("enum")
                enum = (
                    {str(k): _parse_enum_value(str(v)) for k, v in enum_raw.items()}
                    if isinstance(enum_raw, Mapping)
                    else None
                )
                struct_raw = entry.get("struct")
                params.append(
                    DDM2Parameter(
                        class_name=class_name,
                        name=name,
                        param_id=int(entry["param_id"]),
                        class_id=int(entry["class_id"]),
                        group_id=int(entry["group_id"]),
                        in_type=DDM2Type(entry.get("in", "-")),
                        out_type=DDM2Type(entry.get("out", "-")),
                        unit=str(entry.get("unit", "-")),
                        factor=_parse_factor(entry.get("factor")),
                        writable=bool(entry.get("writeable", entry.get("writable", 0))),
                        enum=enum,
                        struct=parse_struct_spec(struct_raw) if struct_raw else None,
                    )
                )
        return cls(params)

    @classmethod
    def load(cls, path: Path | None = None) -> DDM2Table:
        """Load from a JSON file; defaults to the copy bundled with the package."""
        with (path or DEFAULT_TABLE_PATH).open("rb") as fh:
            return cls.from_json(json.load(fh))

    def get(self, class_name: str, name: str) -> DDM2Parameter:
        """Parameter by class and name, e.g. ``("ac", "itemp")``."""
        try:
            return self._by_name[(class_name, name)]
        except KeyError:
            raise KeyError(f"unknown DDM2 parameter {class_name}.{name}") from None

    def topic_for(self, class_name: str, name: str, instance: int = 0) -> bytes:
        """Topic bytes for a parameter and instance."""
        return self.get(class_name, name).topic(instance)

    def lookup(self, topic: bytes) -> tuple[DDM2Parameter, int] | None:
        """``(parameter, instance)`` for four topic bytes, or ``None`` if unknown."""
        topic = bytes(topic)
        if len(topic) != TOPIC_LENGTH:
            return None
        param_id, instance, class_id, group_id = topic
        param = self._by_id.get((class_id, group_id, param_id))
        return None if param is None else (param, instance)

    def class_names(self) -> list[str]:
        """All class names in the dictionary."""
        return list(self._classes)

    def parameters(self, class_name: str) -> list[DDM2Parameter]:
        """All parameters of one class."""
        return [p for (c, _n), p in self._by_name.items() if c == class_name]

    def __iter__(self) -> Iterator[DDM2Parameter]:
        return iter(self._by_name.values())

    def __len__(self) -> int:
        return len(self._by_name)


@cache
def default_table() -> DDM2Table:
    """The bundled DDM2 dictionary, loaded once."""
    return DDM2Table.load()
