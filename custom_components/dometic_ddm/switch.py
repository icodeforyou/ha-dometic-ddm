"""FreshJet switches: sleep mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DometicDdmConfigEntry
from .coordinator import DometicDdmCoordinator
from .entity import DometicDdmEntity
from .pyddm import Protocol


@dataclass(frozen=True, kw_only=True)
class DdmSwitchDescription(SwitchEntityDescription):
    """Switch bound to one writable boolean parameter."""

    group: str
    parameter: str


# ac.sleep is a writable bool in the dictionary and was read as 0 on the FJZ7; writing it has
# not been tried yet (needs verification).
FJZ7_SWITCHES: tuple[DdmSwitchDescription, ...] = (
    DdmSwitchDescription(key="sleep", translation_key="sleep", group="ac", parameter="sleep"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DometicDdmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up FreshJet switches."""
    coordinator = entry.runtime_data
    if coordinator.protocol is not Protocol.DDM2:
        return
    async_add_entities(DdmSwitch(coordinator, desc) for desc in FJZ7_SWITCHES)


class DdmSwitch(DometicDdmEntity, SwitchEntity):
    """A writable boolean parameter."""

    entity_description: DdmSwitchDescription

    def __init__(
        self, coordinator: DometicDdmCoordinator, description: DdmSwitchDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self._bool(self.entity_description.group, self.entity_description.parameter)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_write(
            self.entity_description.group, self.entity_description.parameter, 1
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write(
            self.entity_description.group, self.entity_description.parameter, 0
        )
