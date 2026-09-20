# FJZ7 (SHE_366f0c, 68:FE:71:36:6F:0E) – first contact – 2026-09-20

Setup: laptop Intel AX201 / BlueZ 5.87, ~2 m from the AC, RSSI -66 … -86. Console
`tools/ac_console`, protocol DDM2, handshake default (none). Phone state during the
attempts: unknown (to be checked; see conclusions).

## Attempts

1. 11:42 Connect, no bonding. Link up, MTU reported 23. ~1.5 s later the AC dropped the
   link while notifications on 537a0402 were being enabled:
   `[org.bluez.Error.NotConnected] Not Connected`.
2. 11:47 Connect with "bond first". Link up, then dropped **during GATT service discovery**,
   0.8 s after connect, before any pairing or write:
   `bleak.exc.BleakError: failed to discover services, device disconnected`.
3. 11:5x `bluetoothctl` `pair 68:FE:71:36:6F:0E` (agent on, default-agent, scan on):
   ```
   Attempting to pair with 68:FE:71:36:6F:0E
   [CHG] Device 68:FE:71:36:6F:0E Connected: yes
   [SIGNAL] LE.Disconnected - org.bluez.Reason.Remote, Connection terminated by remote user
   [SIGNAL] Disconnected - org.bluez.Reason.Remote, Connection terminated by remote user
   [CHG] Device 68:FE:71:36:6F:0E Connected: no
   Failed to pair: org.bluez.Error.AuthenticationCanceled
   ```
   Note also `bluetoothctl pair` without its own `scan on` first: "Device not available"
   (BlueZ forgets unpaired devices ~30 s after discovery stops).

## Result

The AC accepts the LE connection and terminates it itself within ~1 s, regardless of what
the central does (nothing / service discovery / pairing request). No DDM2 frame was
exchanged. Open question 1 (is the `ac` class reachable over BLE) is still open.

## Conclusions / next

- Advertising and classification are verified: name `SHE_…`, company id 0x0845, payload `00`.
- The connection drop is not caused by our notification write (attempt 2 and 3 never got
  that far).
- Hypotheses: (a) AC only pairs in a dedicated pairing/onboarding mode (remote / panel /
  app flow); (b) AC is bonded to the owner's phone and refuses other centrals while that
  bond exists. Test (b) first: Bluetooth off on all phones with the Dometic app, retry.
- `sudo btmon` during an attempt would show whether the AC hangs up before or after the
  SMP Pairing Request.
