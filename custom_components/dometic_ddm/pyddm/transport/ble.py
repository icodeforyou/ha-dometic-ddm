"""BLE transport on top of bleak.

Works with any ``BleakClient``-compatible object, including the clients returned by
``bleak_retry_connector.establish_connection`` in Home Assistant (which route through
ESPHome bluetooth proxies transparently).

Needs verification on hardware:
* whether the device requires bonding before it accepts writes/notifications (the app
  bonds on Android). Bonding is the caller's job (``establish_connection(pair=True)`` or
  ``client.pair()``); this transport does not pair.
* whether the default MTU is enough. The app requests MTU 153; bleak cannot request an
  MTU portably, so we only log the negotiated value.
* write-with-response vs. write-without-response. ``write_response=None`` lets bleak pick
  based on the characteristic's properties, like the app's BLE library does.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from typing import Protocol as TypingProtocol

from ..const import APP_REQUESTED_MTU, NOTIFY_UUIDS, WRITE_UUIDS, Protocol
from .base import Transport, TransportError

if TYPE_CHECKING:
    from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)


class BleakClientLike(TypingProtocol):
    """The subset of ``bleak.BleakClient`` this transport needs (keeps bleak optional)."""

    @property
    def is_connected(self) -> bool: ...

    @property
    def mtu_size(self) -> int: ...

    async def connect(self, **kwargs: Any) -> Any: ...

    async def disconnect(self) -> Any: ...

    async def start_notify(self, char_specifier: Any, callback: Callable[..., Any]) -> None: ...

    async def stop_notify(self, char_specifier: Any) -> None: ...

    async def write_gatt_char(
        self, char_specifier: Any, data: Any, response: bool | None = None
    ) -> None: ...


class BleTransport(Transport):
    """Raw frame channel over the DDM1 or DDM2 GATT characteristics."""

    def __init__(
        self,
        client: BleakClientLike,
        protocol: Protocol,
        *,
        owns_client: bool = True,
        write_response: bool | None = None,
    ) -> None:
        """Wrap ``client``.

        ``owns_client=False`` means the caller connected the client and will disconnect
        it; :meth:`disconnect` then only stops notifications.
        """
        super().__init__()
        self._client = client
        self._protocol = protocol
        self._owns_client = owns_client
        self._write_response = write_response
        self._write_uuid = WRITE_UUIDS[protocol]
        self._notify_uuid = NOTIFY_UUIDS[protocol]
        self._notifying = False

    @property
    def connected(self) -> bool:
        return self._notifying and self._client.is_connected

    @property
    def client(self) -> BleakClientLike:
        """The wrapped client."""
        return self._client

    async def connect(self) -> None:
        if not self._client.is_connected:
            if not self._owns_client:
                raise TransportError("client is not connected")
            try:
                await self._client.connect()
            except Exception as err:  # bleak raises backend-specific exception types
                raise TransportError(f"BLE connect failed: {err}") from err
        mtu = self._client.mtu_size
        if mtu < APP_REQUESTED_MTU:
            _LOGGER.debug(
                "%s: reported MTU %d is below the app's requested %d "
                "(BlueZ reports 23 until the first write; needs verification whether it matters)",
                self._protocol.value,
                mtu,
                APP_REQUESTED_MTU,
            )
        try:
            await self._client.start_notify(self._notify_uuid, self._on_gatt_notify)
        except Exception as err:
            if not self._client.is_connected:
                raise TransportError(
                    f"device dropped the link while notifications were being enabled: {err} "
                    "(weak signal or the device wants a bond first?)"
                ) from err
            raise TransportError(f"enabling notifications failed: {err}") from err
        self._notifying = True

    async def disconnect(self) -> None:
        was_notifying = self._notifying
        self._notifying = False
        if was_notifying and self._client.is_connected:
            try:
                await self._client.stop_notify(self._notify_uuid)
            except Exception:  # best effort during teardown
                _LOGGER.debug("stop_notify failed during disconnect", exc_info=True)
        if self._owns_client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except Exception:  # best effort during teardown
                _LOGGER.debug("disconnect failed during teardown", exc_info=True)

    async def write(self, data: bytes) -> None:
        if not self._client.is_connected:
            raise TransportError("not connected")
        try:
            await self._client.write_gatt_char(
                self._write_uuid, bytes(data), response=self._write_response
            )
        except Exception as err:
            raise TransportError(f"BLE write failed: {err}") from err

    def _on_gatt_notify(self, _sender: Any, data: bytearray) -> None:
        self._deliver(bytes(data))

    def handle_disconnected(self) -> None:
        """Called by the owner when bleak reports the link dropped."""
        self._notifying = False
        self._notify_disconnect()
