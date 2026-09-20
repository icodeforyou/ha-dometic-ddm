"""Base entity: device info, availability, value access."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import DometicDdmCoordinator


class DometicDdmEntity(CoordinatorEntity[DometicDdmCoordinator]):
    """Entity bound to one parameter (or a set of them) of one device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DometicDdmCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}-{key}"

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.device_info()

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.connected

    def _value(self, group: str, name: str) -> object:
        return self.coordinator.value(group, name)

    def _int(self, group: str, name: str) -> int | None:
        value = self.coordinator.value(group, name)
        return int(value) if isinstance(value, int) and not isinstance(value, bool) else None

    def _float(self, group: str, name: str) -> float | None:
        value = self.coordinator.value(group, name)
        return (
            float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
        )

    def _bool(self, group: str, name: str) -> bool | None:
        value = self.coordinator.value(group, name)
        return bool(value) if isinstance(value, bool | int) else None
