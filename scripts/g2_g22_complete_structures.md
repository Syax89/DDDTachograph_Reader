# G2/G2.2 Complete Data Structures

> **Document versione**: 1.0  
> **Date**: 2026-06-08  
> **Normative References**:
> - Reg. EU 2016/799 — Annex 1C (G2 data dictionary, RecordArray, BER-TLV)
> - Reg. EU 2021/1228 — Annex 1C amendments (G2.2 new data elements)
> - Reg. EU 2023/980 — Smart Tachograph V2 full spec
> - Appendix 7 (RecordArray format), Appendix 11 (security)

---

## 1. RecordArray Format (Appendix 7)

Ogni tag che materializza un `RecordArray` ha questa struttura:

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | recordType | UInt8 | Tipo record contenuto |
| 1 | 2 | recordSize | UInt16 BE | Dimensione di ogni record in byte |
| 3 | 2 | noOfRecords | UInt16 BE | Numero di record nell'array |

**Header totale: 5 byte**. Seguono `noOfRecords * recordSize` byte di dati record.

### RecordType values
| Code | Record |
|------|--------|
| 0x00 | VuCardRecord |
| 0x01 | VuCardIWRecord |
| 0x02 | VuDownloadablePeriod |
| 0x03 | VuTimeAdjustmentRecord |
| 0x04 | VuCompanyLocksRecord |
| 0x05 | SensorPairedRecord |
| 0x06 | SensorExternalGNSSCoupledRecord |
| 0x07 | VuITSConsentRecord |
| 0x08 | VuOverSpeedingEventRecord |
| 0x09 | VuOverSpeedingControlRecord |
| 0x0A | VuTimeAdjustmentGNSSRecord |
| 0x0B | VuPowerSupplyInterruptionRecord |
| 0x0C | VuSensorFaultRecord |
| 0x0D | VuDetailedSpeedBlock |

---

## 2. BER-TLV Encoding

Usato nei container G2/G2.2. Il tag puo' essere:
- **1 byte**: se bit[4:0] != 0x1F
- **Multi-byte**: se bit[4:0] == 0x1F, continua fino a quando il bit 7 del byte successivo e' 1

La lunghezza e':
- **Short form**: bit 7 = 0, bit[6:0] = lunghezza (0-127)
- **Long form**: bit 7 = 1, bit[6:0] = numero byte successivi che contengono la lunghezza

Bit 5 del primo byte di tag = 1 indica tag costruito (CONSTRUCTED / container).

---

## 3. G2 VU Records (Annex 1C — confirmed)

### Tag 0x0509 — VuCardRecord
- **Nome**: VuCardRecord
- **Annex reference**: Annex 1C §4.5.3.2.8
- **Dimensione record**: **29 byte**
- **Decoder**: `parse_g2_card_record` in `g2_decoders.py:7`
- **Stato**: ✅ CONFERMATO

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | cardIssuingMemberState | NationNumeric | |
| 1 | 16 | cardNumber | String(16) | ASCII, non terminato |
| 17 | 4 | cardExpiryDate | TimeReal | Unix timestamp BE |
| 21 | 1 | cardConsecutiveIndex | UInt8 | |
| 22 | 1 | cardReplacementIndex | UInt8 | |
| 23 | 1 | cardRenewalIndex | UInt8 | |
| 24 | 4 | cardApprovalNumber | SimpleString(4) | 4 byte big-endian |

---

### Tag 0x050A — VuCardIWRecord
- **Nome**: VuCardIWRecord (Insert/Withdrawal)
- **Annex reference**: Annex 1C §4.5.3.2.9
- **Dimensione record**: **28 byte**
- **Decoder**: `parse_g2_card_iw_record` in `g2_decoders.py:49`
- **Stato**: ✅ CONFERMATO

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | cardInsertionType | UInt8 | 0=Withdrawn, 1=Inserted |
| 1 | 4 | cardInsertionTime | TimeReal | Unix timestamp BE |
| 5 | 3 | vehicleOdometerValue | OdometerValue | 3 byte big-endian |
| 8 | 1 | cardSlot | UInt8 | 0=Driver, 1=Co-Driver |
| 9 | 1 | cardIssuingMemberState | NationNumeric | |
| 10 | 16 | cardNumber | String(16) | |
| 26 | 1 | cardConsecutiveIndex | UInt8 | |
| 27 | 1 | cardReplacementIndex | UInt8 | |
| 28 | 1 | cardRenewalIndex | UInt8 | Opzionale nel record (28 byte totali senza) |

