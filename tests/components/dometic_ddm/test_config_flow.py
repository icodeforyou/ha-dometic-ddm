"""Config flow: bluetooth discovery and manual selection."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dometic_ddm.const import CONF_PROTOCOL, DOMAIN

from .conftest import (
    CFX3_ADDRESS,
    CFX3_NAME,
    CFX3_SERVICE_INFO,
    FJZ7_ADDRESS,
    FJZ7_SERVICE_INFO,
    UNRELATED_SERVICE_INFO,
)


async def test_bluetooth_discovery_cfx3(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=CFX3_SERVICE_INFO
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "bluetooth_confirm"
    assert result["description_placeholders"] == {
        "name": CFX3_NAME,
        "protocol": "DDM1",
        "address": CFX3_ADDRESS,
    }

    with patch("custom_components.dometic_ddm.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == CFX3_NAME
    assert result["data"] == {
        CONF_ADDRESS: CFX3_ADDRESS,
        CONF_NAME: CFX3_NAME,
        CONF_PROTOCOL: "ddm1",
    }
    assert result["result"].unique_id == CFX3_ADDRESS.lower()


async def test_bluetooth_discovery_ddm2_by_manufacturer_id(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=FJZ7_SERVICE_INFO
    )
    assert result["type"] is FlowResultType.FORM
    assert result["description_placeholders"]["protocol"] == "DDM2"
    with patch("custom_components.dometic_ddm.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input={})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PROTOCOL] == "ddm2"
    assert result["data"][CONF_ADDRESS] == FJZ7_ADDRESS


async def test_bluetooth_discovery_rejects_unrelated_device(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=UNRELATED_SERVICE_INFO
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_supported"


async def test_bluetooth_discovery_already_configured(
    hass: HomeAssistant, cfx3_entry: MockConfigEntry
) -> None:
    cfx3_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=CFX3_SERVICE_INFO
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_lists_only_ddm_devices(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.dometic_ddm.config_flow.bluetooth.async_discovered_service_info",
        return_value=[CFX3_SERVICE_INFO, UNRELATED_SERVICE_INFO, FJZ7_SERVICE_INFO],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    schema = result["data_schema"]
    assert schema is not None
    options = next(iter(schema.schema.values())).container
    assert set(options) == {CFX3_ADDRESS, FJZ7_ADDRESS}
    assert "DDM1" in options[CFX3_ADDRESS]

    with patch("custom_components.dometic_ddm.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={CONF_ADDRESS: CFX3_ADDRESS}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PROTOCOL] == "ddm1"


async def test_user_flow_no_devices(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.dometic_ddm.config_flow.bluetooth.async_discovered_service_info",
        return_value=[UNRELATED_SERVICE_INFO],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"


async def test_user_flow_skips_configured(hass: HomeAssistant, cfx3_entry: MockConfigEntry) -> None:
    cfx3_entry.add_to_hass(hass)
    with patch(
        "custom_components.dometic_ddm.config_flow.bluetooth.async_discovered_service_info",
        return_value=[CFX3_SERVICE_INFO],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_devices_found"
