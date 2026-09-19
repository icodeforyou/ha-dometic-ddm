# Dometic Power (com.dometic.app v2.2.8) — reverse engineering av BLE-protokollen

Källa: `Power.apk` (Expo/React Native, Hermes-bytecode `index.android.bundle`, dekompilerad med hermes-dec). BLE-lagret är `react-native-ble-manager`. All protokoll-logik ligger i JS-bundeln, inte i native-kod — det är därför den gick att läsa ut komplett.

Mål: Dometic CFX3 (kylbox) och Dometic FreshJet FJZ7 2600 (AC). Båda hanteras av appen, men med **två olika protokoll**.

---

## 1. Protokollfamiljer i appen

| Protokoll (appens namn) | BLE-service | Write-char | Notify-char | Används av |
|---|---|---|---|---|
| **DDM1** | `537a0300-0995-481f-926c-1604e23fd515` | `537a0301-…` | `537a0302-…` | **CFX3** (firmware-id `CFX3`) |
| **DDM2** | `537a0400-0995-481f-926c-1604e23fd515` | `537a0401-…` | `537a0402-…` | **FreshJet FJX/FJZ ("SHAPE"/`SHE`)**, CFX5 (`MC1`), gateways, batterier m.m. |
| NBUS | `0000FEFB-…` (chars `00000001..4-0000-1000-8000-008025000000`) | | | Tempra-batteri, solregulator, Smart-in inverter (AT-liknande textkommandon `APP+…`/`MST+…`) |
| AREA_LIGHT | `55535343-fe7d-4ae5-8fa9-9fafd205e455` (Microchip RN487x transparent UART) | | | Area Camp Light |
| BTEC | `0000FFE0` / `FFE3` / `FFE4` | | | batteri-nätverkskonfig (register/CRC) |

Identifiering vid scanning (`getBleProtocol`):
- firmwareId härleds ur annonserat namn (första 3 tecken uppercase; innehåller namnet `SHE` → SHAPE/AC). Om firmwareId === `'CFX3'` → **DDM1**.
- Annars: manufacturer data med Bluetooth company-ID **`0x0845`** → **DDM2**. (AC:n bör alltså annonsera 0xFF-AD-struktur med `45 08`.) *Behöver verifieras med en riktig scan.*

Anslutningssekvens i appen (alla protokoll): connect → **createBond** (Android, alla utom MPS) → retrieveServices → **requestMTU(153)** → enable notifications på notify-char → protokollspecifik handskakning.

---

## 2. Gemensamt ramformat (DDM1 och DDM2)

Rå BLE-nyttolast (ingen längd, ingen CRC, ingen framing utöver GATT-paketet):

```
byte 0      : action
byte 1..4   : topic (4 byte)
byte 5..n   : value (typberoende, kan vara tom)
```

Kontrollmeddelanden är **ett enda byte** (bara action, ingen topic).

App-koden parsar: `topic = bytes.slice(1,5)`, `value = bytes.slice(5)`, och kräver `length >= 5` för datameddelanden.

### Action-koder

| Action | DDM1 (CFX3) | DDM2 (FJZ/CFX5) |
|---|---|---|
| PUBLISH (skriv/rapportera värde) | `0x00` | `0x10` (16) |
| SUBSCRIBE | `0x01` | `0x12` (18) |
| SET (skriv) | – (DDM1 använder PUBLISH för skriv) | `0x11` (17) |
| PING | `0x02` | – |
| HELLO | `0x03` | `0x03` |
| ACK | `0x04` | `0x04` |
| NAK | `0x05` | `0x05` |
| NOP | `0x06` | `0x06` |
| FRAGMENT | – | `0x14` (20) — bara för jumbo-överföringar (TLS-CSR), irrelevant för oss |

### Handskakning (DDM1, ur `reportDDM1Data`)

1. Enheten skickar `[0x04]` (ACK) efter att notifications aktiverats.
2. Appen svarar `[0x03]` (HELLO).
3. Enheten svarar `[0x04]` (ACK) → sessionen är "hello:ad", appen skickar sina SUBSCRIBE.
4. Varje inkommande PUBLISH-ram från enheten besvaras av appen med `[0x04]` (ACK). *Detta tror vi är obligatoriskt för att enheten ska fortsätta skicka — behöver verifieras.*

