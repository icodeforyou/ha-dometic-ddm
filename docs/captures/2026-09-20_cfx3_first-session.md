# CFX3 (CFX335, FC:E8:C0:A9:0B:FA) – first contact and first session – 2026-09-20

Setup: laptop Intel AX201 / BlueZ 5.87, first ~2 m from the cooler (RSSI -75 … -85), later
on top of it. Console `tools/ac_console` + WebSocket probe scripts. Owner's phone Bluetooth off
from 12:25. Cooler: single zone, model string `CFX335`, firmware `V3.510+DD2.2`,
serial `44304345`, name `CFX3_a90bf8`.

## Timeline

- 12:03–12:10 Connect attempts without bond: link accepted, dropped by the cooler within
  1–4 s (during service discovery or right after notifications). `Device1.Pair` via D-Bus
  without an agent: `AuthenticationFailed` after ~30 s.
- ~12:12 `bluetoothctl` with `agent on` / `default-agent` / `scan on`, cooler in its
  Bluetooth pairing menu: **Pairing successful**, `trust`. (Exact prompt, if any, not
  recorded; Johan did not report a passkey.)
- 12:17:10 First bonded connect (bleak, 5 s). Notifications on. **Cooler sent nothing** for
  35 s. Manual `Send PING`: `02` → `04` → `03` → `04`, READY within 150 ms.
- 12:18–12:31 Many bleak connects timed out after ~33 s ("device not found" or BlueZ
  Connect failing) although the cooler was visible in scans at -75 … -85 dBm.
  `bluetoothctl connect` succeeded first try every time (12:23, 12:30, 12:31, 12:34,
  12:35, 12:38). Cause on our side: bleak resolves a string address by scanning, and a
  connected/rarely advertising device is invisible to that scan. Fixed in the console by
  handing bleak BlueZ's device object. Also: the cooler stays silent for ~1 min after a
  disconnect before advertising again.
- 12:35:28 Attached to a `bluetoothctl` link, PING-first handshake READY. 14 individual
  SUBSCRIBEs → 14 ACKs, **no PUBLISH**. Cooler sends `02` (PING) every 2 s; we did not
  answer; link stayed up > 60 s anyway.
- 12:38:04 Same, but now the session answers every cooler PING with `04`. **All 14
  SUBSCRIBEs answered with PUBLISH** within 3 s. Values:
  productType 1 (single zone), c0Power on, c0MeasuredTemperature 18.0 °C (19.0 °C at
  12:38:47, pushed unprompted), c0SetTemperature 2.0 °C, c0DoorOpen no,
  c0TemperatureRange -22.0 … 20.0 °C, coolerPower on, batteryVoltageLevel 13.2 V,
  batteryProtectionLevel 1, compressorPower no, powerSource 1, model `CFX335`, serial,
  firmware.
- 12:38:16 Raw `01 01 00 00 81` (subscribeAppSz): burst of ~30 PUBLISHes incl. deviceName,
  all `errors.*` and `alerts.*` flags (all 0), WiFi station SSIDs (slot 0 set, 1–2 empty),
  wifiApConnected 1, presentedTemperatureUnit 0, temperature/current history arrays, and
  the dashboard values again.
- 12:38:36 `01 02 00 00 81` (Szi): same kind of burst.
- 12:38:56 `01 03 00 00 81` (Dz): burst including the `c1…` (instance 0x10) topics:
  c1MeasuredTemperature 0.0, c1SetTemperature -15.0, c1DoorOpen 0, c1TemperatureRange
  -22 … 20, c1 history all-empty — placeholders on a single-zone unit.

## Verified

- Bonding mandatory; pairing only while the cooler's pairing menu is active.
- DDM1 handshake: **client opens with PING** (`02`), cooler `04`, client `03`, cooler `04`.
  The docs' claim that the cooler speaks first is wrong.
- Cooler PINGs every 2 s once READY and **publishes nothing until the client ACKs those
  PINGs**. With ACKs, individual SUBSCRIBEs are answered immediately.
- Bulk subscriptions `01/02/03 00 00 81` work (open question 3: yes).
- DDM1 codec: topic layout `[instance, param, class, group]`, int16 LE deci-values,
  INT16_ARRAY (min,max), UTF8 strings zero-terminated, INT8 bools. Display comparison
  still to be done by the owner (18–19 °C, set 2 °C, 13.2 V).
- Unprompted PUBLISH on change (18.0 → 19.0 °C).

## To change in the code (not done yet, on request)

- HISTORY_DATA_ARRAY: `0x8000` (-3276.8) is a "no sample" sentinel → decode as None. The
  trailing byte increments over time (39 → 40 within a minute) – a slot index/counter.
- productModelNumber raw `43 46 58 33 33 35 00 35 20 44 5A 00 …` = "CFX335\0" followed by
  leftover "5 DZ": the cooler does not clear the buffer after the terminator. Cutting at the
  first NUL (current behaviour) is right.
- Integration: subscribe with `01 00 00 81` (one frame) instead of 14 individual frames,
  or keep individual ones; both verified. Always ACK device PINGs (now default in pyddm).
- Reconnect logic must tolerate ~1 min of no advertising after a disconnect and should use
  BlueZ's device object / `establish_connection` rather than address scanning.

## Privacy

WiFi SSID redacted in the `.log`. Serial and MAC left in (owner aware).
