"""FreshJet FJZ7 entities against a simulator that replays the 2026-09-20 captures."""

from __future__ import annotations

from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    SERVICE_SET_FAN_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
)
from homeassistant.components.light import (
    DOMAIN as LIGHT_DOMAIN,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dometic_ddm.const import DOMAIN, FJZ7_SUBSCRIPTIONS

from .conftest import FJZ7_ADDRESS
from .fake_freshjet import FakeFreshJetClient

CLIMATE = "climate.fjz7_2600"
LIGHT = "light.fjz7_2600_light"
SLEEP = "switch.fjz7_2600_sleep_mode"
INSIDE = "sensor.fjz7_2600_inside_temperature"
POWER = "sensor.fjz7_2600_power"
CURRENT = "sensor.fjz7_2600_current"
OPERST = "sensor.fjz7_2600_operating_state"
COMPRESSOR = "binary_sensor.fjz7_2600_compressor"
PROBLEM = "binary_sensor.fjz7_2600_error"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_no_handshake_and_entities(
    hass: HomeAssistant, fjz7_entry: MockConfigEntry, patched_ble_fjz7: FakeFreshJetClient
) -> None:
    await _setup(hass, fjz7_entry)
    assert fjz7_entry.state is ConfigEntryState.LOADED
    # No HELLO/PING for DDM2, straight to SUBSCRIBEs, one per profile parameter.
    assert all(w[0] == 0x12 for w in patched_ble_fjz7.writes)
    assert len(patched_ble_fjz7.writes) == len(FJZ7_SUBSCRIPTIONS)
    assert patched_ble_fjz7.writes[0] == bytes([0x12, 0x00, 0x00, 0x00, 0x00])  # gw.avl
    assert patched_ble_fjz7.pair_requested is True

    climate = hass.states.get(CLIMATE)
    assert climate.state == HVACMode.FAN_ONLY
    assert climate.attributes[ATTR_TEMPERATURE] == 22.0
    assert climate.attributes["current_temperature"] == 26.0
    assert climate.attributes[ATTR_FAN_MODE] == "2"
    assert climate.attributes[ATTR_HVAC_ACTION] == HVACAction.FAN
    assert HVACMode.DRY in climate.attributes[ATTR_HVAC_MODES]
    assert "turbo" not in [m.lower() for m in climate.attributes[ATTR_HVAC_MODES]]

    assert hass.states.get(LIGHT).state == STATE_OFF
    assert hass.states.get(SLEEP).state == STATE_OFF
    assert hass.states.get(INSIDE).state == "26.0"
    assert hass.states.get(POWER).state == "0.0"
    assert hass.states.get(CURRENT).state == "0.6"
    assert hass.states.get(OPERST).state == "unknown"  # operst only publishes on change
    assert hass.states.get(COMPRESSOR).state == STATE_OFF
    assert hass.states.get(PROBLEM).state == STATE_OFF

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, FJZ7_ADDRESS), fjz7_entry.entry_id
    )
    assert device is not None
    assert device.model == "Dometic FJZ7000 series"
    assert device.sw_version == "2.2.0"
    assert device.hw_version == "gateway 2.2.1"
    assert device.model_id == "9600051000"