Ett externt projekt (philippe-a11y) beskriver sekvensen som PING → ACK → HELLO → ACK, dvs appen/klienten kan inleda med `[0x02]`. Den dekompilerade koden visar ACK-triggern; båda är förenliga.

### SUBSCRIBE-ram
`[SUBSCRIBE, t0, t1, t2, t3]` — inget value. Enheten svarar med PUBLISH-ramar för det topic:et (och fortsätter pusha vid ändring).

### Skrivning
- DDM1: `[0x00, t0,t1,t2,t3, …encodedValue]`
- DDM2: `[0x11, t0,t1,t2,t3, …encodedValue]`

---

## 3. DDM1 — CFX3

### Topic-layout (4 byte)
`[instance, param, class, group]`
- `instance`: `0x00` = compartment 0, `0x10` (16) = compartment 1 (för errors används 1/17 i param-byten i stället), `0x20` = tredje enhet (dcm) i deviceSpecific.
- `group`: `0` = produktinfo, `1` = enhetsdata, `128` = deviceSpecific, `129` = multi-subscription.

### Datatyper / kodning (ur `ddm1Encoder`/`ddm1Decoder`)
| Typ | Bytes | Kodning |
|---|---|---|
| INT8_BOOLEAN | 1 | 0/1 |
| INT8_NUMBER / UINT8_NUMBER | 1 | rå |
| INT16_DECIDEGREE_CELSIUS | 2 | **little-endian signed**, °C·10 (t.ex. `0x0A 0xFF` = -246 → -24.6 °C? Nej: `lo=0x0A, hi=0xFF` → 0xFF0A = -246/10 = -24.6 °C) |
| INT16_DECICURRENT_VOLT | 2 | little-endian, V·10 (avrundas) |
| INT16_ARRAY | 4 | två decigrad-värden (min,max) |
| HISTORY_DATA_ARRAY | 15 | 7 × int16 decigrad (LE) + 1 byte |
| UTF8_STRING | ≤15 | UTF-8, nollterminerad om kortare än 15 |
| EMPTY | 0 | kommando utan värde (t.ex. factoryReset) |

### Viktigaste topics (fullständig lista i `ddm1_cfx3_parameters.json`, 86 st)

| Namn | topic | typ | R/W |
|---|---|---|---|
| c0Power | `00 00 01 01` | INT8_BOOLEAN | W |
| c0MeasuredTemperature | `00 01 01 01` | INT16_DECIDEG | R |
| c0SetTemperature | `00 02 01 01` | INT16_DECIDEG | W |
| c0DoorOpen | `00 08 01 01` | INT8_BOOLEAN | R |
| c0TemperatureRange | `00 80 01 01` | INT16_ARRAY | R |
| c0RecommendedRange | `00 81 01 01` | INT16_ARRAY | R |
| c1… (dual zone) | `10 xx 01 01` | | |
| coolerPower | `00 00 03 01` | INT8_BOOLEAN | W |
| batteryVoltageLevel | `00 01 03 01` | INT16_DECIVOLT | R |
| batteryProtectionLevel | `00 02 03 01` | INT8 enum (0 Low,1 Med,2 High) | W |
| compressorPower | `00 03 03 01` | INT8_BOOLEAN | R |
| powerSource | `00 05 03 01` | INT8 enum (0 AC,1 DC,2 Battery — *enum-värden hämtade från DDM2-tabellen, verifiera för DDM1*) | R |
| icemakerPower | `00 06 03 01` | INT8_BOOLEAN | W |
| errors.* | `00 xx 04 01` | INT8_BOOLEAN | R |
| alerts.* (temp/door/voltage) | `00 0x 05 01` | INT8_BOOLEAN | R |
| deviceName | `00 00 06 01` | UTF8_STRING | W |
| bluetoothBondMode | `00 07 06 01` | INT8_BOOLEAN | W |
| productModelNumber / SerialNumber | `00 C0 00 00` / `00 C1 00 00` | UTF8_STRING | R |
| ccFirmwareVersion | `00 C1 00 80` | UTF8_STRING | R |
| **subscribeAppSz / Szi / Dz** | `01 00 00 81` / `02 00 00 81` / `03 00 00 81` | EMPTY | – |