**Nota**: il codice attuale include `cardRenewalIndex` a offset 28 se `len(rec) > 28`.

---

### Tag 0x050B — VuDownloadablePeriod
- **Nome**: VuDownloadablePeriod
- **Annex reference**: Annex 1C §4.5.3.2.10
- **Dimensione record**: **8 byte**
- **Decoder**: `parse_g2_downloadable_period` in `g2_decoders.py:97`
- **Stato**: ✅ CONFERMATO

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 4 | minDownloadableTime | TimeReal | Unix timestamp BE |
| 4 | 4 | maxDownloadableTime | TimeReal | Unix timestamp BE |

---

### Tag 0x050D — VuTimeAdjustmentData
- **Nome**: VuTimeAdjustmentData
- **Annex reference**: Annex 1C §4.5.3.2.12
- **Dimensione record**: **variabile** (minimo 9 byte fissi, + parte variabile per workshop)
- **Decoder**: `parse_g2_time_adjustment` in `g2_decoders.py:118`
- **Stato**: ⚠️ PARZIALE (parte variabile non decodificata)

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | timeAdjustmentType | UInt8 | 0=Auto, 1=Manual, 2=Workshop |
| 1 | 4 | oldTimeValue | TimeReal | |
| 5 | 4 | newTimeValue | TimeReal | |
| 9+ | var | workshopName | CodedString | Solo per manual records |
| + | 18 | workshopCardNumber | CardNumber | |
| + | 3 | vehicleOdometerValue | OdometerValue | |

---

### Tag 0x050F — VuCompanyLocksData
- **Nome**: VuCompanyLocksData
- **Annex reference**: Annex 1C §4.5.3.2.14
- **Dimensione record**: **25 byte**
- **Decoder**: `parse_g2_company_locks` in `g2_decoders.py:145`
- **Stato**: ✅ CONFERMATO

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | cardIssuingMemberState | NationNumeric | |
| 1 | 16 | cardNumber | String(16) | |
| 17 | 4 | lockInTime | TimeReal | |
| 21 | 4 | lockOutTime | TimeReal | |

---

### Tag 0x0510 — SensorPairedData
- **Nome**: SensorPairedData
- **Annex reference**: Annex 1C §4.5.3.2.15
- **Dimensione record**: **24 byte**
- **Decoder**: `parse_g2_sensor_paired` in `g2_decoders.py:176`
- **Stato**: ✅ CONFERMATO

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 8 | sensorSerialNumber | UInt64 | Big-endian |
| 8 | 8 | sensorApprovalNumber | UInt64 | Big-endian |
| 16 | 4 | sensorPairingDateFirst | TimeReal | |
| 20 | 4 | sensorPairingDateCurrent | TimeReal | |

---

### Tag 0x0511 — SensorExternalGNSSCoupledData
- **Nome**: SensorExternalGNSSCoupledData
- **Annex reference**: Annex 1C §4.5.3.2.16
- **Dimensione record**: **20 byte**
- **Decoder**: `parse_g2_sensor_gnss_coupled` in `g2_decoders.py:203`
- **Stato**: ✅ CONFERMATO

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 8 | serialNumber | UInt64 | Big-endian |
| 8 | 8 | approvalNumber | UInt64 | Big-endian |
| 16 | 4 | couplingDate | TimeReal | |

---

### Tag 0x0512 — VuITSConsentData
- **Nome**: VuITSConsentData
- **Annex reference**: Annex 1C §4.5.3.2.17
- **Dimensione record**: **23 byte**
- **Decoder**: `parse_g2_its_consent` in `g2_decoders.py:226`
- **Stato**: ✅ CONFERMATO

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | consentType | UInt8 | 0=NoConsent, 1=ConsentGiven |
| 1 | 4 | consentTime | TimeReal | |
| 5 | 18 | cardNumber | FullCardNumber | nation(1) + number(16) + terminator(1) |

---

## 4. G2 Containers (Annex 1C)

| Tag | Nome | Note |
|-----|------|------|
| 0x7621 | G2_ApplicationContainer | BER-TLV interni |
| 0x7622 | G2_VU_Activities | TREP 02 — contiene driver card holder + daily activity records con firma ECDSA (113 byte G2) |
| 0x7623 | G2_VU_EventsFaults | TREP 03 — eventi + fault records |
| 0x7624 | G2_VU_Speed | TREP 04/24 — VuDetailedSpeedBlockRecordArray |
| 0x7D21 | G2_SecurityContainer | BER-TLV, contiene certificati |
| 0xAD21 | G2_SecurityContainer (alt) | Stesso contenuto di 0x7D21 |

