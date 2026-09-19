"""Config flow: discover DDM1/DDM2 devices over Bluetooth and store address + protocol."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.helpers.device_registry import format_mac
import voluptuous as vol

from .const import CONF_PROTOCOL, DOMAIN
from .pyddm import Protocol, protocol_from_advertisement

_LOGGER = logging.getLogger(__name__)


def classify(info: BluetoothServiceInfoBleak) -> Protocol | None:
    """Protocol for a discovered device, or None if it is not a DDM device."""
    return protocol_from_advertisement(info.name, info.service_uuids, list(info.manufacturer_data))


def _title(info: BluetoothServiceInfoBleak) -> str:
    return info.name or info.address


def _protocol_label(info: BluetoothServiceInfoBleak) -> str:
    protocol = classify(info)
    return protocol.value.upper() if protocol is not None else "?"


class DometicDdmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle Bluetooth discovery and manual selection."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a device found by the bluetooth matchers in manifest.json."""
        protocol = classify(discovery_info)
        if protocol is None:
            return self.async_abort(reason="not_supported")
        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {"name": _title(discovery_info)}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm the discovered device."""
        assert self._discovery is not None
        info = self._discovery
        protocol = classify(info)
        assert protocol is not None
        if user_input is not None:
            return self._create(info, protocol)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": _title(info),
                "protocol": protocol.value.upper(),
                "address": info.address,
            },
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Let the user pick from currently visible, not yet configured DDM devices."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            info = self._discovered[address]
            protocol = classify(info)
            assert protocol is not None
            await self.async_set_unique_id(format_mac(address), raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self._create(info, protocol)

        configured = self._async_current_ids(include_ignore=False)
        for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
            if format_mac(info.address) in configured or classify(info) is None:
                continue
            self._discovered[info.address] = info
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")

        options = {
            address: f"{_title(info)} ({address}, {_protocol_label(info)})"
            for address, info in self._discovered.items()
        }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(options)}),
        )

    def _create(self, info: BluetoothServiceInfoBleak, protocol: Protocol) -> ConfigFlowResult:
        return self.async_create_entry(
            title=_title(info),
            data={
                CONF_ADDRESS: info.address,
                CONF_NAME: _title(info),
                CONF_PROTOCOL: protocol.value,
            },
        )