`multiSubscriptionParameters` (group 129) ser ut som **bulk-prenumerationer**: en SUBSCRIBE på `01 00 00 81` bör ge alla "single zone"-parametrar, `03 00 00 81` för dual zone. *Detta tror vi — verifiera genom att skicka `01 01 00 00 81` och se vad som kommer tillbaka.*

---

## 4. DDM2 — FreshJet FJZ7 (2600) och CFX5

### Topic-layout (4 byte)
`[param, instance, class, group]` — **obs, annan ordning än DDM1.** `instance` sätts av appen (`formatDDM2Parameter` skriver `Number(instance)` i byte 1); normalt `0`.

### Datatyper (ur `ddm2Encoder`/`ddm2Decoder`)
- INT32_T / UINT32_T: **4 byte little-endian**. Fysiska storheter skalas med `factor` (nästan alltid 1000): °C·1000, V·1000, A·1000, W·1000.
- STRING: UTF-8-bytes (URI-encode/unescape-trick), ingen längdprefix.
- STRUCT: definieras per parameter (`struct`-fältet, t.ex. `{"temp":["i32",0,"^C"]}` eller `{"bool_arr":["i32",0,"bool"]}` = array av i32).
- Enum/bitfield: INT32.

### Hela datamodellen
`ddm2_parameters.json` innehåller **240 klasser / 2 464 parametrar** — hela Dometics DDM2/CI-BUS-datamodell (gateway, wifi, mqtt, tls, batterier, inverters, solregulatorer, AC, kylbox, värmare, vatten, belysning, RV-C-bryggor …). Varje post har `param_id`, `class_id`, `group_id`, in/out-typ, enhet, faktor, skrivbar, enum.

Klass för **AC** (`class_id=2, group_id=1`, appens `ac`) — det som bör gälla FJZ7 (`mdl`-enum har `Dometic FJZ7000 series = 18`). Topic = `[param_id, 0, 2, 1]`:

| Param | id | typ | enhet | R/W | Enum |
|---|---|---|---|---|---|
| avl | 0 | i32 | bool | R | |
| **on** | 1 | i32 | bool | W | |
| fspd | 2 | i32 | enum | W | |
| **md** | 3 | i32 | enum | W | 0 Cool,1 Heat,2 Fan,3 Auto,4 Dry,5 Turbo |
| **ttemp** | 4 | i32 | °C·1000 | W | |
| lgt | 5 | i32 | bool | W | belysning |
| dmr | 6 | i32 | % | W | dimmer |
| pwr | 7 | i32 | W·1000 | W | |
| mdl | 9 | i32 | enum | R | modell (18 = FJZ7000) |
| **itemp** | 10 | i32 | °C·1000 | R | innetemp |
| fs | 11 | i32 | % | W | fläkt |
| fmd | 12 | i32 | enum | R | 0 Auto,1 On |
| sysu | 16 | i32 | enum | W | 0 Metric,1 Imperial |
| tona/tonh/tonm, toffa/toffh/toffm | 19–24 | i32 | | W | timer |
| status | 26 | STRUCT x16 | error | R | felkoder (AIRC_*, se lista i appen) |
| sleep | 27 | i32 | bool | W | |
| actext | 30 | u32 | bitfield | W | 1 Heater,2 Compressor,0x10 Inverter,0x20 FanEvap,0x40 ForceLoadShed |
| ver | 33 | STRING | | R | |
| operst | 35 | i32 | enum | R | 0 FanOnly,1 Cool,2 Heat |
| eco | 36 | i32 | bool | W | |
| flaps | 37 | i32 | enum | W | 0 stopped,3 Flap2,12 Flap1,15 both |
| etemp | 39 | i32 | °C·1000 | R | utetemp |
| curr | 44 | i32 | A·1000 | W | |
| currlim | 45 | i32 | enum | W | 0=4A,1=5A,2=6A,3=7A,7=Unlimited |

