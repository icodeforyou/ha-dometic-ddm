"""CFX3 binary sensors: door open and compressor running."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DometicDdmConfigEntry
from .coordinator import DometicDdmCoordinator
from .entity import DometicDdmEntity
from .pyddm import Protocol


@dataclass(frozen=True, kw_only=True)
class DdmBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor bound to one INT8_BOOLEAN DDM1 parameter."""

    group: str
    parameter: str


CFX3_BINARY_SENSORS: tuple[DdmBinarySensorDescription, ...] = (
    DdmBinarySensorDescription(
        key="c0_door",
        translation_key="door",
        group="compartment",
        parameter="c0DoorOpen",
        device_class=BinarySensorDeviceClass.DOOR,
    ),
    DdmBinarySensorDescription(
        key="compressor",
        translation_key="compressor",
        group="power",
        parameter="compressorPower",
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DometicDdmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up CFX3 binary sensors."""
    coordinator = entry.runtime_data
    if coordinator.protocol is not Protocol.DDM1:
        return
    async_add_entities(DdmBinarySensor(coordinator, desc) for desc in CFX3_BINARY_SENSORS)


class DdmBinarySensor(DometicDdmEntity, BinarySensorEntity):
    """A boolean DDM1 parameter."""

    entity_description: DdmBinarySensorDescription

    def __init__(
        self, coordinator: DometicDdmCoordinator, description: DdmBinarySensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        value = self._value(self.entity_description.group, self.entity_description.parameter)
        return bool(value) if isinstance(value, bool | int) else None
