"""CFX3 sensors: compartment temperature and battery voltage."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfElectricPotential, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DometicDdmConfigEntry
from .coordinator import DometicDdmCoordinator
from .entity import DometicDdmEntity
from .pyddm import Protocol


@dataclass(frozen=True, kw_only=True)
class DdmSensorDescription(SensorEntityDescription):
    """Sensor bound to one DDM1 parameter."""

    group: str
    parameter: str


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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DometicDdmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up CFX3 sensors. DDM2 devices get no entities yet."""
    coordinator = entry.runtime_data
    if coordinator.protocol is not Protocol.DDM1:
        return
    async_add_entities(DdmSensor(coordinator, desc) for desc in CFX3_SENSORS)


class DdmSensor(DometicDdmEntity, SensorEntity):
    """A numeric DDM1 parameter."""

    entity_description: DdmSensorDescription

    def __init__(
        self, coordinator: DometicDdmCoordinator, description: DdmSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        value = self._value(self.entity_description.group, self.entity_description.parameter)
        return float(value) if isinstance(value, int | float) else None
