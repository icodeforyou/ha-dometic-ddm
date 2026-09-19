"""Base entity: device info, availability, value access."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import DometicDdmCoordinator


class DometicDdmEntity(CoordinatorEntity[DometicDdmCoordinator]):
    """Entity bound to one parameter (or a set of them) of one device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DometicDdmCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}-{key}"

    @property
    def device_info(self) -> DeviceInfo:
        coordinator = self.coordinator
        model = coordinator.value("productInformation", "productModelNumber")
        firmware = coordinator.value("deviceSpecific", "ccFirmwareVersion")
        serial = coordinator.value("productInformation", "productSerialNumber")
        return DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            name=coordinator.device_name,
            manufacturer=MANUFACTURER,
            model=str(model) if model else "CFX3" if coordinator.protocol.value == "ddm1" else None,
            sw_version=str(firmware) if firmware else None,
            serial_number=str(serial) if serial else None,
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.connected

    def _value(self, group: str, name: str) -> object:
        return self.coordinator.value(group, name)
