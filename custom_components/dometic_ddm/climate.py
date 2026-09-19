"""CFX3 compartment 0 as a climate entity: target temperature and power."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import PRECISION_TENTHS, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DometicDdmConfigEntry
from .const import FALLBACK_MAX_TEMP_C, FALLBACK_MIN_TEMP_C
from .coordinator import DometicDdmCoordinator
from .entity import DometicDdmEntity
from .pyddm import Protocol


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DometicDdmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the CFX3 compartment climate entity."""
    coordinator = entry.runtime_data
    if coordinator.protocol is not Protocol.DDM1:
        return
    async_add_entities([CompartmentClimate(coordinator)])


class CompartmentClimate(DometicDdmEntity, ClimateEntity):
    """Compartment 0 of a CFX3.

    Power maps to ``compartment.c0Power``; the target temperature to ``c0SetTemperature``.
    Whole-degree steps match the cooler's own display; the wire format allows 0.1 °C and
    a device may report tenths (needs verification).
    """

    _attr_translation_key = "compartment"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_TENTHS
    _attr_target_temperature_step = 1.0
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: DometicDdmCoordinator) -> None:
        super().__init__(coordinator, "c0_climate")

    @property
    def hvac_mode(self) -> HVACMode | None:
        power = self._value("compartment", "c0Power")
        if power is None:
            return None
        return HVACMode.COOL if power else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        power = self._value("compartment", "c0Power")
        if power is None:
            return None
        if not power:
            return HVACAction.OFF
        compressor = self._value("power", "compressorPower")
        if compressor is None:
            return None
        return HVACAction.COOLING if compressor else HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        value = self._value("compartment", "c0MeasuredTemperature")
        return float(value) if isinstance(value, int | float) else None

    @property
    def target_temperature(self) -> float | None:
        value = self._value("compartment", "c0SetTemperature")
        return float(value) if isinstance(value, int | float) else None

    @property
    def min_temp(self) -> float:
        value = self._value("compartment", "c0TemperatureRange")
        if isinstance(value, tuple) and len(value) == 2:
            return float(value[0])
        return FALLBACK_MIN_TEMP_C

    @property
    def max_temp(self) -> float:
        value = self._value("compartment", "c0TemperatureRange")
        if isinstance(value, tuple) and len(value) == 2:
            return float(value[1])
        return FALLBACK_MAX_TEMP_C

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.async_write("compartment", "c0SetTemperature", float(temperature))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.coordinator.async_write("compartment", "c0Power", hvac_mode == HVACMode.COOL)

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.COOL)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
