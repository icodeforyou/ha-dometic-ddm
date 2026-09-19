"""pyddm: Dometic DDM1/DDM2 protocol implementation, transport independent.

Derived from the decompiled Dometic Power app (v2.2.8). Not yet verified against
hardware; see the README and ``docs/`` for status.
"""

from .const import (
    DDM1_NOTIFY_UUID,
    DDM1_SERVICE_UUID,
    DDM1_WRITE_UUID,
    DDM2_MANUFACTURER_ID,
    DDM2_NOTIFY_UUID,
    DDM2_SERVICE_UUID,
    DDM2_WRITE_UUID,
    Protocol,
    protocol_from_advertisement,
)
from .frame import DDM1Action, DDM2Action, Frame, FrameError, hexdump
from .session import (
    HandshakeConfig,
    HandshakeStep,
    ProtocolMachine,
    Session,
    SessionError,
    SessionState,
    Update,
)

__version__ = "0.1.0a0"

__all__ = [
    "DDM1_NOTIFY_UUID",
    "DDM1_SERVICE_UUID",
    "DDM1_WRITE_UUID",
    "DDM2_MANUFACTURER_ID",
    "DDM2_NOTIFY_UUID",
    "DDM2_SERVICE_UUID",
    "DDM2_WRITE_UUID",
    "DDM1Action",
    "DDM2Action",
    "Frame",
    "FrameError",
    "HandshakeConfig",
    "HandshakeStep",
    "Protocol",
    "ProtocolMachine",
    "Session",
    "SessionError",
    "SessionState",
    "Update",
    "__version__",
    "hexdump",
    "protocol_from_advertisement",
]