---

## 5. G2.2 Containers (Reg. 2021/1228 + 2023/980)

| Tag | Nome | TREP | Note |
|-----|------|------|------|
| 0x7631 | G22_ApplicationContainer | — | BER-TLV interni, come 0x7621 |
| 0x7632 | G22_VU_Activities | TREP 22 | Daily activity records G2.2 (128 byte: 48 + sig_len=80) |
| 0x7633 | G22_VU_EventsFaults | TREP 33 | Events and faults G2.2 |
| 0x7634 | G22_VU_Speed | TREP 24 (stesso G2) | VuDetailedSpeedBlockRecordArray |
| 0x7F21 | G22_CardCertificateContainer | — | Certificati card G2.2 |
| 0x7F4E | G22_SecurityContainer | — | Security container G2.2 |

---

## 6. G2.2 card EF tags and VU RecordArrays (0x0525-0x0533)

### ENCODING NOTE
I tag card **0x0525-0x052A** sono payload EF, non container BER-TLV. Il parser
non deve tentare una passeggiata TLV annidata sui loro valori. I tag 0x0525,
0x0526 e 0x052A hanno un puntatore iniziale di due byte; 0x0527 usa il wrapper
RecordArray e 0x0528 e' una sequenza piatta di record. `GeoCoordinates` e'
un `Int24` firmato: latitudine e longitudine sono rispettivamente `+/-DDMM.M x10` e
`+/-DDDMM.M x10`; `7FFFFF` indica una posizione sconosciuta.

`VehicleRegistrationIdentificationRecordArray` usa invece il wrapper RecordArray
verificato: `recordType(0x24) + recordSize(0x000F) + noOfRecords + records`.
I tag VU **0x052B-0x0533** sono RecordArray nel flusso VU.

---

### Tag 0x0525 — G22_GNSSAccumulatedDriving
- **Nome**: GNSSAccumulatedDriving
- **Annex reference**: Annex 1C (amended 2021/1228) §§2.79, 2.79a, 2.79b
- **Encoding**: `gnssADPointerNewestRecord(2) + N x 19-byte record`
- **Decoder**: `parse_g22_gnss_accumulated_driving`

**Struttura del record interno**:

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 4 | timeStamp | TimeReal | |
| 4 | 12 | gnssPlaceAuthRecord | timestamp + accuracy + GeoCoordinates(6) + auth | |
| 16 | 3 | vehicleOdometerValue | OdometerShort | |
| **Totale** | **19** | | | |

La vecchia descrizione `Int32 + Int32` e speed/heading era errata: Annex 1C §2.76
definisce GeoCoordinates come due Int24, non micro-gradi Int32.

---

### Tag 0x0526 — G22_LoadUnloadOperations
- **Nome**: LoadUnloadOperations
- **Annex reference**: Annex 1C (amended 2021/1228) §§2.24c, 2.24d
- **Encoding**: `loadUnloadPointerNewestRecord(2) + N x 20-byte CardLoadUnloadRecord`
- **Decoder**: `parse_g22_load_unload_operations`

**Struttura del record interno**:

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 4 | timeStamp | TimeReal | |
| 4 | 1 | operationType | UInt8 | 1=LOAD, 2=UNLOAD, 3=SIMULTANEOUS |
| 5 | 12 | gnssPlaceAuthRecord | §2.79c | |
| 17 | 3 | vehicleOdometerValue | OdometerShort | |
| **Totale** | **20** | | | |

Formato verificato dalla composizione dei campi normativi: `TimeReal(4) + operationType(1) + GNSSPlaceAuthRecord(12) + OdometerShort(3)`.

---

### Tag 0x0527 — G22_TrailerRegistrations
- **Nome**: TrailerRegistrations — VehicleRegistrationIdentificationRecordArray
- **Annex reference**: Annex 1C (amended 2021/1228) §2.166a
- **Encoding**: RecordArray `0x24 + 0x000F + count + N x 15-byte record`
- **Decoder**: `parse_g22_trailer_registrations`

**Struttura del record interno**:

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | vehicleRegistrationNation | NationNumeric | |
| 1 | 14 | vehicleRegistrationNumber | InternationalString{13} | |
| **Totale** | **15** | | | |

Il wrapper e la dimensione sono verificati: Annex 1C §2.166a definisce `recordType`, `recordSize`, `noOfRecords` e una serie di `VehicleRegistrationIdentification` (§2.166, 15 byte).

---