*Behöver verifieras:* att FJZ7 exponerar `ac`-klassen direkt över BLE (och inte enbart via WiFi/cloud). Appen har tre transportvägar för DDM2 — BLE, lokal WiFi-TCP (base64-rader avslutade med `\r`) och AWS IoT/MQTT-shadow — och samma topics används på alla. FJZ7 marknadsförs med Wi-Fi; BLE-tjänsten 537a0400 är sannolikt där ändå för onboarding, men **detta måste bekräftas med en scan/GATT-dump**.

Även gateway-klassen (`gw`, class 0 group 0) är intressant: `ver`, `mac`, `dsn`, `sku`, `ptype`.

CFX5 (om det blir aktuellt) ligger i klassen `mccc` (class 0, group 26): `cpow`, `ctemp`, `csettemp`, `cdoor`, `v`, `i`, `powsrc`, `batprotlvl`, `errst` osv.

---

## 5. Vad som redan finns publikt (så vi inte gör om det)

- **philippe-a11y/home-assistant-dometic-cfx** — HA custom integration över BLE, implementerar både DDM1 och DDM2 för CFX2/CFX3/CFX5, med climate-entities. CFX5 verifierad på hårdvara, CFX3 "implemented, awaiting hardware testing". Rekommenderar ESPHome Bluetooth-proxy eftersom BlueZ tappar bond efter omstart.
- **JS-DE-Tech/hacs-dometic-cfx3** — HA-integration över **lokal WiFi ("DDMP")**, ingen cloud.
- **andrewbackway** — ESPHome external component för CFX över BLE (ESP-IDF BLE-stack), fungerar med CFX3 enligt HA-forumet, men "frekvent om-parning" rapporterad.
- keshavdv/dometic-cfx3 — python-skelett, i praktiken tomt.
- **Ingen** publik implementation för FreshJet FJZ/FJX (AC) hittad.

Konsekvens: för CFX3 är den snabbaste vägen att **testa philippe-a11y-integrationen** (vi bidrar med CFX3-verifiering) eller bygga en egen ESPHome/ESP32-C3-brygga med tabellen ovan. För FJZ7 är vi troligen först — värdet av vårt arbete ligger där.

---

## 6. Bonding / parning — den praktiska fällan

- CFX3 kräver att man aktiverar "PAIR" i kylboxens meny (BT-ikonen blinkar 60 s) och appen skapar en **BLE-bond**. Utan bond nekar enheten troligen GATT-write/notify (encryption required). Forumrapporter: BlueZ på RPi tappar bonden efter reboot; ESP32 (NimBLE/Bluedroid) behåller den i NVS om man sparar.
- För vår XIAO ESP32-C3-brygga: aktivera security (bonding, "just works"), spara bond i NVS, initiera pairing en gång under PAIR-läget.
- CFX3 tillåter en (1) BLE-klient åt gången — appen och bryggan kan inte vara anslutna samtidigt.

---

## 7. Föreslagen plan

1. **Scan-experiment (låg risk, 10 min):** nRF Connect på telefon. Bekräfta: (a) CFX3 annonserar namn `CFX3…` och service `537a0300`; (b) FJZ7 annonserar manufacturer data `45 08 …` och service `537a0400`. Notera exakt namn och manufacturer-data.
2. **CFX3 GATT-experiment i nRF Connect:** bond → enable notify på `537a0302` → förvänta `04` → skriv `03` → förvänta `04` → skriv `01 01 00 00 81` (subscribeAppSz) → förvänta ström av `00 tt tt tt tt vv…`-ramar. Avkoda `00 01 01 01`-topic (c0MeasuredTemperature) mot displayen.
3. **FJZ7 GATT-experiment:** samma, men notify `537a0402`, HELLO `03`, subscribe `12 0A 00 02 01` (itemp) → förvänta `10 0A 00 02 01 xx xx xx xx` med i32 LE °C·1000. Om inget kommer: prova `12 00 00 02 01` (avl) och `12 00 00 00 00` (gw.avl) för att avgöra om klassen är tillgänglig över BLE.
4. Först därefter bygga ESPHome/ESP32-C3-firmware (eller Python/bleak-prototyp via HA:s BT-proxy). Skrivkommandon (SET) testas sist, ett i taget, efter att READ är stabil.
