# Frame captures

Raw frames seen on real Dometic hardware. This is the evidence that turns a *needs
verification* comment into a fact. Everything in `docs/dometic-power-protokoll.md` was
derived from app code; the files here are what the devices actually said.

Working rule (CLAUDE.md): observed reality > docs > logs > code > hypotheses. A capture
here outranks the protocol doc. If they disagree, fix the doc and cite the capture.

## Naming

```
YYYY-MM-DD_<device>_<what>.log        frame log from the console (or HA debug log)
YYYY-MM-DD_<device>_<what>.md         notes: setup, what was on the display, conclusions
YYYY-MM-DD_<device>_scan.txt          advertisement data (name, service UUIDs, manufacturer data)
```

`<device>` is `fjz7`, `cfx3`, `cfx5`, … `<what>` is short: `first-contact`, `subscribe-ac`,
`set-ttemp`, `handshake-hello`, `bond-reboot`. One log per experiment, not one per day.

Example: `2026-09-20_fjz7_first-contact.log` + `2026-09-20_fjz7_first-contact.md`.

## Saving a log from the test console

1. Start it: `uv run python -m tools.ac_console -v` and open http://127.0.0.1:8765/.
2. Before connecting, untick **hide ACKs** in the frame log so the capture is complete.
3. Run one experiment. Do not clear the log between steps of the same experiment.
4. Press **Copy** in the frame log header, paste into a new file here with the name above.
   Alternatively copy the terminal output: with `-v` every frame is also printed as
   `pyddm TX …` / `pyddm RX …` lines together with the console's own messages.
5. Write the `.md` notes file next to it (template below). Do it immediately; the value of
   a capture halves once you no longer remember what the device display showed.
6. Commit both: `git add docs/captures && git commit -m "docs(captures): fjz7 first contact"`.

Lines in the console log look like

```
18:41:07.412  TX  12 0A 00 02 01         SUBSCRIBE 0A 00 02 01  ac.itemp
18:41:07.630  RX  10 0A 00 02 01 FC 53 00 00  PUBLISH 0A 00 02 01 = FC 53 00 00  ac.itemp = 21.5 °C
```

TX is what we sent, RX what the device sent. The hex is exactly what went over GATT; the
text after it is our decoding and may be wrong. That is the point of keeping the hex.

## Saving a scan

Press **Scan** with *show non-Dometic* ticked, then copy the row for the Dometic device
(name, address, RSSI, protocol, manufacturer data) into `..._scan.txt`. If the device is
*not* classified as DDM1/DDM2, capture it anyway: that is a bug in
`pyddm.const.protocol_from_advertisement` and the row is the test case.

## Saving a log from Home Assistant

Enable debug logging for the integration and the protocol package, reproduce, then
download the log from Settings → System → Logs, or copy the relevant lines.

```yaml
logger:
  default: warning
  logs:
    custom_components.dometic_ddm: debug
    custom_components.dometic_ddm.pyddm: debug
```

Frames appear as `ddm1 TX 03` / `ddm1 RX 00 01 01 01 0A FF` lines. Trim the file to the
relevant window and name it like a console log, e.g. `2026-10-02_cfx3_ha-reconnect.log`.

## Notes template (`.md`)

```markdown
# <device> – <what> – <date>

Setup: device model / firmware (from the display), adapter (laptop BlueZ / ESPHome proxy),
distance, was the device in pairing mode, was the phone app disconnected.

Steps: what was pressed, in order, with timestamps matching the log.

Device display said: e.g. inside 21.5 °C, target 22 °C, mode Cool, fan auto.

Result: which frames answered, which did not, decode matches display? (yes/no, which)

Conclusions: which "needs verification" items are now verified, which docs statements
are wrong, new open questions.
```

## Privacy

Captures may contain the device serial number, MAC address, WiFi SSIDs or a device name
you typed yourself. Redact what you do not want public (`XX:XX` for MAC halves is fine);
this repository is public.

## Turning a capture into a test

Every verified frame belongs in `tests/` as a byte sequence, e.g. a new case in
`tests/test_cfx3_golden.py` or a `tests/test_fjz7_golden.py`. Reference the capture file
in the test docstring. Then remove the matching *needs verification* comment.
