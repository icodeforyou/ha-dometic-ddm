"""DDM1 codec and parameter table (Dometic CFX3).

Semantics follow ``ddm1Encoder``/``ddm1Decoder`` in the decompiled Dometic Power app as
documented in ``docs/dometic-power-protokoll.md`` section 3. Topic layout is
``[instance, param, class, group]``.

Needs verification on hardware: everything. In particular the enum value tables at the
bottom of this module were lifted from the DDM2 dictionary because the DDM1 table only
says "enum".
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
    "BATTERY_PROTECTION_LEVEL",
    "POWER_SOURCE",
    "PRODUCT_TYPE",
    "STRING_MAX_LENGTH",
    "CodecError",
    "DDM1Parameter",
    "DDM1Table",
    "DDM1Type",
    "DDM1Value",
    "HistoryData",
    "decode",
    "default_table",
    "encode",
]

DEFAULT_TABLE_PATH: Final = Path(__file__).parent / "data" / "ddm1_cfx3_parameters.json"

STRING_MAX_LENGTH: Final = 15
HISTORY_VALUES: Final = 7
HISTORY_LENGTH: Final = HISTORY_VALUES * 2 + 1  # 7 x int16 LE + 1 trailing byte

_INT16 = struct.Struct("<h")
_INT16x2 = struct.Struct("<hh")
_HISTORY = struct.Struct("<" + "h" * HISTORY_VALUES + "B")


class CodecError(ValueError):
    """Raised when a value cannot be encoded/decoded for a DDM1 type."""


class DDM1Type(StrEnum):
    """Value types used by the DDM1 parameter table."""

    INT8_BOOLEAN = "INT8_BOOLEAN"
    INT8_NUMBER = "INT8_NUMBER"
    UINT8_NUMBER = "UINT8_NUMBER"
    INT16_DECIDEGREE_CELSIUS = "INT16_DECIDEGREE_CELSIUS"
    INT16_DECICURRENT_VOLT = "INT16_DECICURRENT_VOLT"
    INT16_ARRAY = "INT16_ARRAY"
    HISTORY_DATA_ARRAY = "HISTORY_DATA_ARRAY"
    UTF8_STRING = "UTF8_STRING"
    EMPTY = "EMPTY"


HISTORY_NO_SAMPLE: Final = -32768
"""Raw int16 a CFX3 puts in history slots that have no sample yet (verified 2026-09-20)."""


@dataclass(frozen=True, slots=True)
class HistoryData:
    """Decoded HISTORY_DATA_ARRAY: seven deci-scaled int16 samples and one trailing byte.

    Samples are newest first; ``None`` marks an empty slot (raw ``0x8000``). The trailing
    byte is a counter the cooler advances over time (minutes for the day array); it is
    passed through unchanged. Verified on a CFX3 on 2026-09-20.
    """

    values: tuple[float | None, ...]
    trailer: int


type DDM1Value = bool | int | float | str | tuple[float, float] | HistoryData | None


def _deci_to_bytes(value: float, what: str) -> bytes:
    raw = round(value * 10)
    if not -32768 <= raw <= 32767:
        raise CodecError(f"{what} {value!r} out of int16 deci range")
    return _INT16.pack(raw)


def _expect_length(kind: DDM1Type, data: bytes, expected: int) -> None:
    if len(data) != expected:
        raise CodecError(
            f"{kind.value} expects {expected} byte(s), got {len(data)}: {data.hex(' ').upper()}"
        )


def encode(kind: DDM1Type, value: DDM1Value) -> bytes:
    """Encode ``value`` as ``kind``. Mirrors ``ddm1Encoder``."""
    match kind:
        case DDM1Type.INT8_BOOLEAN:
            if not isinstance(value, bool | int):
                raise CodecError(f"INT8_BOOLEAN needs a bool, got {value!r}")
            return bytes((1 if value else 0,))
        case DDM1Type.INT8_NUMBER:
            if not isinstance(value, int) or isinstance(value, bool):
                raise CodecError(f"INT8_NUMBER needs an int, got {value!r}")
            if not -128 <= value <= 127:
                raise CodecError(f"INT8_NUMBER {value} out of range")
            return struct.pack("<b", value)
        case DDM1Type.UINT8_NUMBER:
            if not isinstance(value, int) or isinstance(value, bool):
                raise CodecError(f"UINT8_NUMBER needs an int, got {value!r}")
            if not 0 <= value <= 255:
                raise CodecError(f"UINT8_NUMBER {value} out of range")
            return struct.pack("<B", value)
        case DDM1Type.INT16_DECIDEGREE_CELSIUS:
            if not isinstance(value, int | float) or isinstance(value, bool):
                raise CodecError(f"INT16_DECIDEGREE_CELSIUS needs a number, got {value!r}")
            return _deci_to_bytes(value, "temperature")
        case DDM1Type.INT16_DECICURRENT_VOLT:
            if not isinstance(value, int | float) or isinstance(value, bool):
                raise CodecError(f"INT16_DECICURRENT_VOLT needs a number, got {value!r}")
            return _deci_to_bytes(value, "voltage")
        case DDM1Type.INT16_ARRAY:
            if not isinstance(value, tuple) or len(value) != 2:
                raise CodecError(f"INT16_ARRAY needs a (min, max) tuple, got {value!r}")
            return _deci_to_bytes(value[0], "min") + _deci_to_bytes(value[1], "max")
        case DDM1Type.HISTORY_DATA_ARRAY:
            if not isinstance(value, HistoryData) or len(value.values) != HISTORY_VALUES:
                raise CodecError(
                    f"HISTORY_DATA_ARRAY needs HistoryData with 7 values, got {value!r}"
                )
            return b"".join(
                _INT16.pack(HISTORY_NO_SAMPLE) if v is None else _deci_to_bytes(v, "history")
                for v in value.values
            ) + struct.pack("<B", value.trailer)
        case DDM1Type.UTF8_STRING:
            if not isinstance(value, str):
                raise CodecError(f"UTF8_STRING needs a str, got {value!r}")
            raw = value.encode("utf-8")
            if len(raw) > STRING_MAX_LENGTH:
                raise CodecError(f"UTF8_STRING longer than {STRING_MAX_LENGTH} bytes: {value!r}")
            # Zero-terminated when shorter than the maximum length, per the app encoder.
            return raw if len(raw) == STRING_MAX_LENGTH else raw + b"\x00"
        case DDM1Type.EMPTY:
            if value is not None:
                raise CodecError(f"EMPTY takes no value, got {value!r}")
            return b""
    raise CodecError(f"unsupported DDM1 type {kind!r}")  # pragma: no cover


def decode(kind: DDM1Type, data: bytes) -> DDM1Value:
    """Decode ``data`` as ``kind``. Mirrors ``ddm1Decoder``. Strict about lengths."""
    data = bytes(data)
    match kind:
        case DDM1Type.INT8_BOOLEAN:
            _expect_length(kind, data, 1)
            return data[0] != 0
        case DDM1Type.INT8_NUMBER:
            _expect_length(kind, data, 1)
            return int(struct.unpack("<b", data)[0])
        case DDM1Type.UINT8_NUMBER:
            _expect_length(kind, data, 1)
            return int(data[0])
        case DDM1Type.INT16_DECIDEGREE_CELSIUS | DDM1Type.INT16_DECICURRENT_VOLT:
            _expect_length(kind, data, 2)
            return int(_INT16.unpack(data)[0]) / 10
        case DDM1Type.INT16_ARRAY:
            _expect_length(kind, data, 4)
            lo, hi = _INT16x2.unpack(data)
            return (int(lo) / 10, int(hi) / 10)
        case DDM1Type.HISTORY_DATA_ARRAY:
            _expect_length(kind, data, HISTORY_LENGTH)
            *values, trailer = _HISTORY.unpack(data)
            return HistoryData(
                tuple(None if int(v) == HISTORY_NO_SAMPLE else int(v) / 10 for v in values),
                int(trailer),
            )
        case DDM1Type.UTF8_STRING:
            if len(data) > STRING_MAX_LENGTH:
                raise CodecError(
                    f"UTF8_STRING longer than {STRING_MAX_LENGTH} bytes: {data.hex(' ').upper()}"
                )
            return data.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        case DDM1Type.EMPTY:
            _expect_length(kind, data, 0)
            return None
    raise CodecError(f"unsupported DDM1 type {kind!r}")  # pragma: no cover


@dataclass(frozen=True, slots=True)
class DDM1Parameter:
    """One row of the CFX3 parameter table."""

    group: str
    """Table section in the app, e.g. ``"compartment"`` or ``"power"``."""
    name: str
    topic: bytes
    type: DDM1Type
    unit: str
    writable: bool
    """As listed by the app. The app marks *every* CFX3 parameter writable, so this flag
    is not a reliable read-only indicator. Needs verification."""

    @property
    def instance(self) -> int:
        """Topic byte 0: ``0x00`` compartment 0, ``0x10`` compartment 1, ``0x20`` dcm."""
        return self.topic[0]

    @property
    def param_id(self) -> int:
        """Topic byte 1."""
        return self.topic[1]

    @property
    def class_id(self) -> int:
        """Topic byte 2."""
        return self.topic[2]

    @property
    def group_id(self) -> int:
        """Topic byte 3: 0 product info, 1 device data, 128 device specific, 129 multi."""
        return self.topic[3]

    @property
    def qualified_name(self) -> str:
        """``group.name`` for logs."""
        return f"{self.group}.{self.name}"

    def encode(self, value: DDM1Value) -> bytes:
        """Encode a value for this parameter."""
        return encode(self.type, value)

    def decode(self, data: bytes) -> DDM1Value:
        """Decode a value of this parameter."""
        return decode(self.type, data)


class DDM1Table:
    """Lookup structure over the CFX3 parameter table."""

    def __init__(self, parameters: Iterable[DDM1Parameter]) -> None:
        self._by_name: dict[tuple[str, str], DDM1Parameter] = {}
        self._by_topic: dict[bytes, DDM1Parameter] = {}
        for param in parameters:
            key = (param.group, param.name)
            if key in self._by_name:
                raise ValueError(f"duplicate parameter {param.qualified_name}")
            if param.topic in self._by_topic:
                raise ValueError(
                    f"topic {param.topic.hex(' ')} used by both "
                    f"{self._by_topic[param.topic].qualified_name} and {param.qualified_name}"
                )
            self._by_name[key] = param
            self._by_topic[param.topic] = param

    @classmethod
    def from_json(cls, raw: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> DDM1Table:
        """Build from the ``ddm1_cfx3_parameters.json`` structure.

        Rows whose topic contains ``null`` (``appConnectParameters``, whose first byte
        is filled in at runtime by the app) have no fixed topic and are skipped.
        """
        params: list[DDM1Parameter] = []
        for group, entries in raw.items():
            for name, entry in entries.items():
                topic_bytes = entry["topic_bytes"]
                if len(topic_bytes) != TOPIC_LENGTH or any(b is None for b in topic_bytes):
                    continue
                params.append(
                    DDM1Parameter(
                        group=group,
                        name=name,
                        topic=bytes(topic_bytes),
                        type=DDM1Type(entry["type"]),
                        unit=str(entry.get("unit", "-")),
                        writable=bool(entry.get("writable", 0)),
                    )
                )
        return cls(params)

    @classmethod
    def load(cls, path: Path | None = None) -> DDM1Table:
        """Load from a JSON file; defaults to the copy bundled with the package."""
        with (path or DEFAULT_TABLE_PATH).open("rb") as fh:
            return cls.from_json(json.load(fh))

    def get(self, group: str, name: str) -> DDM1Parameter:
        """Parameter by table section and name, e.g. ``("compartment", "c0SetTemperature")``."""
        try:
            return self._by_name[(group, name)]
        except KeyError:
            raise KeyError(f"unknown DDM1 parameter {group}.{name}") from None

    def topic_for(self, group: str, name: str) -> bytes:
        """Four topic bytes for a parameter."""
        return self.get(group, name).topic

    def lookup(self, topic: bytes) -> DDM1Parameter | None:
        """Parameter for four topic bytes, or ``None`` if the topic is not in the table."""
        return self._by_topic.get(bytes(topic))

    def __iter__(self) -> Iterator[DDM1Parameter]:
        return iter(self._by_name.values())

    def __len__(self) -> int:
        return len(self._by_name)

    def __contains__(self, topic: object) -> bool:
        return isinstance(topic, bytes | bytearray) and bytes(topic) in self._by_topic


@cache
def default_table() -> DDM1Table:
    """The bundled CFX3 table, loaded once."""
    return DDM1Table.load()


# Enum value names. The DDM1 table only says "enum"; these names come from the matching
# DDM2 parameters (mccc.batprotlvl, mccc.powsrc, gw.ptype). Needs verification on a CFX3.
BATTERY_PROTECTION_LEVEL: Final[Mapping[int, str]] = {0: "Low", 1: "Medium", 2: "High"}
POWER_SOURCE: Final[Mapping[int, str]] = {0: "AC", 1: "DC", 2: "Battery"}
PRODUCT_TYPE: Final[Mapping[int, str]] = {
    0: "Unconfigured",
    1: "Single Zone",
    2: "Single Zone with icemaker",
    3: "Dual Zone",
}