### Tag 0x0528 — G22_GNSSEnhancedPlaces
- **Nome**: GNSSEnhancedPlaces / GNSSPlaceAuthRecord
- **Annex reference**: Annex 1C (amended 2021/1228) §2.79c (GNSSPlaceAuthRecord)
- **Encoding**: `N x 12-byte GNSSPlaceAuthRecord`
- **Decoder**: `parse_g22_gnss_enhanced_places`

**Struttura del record interno** (GNSSPlaceAuthRecord):

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 4 | timeStamp | TimeReal | |
| 4 | 1 | gnssAccuracy | UInt8 | |
| 5 | 6 | geoCoordinates | latitude Int24 + longitude Int24 | §2.76 |
| 11 | 1 | authenticationStatus | UInt8 | |
| **Totale** | **12** | | | |

---

### Tag 0x0529 — G22_LoadSensorData
- **Nome**: LoadSensorData
- **Annex reference**: Annex 1C (amended 2023/980) — LoadType, axle weights
- **Encoding**: payload EF piatto
- **Contiene**: timestamp + pesi per asse (2 byte ciascuno)
- **Decoder**: `parse_g22_load_sensor_data` in `decoders.py:463`
- **Stato**: ⚠️ EURISTICO (struttura parzialmente nota)

**Struttura stimata**:
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 4 | timeStamp | TimeReal | |
| 4+ | 2*n | axleWeights | UInt16[] | 2 byte per asse, 0xFFFF = non valido |

**Certezza**: LOW — la specifica 2023/980 definisce LoadType e pesi ma senza struttura byte-level pubblica.

---

### Tag 0x052A — G22_BorderCrossings
- **Nome**: BorderCrossings / CardBorderCrossingRecord
- **Annex reference**: Annex 1C (amended 2021/1228) §§2.11a, 2.11b
- **Encoding**: `borderCrossingPointerNewestRecord(2) + N x 17-byte CardBorderCrossingRecord`
- **Decoder**: `parse_g22_border_crossings`

**Struttura del record interno**:

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | countryLeft | NationNumeric | |
| 1 | 1 | countryEntered | NationNumeric | |
| 2 | 12 | gnssPlaceAuthRecord | §2.79c | |
| 14 | 3 | vehicleOdometerValue | OdometerShort | |
| **Totale** | **17** | | | |

Formato verificato dalla composizione dei campi normativi: due `NationNumeric`, `GNSSPlaceAuthRecord(12)` e `OdometerShort(3)`.

---

### Tag 0x052B — VuControllerIdentification
- **Nome**: VuControllerIdentification
- **Annex reference**: Annex 1C (amended 2021/1228) — VU configuration
- **Encoding**: RecordArray o record singolo (dimensione variabile)
- **Decoder**: `parse_g22_controller_identification` in `g2_decoders.py:256`
- **Stato**: ⚠️ PARZIALMENTE IMPLEMENTATO (struttura variabile con CodedString)

**Struttura** (record singolo, dimensione variabile):

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | manufacturerCode | UInt8 | |
| 1 | var | manufacturerName | CodedString | codePage(1) + size(1) + text |
| var | var | hardwareVersion | CodedString | codePage(1) + size(1) + text |
| var | var | softwareVersion | CodedString | codePage(1) + size(1) + text |
| var | 8 | approvalNumber | UInt64 BE | |
| var | 8 | serialNumber | UInt64 BE | |
| var | 1 | manufacturingYear | UInt8 | offset da 2000 |

**Certezza**: MEDIUM — struttura ragionevolmente dedotta dalla specifica G2.2, ma non confermata da documentazione pubblica.

---

### Tag 0x052C — VuDetailedSpeedData (RECORDARRAY)
- **Nome**: VuDetailedSpeedBlockRecordArray
- **Annex reference**: Annex 1C §2.191 (amended 2016/799)
- **Dimensione record**: **64 byte** (confermato)
- **Decoder**: ❌ NON IMPLEMENTATO
- **Stato**: ❌ ASSENTE

**Struttura** (VuDetailedSpeedBlock, 64 byte):

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 4 | speedBlockBeginDate | TimeReal | |
| 4 | 60 | speedsPerSecond | UInt8[60] | 1 byte al secondo per 1 minuto |

**Certezza**: HIGH — specifica Annex 1C §2.190-2.191: speedBlockBeginDate + 60 speed values (1/sec).

---

### Tag 0x052D — VuOverSpeedingEventData (RECORDARRAY)
- **Nome**: VuOverSpeedingEventRecordArray
- **Annex reference**: Annex 1C §2.215 (G1) + amendments 2021/1228 per G2
- **Dimensione record**: **33 byte** (G2, stima)
- **Decoder**: ❌ NON IMPLEMENTATO
- **Stato**: ❌ ASSENTE

