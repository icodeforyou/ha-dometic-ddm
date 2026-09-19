"""Abstract transport: write raw bytes, receive raw notifications."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

type NotifyCallback = Callable[[bytes], None]
type DisconnectCallback = Callable[[], None]


class TransportError(Exception):
    """A transport-level failure (link down, write failed, ...)."""


class Transport(ABC):
    """One raw byte channel to a device.

    Implementations deliver every incoming notification (one GATT notification or one
    TCP line) as a whole to the callback registered via :meth:`on_notify`. The callback
    is invoked on the asyncio event loop thread.
    """

    def __init__(self) -> None:
        self._notify_callback: NotifyCallback | None = None
        self._disconnect_callback: DisconnectCallback | None = None

    @abstractmethod
    async def connect(self) -> None:
        """Open the channel and start delivering notifications."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the channel. Idempotent."""

    @abstractmethod
    async def write(self, data: bytes) -> None:
        """Send one frame. Raises :class:`TransportError` on failure."""

    @property
    @abstractmethod
    def connected(self) -> bool:
        """True while the channel is usable."""

    def on_notify(self, callback: NotifyCallback | None) -> None:
        """Register the receiver of incoming frames (``None`` unregisters)."""
        self._notify_callback = callback

    def on_disconnect(self, callback: DisconnectCallback | None) -> None:
        """Register a callback fired once when the link drops unexpectedly."""
        self._disconnect_callback = callback

    def _deliver(self, data: bytes) -> None:
        if self._notify_callback is not None:
            self._notify_callback(bytes(data))

    def _notify_disconnect(self) -> None:
        if self._disconnect_callback is not None:
            self._disconnect_callback()
