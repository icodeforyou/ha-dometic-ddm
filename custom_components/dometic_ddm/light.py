"""FreshJet interior light (``ac.lgt`` on/off, ``ac.dmr`` dimmer in percent)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.color import brightness_to_value, value_to_brightness

from . import DometicDdmConfigEntry
from .coordinator import DometicDdmCoordinator
from .entity import DometicDdmEntity
from .pyddm import Protocol

DIMMER_RANGE = (1, 100)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DometicDdmConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the FreshJet light. CFX3 has none."""
    coordinator = entry.runtime_data
    if coordinator.protocol is not Protocol.DDM2:
        return
    async_add_entities([FreshJetLight(coordinator)])


class FreshJetLight(DometicDdmEntity, LightEntity):
    """On/off verified on a FJZ7 2600 (2026-09-20; the unit echoed ``lgt`` and re-published
    ``dmr = 100`` when switched on). Dimming via ``ac.dmr`` is from the dictionary only and
    needs verification."""

    _attr_translation_key = "light"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator: DometicDdmCoordinator) -> None:
        super().__init__(coordinator, "light")

    @property
    def is_on(self) -> bool | None:
        return self._bool("ac", "lgt")

    @property
    def brightness(self) -> int | None:
        percent = self._int("ac", "dmr")
        if percent is None:
            return None
        return value_to_brightness(DIMMER_RANGE, max(DIMMER_RANGE[0], min(percent, 100)))

    async def async_turn_on(self, **kwargs: Any) -> None:
        if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
            percent = round(brightness_to_value(DIMMER_RANGE, brightness))
            await self.coordinator.async_write("ac", "dmr", percent)
        await self.coordinator.async_write("ac", "lgt", 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write("ac", "lgt", 0)