**Struttura** (VuOverSpeedingEventRecord G2):

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | eventType | UInt8 | |
| 1 | 1 | eventRecordPurpose | UInt8 | |
| 2 | 4 | eventBeginTime | TimeReal | |
| 6 | 4 | eventEndTime | TimeReal | |
| 10 | 1 | maxSpeedValue | UInt8 | km/h |
| 11 | 1 | averageSpeedValue | UInt8 | km/h |
| 12 | 20 | cardNumberAndGenDriverSlotBegin | FullCardNumber+Gen | generation(1) + nation(1) + cardNumber(16) + terminator(0x02) |
| 32 | 1 | similarEventsNumber | UInt8 | |

**Certezza**: MEDIUM — derivato dalla specifica Annex 1C §2.215 (campologia) ma le dimensioni esatte dei campi intermedi possono variare. Il `cardNumberAndGen` in G2 include un byte generation. Totale stimato: 33 byte.

---

### Tag 0x052E — VuOverSpeedingControlData (RECORDARRAY)
- **Nome**: VuOverSpeedingControlDataRecordArray
- **Annex reference**: Annex 1C §2.212-2.213
- **Dimensione record**: **10 byte** (stima)
- **Decoder**: ❌ NON IMPLEMENTATO
- **Stato**: ❌ ASSENTE

**Struttura** (VuOverSpeedingControlData, a singolo record):

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 4 | lastOverspeedControlTime | TimeReal | |
| 4 | 4 | firstOverspeedSince | TimeReal | |
| 8 | 2 | numberOfOverspeedSince | UInt16 | |
| **Totale** | **10** | | | |

**Certezza**: MEDIUM — derivato dai campi definiti in Annex 1C §2.212.

---

### Tag 0x052F — VuTimeAdjustmentGNSSRecord (RECORDARRAY)
- **Nome**: VuTimeAdjustmentGNSSRecordArray
- **Annex reference**: Annex 1C §2.230-2.231
- **Dimensione record**: **8 byte** (stima)
- **Decoder**: ❌ NON IMPLEMENTATO
- **Stato**: ❌ ASSENTE

**Struttura** (VuTimeAdjustmentGNSSRecord):

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 4 | oldTimeValue | TimeReal | |
| 4 | 4 | newTimeValue | TimeReal | |
| **Totale** | **8** | | | |

**Certezza**: MEDIUM — definito in Annex 1C §2.230 come avente solo oldTimeValue e newTimeValue.

---

### Tag 0x0530 — VuPowerSupplyInterruptionData (RECORDARRAY)
- **Nome**: VuPowerSupplyInterruptionRecordArray
- **Annex reference**: Annex 1C §2.240-2.241
- **Dimensione record**: **90 byte** (G2, stima)
- **Decoder**: ❌ NON IMPLEMENTATO
- **Stato**: ❌ ASSENTE

**Struttura** (VuPowerSupplyInterruptionRecord G2):

| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | eventType | UInt8 | |
| 1 | 1 | eventRecordPurpose | UInt8 | |
| 2 | 4 | eventBeginTime | TimeReal | |
| 6 | 4 | eventEndTime | TimeReal | |
| 10 | 20 | cardNumberAndGenDriverSlotBegin | FullCardNumber+Gen | |
| 30 | 20 | cardNumberAndGenDriverSlotEnd | FullCardNumber+Gen | |
| 50 | 20 | cardNumberAndGenCodriverSlotBegin | FullCardNumber+Gen | |
| 70 | 20 | cardNumberAndGenCodriverSlotEnd | FullCardNumber+Gen | |
| **Totale** | **90** | | | |

**Certezza**: MEDIUM — derivato dai campi in Annex 1C §2.240. FullCardNumber con generation = 20 byte (1 gen + 1 nation + 16 cardNumber + 1 terminator + 1 padding? o 18+1?).

---

### Tag 0x0531 — VuSensorFaultData (RECORDARRAY)
- **Nome**: VuSensorFaultRecordArray
- **Annex reference**: Annex 1C (amended 2021/1228) — sensor fault events
- **Dimensione record**: **~90 byte** (stima, struttura simile a PowerSupplyInterruption)
- **Decoder**: ❌ NON IMPLEMENTATO
- **Stato**: ❌ ASSENTE

