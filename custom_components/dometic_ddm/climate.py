"""Climate entities: CFX3 compartment 0 and the FreshJet air conditioner."""

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
from .const import (
    AC_ACTEXT_COMPRESSOR,
    AC_ACTEXT_HEATER,
    AC_FAN_SPEEDS,
    FALLBACK_MAX_TEMP_C,
    FALLBACK_MIN_TEMP_C,
    FJZ7_MAX_TEMP_C,
    FJZ7_MIN_TEMP_C,
)
from .coordinator import DometicDdmCoordinator
from .entity import DometicDdmEntity
from .pyddm import Protocol

# ac.md enum from the dictionary. Turbo (5) exists in the dictionary but the FJZ7 2600
# refused it (answered md = 2), so it is not offered. Verified 2026-09-20.
AC_MODE_TO_HVAC: dict[int, HVACMode] = {
    0: HVACMode.COOL,
    1: HVACMode.HEAT,
    2: HVACMode.FAN_ONLY,
    3: HVACMode.AUTO,
    4: HVACMode.DRY,
}
HVAC_TO_AC_MODE: dict[HVACMode, int] = {v: k for k, v in AC_MODE_TO_HVAC.items()}
# ac.operst: 0 FanOnly, 1 Cool, 2 Heat.
OPERST_TO_ACTION: dict[int, HVACAction] = {
    0: HVACAction.FAN,
    1: HVACAction.COOLING,
    2: HVACAction.HEATING,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DometicDdmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the climate entity for the device's protocol."""
    coordinator = entry.runtime_data
    if coordinator.protocol is Protocol.DDM1:
        async_add_entities([CompartmentClimate(coordinator)])
    else:
        async_add_entities([FreshJetClimate(coordinator)])


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
        power = self._bool("compartment", "c0Power")
        if power is None:
            return None
        return HVACMode.COOL if power else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        power = self._bool("compartment", "c0Power")
        if power is None:
            return None
        if not power:
            return HVACAction.OFF
        compressor = self._bool("power", "compressorPower")
        if compressor is None:
            return None
        return HVACAction.COOLING if compressor else HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        return self._float("compartment", "c0MeasuredTemperature")

    @property
    def target_temperature(self) -> float | None:
        return self._float("compartment", "c0SetTemperature")

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


class FreshJetClimate(DometicDdmEntity, ClimateEntity):
    """A FreshJet roof air conditioner (DDM2 ``ac`` class).

    Verified on a FJZ7 2600 (2026-09-20): ``ac.on``, ``ac.md`` and ``ac.ttemp`` writes are
    confirmed by the unit with a PUBLISH; the unit pushes ``operst``, ``fspd``, ``fmd`` and
    ``actext`` on its own when the state changes. Fan speed levels are exposed as the raw
    enum values 0-5 because the dictionary has no names for them (needs verification).
    """

    _attr_translation_key = "air_conditioner"
    _attr_name = None  # the device itself
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_TENTHS  # the unit reports tenths (25.5 °C observed)
    _attr_target_temperature_step = 1.0
    _attr_min_temp = FJZ7_MIN_TEMP_C
    _attr_max_temp = FJZ7_MAX_TEMP_C
    _attr_hvac_modes = [HVACMode.OFF, *AC_MODE_TO_HVAC.values()]
    _attr_fan_modes = list(AC_FAN_SPEEDS)
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: DometicDdmCoordinator) -> None:
        super().__init__(coordinator, "ac_climate")

    @property
    def hvac_mode(self) -> HVACMode | None:
        power = self._bool("ac", "on")
        if power is None:
            return None
        if not power:
            return HVACMode.OFF
        mode = self._int("ac", "md")
        return None if mode is None else AC_MODE_TO_HVAC.get(mode)

    @property
    def hvac_action(self) -> HVACAction | None:
        power = self._bool("ac", "on")
        if power is None:
            return None
        if not power:
            return HVACAction.OFF
        operst = self._int("ac", "operst")
        if operst is not None and operst in OPERST_TO_ACTION:
            return OPERST_TO_ACTION[operst]
        # operst only publishes on change; fall back to the active-components bitfield.
        actext = self._int("ac", "actext")
        if actext is None:
            return None
        if actext & AC_ACTEXT_COMPRESSOR:
            return HVACAction.HEATING if self.hvac_mode is HVACMode.HEAT else HVACAction.COOLING
        if actext & AC_ACTEXT_HEATER:
            return HVACAction.HEATING
        return HVACAction.FAN if self.hvac_mode is HVACMode.FAN_ONLY else HVACAction.IDLE

    @property
    def current_temperature(self) -> float | None:
        return self._float("ac", "itemp")

    @property
    def target_temperature(self) -> float | None:
        return self._float("ac", "ttemp")

    @property
    def fan_mode(self) -> str | None:
        speed = self._int("ac", "fspd")
        return str(speed) if speed is not None and str(speed) in AC_FAN_SPEEDS else None

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self.coordinator.async_write("ac", "ttemp", float(temperature))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode is HVACMode.OFF:
            await self.coordinator.async_write("ac", "on", 0)
            return
        if not self._bool("ac", "on"):
            await self.coordinator.async_write("ac", "on", 1)
        await self.coordinator.async_write("ac", "md", HVAC_TO_AC_MODE[hvac_mode])

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self.coordinator.async_write("ac", "fspd", int(fan_mode))

    async def async_turn_on(self) -> None:
        await self.coordinator.async_write("ac", "on", 1)

    async def async_turn_off(self) -> None:
        await self.coordinator.async_write("ac", "on", 0)
