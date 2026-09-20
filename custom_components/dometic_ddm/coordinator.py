"""Coordinator: owns the BLE connection and the pyddm session for one device.

Values are pushed by the device; the coordinator's periodic update only checks the link
and reconnects. Every decoded update is published to entities immediately.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import logging
from typing import Any

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CFX3_SUBSCRIPTIONS,
    CONF_PAIR,
    CONF_PROTOCOL,
    CONNECT_MAX_ATTEMPTS,
    DOMAIN,
    FJZ7_SUBSCRIPTIONS,
    HANDSHAKE_TIMEOUT_SECONDS,
    MANUFACTURER,
    UPDATE_INTERVAL_SECONDS,
)
from .pyddm import Protocol, Session, SessionError, Update
from .pyddm.ddm1 import default_table as ddm1_table
from .pyddm.ddm2 import default_table as ddm2_table
from .pyddm.session import DDM1_HANDSHAKE_WITH_PING, DDM2_HANDSHAKE_NONE
from .pyddm.transport.base import TransportError
from .pyddm.transport.ble import BleTransport

_LOGGER = logging.getLogger(__name__)

type DdmData = dict[str, Update]
"""Latest update per parameter, keyed by ``group.name`` (DDM1) or ``class.param`` (DDM2)."""


class DometicDdmCoordinator(DataUpdateCoordinator[DdmData]):
    """Keep one DDM device connected and fan out its pushed values."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.address: str = entry.data[CONF_ADDRESS]
        self.device_name: str = entry.data.get(CONF_NAME) or self.address
        self.protocol = Protocol(entry.data[CONF_PROTOCOL])
        # Bonding is mandatory: both a FreshJet and a CFX3 drop unbonded centrals within a
        # few seconds (verified 2026-09-20). bleak's BlueZ backend pairs *before* opening the
        # link when asked, which is the sequence the devices accept; the device must be in
        # its pairing mode the first time, afterwards the bond is reused. Whether a bond
        # survives an HA restart through an ESPHome proxy is open question 2.
        self._pair: bool = entry.options.get(CONF_PAIR, True)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.device_name}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SECONDS),
        )
        self.data: DdmData = {}
        self._session: Session | None = None
        self._client: BleakClientWithServiceCache | None = None
        self._unregister_adv: Callable[[], None] | None = None
        self._shutting_down = False

    # -- public --------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        """True while the session is ready and the link is up."""
        return (
            self._session is not None and self._session.ready and self._session.transport.connected
        )

    def value(self, group: str, name: str) -> Any:
        """Latest decoded value of a parameter, or None if not received / undecodable."""
        update = self.data.get(f"{group}.{name}")
        return None if update is None or update.error is not None else update.value

    def topic(self, group: str, name: str) -> bytes:
        """Topic bytes for a parameter of the active protocol."""
        if self.protocol is Protocol.DDM1:
            return ddm1_table().topic_for(group, name)
        return ddm2_table().topic_for(group, name)

    def enum_name(self, class_name: str, name: str) -> str | None:
        """Dictionary enum name of a DDM2 parameter's current value, or None."""
        value = self.value(class_name, name)
        if self.protocol is not Protocol.DDM2 or not isinstance(value, int):
            return None
        return ddm2_table().get(class_name, name).enum_name(value)

    def device_info(self) -> DeviceInfo:
        """Device registry entry, filled in as identification parameters arrive."""
        info = DeviceInfo(
            identifiers={(DOMAIN, self.address)},
            connections={(CONNECTION_BLUETOOTH, self.address)},
            name=self.device_name,
            manufacturer=MANUFACTURER,
        )
        if self.protocol is Protocol.DDM1:
            model = self.value("productInformation", "productModelNumber")
            firmware = self.value("deviceSpecific", "ccFirmwareVersion")
            serial = self.value("productInformation", "productSerialNumber")
            info["model"] = str(model) if model else "CFX3"
            if firmware:
                info["sw_version"] = str(firmware)
            if serial:
                info["serial_number"] = str(serial)
            return info
        info["model"] = self.enum_name("ac", "mdl") or "FreshJet"
        if firmware := self.value("ac", "ver"):
            info["sw_version"] = str(firmware)
        if gateway := self.value("gw", "ver"):
            info["hw_version"] = f"gateway {gateway}"
        if sku := self.value("gw", "sku"):
            info["model_id"] = str(sku)
        if serial := self.value("gw", "dsn"):
            info["serial_number"] = str(serial)
        return info

    async def async_write(self, group: str, name: str, value: Any) -> None:
        """Write one parameter (DDM1 PUBLISH / DDM2 SET)."""
        session = self._session
        if session is None or not self.connected:
            raise HomeAssistantError(f"{self.device_name} is not connected")
        topic = self.topic(group, name)
        try:
            await session.write(topic, value)
            if self.protocol is Protocol.DDM1:
                # A CFX3 ACKs and applies a write but does not publish the new value on its
                # own (verified 2026-09-20); a FreshJet echoes it. Ask for it explicitly.
                await session.subscribe(topic)
        except (SessionError, TransportError, ValueError) as err:
            raise HomeAssistantError(f"Write to {group}.{name} failed: {err}") from err

    async def async_shutdown(self) -> None:
        """Disconnect and stop."""
        self._shutting_down = True
        if self._unregister_adv is not None:
            self._unregister_adv()
            self._unregister_adv = None
        await self._async_close_session()
        await super().async_shutdown()

    # -- DataUpdateCoordinator -----------------------------------------------------

    async def _async_setup(self) -> None:
        # Reconnect promptly when the device comes back into range instead of waiting for
        # the next watchdog tick.
        self._unregister_adv = bluetooth.async_register_callback(
            self.hass,
            self._async_on_advertisement,
            BluetoothCallbackMatcher(address=self.address, connectable=True),
            BluetoothScanningMode.ACTIVE,
        )

    async def _async_update_data(self) -> DdmData:
        if not self.connected:
            await self._async_connect()
        return self.data

    # -- connection ----------------------------------------------------------------

    def _ble_device(self) -> BLEDevice | None:
        return bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)

    async def _async_connect(self) -> None:
        await self._async_close_session()
        ble_device = self._ble_device()
        if ble_device is None:
            raise UpdateFailed(
                f"{self.device_name} ({self.address}) is not in range of any adapter"
            )
        _LOGGER.debug("Connecting to %s (%s, %s)", self.device_name, self.address, self.protocol)
        try:
            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self.device_name,
                disconnected_callback=self._on_bleak_disconnected,
                ble_device_callback=self._ble_device,
                max_attempts=CONNECT_MAX_ATTEMPTS,
                pair=self._pair,
            )
        except Exception as err:  # bleak/backends raise many exception types
            raise UpdateFailed(f"Connecting to {self.device_name} failed: {err}") from err

        self._client = client
        transport = BleTransport(client, self.protocol, owns_client=True)
        transport.on_disconnect(self._on_transport_disconnect)
        session = Session(
            self.protocol,
            transport,
            # CFX3: client opens with PING, ACKs every device PING (or nothing is published).
            # FreshJet: no handshake at all. Both verified 2026-09-20.
            handshake=(
                DDM1_HANDSHAKE_WITH_PING if self.protocol is Protocol.DDM1 else DDM2_HANDSHAKE_NONE
            ),
            on_update=self._on_update,
            on_error=self._on_session_error,
            logger=_LOGGER,
        )
        self._session = session
        try:
            await session.start(ready_timeout=HANDSHAKE_TIMEOUT_SECONDS)
            await session.subscribe_many([self.topic(g, n) for g, n in self._subscriptions()])
        except TimeoutError as err:
            await self._async_close_session()
            raise UpdateFailed(
                f"{self.device_name} did not complete the {self.protocol.value.upper()} handshake "
                f"within {HANDSHAKE_TIMEOUT_SECONDS}s (is the device bonded? put it in pairing "
                "mode and reload)"
            ) from err
        except (TransportError, SessionError) as err:
            await self._async_close_session()
            raise UpdateFailed(f"Session setup with {self.device_name} failed: {err}") from err
        _LOGGER.info("Connected to %s (%s)", self.device_name, self.protocol.value.upper())

    def _subscriptions(self) -> tuple[tuple[str, str], ...]:
        if self.protocol is Protocol.DDM1:
            return CFX3_SUBSCRIPTIONS
        return FJZ7_SUBSCRIPTIONS

    async def _async_close_session(self) -> None:
        session, self._session = self._session, None
        self._client = None
        if session is not None:
            try:
                await session.close()
            except Exception:  # teardown must never raise
                _LOGGER.debug("Closing session to %s failed", self.device_name, exc_info=True)

    # -- callbacks -----------------------------------------------------------------

    @callback
    def _on_update(self, update: Update) -> None:
        _LOGGER.debug(
            "%s: %s = %r (raw %s)", self.device_name, update.name, update.value, update.raw.hex(" ")
        )
        new_data = dict(self.data)
        new_data[update.name] = update
        self.async_set_updated_data(new_data)

    @callback
    def _on_session_error(self, err: Exception) -> None:
        _LOGGER.debug("%s: session error: %s", self.device_name, err)

    def _on_bleak_disconnected(self, client: BleakClientWithServiceCache) -> None:
        # bleak may call this from a non-loop thread depending on backend.
        self.hass.loop.call_soon_threadsafe(self._handle_disconnect, client)

    @callback
    def _handle_disconnect(self, client: BleakClientWithServiceCache | None) -> None:
        if client is not None and client is not self._client:
            return  # stale callback from a previous connection
        if self._shutting_down:
            return
        _LOGGER.warning("%s disconnected", self.device_name)
        if self._session is not None:
            transport = self._session.transport
            if isinstance(transport, BleTransport):
                transport.handle_disconnected()
        self.hass.async_create_task(self._async_after_disconnect())

    async def _async_after_disconnect(self) -> None:
        await self._async_close_session()
        self.async_set_update_error(UpdateFailed(f"{self.device_name} disconnected"))
        await self.async_request_refresh()

    @callback
    def _on_transport_disconnect(self) -> None:
        # BleTransport.handle_disconnected() is only ever triggered from _handle_disconnect,
        # so nothing extra to do here; kept for transports that detect drops themselves.
        return

    @callback
    def _async_on_advertisement(
        self, service_info: BluetoothServiceInfoBleak, change: BluetoothChange
    ) -> None:
        if not self.connected and not self._shutting_down:
            _LOGGER.debug("%s seen again (%s); scheduling reconnect", self.device_name, change)
            self.hass.async_create_task(self.async_request_refresh())