Struttura analoga a VuPowerSupplyInterruptionRecord ma con sensor-specific data. Nessuna documentazione pubblica trovata per la struttura byte-level esatta.

**Certezza**: LOW — nessuna conferma da specifica pubblica.

---

### Tag 0x0532 — G22_SensorExternalGNSSCoupledData (RECORDARRAY)
- **Nome**: VuSensorExternalGNSSCoupledRecordArray
- **Annex reference**: Annex 1C §2.242
- **Dimensione record**: **20 byte** (stessa struttura di 0x0511)
- **Decoder**: ❌ NON IMPLEMENTATO in G2_VU_RECORD_DECODERS
- **Stato**: ⚠️ STRUTTURA NOTA, DECODER MANCANTE

**Struttura**: identica a SensorExternalGNSSCoupledData (0x0511, 20 byte). Stessi campi: serialNumber(8) + approvalNumber(8) + couplingDate(4).

Il decoder esiste (`parse_g2_sensor_gnss_coupled`) ma non e' registrato in `G2_VU_RECORD_DECODERS` per il tag 0x0532.

**Certezza**: HIGH — struttura nota, confermata da Annex 1C §2.242.

---

### Tag 0x0533 — G22_SensorPairedData (RECORDARRAY)
- **Nome**: VuSensorPairedRecordArray
- **Annex reference**: Annex 1C §2.243
- **Dimensione record**: **24 byte** (stessa struttura di 0x0510)
- **Decoder**: ❌ NON IMPLEMENTATO in G2_VU_RECORD_DECODERS
- **Stato**: ⚠️ STRUTTURA NOTA, DECODER MANCANTE

**Struttura**: identica a SensorPairedData (0x0510, 24 byte). Stessi campi: sensorSerialNumber(8) + sensorApprovalNumber(8) + pairingDateFirst(4) + pairingDateCurrent(4).

Il decoder esiste (`parse_g2_sensor_paired`) ma non e' registrato in `G2_VU_RECORD_DECODERS` per il tag 0x0533.

**Certezza**: HIGH — struttura nota, confermata da Annex 1C §2.243.

---

## 7. G2.2 Certificate Sub-tags (inside 0x7F21 security container)

| Tag | Nome | Dimensione | Decoder | Stato |
|-----|------|-----------|---------|-------|
| 0x5F20 | G22_CardHolderName | Variabile (CodedString) | `parse_g22_certificate_subtag` | ✅ |
| 0x5F24 | G22_CardEffectiveDate | 4 byte (TimeReal o Datef) | `parse_g22_certificate_subtag` | ✅ |
| 0x5F25 | G22_CardExpiryDate | 4 byte (TimeReal o Datef) | `parse_g22_certificate_subtag` | ✅ |
| 0x5F29 | G22_CardIssuingMemberState | 1 byte (NationNumeric) | `parse_g22_certificate_subtag` | ✅ |
| 0x5F37 | G22_CertificateSignature | 64 byte (ECDSA P-256 r\|s) | `parse_certificate_signature` | ✅ |
| 0x5F4C | G22_CardExtendedSerialNumber | Variabile (ICC serial) | `parse_g22_certificate_subtag` | ✅ |
| 0x7F49 | G22_PublicKeyInfo | Variabile (EC curve OID + point Q) | `parse_public_key_info` | ✅ |
| 0x960F | G22_GNSS_Auth_Data | Sconosciuto | Nessuno | ❌ |
| 0x6399 | G22_Load_Unload_Auth | Sconosciuto | Nessuno | ❌ |

---

## 8. G2.2 Internal VU Elementary Files

Questi tag (0x0225-0x0228) rappresentano EF interni alla VU e sono anch'essi CONTAINER con codifica BER-TLV.

| Tag | Nome | Mappato a decoder | Note |
|-----|------|------------------|------|
| 0x0225 | G22_VU_GNSSADRecord | `parse_g22_gnss_enhanced_places` (⚠️ mappatura errata!) | Dovrebbe mappare a `parse_g22_gnss_accumulated_driving` |
| 0x0226 | G22_VU_LoadUnloadRecord | `parse_g22_load_unload_operations` | ✅ Corretto |
| 0x0227 | G22_VU_TrailerRecord | `parse_g22_trailer_registrations` | ✅ Corretto |
| 0x0228 | G22_VU_BorderCrossingRecord | `parse_g22_border_crossings` | ✅ Corretto |

**Bug rilevato**: 0x0225 (`G22_VU_GNSSADRecord` = GNSS Accumulated Driving Record) e' mappato a `parse_g22_gnss_enhanced_places` invece che a `parse_g22_gnss_accumulated_driving` in `tag_navigator.py:302`.

