"""Advertisement classification and UUID constants."""

from __future__ import annotations

from pyddm import (
    DDM1_NOTIFY_UUID,
    DDM1_SERVICE_UUID,
    DDM1_WRITE_UUID,
    DDM2_MANUFACTURER_ID,
    DDM2_NOTIFY_UUID,
    DDM2_SERVICE_UUID,
    DDM2_WRITE_UUID,
    Protocol,
    protocol_from_advertisement,
)


def test_uuids_match_claude_md() -> None:
    assert DDM1_SERVICE_UUID == "537a0300-0995-481f-926c-1604e23fd515"
    assert DDM1_WRITE_UUID == "537a0301-0995-481f-926c-1604e23fd515"
    assert DDM1_NOTIFY_UUID == "537a0302-0995-481f-926c-1604e23fd515"
    assert DDM2_SERVICE_UUID == "537a0400-0995-481f-926c-1604e23fd515"
    assert DDM2_WRITE_UUID == "537a0401-0995-481f-926c-1604e23fd515"
    assert DDM2_NOTIFY_UUID == "537a0402-0995-481f-926c-1604e23fd515"
    assert DDM2_MANUFACTURER_ID == 0x0845


def test_cfx3_name_wins() -> None:
    assert protocol_from_advertisement("CFX3 45", [], [0x0845]) is Protocol.DDM1
    assert protocol_from_advertisement("cfx3-abc") is Protocol.DDM1


def test_manufacturer_id_means_ddm2() -> None:
    assert protocol_from_advertisement("SHE-1234", [], [0x0845]) is Protocol.DDM2
    assert protocol_from_advertisement(None, [], [0x0845]) is Protocol.DDM2


def test_service_uuid_fallback() -> None:
    assert protocol_from_advertisement(None, [DDM1_SERVICE_UUID.upper()]) is Protocol.DDM1
    assert protocol_from_advertisement("Whatever", [DDM2_SERVICE_UUID]) is Protocol.DDM2


def test_unknown() -> None:
    assert (
        protocol_from_advertisement("Nordic_UART", ["6e400001-b5a3-f393-e0a9-e50e24dcca9e"], [89])
        is None
    )
    assert protocol_from_advertisement(None) is None
