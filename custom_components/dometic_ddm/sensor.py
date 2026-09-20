"""Sensors: CFX3 compartment temperature and battery voltage; FreshJet temperature,
power, current and operating state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DometicDdmConfigEntry
from .coordinator import DometicDdmCoordinator
from .entity import DometicDdmEntity
from .pyddm import Protocol


@dataclass(frozen=True, kw_only=True)
class DdmSensorDescription(SensorEntityDescription):
    """Sensor bound to one parameter."""

    group: str
    parameter: str
    enum_states: Mapping[int, str] | None = None
    """For ENUM sensors: raw value → option key."""


CFX3_SENSORS: tuple[DdmSensorDescription, ...] = (
    DdmSensorDescription(
        key="c0_measured_temperature",
        translation_key="measured_temperature",
        group="compartment",
        parameter="c0MeasuredTemperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    DdmSensorDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        group="power",
        parameter="batteryVoltageLevel",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
    ),
)

# ac.operst enum from the dictionary: 0 FanOnly, 1 Cool, 2 Heat.
OPERATING_STATES: Mapping[int, str] = {0: "fan_only", 1: "cooling", 2: "heating"}

FJZ7_SENSORS: tuple[DdmSensorDescription, ...] = (
    DdmSensorDescription(
        key="inside_temperature",
        translation_key="inside_temperature",
        group="ac",
        parameter="itemp",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    ),
    # Dictionary says factor 1000 → W. Observed 29 "W" at 1.6 A while cooling, which is
    # ~10x too low; the real factor may be 100. Needs verification against a plug meter.
    DdmSensorDescription(
        key="power",
        translation_key="power",
        group="ac",
        parameter="pwr",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=0,
    ),
    DdmSensorDescription(
        key="current",
        translation_key="current",
        group="ac",
        parameter="curr",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=1,
    ),
    DdmSensorDescription(
        key="operating_state",
        translation_key="operating_state",
        group="ac",
        parameter="operst",
        device_class=SensorDeviceClass.ENUM,
        options=list(OPERATING_STATES.values()),
        enum_states=OPERATING_STATES,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DometicDdmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors for the device's protocol."""
    coordinator = entry.runtime_data
    descriptions = CFX3_SENSORS if coordinator.protocol is Protocol.DDM1 else FJZ7_SENSORS
    async_add_entities(DdmSensor(coordinator, desc) for desc in descriptions)


class DdmSensor(DometicDdmEntity, SensorEntity):
    """A numeric or enum parameter."""

    entity_description: DdmSensorDescription

    def __init__(
        self, coordinator: DometicDdmCoordinator, description: DdmSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | str | None:
        desc = self.entity_description
        if desc.enum_states is not None:
            raw = self._int(desc.group, desc.parameter)
            return None if raw is None else desc.enum_states.get(raw)
        return self._float(desc.group, desc.parameter)