---

## 9. Record G2/G2.2 dei Daily Activity (TREP 02 / 22)

### G2 Daily Activity Record (0x7622)
- **Dimensione**: **113 byte**
- **Struttura** (Annex 1C):
  - header: tag(2) + dtype(1) + length(2) + dailyCounter(4) = 9 byte
  - STAP pseudo-header: tag(2) + dtype(1) + len(3) = 6 byte
  - dayField(2) + marker(1) + changesCount(2) = 5 byte
  - counters: 11 x UInt16 = 22 byte
  - padding(1) + sigLen(1) + marker(2) = 4 byte
  - signature: 64 byte (ECDSA r||s)
  - totale: 9 + 6 + 5 + 22 + 4 + 64 = **110 byte** (+ 3 di padding variabile = **113**)

### G2.2 Daily Activity Record (0x7632)
- **Dimensione**: **128 byte** (48 + ECDSA signature 80 byte per brainpoolP256r1)
- Stessa struttura ma con firma piu' lunga (brainpool vs NIST P-256)

---

## 10. Tabella riepilogativa — Stato decoder G2.2

| Tag | Nome | Dimensione Record | Certezza | Decoder | Stato |
|-----|------|-------------------|----------|---------|-------|
| 0x0525 | GNSSAccumulatedDriving | pointer(2) + 19 | HIGH | `parse_g22_gnss_accumulated_driving` | ✅ |
| 0x0526 | LoadUnloadOperations | 20 | HIGH | `parse_g22_load_unload_operations` | ✅ |
| 0x0527 | TrailerRegistrations | RecordArray, 15 | HIGH | `parse_g22_trailer_registrations` | ✅ |
| 0x0528 | GNSSEnhancedPlaces | 12 | HIGH | `parse_g22_gnss_enhanced_places` | ✅ |
| 0x0529 | LoadSensorData | Variabile | LOW | `parse_g22_load_sensor_data` | ⚠️ Euristico |
| 0x052A | BorderCrossings | 17 | HIGH | `parse_g22_border_crossings` | ✅ |
| 0x052B | VuControllerIdentification | Variabile | MEDIUM | `parse_g22_controller_identification` | ⚠️ Parziale |
| 0x052C | VuDetailedSpeedData | 64 | HIGH | Nessuno | ❌ Assente |
| 0x052D | VuOverSpeedingEventData | 33 (stima) | MEDIUM | Nessuno | ❌ Assente |
| 0x052E | VuOverSpeedingControlData | 10 (stima) | MEDIUM | Nessuno | ❌ Assente |
| 0x052F | VuTimeAdjustmentGNSSRecord | 8 (stima) | MEDIUM | Nessuno | ❌ Assente |
| 0x0530 | VuPowerSupplyInterruptionData | 90 (stima) | MEDIUM | Nessuno | ❌ Assente |
| 0x0531 | VuSensorFaultData | ~90 (stima) | LOW | Nessuno | ❌ Assente |
| 0x0532 | G22_SensorExternalGNSSCoupled | 20 | HIGH | Esistente (non registrato) | ⚠️ Mancante in dispatch |
| 0x0533 | G22_SensorPairedData | 24 | HIGH | Esistente (non registrato) | ⚠️ Mancante in dispatch |
| 0x0225 | G22_VU_GNSSADRecord | (container) | — | Mappato a decoder errato | ⚠️ Bug |
| 0x960F | G22_GNSS_Auth_Data | Sconosciuto | LOW | Nessuno | ❌ Assente |
| 0x6399 | G22_Load_Unload_Auth | Sconosciuto | LOW | Nessuno | ❌ Assente |

---

## 11. Problemi identificati nel codebase

### 11.1 — Tag 0x052C-0x0533 non in G2_VU_RECORD_DECODERS
`g2_decoders.py:309` — `G2_VU_RECORD_DECODERS` contiene solo 0x0509-0x0512 e 0x052B.
`decoders.py:167-169` — `parse_g2_vu_record` controlla `if tag not in decoders_map: return`, quindi i tag 0x052C-0x0533 vengono silenziosamente ignorati anche se il `tag_navigator.py:274-278` li dispatcherebbe.

**Fix**: aggiungere entries per 0x052C-0x0533 in `G2_VU_RECORD_DECODERS`.

### 11.2 — Tag 0x0532 e 0x0533
I decoder `parse_g2_sensor_gnss_coupled` e `parse_g2_sensor_paired` esistono ma sono registrati solo per i tag G2 (0x0511, 0x0510). Per G2.2 si possono riusare con la stessa funzione, aggiungendo le entries in `G2_VU_RECORD_DECODERS`.

