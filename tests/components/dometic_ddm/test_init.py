"""Setup against a simulated CFX3: handshake, subscriptions, entities, writes, reconnect."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.components.climate import (
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.components.select import (
    ATTR_OPTION,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.select import (
    DOMAIN as SELECT_DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dometic_ddm.const import CFX3_SUBSCRIPTIONS, DOMAIN

from .conftest import CFX3_ADDRESS
from .fake_cfx3 import FakeCfx3Client

TEMP = "sensor.cfx3_45_temperature"
VOLTAGE = "sensor.cfx3_45_battery_voltage"
DOOR = "binary_sensor.cfx3_45_door"
COMPRESSOR = "binary_sensor.cfx3_45_compressor"
CLIMATE = "climate.cfx3_45_compartment"
PROTECTION = "select.cfx3_45_battery_protection"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_runs_handshake_and_creates_entities(
    hass: HomeAssistant, cfx3_entry: MockConfigEntry, patched_ble: FakeCfx3Client
) -> None:
    await _setup(hass, cfx3_entry)
    assert cfx3_entry.state is ConfigEntryState.LOADED

    # Handshake per docs: device 04 → we 03 → device 04, then one SUBSCRIBE per topic,
    # and an ACK for every PUBLISH the device sent.
    assert patched_ble.writes[0] == b"\x03"
    subscribes = [w for w in patched_ble.writes if w[0] == 0x01]
    assert len(subscribes) == len(CFX3_SUBSCRIPTIONS)
    assert subscribes[0] == bytes([0x01, 0x00, 0xC0, 0x00, 0x00])  # productModelNumber first
    assert b"\x01\x01\x00\x00\x81" not in patched_ble.writes  # bulk topic not used by default
    assert patched_ble.acks_received == len(CFX3_SUBSCRIPTIONS)
    assert patched_ble.pair_requested is True  # DDM1 defaults to bonding (open question 2)

    assert hass.states.get(TEMP).state == "-24.6"
    assert hass.states.get(VOLTAGE).state == "12.6"
    assert hass.states.get(DOOR).state == STATE_OFF
    assert hass.states.get(COMPRESSOR).state == STATE_ON
    assert hass.states.get(PROTECTION).state == "medium"

    climate = hass.states.get(CLIMATE)
    assert climate.state == HVACMode.COOL
    assert climate.attributes[ATTR_TEMPERATURE] == -18.0
    assert climate.attributes["current_temperature"] == -24.6
    assert climate.attributes[ATTR_HVAC_ACTION] == HVACAction.COOLING
    assert climate.attributes[ATTR_MIN_TEMP] == -22.0
    assert climate.attributes[ATTR_MAX_TEMP] == 10.0

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, CFX3_ADDRESS)})
    assert device is not None
    assert device.manufacturer == "Dometic"
    assert device.model == "CFX3 45"
    assert device.sw_version == "1.2.3"
    assert device.serial_number == "SN123456"


async def test_pushed_updates_reach_entities(
    hass: HomeAssistant, cfx3_entry: MockConfigEntry, patched_ble: FakeCfx3Client
) -> None:
    await _setup(hass, cfx3_entry)
    patched_ble.publish("compartment", "c0DoorOpen", True)
    patched_ble.publish("compartment", "c0MeasuredTemperature", -20.1)
    patched_ble.publish("power", "compressorPower", False)
    await hass.async_block_till_done()
    assert hass.states.get(DOOR).state == STATE_ON
    assert hass.states.get(TEMP).state == "-20.1"
    assert hass.states.get(CLIMATE).attributes[ATTR_HVAC_ACTION] == HVACAction.IDLE


async def test_climate_writes_publish_frames(
    hass: HomeAssistant, cfx3_entry: MockConfigEntry, patched_ble: FakeCfx3Client
) -> None:
    await _setup(hass, cfx3_entry)
    patched_ble.writes.clear()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: CLIMATE, ATTR_TEMPERATURE: 4},
        blocking=True,
    )
    await hass.async_block_till_done()
    # DDM1 writes with PUBLISH: 00 + topic c0SetTemperature + int16 LE 40 (= 4.0 °C)
    assert patched_ble.writes[0] == bytes([0x00, 0x00, 0x02, 0x01, 0x01, 0x28, 0x00])
    assert hass.states.get(CLIMATE).attributes[ATTR_TEMPERATURE] == 4.0  # echoed by device

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: CLIMATE, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert bytes([0x00, 0x00, 0x00, 0x01, 0x01, 0x00]) in patched_ble.writes
    assert hass.states.get(CLIMATE).state == HVACMode.OFF
    assert hass.states.get(CLIMATE).attributes[ATTR_HVAC_ACTION] == HVACAction.OFF


async def test_select_writes_enum_value(
    hass: HomeAssistant, cfx3_entry: MockConfigEntry, patched_ble: FakeCfx3Client
) -> None:
    await _setup(hass, cfx3_entry)
    patched_ble.writes.clear()
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: PROTECTION, ATTR_OPTION: "high"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert patched_ble.writes[0] == bytes([0x00, 0x00, 0x02, 0x03, 0x01, 0x02])
    assert hass.states.get(PROTECTION).state == "high"


async def test_disconnect_reconnects_immediately(
    hass: HomeAssistant, cfx3_entry: MockConfigEntry, patched_ble: FakeCfx3Client
) -> None:
    await _setup(hass, cfx3_entry)
    patched_ble.writes.clear()
    patched_ble.drop_link()
    await hass.async_block_till_done()
    # A fresh connection with a fresh handshake, no manual intervention.
    assert patched_ble.writes[0] == b"\x03"
    assert hass.states.get(TEMP).state == "-24.6"


async def test_disconnect_out_of_range_marks_unavailable_then_recovers(
    hass: HomeAssistant, cfx3_entry: MockConfigEntry, patched_ble: FakeCfx3Client
) -> None:
    await _setup(hass, cfx3_entry)
    coordinator = cfx3_entry.runtime_data
    with patch(
        "custom_components.dometic_ddm.coordinator.bluetooth.async_ble_device_from_address",
        return_value=None,
    ):
        patched_ble.drop_link()
        await hass.async_block_till_done()
        assert hass.states.get(TEMP).state == STATE_UNAVAILABLE
        assert hass.states.get(CLIMATE).state == STATE_UNAVAILABLE
        with pytest.raises(HomeAssistantError, match="not connected"):
            await coordinator.async_write("compartment", "c0Power", True)

    # Back in range: the watchdog refresh reconnects and values return.
    patched_ble.writes.clear()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert patched_ble.writes[0] == b"\x03"
    assert hass.states.get(TEMP).state == "-24.6"


async def test_setup_retries_when_out_of_range(
    hass: HomeAssistant, cfx3_entry: MockConfigEntry
) -> None:
    cfx3_entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.dometic_ddm.coordinator.bluetooth.async_ble_device_from_address",
            return_value=None,
        ),
        patch(
            "custom_components.dometic_ddm.coordinator.bluetooth.async_register_callback",
            return_value=lambda: None,
        ),
    ):
        assert not await hass.config_entries.async_setup(cfx3_entry.entry_id)
        await hass.async_block_till_done()
    assert cfx3_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_retries_on_handshake_timeout(
    hass: HomeAssistant, cfx3_entry: MockConfigEntry, patched_ble: FakeCfx3Client
) -> None:
    async def silent_start_notify(char: object, callback: object) -> None:
        return  # device never sends its ACK

    patched_ble.start_notify = silent_start_notify  # type: ignore[method-assign]
    cfx3_entry.add_to_hass(hass)
    with patch("custom_components.dometic_ddm.coordinator.HANDSHAKE_TIMEOUT_SECONDS", 0.05):
        assert not await hass.config_entries.async_setup(cfx3_entry.entry_id)
        await hass.async_block_till_done()
    assert cfx3_entry.state is ConfigEntryState.SETUP_RETRY
    assert not patched_ble.is_connected  # session closed the client


async def test_unload_disconnects(
    hass: HomeAssistant, cfx3_entry: MockConfigEntry, patched_ble: FakeCfx3Client
) -> None:
    await _setup(hass, cfx3_entry)
    assert patched_ble.is_connected
    assert await hass.config_entries.async_unload(cfx3_entry.entry_id)
    await hass.async_block_till_done()
    assert cfx3_entry.state is ConfigEntryState.NOT_LOADED
    assert not patched_ble.is_connected
    assert hass.states.get(TEMP).state == STATE_UNAVAILABLE
