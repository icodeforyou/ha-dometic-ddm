"""CFX3 golden sequence from CLAUDE.md / the kickoff prompt, driven end to end.

    device  04                       (ACK after notifications enabled)
    us      03                       (HELLO)
    device  04                       (ACK → ready)
    us      01 01 00 00 81           (SUBSCRIBE subscribeAppSz — bulk subscription,
                                      open question 3: needs verification)
    device  00 00 01 01 01 0A FF     (PUBLISH c0MeasuredTemperature)
    us      04                       (ACK)

Value check: ``0A FF`` little-endian signed = 0xFF0A = -246 → -24.6 °C. The codec agrees
with the docs' worked example, so no discrepancy to note.
"""

from __future__ import annotations

import asyncio

from pyddm import Protocol, Session, Update
from pyddm.ddm1 import default_table

from .fakes import FakeTransport

DEVICE_ACK = bytes([0x04])
OUR_HELLO = bytes([0x03])
OUR_SUBSCRIBE_APP_SZ = bytes([0x01, 0x01, 0x00, 0x00, 0x81])
DEVICE_PUBLISH_TEMP = bytes([0x00, 0x00, 0x01, 0x01, 0x01, 0x0A, 0xFF])
OUR_ACK = bytes([0x04])


async def test_cfx3_golden_sequence() -> None:
    transport = FakeTransport()
    updates: list[Update] = []
    session = Session(Protocol.DDM1, transport, on_update=updates.append)

    start = asyncio.create_task(session.start(ready_timeout=1.0))
    await asyncio.sleep(0)
    transport.notify(DEVICE_ACK)
    assert await transport.wait_for_writes(1) == [OUR_HELLO]
    transport.notify(DEVICE_ACK)
    await start
    assert session.ready

    table = default_table()
    bulk = table.topic_for("multiSubscriptionParameters", "subscribeAppSz")
    await session.subscribe(bulk)
    assert transport.written == [OUR_HELLO, OUR_SUBSCRIBE_APP_SZ]

    transport.notify(DEVICE_PUBLISH_TEMP)
    assert await transport.wait_for_writes(3) == [OUR_HELLO, OUR_SUBSCRIBE_APP_SZ, OUR_ACK]

    assert len(updates) == 1
    update = updates[0]
    assert update.parameter is table.get("compartment", "c0MeasuredTemperature")
    assert update.value == -24.6
    assert update.error is None
    await session.close()