### 11.3 — Tag 0x0225 mappato a decoder errato
`tag_navigator.py:302` mappa `0x0225` a `parse_g22_gnss_enhanced_places` ma 0x0225 e' `G22_VU_GNSSADRecord` (GNSS Accumulated Driving record). Dovrebbe invece mappare a `parse_g22_gnss_accumulated_driving` (tag 0x0525).

### 11.4 — Tag 0x0225 e 0x0226 riferimento incrociato
`tag_navigator.py:298-303`:
```python
elif tag == 0x0526 or tag == 0x0226:
    decoders.parse_g22_load_unload_operations(...)
elif tag == 0x0527 or tag == 0x0227:
    decoders.parse_g22_trailer_registrations(...)
elif tag == 0x0528 or tag == 0x0225:  # ← BUG: 0x0225 != 0x0528
    decoders.parse_g22_gnss_enhanced_places(...)
elif tag == 0x052A or tag == 0x0228:
    decoders.parse_g22_border_crossings(...)
```

Il riferimento 0x0225 dovrebbe essere associato a 0x0525 (GNSS Accumulated Driving), non a 0x0528 (GNSS Enhanced Places).

### 11.5 — RecordArray header nel dispatch
`decoders.py:173` controlla la presenza di un header RecordArray e, se presente, itera i record. Per i tag 0x052C-0x0533, anche quando verranno aggiunti decoder, questo meccanismo funzionera' automaticamente poiche' il RecordArray e' gestito in modo generico.

---

## 12. Riferimenti normativi per ogni record G2.2

| Record | Annex 1C Section | Introdotto da |
|--------|-----------------|---------------|
| VuCardRecord | §4.5.3.2.8 | 2016/799 |
| VuCardIWRecord | §4.5.3.2.9 | 2016/799 |
| VuDownloadablePeriod | §4.5.3.2.10 | 2016/799 |
| VuTimeAdjustmentData | §4.5.3.2.12 | 2016/799 |
| VuCompanyLocksData | §4.5.3.2.14 | 2016/799 |
| SensorPairedData | §4.5.3.2.15 | 2016/799 |
| SensorExternalGNSSCoupledData | §4.5.3.2.16 | 2016/799 |
| VuITSConsentData | §4.5.3.2.17 | 2016/799 |
| GNSSAccumulatedDrivingRecord | §2.79 | 2021/1228 |
| GNSSAuthStatusADRecord | §2.79b | 2021/1228 |
| GNSSPlaceAuthRecord | §2.79c | 2021/1228 |
| VuBorderCrossingRecord | §2.203a | 2021/1228 |
| VuBorderCrossingRecordArray | §2.203b | 2021/1228 |
| VuLoadUnloadRecord | §2.208a | 2021/1228 |
| VuLoadUnloadRecordArray | §2.208b | 2021/1228 |
| VehicleRegistrationIdentificationRecordArray | §2.166a | 2021/1228 |
| VuDetailedSpeedBlock | §2.190 | 2016/799 |
| VuDetailedSpeedBlockRecordArray | §2.191 | 2016/799 |
| VuOverSpeedingControlData | §2.212 | 2016/799 |
| VuOverSpeedingControlDataRecordArray | §2.213 | 2016/799 |
| VuOverSpeedingEventRecord | §2.215 | 2016/799 |
| VuOverSpeedingEventData | §2.214 | 2016/799 |
| VuTimeAdjustmentGNSSRecord | §2.230 | 2016/799 |
| VuTimeAdjustmentGNSSRecordArray | §2.231 | 2016/799 |
| VuPowerSupplyInterruptionRecord | §2.240 | 2016/799 |
| VuSensorExternalGNSSCoupledRecordArray | §2.242 | 2016/799 |
| VuSensorPairedRecordArray | §2.243 | 2016/799 |
| LoadType | §2.90a | 2021/1228 |
| NoOfBorderCrossingRecords | §2.101a | 2021/1228 |
| NoOfLoadUnloadRecords | §2.111a | 2021/1228 |
| VuConfigurationLengthRange | §2.185a | 2021/1228 |
| VuDigitalMapVersion | §2.192a | 2021/1228 |
| VuGnssMaximalTimeDifference | §2.204a | 2021/1228 |
| VuRtcTime | §2.222a | 2021/1228 |

---

*Documento generato il 2026-06-08 da Agent 2 — Spec G2/G2.2*
