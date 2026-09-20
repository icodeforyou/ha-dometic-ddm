"""Fixtures for the Home Assistant integration tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_ADDRESS, CONF_NAME
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dometic_ddm.const import CONF_PROTOCOL, DOMAIN

from .fake_cfx3 import FakeCfx3Client
from .fake_freshjet import FakeFreshJetClient

CFX3_ADDRESS = "AA:BB:CC:DD:EE:01"
CFX3_NAME = "CFX3 45"
DDM1_SERVICE = "537a0300-0995-481f-926c-1604e23fd515"
DDM2_SERVICE = "537a0400-0995-481f-926c-1604e23fd515"
FJZ7_ADDRESS = "AA:BB:CC:DD:EE:02"


def make_service_info(
    *,
    address: str,
    name: str | None,
    service_uuids: list[str],
    manufacturer_data: dict[int, bytes] | None = None,
) -> BluetoothServiceInfoBleak:
    """Build a discovery record like HA's bluetooth manager would."""
    manufacturer_data = manufacturer_data or {}
    advertisement = AdvertisementData(
        local_name=name,
        manufacturer_data=manufacturer_data,
        service_data={},
        service_uuids=service_uuids,
        tx_power=-127,
        rssi=-60,
        platform_data=(),
    )
    return BluetoothServiceInfoBleak(
        name=name or address,
        address=address,
        rssi=-60,
        manufacturer_data=manufacturer_data,
        service_data={},
        service_uuids=service_uuids,
        source="local",
        device=BLEDevice(address, name, {}),
        advertisement=advertisement,
        connectable=True,
        time=0.0,
        tx_power=-127,
    )


CFX3_SERVICE_INFO = make_service_info(
    address=CFX3_ADDRESS, name=CFX3_NAME, service_uuids=[DDM1_SERVICE]
)
FJZ7_NAME = "FJZ7 2600"
FJZ7_SERVICE_INFO = make_service_info(
    address=FJZ7_ADDRESS,
    name="SHE_366f0c",  # as advertised by the real unit (2026-09-20 scan)
    service_uuids=[DDM2_SERVICE],
    manufacturer_data={0x0845: b"\x00"},
)
UNRELATED_SERVICE_INFO = make_service_info(
    address="AA:BB:CC:DD:EE:99",
    name="Nordic_UART",
    service_uuids=["6e400001-b5a3-f393-e0a9-e50e24dcca9e"],
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None, mock_bluetooth: None) -> None:
    """Make custom_components/ loadable and let HA's bluetooth dependency start without HW."""


@pytest.fixture
def cfx3_entry() -> MockConfigEntry:
    """A configured CFX3."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=CFX3_NAME,
        unique_id=CFX3_ADDRESS.lower(),
        data={CONF_ADDRESS: CFX3_ADDRESS, CONF_NAME: CFX3_NAME, CONF_PROTOCOL: "ddm1"},
    )


@pytest.fixture
def fake_cfx3() -> FakeCfx3Client:
    """A simulated CFX3 behind a bleak-like client."""
    return FakeCfx3Client(CFX3_ADDRESS)


@pytest.fixture
def patched_ble(fake_cfx3: FakeCfx3Client) -> Generator[FakeCfx3Client]:
    """Route the coordinator's BLE calls to the fake cooler."""

    async def _establish(client_class, device, name, **kwargs):  # type: ignore[no-untyped-def]
        fake_cfx3.disconnected_callback = kwargs.get("disconnected_callback")
        fake_cfx3.pair_requested = kwargs.get("pair", False)
        await fake_cfx3.connect()
        return fake_cfx3

    with (
        patch(
            "custom_components.dometic_ddm.coordinator.bluetooth.async_ble_device_from_address",
            return_value=BLEDevice(CFX3_ADDRESS, CFX3_NAME, {}),
        ),
        patch(
            "custom_components.dometic_ddm.coordinator.bluetooth.async_register_callback",
            return_value=lambda: None,
        ),
        patch("custom_components.dometic_ddm.coordinator.establish_connection", _establish),
    ):
        yield fake_cfx3


@pytest.fixture
def fjz7_entry() -> MockConfigEntry:
    """A configured FreshJet FJZ7."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=FJZ7_NAME,
        unique_id=FJZ7_ADDRESS.lower(),
        data={CONF_ADDRESS: FJZ7_ADDRESS, CONF_NAME: FJZ7_NAME, CONF_PROTOCOL: "ddm2"},
    )


@pytest.fixture
def patched_ble_fjz7() -> Generator[FakeFreshJetClient]:
    """Route the coordinator's BLE calls to the fake air conditioner."""
    fake = FakeFreshJetClient(FJZ7_ADDRESS)

    async def _establish(client_class, device, name, **kwargs):  # type: ignore[no-untyped-def]
        fake.disconnected_callback = kwargs.get("disconnected_callback")
        fake.pair_requested = kwargs.get("pair", False)
        await fake.connect()
        return fake

    with (
        patch(
            "custom_components.dometic_ddm.coordinator.bluetooth.async_ble_device_from_address",
            return_value=BLEDevice(FJZ7_ADDRESS, FJZ7_NAME, {}),
        ),
        patch(
            "custom_components.dometic_ddm.coordinator.bluetooth.async_register_callback",
            return_value=lambda: None,
        ),
        patch("custom_components.dometic_ddm.coordinator.establish_connection", _establish),
    ):
        yield fake
