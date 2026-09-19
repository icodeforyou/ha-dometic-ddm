"""Protocol constants shared by transports and the Home Assistant integration.

Everything here comes from ``docs/dometic-power-protokoll.md`` (decompiled Dometic Power
app v2.2.8). Values marked *needs verification* have not been observed on real hardware.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class Protocol(StrEnum):
    """The two Dometic data-model protocols this package speaks."""

    DDM1 = "ddm1"
    DDM2 = "ddm2"


# GATT service and characteristic UUIDs (from the app's BLE layer).
DDM1_SERVICE_UUID = "537a0300-0995-481f-926c-1604e23fd515"
DDM1_WRITE_UUID = "537a0301-0995-481f-926c-1604e23fd515"
DDM1_NOTIFY_UUID = "537a0302-0995-481f-926c-1604e23fd515"

DDM2_SERVICE_UUID = "537a0400-0995-481f-926c-1604e23fd515"
DDM2_WRITE_UUID = "537a0401-0995-481f-926c-1604e23fd515"
DDM2_NOTIFY_UUID = "537a0402-0995-481f-926c-1604e23fd515"

SERVICE_UUIDS: dict[Protocol, str] = {
    Protocol.DDM1: DDM1_SERVICE_UUID,
    Protocol.DDM2: DDM2_SERVICE_UUID,
}
WRITE_UUIDS: dict[Protocol, str] = {
    Protocol.DDM1: DDM1_WRITE_UUID,
    Protocol.DDM2: DDM2_WRITE_UUID,
}
NOTIFY_UUIDS: dict[Protocol, str] = {
    Protocol.DDM1: DDM1_NOTIFY_UUID,
    Protocol.DDM2: DDM2_NOTIFY_UUID,
}

# The app requests this MTU after connecting. bleak has no portable "request MTU" API; the
# BLE transport only logs the negotiated size. Needs verification that the default MTU is
# sufficient for the longest DDM1 frame (1 + 4 + 15 bytes) and DDM2 STRUCT frames.
APP_REQUESTED_MTU = 153

# Identification at scan time (``getBleProtocol`` in the app).
# A local name whose first characters are "CFX3" means DDM1.
DDM1_LOCAL_NAME_PREFIX = "CFX3"
# Manufacturer-specific data with Bluetooth company id 0x0845 means DDM2.
# Needs verification with a real FJZ7 scan.
DDM2_MANUFACTURER_ID = 0x0845

TOPIC_LENGTH = 4


def protocol_from_advertisement(
    local_name: str | None,
    service_uuids: Iterable[str] = (),
    manufacturer_ids: Iterable[int] = (),
) -> Protocol | None:
    """Classify an advertisement the way the Dometic Power app does.

    Order matters and mirrors the app: the ``CFX3`` name wins, then the DDM2 company id.
    As a fallback (not in the app, but harmless) the advertised service UUID decides.
    """
    if local_name and local_name.upper().startswith(DDM1_LOCAL_NAME_PREFIX):
        return Protocol.DDM1
    if DDM2_MANUFACTURER_ID in set(manufacturer_ids):
        return Protocol.DDM2
    uuids = {u.lower() for u in service_uuids}
    if DDM1_SERVICE_UUID in uuids:
        return Protocol.DDM1
    if DDM2_SERVICE_UUID in uuids:
        return Protocol.DDM2
    return None
