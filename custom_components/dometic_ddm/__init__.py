"""Dometic DDM (CFX3, FreshJet) integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import DometicDdmCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SELECT,
    Platform.SENSOR,
]

type DometicDdmConfigEntry = ConfigEntry[DometicDdmCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: DometicDdmConfigEntry) -> bool:
    """Connect to the device and set up entities."""
    coordinator = DometicDdmCoordinator(hass, entry)
    # Raises ConfigEntryNotReady (and HA retries) if the device is out of range or the
    # handshake fails, which is the right behaviour for a battery powered BLE device.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(coordinator.async_shutdown)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DometicDdmConfigEntry) -> bool:
    """Unload entities; the coordinator shuts down via async_on_unload."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