async def test_climate_writes_are_set_frames_and_echo_updates_state(
    hass: HomeAssistant, fjz7_entry: MockConfigEntry, patched_ble_fjz7: FakeFreshJetClient
) -> None:
    await _setup(hass, fjz7_entry)
    patched_ble_fjz7.writes.clear()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: CLIMATE, ATTR_TEMPERATURE: 24},
        blocking=True,
    )
    await hass.async_block_till_done()
    # exactly the frame captured on 2026-09-20 11:58:41
    assert patched_ble_fjz7.writes[-1] == bytes(
        [0x11, 0x04, 0x00, 0x02, 0x01, 0xC0, 0x5D, 0x00, 0x00]
    )
    assert hass.states.get(CLIMATE).attributes[ATTR_TEMPERATURE] == 24.0

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: CLIMATE, ATTR_HVAC_MODE: HVACMode.COOL},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert patched_ble_fjz7.writes[-1] == bytes([0x11, 0x03, 0x00, 0x02, 0x01, 0, 0, 0, 0])
    assert hass.states.get(CLIMATE).state == HVACMode.COOL

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: CLIMATE, ATTR_HVAC_MODE: HVACMode.OFF},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert patched_ble_fjz7.writes[-1] == bytes([0x11, 0x01, 0x00, 0x02, 0x01, 0, 0, 0, 0])
    assert hass.states.get(CLIMATE).state == HVACMode.OFF
    assert hass.states.get(CLIMATE).attributes[ATTR_HVAC_ACTION] == HVACAction.OFF

    # Turning a mode on while off first powers the unit on, then sets the mode.
    patched_ble_fjz7.writes.clear()
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: CLIMATE, ATTR_HVAC_MODE: HVACMode.AUTO},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert patched_ble_fjz7.writes[0] == bytes([0x11, 0x01, 0x00, 0x02, 0x01, 1, 0, 0, 0])
    assert patched_ble_fjz7.writes[1] == bytes([0x11, 0x03, 0x00, 0x02, 0x01, 3, 0, 0, 0])
    assert hass.states.get(CLIMATE).state == HVACMode.AUTO

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_FAN_MODE,
        {ATTR_ENTITY_ID: CLIMATE, ATTR_FAN_MODE: "5"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert patched_ble_fjz7.writes[-1] == bytes([0x11, 0x02, 0x00, 0x02, 0x01, 5, 0, 0, 0])
    assert hass.states.get(CLIMATE).attributes[ATTR_FAN_MODE] == "5"


async def test_pushed_state_from_remote_and_compressor(
    hass: HomeAssistant, fjz7_entry: MockConfigEntry, patched_ble_fjz7: FakeFreshJetClient
) -> None:
    await _setup(hass, fjz7_entry)
    # 12:00:28 burst: remote switched to Auto, operst Cool, compressor running
    patched_ble_fjz7.publish("ac", "md", 3)
    patched_ble_fjz7.publish("ac", "operst", 1)
    patched_ble_fjz7.publish("ac", "actext", 0x12)
    patched_ble_fjz7.publish("ac", "curr", 1.6)
    patched_ble_fjz7.publish("ac", "itemp", 25.5)
    await hass.async_block_till_done()
    climate = hass.states.get(CLIMATE)
    assert climate.state == HVACMode.AUTO
    assert climate.attributes[ATTR_HVAC_ACTION] == HVACAction.COOLING
    assert climate.attributes["current_temperature"] == 25.5
    assert hass.states.get(OPERST).state == "cooling"
    assert hass.states.get(COMPRESSOR).state == STATE_ON
    assert hass.states.get(CURRENT).state == "1.6"

    patched_ble_fjz7.publish("ac", "status", {"error": [0x0210]})
    await hass.async_block_till_done()
    assert hass.states.get(PROBLEM).state == STATE_ON


async def test_light_and_sleep_switch(
    hass: HomeAssistant, fjz7_entry: MockConfigEntry, patched_ble_fjz7: FakeFreshJetClient
) -> None:
    await _setup(hass, fjz7_entry)
    patched_ble_fjz7.writes.clear()
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: LIGHT}, blocking=True
    )
    await hass.async_block_till_done()
    # 11:58:24 capture: SET ac.lgt = 1
    assert patched_ble_fjz7.writes[-1] == bytes([0x11, 0x05, 0x00, 0x02, 0x01, 1, 0, 0, 0])
    assert hass.states.get(LIGHT).state == STATE_ON
    assert hass.states.get(LIGHT).attributes[ATTR_BRIGHTNESS] == 255  # dmr 100 %

    await hass.services.async_call(
        LIGHT_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: LIGHT, ATTR_BRIGHTNESS: 128},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert patched_ble_fjz7.writes[-2] == bytes(
        [0x11, 0x06, 0x00, 0x02, 0x01, 50, 0, 0, 0]
    )  # dmr 50 %
    assert patched_ble_fjz7.writes[-1] == bytes([0x11, 0x05, 0x00, 0x02, 0x01, 1, 0, 0, 0])

    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: LIGHT}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(LIGHT).state == STATE_OFF

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: SLEEP}, blocking=True
    )
    await hass.async_block_till_done()
    assert patched_ble_fjz7.writes[-1] == bytes([0x11, 0x1B, 0x00, 0x02, 0x01, 1, 0, 0, 0])
    assert hass.states.get(SLEEP).state == STATE_ON


async def test_turbo_refused_by_device_keeps_state(
    hass: HomeAssistant, fjz7_entry: MockConfigEntry, patched_ble_fjz7: FakeFreshJetClient
) -> None:
    """Turbo is not offered; if something writes md=5 the unit re-publishes its real mode."""
    await _setup(hass, fjz7_entry)
    coordinator = fjz7_entry.runtime_data
    await coordinator.async_write("ac", "md", 5)
    await hass.async_block_till_done()
    assert hass.states.get(CLIMATE).state == HVACMode.FAN_ONLY
