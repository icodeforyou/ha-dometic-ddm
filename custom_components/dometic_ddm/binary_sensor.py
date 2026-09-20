"""Binary sensors: CFX3 door and compressor; FreshJet compressor and error state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DometicDdmConfigEntry
from .const import AC_ACTEXT_COMPRESSOR
from .coordinator import DometicDdmCoordinator
from .entity import DometicDdmEntity
from .pyddm import Protocol


@dataclass(frozen=True, kw_only=True)
class DdmBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor bound to one parameter, optionally through a value function."""

    group: str
    parameter: str
    value_fn: Callable[[Any], bool | None] | None = None
    """Turn the decoded parameter value into on/off; default: truthiness of bool/int."""


def _bool_value(value: Any) -> bool | None:
    return bool(value) if isinstance(value, bool | int) else None


def _compressor_from_actext(value: Any) -> bool | None:
    # Observed 0x10 (Inverter) idle and 0x12 (Inverter | Compressor) while cooling.
    return bool(value & AC_ACTEXT_COMPRESSOR) if isinstance(value, int) else None


def _has_errors(value: Any) -> bool | None:
    # ac.status is {"error": [u16, ...]}; an empty list was observed as "no errors".
    if isinstance(value, dict) and isinstance(value.get("error"), list):
        return any(code for code in value["error"])
    return None


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

FJZ7_BINARY_SENSORS: tuple[DdmBinarySensorDescription, ...] = (
    DdmBinarySensorDescription(
        key="compressor",
        translation_key="compressor",
        group="ac",
        parameter="actext",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=_compressor_from_actext,
    ),
    DdmBinarySensorDescription(
        key="problem",
        translation_key="problem",
        group="ac",
        parameter="status",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_has_errors,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DometicDdmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors for the device's protocol."""
    coordinator = entry.runtime_data
    descriptions = (
        CFX3_BINARY_SENSORS if coordinator.protocol is Protocol.DDM1 else FJZ7_BINARY_SENSORS
    )
    async_add_entities(DdmBinarySensor(coordinator, desc) for desc in descriptions)


class DdmBinarySensor(DometicDdmEntity, BinarySensorEntity):
    """A boolean derived from one parameter."""

    entity_description: DdmBinarySensorDescription

    def __init__(
        self, coordinator: DometicDdmCoordinator, description: DdmBinarySensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        desc = self.entity_description
        value = self._value(desc.group, desc.parameter)
        if value is None:
            return None
        return (desc.value_fn or _bool_value)(value)
