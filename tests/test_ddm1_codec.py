"""Byte-exact tests for every DDM1 value type (docs section 3, ddm1Encoder/ddm1Decoder)."""

from __future__ import annotations

import pytest

from pyddm import ddm1
from pyddm.ddm1 import CodecError, DDM1Type, HistoryData, decode, encode

T = DDM1Type


@pytest.mark.parametrize(
    ("value", "raw"),
    [(True, b"\x01"), (False, b"\x00")],
)
def test_int8_boolean(value: bool, raw: bytes) -> None:
    assert encode(T.INT8_BOOLEAN, value) == raw
    assert decode(T.INT8_BOOLEAN, raw) is value


def test_int8_boolean_decode_treats_nonzero_as_true() -> None:
    assert decode(T.INT8_BOOLEAN, b"\x02") is True


@pytest.mark.parametrize(
    ("value", "raw"),
    [(0, b"\x00"), (1, b"\x01"), (-1, b"\xff"), (127, b"\x7f"), (-128, b"\x80")],
)
def test_int8_number(value: int, raw: bytes) -> None:
    assert encode(T.INT8_NUMBER, value) == raw
    assert decode(T.INT8_NUMBER, raw) == value


@pytest.mark.parametrize(
    ("value", "raw"),
    [(0, b"\x00"), (2, b"\x02"), (255, b"\xff")],
)
def test_uint8_number(value: int, raw: bytes) -> None:
    assert encode(T.UINT8_NUMBER, value) == raw
    assert decode(T.UINT8_NUMBER, raw) == value


@pytest.mark.parametrize(
    ("value", "raw"),
    [
        # lo=0x0A hi=0xFF → 0xFF0A = -246 → -24.6 °C (docs section 3 example)
        (-24.6, bytes([0x0A, 0xFF])),
        (0.0, bytes([0x00, 0x00])),
        (4.0, bytes([0x28, 0x00])),
        (-18.0, bytes([0x4C, 0xFF])),
        (10.5, bytes([0x69, 0x00])),
        (3276.7, bytes([0xFF, 0x7F])),
        (-3276.8, bytes([0x00, 0x80])),
    ],
)
def test_int16_decidegree_celsius(value: float, raw: bytes) -> None:
    assert encode(T.INT16_DECIDEGREE_CELSIUS, value) == raw
    assert decode(T.INT16_DECIDEGREE_CELSIUS, raw) == pytest.approx(value)


def test_int16_decidegree_is_little_endian_signed() -> None:
    # 0xFF0A read big-endian would be 0x0AFF = 2815 → 281.5; must be -24.6.
    assert decode(T.INT16_DECIDEGREE_CELSIUS, bytes([0x0A, 0xFF])) == -24.6


def test_int16_decidegree_rounds_to_tenths() -> None:
    assert encode(T.INT16_DECIDEGREE_CELSIUS, 4.04) == bytes([0x28, 0x00])
    assert encode(T.INT16_DECIDEGREE_CELSIUS, -0.06) == bytes([0xFF, 0xFF])


@pytest.mark.parametrize(
    ("value", "raw"),
    [(12.6, bytes([0x7E, 0x00])), (13.8, bytes([0x8A, 0x00])), (0.0, b"\x00\x00")],
)
def test_int16_decivolt(value: float, raw: bytes) -> None:
    assert encode(T.INT16_DECICURRENT_VOLT, value) == raw
    assert decode(T.INT16_DECICURRENT_VOLT, raw) == pytest.approx(value)


def test_int16_array_min_max() -> None:
    raw = bytes([0x24, 0xFF, 0x64, 0x00])  # -22.0, 10.0
    assert decode(T.INT16_ARRAY, raw) == (-22.0, 10.0)
    assert encode(T.INT16_ARRAY, (-22.0, 10.0)) == raw


def test_history_data_array() -> None:
    values = (-18.0, -17.5, -17.0, -16.5, -16.0, -15.5, -15.0)
    raw = (
        bytes([0x4C, 0xFF, 0x51, 0xFF, 0x56, 0xFF, 0x5B, 0xFF, 0x60, 0xFF, 0x65, 0xFF, 0x6A, 0xFF])
        + b"\x07"
    )
    assert len(raw) == 15
    decoded = decode(T.HISTORY_DATA_ARRAY, raw)
    assert decoded == HistoryData(values, 7)
    assert encode(T.HISTORY_DATA_ARRAY, HistoryData(values, 7)) == raw


@pytest.mark.parametrize(
    ("value", "raw"),
    [
        ("CFX3 45", b"CFX3 45\x00"),  # shorter than 15 → zero terminated
        ("", b"\x00"),
        ("ABCDEFGHIJKLMNO", b"ABCDEFGHIJKLMNO"),  # exactly 15 → no terminator
        ("Kylbox å", "Kylbox å".encode() + b"\x00"),
    ],
)
def test_utf8_string(value: str, raw: bytes) -> None:
    assert encode(T.UTF8_STRING, value) == raw
    assert decode(T.UTF8_STRING, raw) == value


def test_utf8_string_decode_stops_at_first_nul_and_accepts_padding() -> None:
    assert decode(T.UTF8_STRING, b"CFX3\x00\x00\x00\x00") == "CFX3"
    assert decode(T.UTF8_STRING, b"") == ""


def test_utf8_string_too_long() -> None:
    with pytest.raises(CodecError):
        encode(T.UTF8_STRING, "ABCDEFGHIJKLMNOP")
    with pytest.raises(CodecError):
        decode(T.UTF8_STRING, b"A" * 16)


def test_empty() -> None:
    assert encode(T.EMPTY, None) == b""
    assert decode(T.EMPTY, b"") is None
    with pytest.raises(CodecError):
        encode(T.EMPTY, 1)
    with pytest.raises(CodecError):
        decode(T.EMPTY, b"\x00")


@pytest.mark.parametrize(
    ("kind", "raw"),
    [
        (T.INT8_BOOLEAN, b""),
        (T.INT8_BOOLEAN, b"\x01\x00"),
        (T.INT16_DECIDEGREE_CELSIUS, b"\x0a"),
        (T.INT16_DECIDEGREE_CELSIUS, b"\x0a\xff\x00"),
        (T.INT16_ARRAY, b"\x00\x00"),
        (T.HISTORY_DATA_ARRAY, b"\x00" * 14),
    ],
)
def test_decode_is_strict_about_lengths(kind: DDM1Type, raw: bytes) -> None:
    with pytest.raises(CodecError):
        decode(kind, raw)


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        (T.INT8_NUMBER, 128),
        (T.INT8_NUMBER, -129),
        (T.UINT8_NUMBER, -1),
        (T.UINT8_NUMBER, 256),
        (T.INT16_DECIDEGREE_CELSIUS, 3276.8),
        (T.INT16_DECIDEGREE_CELSIUS, "warm"),
        (T.INT8_BOOLEAN, "yes"),
        (T.INT16_ARRAY, (1.0,)),
        (T.HISTORY_DATA_ARRAY, HistoryData((1.0,), 0)),
        (T.UTF8_STRING, 5),
    ],
)
def test_encode_rejects_bad_values(kind: DDM1Type, value: object) -> None:
    with pytest.raises(CodecError):
        encode(kind, value)  # type: ignore[arg-type]


def test_enum_tables_present() -> None:
    assert ddm1.BATTERY_PROTECTION_LEVEL == {0: "Low", 1: "Medium", 2: "High"}
    assert ddm1.POWER_SOURCE[2] == "Battery"
    assert ddm1.PRODUCT_TYPE[3] == "Dual Zone"
