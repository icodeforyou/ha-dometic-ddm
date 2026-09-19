"""CFX3 battery protection level select."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DometicDdmConfigEntry
from .coordinator import DometicDdmCoordinator
from .entity import DometicDdmEntity
from .pyddm import Protocol
from .pyddm.ddm1 import BATTERY_PROTECTION_LEVEL

# Option keys (translation keys) ↔ raw enum values. Names 0 Low / 1 Medium / 2 High come
# from the DDM2 dictionary; needs verification on a CFX3.
_OPTION_TO_VALUE: dict[str, int] = {
    name.lower(): value for value, name in BATTERY_PROTECTION_LEVEL.items()
}
_VALUE_TO_OPTION: dict[int, str] = {
    value: name.lower() for value, name in BATTERY_PROTECTION_LEVEL.items()
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DometicDdmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the CFX3 battery protection select."""
    coordinator = entry.runtime_data
    if coordinator.protocol is not Protocol.DDM1:
        return
    async_add_entities([BatteryProtectionSelect(coordinator)])


class BatteryProtectionSelect(DometicDdmEntity, SelectEntity):
    """power.batteryProtectionLevel as Low / Medium / High."""

    _attr_translation_key = "battery_protection"
    _attr_options = list(_OPTION_TO_VALUE)

    def __init__(self, coordinator: DometicDdmCoordinator) -> None:
        super().__init__(coordinator, "battery_protection")

    @property
    def current_option(self) -> str | None:
        value = self._value("power", "batteryProtectionLevel")
        return _VALUE_TO_OPTION.get(value) if isinstance(value, int) else None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_write(
            "power", "batteryProtectionLevel", _OPTION_TO_VALUE[option]
        )
