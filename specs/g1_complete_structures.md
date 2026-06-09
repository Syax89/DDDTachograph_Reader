# G1 Complete Structures — Annex 1B (Reg. 3821/85)

**Document version**: 1.0  
**Date**: 2026-06-08  
**References**:
- Reg. CE 1360/2002 — Annex 1B (jugglingcats/tachograph-reader repo PDF `1360_2002-Annex_1B-GB.pdf`)
- `DriverCardData.config` / `VehicleUnitData.config` — C# reference implementation (jugglingcats/tachograph-reader)
- ECE/TRANS/SC.1/2006/2/Add.1 — UNECE consolidated spec

**Conventions**:
- All integers are **big-endian** (network byte order)
- `TimeReal` = Unix timestamp, unsigned 32-bit big-endian, seconds since 1970-01-01 00:00:00 UTC (Annex 1B §2.162)
- `Datef` = BCD-encoded date: `[YYh][YYl][MM][DD]`, 4 bytes (Annex 1B §2.26)
- `Name` = 36 bytes: 1 byte CodePage + 35 byte Latin-1 string (Annex 1B §2.74)
- `CardNumber` = 16 bytes: 1 byte CodePage + 15 byte alphanumeric
- `InternationalString L=N` = 1 byte CodePage + N byte string
- `Country/NationNumeric` = 1 byte numeric code (Annex 1B nation table)
- `UInt24` = 3-byte unsigned integer, big-endian
- `BCDString Size=N` = N bytes, each byte encodes 2 BCD digits

---

## Driver Card Tags

### Tag 0x0002 — EF_ICC (CardIccIdentification)

- **Nome**: G1_CardIccIdentification
- **Annex reference**: Annex 1B §2.7
- **Dimensione record**: 18+ byte (variabile)
- **Numero record**: 1
- **Stato decoder**: ⚠️ PARZIALE — decoder euristico, non basato sulla struttura ASN.1 esatta
- **Decoder function**: `parse_ef_icc()` (decoders.py:726)

**Struttura** (da C# config):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | ClockStop | UInt8 | 0=Normal, else stopped |
| 1 | 8 | CardExtendedSerialNumber | ExtendedSerialNumber | 8 byte serial |
| 9 | 8 | CardApprovalNumber | SimpleString(8) | Approval code |
| 17 | 1 | CardPersonaliserId | UInt8 | Personaliser ID |
| 18 | 4 | EmbedderIcAssemblerId | Object | CountryCode(2) + BCD(2) + ManufacturerInfo(1) |
| 22 | 2 | IcIdentifier | UInt16 | IC identifier |
| 24+ | — | HistoricalInfo | variable | Historical bytes (ISO 7816) |

**Nota**: La dimensione totale non è fissa a causa dei campi variabili. Il decoder attuale legge i primi 9 byte come clock_stop + ic_data e interpreta il resto come historical_info testuale.

---

### Tag 0x0005 — EF_IC (CardChipIdentification)

- **Nome**: G1_CardChipIdentification
- **Annex reference**: Annex 1B §2.6
- **Dimensione record**: 8 byte
- **Numero record**: 1
- **Stato decoder**: ⚠️ PARZIALE — restituisce solo hex dump, senza parsed fields
- **Decoder function**: `parse_ef_ic()` (decoders.py:743)

**Struttura** (da C# config):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 4 | IcSerialNumber | HexValue(4) | IC serial number |
| 4 | 4 | IcManufacturingReferences | HexValue(4) | Manufacturing refs |

**Nota**: Il decoder attuale non esegue parsing strutturato, restituisce solo l'hex dump dell'intero valore.

---

### Tag 0x0100 — CardIssuerIdentification

- **Nome**: G1_CardIssuerIdentification
- **Annex reference**: Annex 1B §2.9 (inferred)
- **Dimensione record**: 20+ byte (variabile)
- **Numero record**: 1
- **Stato decoder**: ⚠️ EURISTICO — usa regex per estrarre numero carta e nome azienda
- **Decoder function**: `parse_card_issuer_identification()` (decoders.py:878)

**Nota**: La struttura esatta di questo tag non è documentata nel file config C# di riferimento (non presente in `DriverCardData.config`). Il decoder usa pattern-matching euristici (regex su `[A-Z]\d{13,20}` per numeri carta italiani). **NON basato su specifica**.

---

### Tag 0x0101 — G2_CardIccIdentification

- **Nome**: G2_CardIccIdentification
- **Annex reference**: Annex 1C §2.23
- **Dimensione record**: 8+ byte (variabile)
- **Numero record**: 1
- **Stato decoder**: ⚠️ PARZIALE — solo campi base + scan euristico nome azienda
- **Decoder function**: `parse_g2_card_icc_identification()` (decoders.py:654)

**Struttura** (G2, da Annex 1C):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | ClockStop | UInt8 | 0=Normal |
| 1 | 8 | CardExtendedSerialNumber | HexValue(8) | Serial number |
| 9 | 8 | CardApprovalNumber | SimpleString(8) | Approval code |
| 17 | 1 | CardPersonaliserId | UInt8 | |
| 18 | 4 | EmbedderIcAssemblerId | Object | Country(2) + BCD(2) + Mfr(1) |
| 22 | 2 | IcIdentifier | UInt16 | |

**Nota**: Questo è un tag G2, non G1. Nel contesto del codebase locale, viene dispatchato per entrambe le generazioni.

---

### Tag 0x0102 — G2_CardIdentification

- **Nome**: G2_CardIdentification
- **Annex reference**: Annex 1C §2.24
- **Dimensione record**: 23 byte (fissi)
- **Numero record**: 1
- **Stato decoder**: ✅ CORRETTO
- **Decoder function**: `parse_card_identification()` (decoders.py:307)

**Struttura** (G2):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | CardIssuingMemberState | NationNumeric | |
| 1 | 16 | CardNumber | CardNumber(16) | CodePage + 15 chars |
| 17 | 2 | CardIssuingAuthorityName | ??? | 2 bytes, partial |
| 19 | 4 | CardExpiryDate | TimeReal | |

**Nota**: Il decoder legge solo nation(1) + cardNumber(16) + expiryDate(bytes 19:23). I campi intermedi (CardIssuingAuthorityName 36 byte, CardIssueDate 4 byte, CardValidityBegin 4 byte) sono saltati. La dimensione totale corretta dovrebbe essere 65 byte (come da 0x0520).

---

### Tag 0x0103 — G2_CardCertificate

- **Nome**: G2_CardCertificate
- **Annex reference**: Annex 1C §2.30
- **Dimensione record**: 194 byte (128 sig + 58 pubkey + 8 CA ref)
- **Numero record**: 1
- **Stato decoder**: ❌ ASSENTE — solo registrazione raw
- **Decoder function**: N/A (gestito come raw in `record_raw_tag`)
- **Nota**: Certificato ECDSA/RSA della carta. La struttura è: Signature(128) + PublicKeyRemainder(58) + CertificationAuthorityReference(8). Il codice lo salva in `self.parser.card_cert_raw`.

---

### Tag 0x0104 — G2_MemberStateCertificate

- **Nome**: G2_MemberStateCertificate
- **Annex reference**: Annex 1C §2.31
- **Dimensione record**: 194 byte (come card cert)
- **Numero record**: 1
- **Stato decoder**: ❌ ASSENTE — solo registrazione raw
- **Decoder function**: N/A (salvato in `self.parser.msca_cert_raw`)

---

### Tag 0x0201 — DriverCardHolderIdentification (G2)

- **Nome**: G2_DriverCardHolderIdentification
- **Annex reference**: Annex 1B §2.17 (G1) / Annex 1C §2.17 (G2)
- **Dimensione record**: 78 byte (fissi)
- **Numero record**: 1
- **Stato decoder**: ✅ CORRETTO
- **Decoder function**: `parse_driver_card_holder_identification()` (decoders.py:313)

**Struttura**:
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 36 | CardHolderSurname | Name(36) | CodePage + 35 chars Latin-1 |
| 36 | 36 | CardHolderFirstNames | Name(36) | CodePage + 35 chars Latin-1 |
| 72 | 4 | CardHolderBirthDate | Datef/TimeReal | BCD (Annex 1B §2.26) or Unix TS |
| 76 | 2 | CardHolderPreferredLanguage | SimpleString(2) | ISO language code |

**Nota**: Il decoder usa `decode_date()` che prova prima TimeReal (Unix TS), poi Datef (BCD). Vedi BUG B6 in COMPLIANCE_REPORT: il `Datef` per la data di nascita andrebbe sempre decodificato come BCD.

---

### Tag 0x0501 — DriverCardApplicationIdentification

- **Nome**: G1_DriverCardApplicationIdentification
- **Annex reference**: Annex 1B §2.28
- **Dimensione record**: 10 byte (fissi)
- **Numero record**: 1
- **Stato decoder**: ✅ CORRETTO
- **Decoder function**: `parse_g1_app_identification()` (decoders.py:512)

**Struttura** (da C# `DriverCardData.config`, Identifier="0x0501"):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | Type | UInt8 | Tipo applicazione carta |
| 1 | 2 | Version | UInt16 | Versione (big-endian) |
| 3 | 1 | NoOfEventsPerType | UInt8 | GlobalValue: usato come count per eventi |
| 4 | 1 | NoOfFaultsPerType | UInt8 | GlobalValue: usato come count per guasti |
| 5 | 2 | ActivityStructureLength | UInt16 | Lunghezza struttura attività |
| 7 | 2 | NoOfCardVehicleRecords | UInt16 | GlobalValue: numero veicoli usati |
| 9 | 1 | NoOfCardPlaceRecords | UInt8 | GlobalValue: numero luoghi |

**Totale**: 1+2+1+1+2+2+1 = 10 byte

---

### Tag 0x0502 — CardEventData

- **Nome**: G1_EventsData
- **Annex reference**: Annex 1B §2.20
- **Dimensione record**: 24 byte per evento (fissi)
- **Numero record**: 6 gruppi × `NoOfEventsPerType` eventi ciascuno
- **Stato decoder**: ✅ CORRETTO
- **Decoder function**: `parse_g1_events_data()` (decoders.py:535)

**Struttura** (da C# `DriverCardData.config`):
```
CardEventData ::= SEQUENCE (SIZE(6)) OF {      -- 6 gruppi di eventi
    SEQUENCE (SIZE(NoOfEventsPerType)) OF CardEventRecord
}
```

**CardEventRecord** (24 byte):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | EventType | UInt8 | Codice tipo evento |
| 1 | 4 | EventBeginTime | TimeReal | Inizio evento |
| 5 | 4 | EventEndTime | TimeReal | Fine evento (0xFFFFFFFF = "in corso") |
| 9 | 1 | VehicleRegistrationNation | NationNumeric | |
| 10 | 14 | VehicleRegistrationNumber | InternationalString(13) | CodePage + 13 chars |

**Totale per record**: 1+4+4+1+14 = 24 byte

**Gruppi di eventi** (ordine da Annex 1B):
1. TimeOverlap
2. LastCardSession (not properly closed)
3. PowerSupplyInterruption
4. CardConflict
5. TimeDifference
6. DrivingWithoutCard

**Nota**: Il decoder avanza sequenzialmente, fermandosi quando trova `EventType == 0xFF` o timestamp 0/0xFFFFFFFF per fine gruppo.

---

### Tag 0x0503 — CardFaultData

- **Nome**: G1_FaultsData
- **Annex reference**: Annex 1B §2.21
- **Dimensione record**: 24 byte per guasto (fissi)
- **Numero record**: 2 gruppi × `NoOfFaultsPerType` guasti ciascuno
- **Stato decoder**: ✅ CORRETTO
- **Decoder function**: `parse_g1_faults_data()` (decoders.py:571)

**Struttura** (da C# `DriverCardData.config`):
```
CardFaultData ::= SEQUENCE (SIZE(2)) OF {       -- 2 gruppi di guasti
    SEQUENCE (SIZE(NoOfFaultsPerType)) OF CardFaultRecord
}
```

**CardFaultRecord** (24 byte):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | FaultType | UInt8 | Codice tipo guasto |
| 1 | 4 | FaultBeginTime | TimeReal | Inizio guasto |
| 5 | 4 | FaultEndTime | TimeReal | Fine guasto (0xFFFFFFFF = attivo) |
| 9 | 1 | VehicleRegistrationNation | NationNumeric | |
| 10 | 14 | VehicleRegistrationNumber | InternationalString(13) | CodePage + 13 chars |

**Totale per record**: 24 byte (identico a CardEventRecord)

**Gruppi di guasti**:
1. RecordingEquipment
2. Card

---

### Tag 0x0504 — DriverActivityData (Buffer Ciclico)

- **Nome**: G1_DriverActivityData
- **Annex reference**: Annex 1B §2.32
- **Dimensione record**: Variabile (buffer ciclico: 4 byte header + N record giornalieri)
- **Numero record**: 1 (il buffer contiene 366+ giorni)
- **Stato decoder**: ✅ CORRETTO
- **Decoder function**: `parse_cyclic_buffer_activities()` (decoders.py:106)

**Struttura buffer ciclico**:
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 2 | OldestPointer | UInt16 | Puntatore al record più vecchio |
| 2 | 2 | NewestPointer | UInt16 | Puntatore al record più nuovo |
| 4 | — | DailyRecords | — | Record giornalieri a partire da offset 4 |

**DailyRecord header** (8 byte):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 2 | PreviousRecordLength | UInt16 | Lunghezza record precedente (per navigazione all'indietro) |
| 2 | 2 | CurrentRecordLength | UInt16 | Lunghezza record corrente (12 + N×2 per attività) |
| 4 | 4 | TimeReal | TimeReal | Timestamp inizio giornata |

**DailyRecord body**:
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 8 | 2 | DailyPresenceCounter | UInt16 | Contatore presenza giornaliera |
| 10 | 2 | DayDistance | UInt16 | Distanza percorsa (km) |
| 12 | N×2 | ActivityChangeInfo | UInt16[N] | Array di cambi attività |

**ActivityChangeInfo** (2 byte, bit layout):
| Bit | Nome | Valori |
|-----|------|--------|
| 15 | Slot | 0=Primo, 1=Secondo |
| 14 | DrivingStatus | 0=Single, 1=Crew |
| 13 | CardStatus | 0=Inserted, 1=Not inserted |
| 12-11 | Activity | 0=REST, 1=AVAILABILITY, 2=WORK, 3=DRIVING |
| 10-0 | Minutes | 0-1439 minuti dall'inizio giornata |

**Nota**: Il decoder implementa navigazione all'indietro tramite wrap-around con `get_cyclic_data()` e gestisce il "Fix Midnight Bug" (valore 0xFFFF è comunque un'attività valida a mezzanotte).

---

### Tag 0x0505 — CardVehiclesUsed

- **Nome**: G1_VehiclesUsed
- **Annex reference**: Annex 1B §2.19
- **Dimensione record**: 31 byte (G1), 35 byte (G2)
- **Numero record**: `NoOfCardVehicleRecords` (da 0x0501)
- **Stato decoder**: ✅ CORRETTO (dopo fix B2)
- **Decoder function**: `parse_g1_vehicles_used()` (decoders.py:234)

**Struttura G1** (31 byte, da C# config):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | — | — | VehiclePointerNewestRecord (header, non parte del record) |
| 1 | 1 | — | — | padding/alignment |
| — | — | **CardVehicleRecord** (×N) | — | — |
| +0 | 3 | VehicleOdometerBegin | UInt24 | km inizio utilizzo |
| +3 | 3 | VehicleOdometerEnd | UInt24 | km fine utilizzo |
| +6 | 4 | VehicleFirstUse | TimeReal | Primo utilizzo veicolo |
| +10 | 4 | VehicleLastUse | TimeReal | Ultimo utilizzo veicolo |
| +14 | 1 | VehicleRegistrationNation | NationNumeric | |
| +15 | 14 | VehicleRegistrationNumber | InternationalString(13) | CodePage + 13 chars |
| +29 | 2 | VuDataBlockCounter | BCDString(2) | Counter BCD-encoded |

**Totale per record**: 3+3+4+4+1+14+2 = 31 byte

**Struttura G2** (35 byte, Annex 1C):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| +0 | 4 | VehicleOdometerBegin | UInt32 | km (UInt32 invece di UInt24) |
| +4 | 4 | VehicleOdometerEnd | UInt32 | km |
| +8 | 4 | VehicleFirstUse | TimeReal | |
| +12 | 4 | VehicleLastUse | TimeReal | |
| +16 | 1 | VehicleRegistrationNation | NationNumeric | |
| +17 | 14 | VehicleRegistrationNumber | InternationalString(13) | |
| +31 | 2 | VuDataBlockCounter | BCDString(2) | |
| +33 | 2 | VehicleOdometerDifference | UInt16 | Differenza km (G2 only) |

**Totale G2**: 4+4+4+4+1+14+2+2 = 35 byte

**Nota**: Il BUG B2 (COMPLIANCE_REPORT §1.4) riportava ordine campi errato. L'ordine sopra è quello **corretto**, già implementato nel decoder attuale dopo il fix. Il codice determina automaticamente G1 vs G2 dalla divisibilità del payload per 35.

---

### Tag 0x0506 — CardPlaceDailyWorkPeriod

- **Nome**: G1_Places
- **Annex reference**: Annex 1B §2.22
- **Dimensione record**: 10 byte (G1 base), 12/13/27 byte (varianti)
- **Numero record**: `NoOfCardPlaceRecords` (da 0x0501)
- **Stato decoder**: ⚠️ PARZIALE — record size determinato euristicamente
- **Decoder function**: `parse_g1_places()` (decoders.py:603)

**Struttura G1 base** (10 byte, da C# config):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | PlacePointerNewestRecord | UInt8 | Puntatore (header) |
| 1 | 1 | — | — | possibile padding |
| — | — | **PlaceRecord** (×N) | — | — |
| +0 | 4 | EntryTime | TimeReal | |
| +4 | 1 | EntryType | UInt8 | 0x01=START, 0x02=END |
| +5 | 1 | DailyWorkPeriodCountry | NationNumeric | |
| +6 | 1 | DailyWorkPeriodRegion | UInt8 | |
| +7 | 3 | VehicleOdometerValue | UInt24 | Odometer in km |

**Totale per record**: 4+1+1+1+3 = 10 byte (minimo)

**Varianti**:
- 12 byte: come 10 byte + padding/alignment (osservata dal decoder)
- 13 byte: include campi aggiuntivi G2
- 27 byte: include anche VehicleRegistration (plate_nation + plate) per G2

**Nota**: Il decoder tenta diverse dimensioni record in base alla divisibilità del payload. Salta timestamp non validi (< 2000 o > 2100) e codici nazione > 0xFD.

---

### Tag 0x0507 — CardCurrentUse

- **Nome**: G1_CurrentUsage
- **Annex reference**: Annex 1B §2.23
- **Dimensione record**: 19 byte (fissi)
- **Numero record**: 1
- **Stato decoder**: ✅ CORRETTO
- **Decoder function**: `parse_g1_current_usage()` (decoders.py:298)

**Struttura** (da C# config):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 4 | SessionOpenTime | TimeReal | |
| 4 | 1 | VehicleRegistrationNation | NationNumeric | |
| 5 | 14 | VehicleRegistrationNumber | InternationalString(13) | CodePage + 13 chars |

**Totale**: 4+1+14 = 19 byte

**Nota**: Il decoder verifica che il timestamp sia valido (< 1798758400 = ~2027-01-01) e non sia 0 o 0xFFFFFFFF.

---

### Tag 0x0508 — ControlActivityData

- **Nome**: G1_ControlActivityData
- **Annex reference**: Annex 1B §2.23 (control activity)
- **Dimensione record**: 46 byte per record (da C# config), ma il decoder usa 24 byte
- **Numero record**: variabile
- **Stato decoder**: ❌ NON CONFORME — dimensione record errata, campi missing
- **Decoder function**: `parse_control_activity_data()` (decoders.py:767)

**Struttura corretta** (da C# config, 46 byte per record):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | ControlType | UInt8 | |
| 1 | 4 | ControlTime | TimeReal | |
| 5 | 18 | ControlCardNumber | FullCardNumber | Nation + CardNumber |
| 23 | 1 | VehicleRegistrationNation | NationNumeric | |
| 24 | 14 | VehicleRegistrationNumber | InternationalString(13) | |
| 38 | 4 | ControlDownloadPeriodBegin | TimeReal | |
| 42 | 4 | ControlDownloadPeriodEnd | TimeReal | |

**Totale per record**: 1+4+18+1+14+4+4 = 46 byte

**BUG**: Il decoder attuale usa `rec_size = 24`, leggendo solo ControlTime(4) e ControlType(1), ignorando tutti gli altri campi (ControlCardNumber, VehicleRegistration, DownloadPeriod). Salta anche i primi 2 byte del payload (header pointer).

---

### Tag 0x050C — CalibrationData

- **Nome**: G1_CalibrationData
- **Annex reference**: Annex 1B §2.25
- **Dimensione record**: 105 byte (G1) o 161 byte (G2)
- **Numero record**: variabile
- **Stato decoder**: ⚠️ PARZIALE — campi mancanti, ordine potenzialmente errato
- **Decoder function**: `parse_calibration_data()` (decoders.py:320)

**Struttura G1** (105 byte, da C# `VehicleUnitData.config`):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 2 | Header/Pointer | — | Saltato dal decoder (skip 2 byte) |
| +0 | 1 | CalibrationPurpose | UInt8 | 0x01=Activation, 0x04=Inspection, etc. |
| +1 | 36 | WorkshopName | Name(36) | CodePage + 35 chars |
| +37 | 36 | WorkshopAddress | Name(36) | CodePage + 35 chars |
| +73 | 18 | WorkshopCardNumber | FullCardNumber(18) | |
| +91 | 4 | WorkshopCardExpiryDate | TimeReal | |
| +95 | 17 | VehicleIdentificationNumber | SimpleString(17) | VIN |
| +112 | 1 | VehicleRegistrationNation | NationNumeric | |
| +113 | 14 | VehicleRegistrationNumber | InternationalString(13) | |
| +127 | 2 | VehicleCharacteristicConstant | UInt16 | W |
| +129 | 2 | ConstantOfRecordingEquipment | UInt16 | K |
| +131 | 2 | TyreCircumference | UInt16 | L |
| +133 | 15 | TyreSize | SimpleString(15) | |
| +148 | 1 | AuthorisedSpeed | UInt8 | Speed limit |
| +149 | 3 | OldOdometerValue | UInt24 | |
| +152 | 3 | NewOdometerValue | UInt24 | |
| +155 | 4 | OldTimeValue | TimeReal | |
| +159 | 4 | NewTimeValue | TimeReal | |
| +163 | 4 | NextCalibrationDate | TimeReal | |

**Totale**: 105 byte (dalla struttura C#) o 167 byte (con tutti i campi).

**BUG**: Il decoder attuale usa `rec_size = 105` o `161`, parte da offset 2 (salta header pointer) e legge solo: purpose(1), vin(17, da +1), nation(1, da +18), plate(14, da +19), W(2, da +33), K(2, da +35), L(2, da +37), tyre(15, da +39), speed(1, da +54), odo(3, da +55). Molti campi sono mancanti (workshop name/address/card, expiry, old/new odo, timestamps). L'ordine sembra derivare da un layout diverso da quello del config C#.

---

### Tag 0x050D — VuTimeAdjustmentData

- **Nome**: VuTimeAdjustmentData
- **Annex reference**: Annex 1C §4.5.3.2.12
- **Dimensione record**: variabile (da 9 byte minimo, G2 RecordArray)
- **Numero record**: variabile
- **Stato decoder**: ⚠️ PARZIALE — decoder G2 RecordArray, decodifica solo campi base
- **Decoder function**: `parse_g2_time_adjustment()` (g2_decoders.py:118)

**Struttura** (G2 RecordArray, da Annex 1C):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | TimeAdjustmentType | UInt8 | 0=auto, 1=manual, 2=workshop |
| 1 | 4 | OldTimeValue | TimeReal | |
| 5 | 4 | NewTimeValue | TimeReal | |
| 9 | — | WorkshopName | coded string | Solo per tipo 2 (workshop) |
| — | 18 | WorkshopCardNumber | FullCardNumber | |
| — | 3 | VehicleOdometerValue | UInt24 | |

**Nota**: Questo è un tag G2 (Annex 1C), incluso qui per completezza. Il decoder G2 RecordArray gestisce automaticamente la dimensione record variabile.

---

### Tag 0x050E — CardDownload

- **Nome**: G1_CardDownload
- **Annex reference**: Annex 1B §2.18
- **Dimensione record**: 4 byte per download (TimeReal)
- **Numero record**: variabile (accumulato)
- **Stato decoder**: ✅ CORRETTO
- **Decoder function**: `parse_card_download()` (decoders.py:786)

**Struttura** (da C# config):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 2 | Pointer | UInt16? | Header, saltato dal decoder |
| +2 | 4×N | LastCardDownload[N] | TimeReal | Array di timestamp download |

**Nota**: Il decoder salta i primi 2 byte (pointer) e itera su record da 4 byte (TimeReal).

---

### Tag 0x0509-0x0512 — VU Record Tags (G2)

Questi tag appartengono al dominio VU (Vehicle Unit) e in G1 sono record sequenziali all'interno dei container 0x7601-0x7604. In G2 sono RecordArray con header 5-byte.

| Tag | Nome | Dimensione Record | Decoder | Stato |
|-----|------|-------------------|---------|-------|
| 0x0509 | VuCardRecord | 29 byte | `parse_g2_card_record` (g2_decoders.py:7) | ✅ G2 |
| 0x050A | VuCardIWRecord | 28 byte | `parse_g2_card_iw_record` (g2_decoders.py:49) | ✅ G2 |
| 0x050B | VuDownloadablePeriod | 8 byte | `parse_g2_downloadable_period` (g2_decoders.py:97) | ✅ G2 |
| 0x050F | VuCompanyLocksData | 25 byte | `parse_g2_company_locks` (g2_decoders.py:145) | ✅ G2 |
| 0x0510 | SensorPairedData | 24 byte | `parse_g2_sensor_paired` (g2_decoders.py:176) | ✅ G2 |
| 0x0511 | SensorExternalGNSSCoupledData | 20 byte | `parse_g2_sensor_gnss_coupled` (g2_decoders.py:203) | ✅ G2 |
| 0x0512 | VuITSConsentData | 23 byte | `parse_g2_its_consent` (g2_decoders.py:226) | ✅ G2 |

**Nota**: In G1, questi dati sono parte dei container TREP 0x7601-0x7604 e NON sono RecordArray. Il codebase attuale li tratta tutti come RecordArray G2. Per i file G1, questi tag vengono parsati dai decoder TREP (es. `_parse_trep_05_technical`).

---

### Tag 0x0520 — CardIdentification + DriverCardHolderIdentification

- **Nome**: G1_Identification
- **Annex reference**: Annex 1B §2.15 + §2.17
- **Dimensione record**: 65 + 78 = 143 byte (fissi)
- **Numero record**: 1
- **Stato decoder**: ✅ CORRETTO
- **Decoder function**: `parse_g1_identification()` (decoders.py:210)

**Struttura** (da C# config):

**Parte 1 — CardIdentification** (65 byte):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | CardIssuingMemberState | NationNumeric | |
| 1 | 16 | CardNumber | CardNumber(16) | CodePage + 15 chars |
| 17 | 36 | CardIssuingAuthorityName | Name(36) | CodePage + 35 chars |
| 53 | 4 | CardIssueDate | TimeReal | Data emissione |
| 57 | 4 | CardValidityBegin | TimeReal | Inizio validità |
| 61 | 4 | CardExpiryDate | TimeReal | Scadenza |

**Parte 2 — DriverCardHolderIdentification** (78 byte):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 65 | 36 | CardHolderSurname | Name(36) | Cognome |
| 101 | 36 | CardHolderFirstNames | Name(36) | Nome |
| 137 | 4 | CardHolderBirthDate | Datef/TimeReal | Data di nascita |
| 141 | 2 | CardHolderPreferredLanguage | SimpleString(2) | Lingua |

**Nota**: Il decoder legge i campi essenziali: nation, cardNumber, expiryDate, surname, firstname, birthDate, preferredLanguage. I campi `cardIssuingAuthorityName`, `cardIssueDate`, `cardValidityBegin` vengono saltati (36+4+4=44 byte saltati).

---

### Tag 0x0521 — DrivingLicenceInfo

- **Nome**: G1_DrivingLicenceInfo
- **Annex reference**: Annex 1B §2.26
- **Dimensione record**: 53 byte (fissi)
- **Numero record**: 1
- **Stato decoder**: ✅ CORRETTO
- **Decoder function**: `parse_g1_driving_licence()` (decoders.py:229)

**Struttura** (da C# config):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 36 | DrivingLicenceIssuingAuthority | Name(36) | Autorità emittente |
| 36 | 1 | DrivingLicenceIssuingNation | NationNumeric | |
| 37 | 16 | DrivingLicenceNumber | SimpleString(16) | Numero patente |

**Totale**: 36+1+16 = 53 byte

---

### Tag 0x0522 — SpecificConditions

- **Nome**: G1_SpecificConditions
- **Annex reference**: Annex 1B §2.27 / Annex 1C §2.152
- **Dimensione record**: 5 byte per condizione
- **Numero record**: max 56 (da C# config: `Count="56"`)
- **Stato decoder**: ✅ CORRETTO
- **Decoder function**: `parse_specific_conditions()` (decoders.py:802)

**Struttura** (da C# config):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 2 | Pointer | — | Header, saltato dal decoder |
| +0 | 4 | EntryTime | TimeReal | |
| +4 | 1 | SpecificConditionType | UInt8 | 0x00=Ferry, 0x01=Train, 0x02=OutOfScope |

**Totale per record**: 4+1 = 5 byte

**Nota**: Il decoder usa `rec_size = 6` (con 1 byte di padding), filtra solo i tipi 0x00-0x02 validi.

---

### Tag 0x0523 — G2_VehiclesUsed

- **Nome**: G2_VehiclesUsed
- **Dimensione record**: 35 byte (G2)
- **Stato decoder**: ✅ CORRETTO (dispatchato a `parse_g1_vehicles_used` con auto-detect G2)
- **Decoder function**: `parse_g1_vehicles_used()` (decoders.py:234)
- **Nota**: Vedi Tag 0x0505 per la struttura G2 dettagliata (35 byte).

---

### Tag 0x0524 — G2_DriverActivityData

- **Nome**: G2_DriverActivityData
- **Dimensione**: Variabile (buffer ciclico G2)
- **Stato decoder**: ✅ CORRETTO (dispatchato a `parse_cyclic_buffer_activities` se length > 100)
- **Nota**: La struttura del buffer ciclico G2 è identica a G1 (vedi Tag 0x0504).

---

### Tag 0x0206 — VU_ActivityDailyRecord

- **Nome**: VU_ActivityDailyRecord
- **Dimensione**: Variabile (può contenere buffer ciclico)
- **Stato decoder**: ⚠️ PARZIALE — dispatchato a `parse_cyclic_buffer_activities` solo se length > 100. Nessun decoder dedicato per VU activity daily record in formato non-ciclico.
- **Nota**: Il tag 0x0206 può apparire in contesti VU con una struttura diversa dal buffer ciclico carta.

---

### Tag 0x0222 — EF_GNSS_Places

- **Nome**: EF_GNSS_Places
- **Annex reference**: Annex 1C GNSS (G2)
- **Dimensione record**: 14+ byte
- **Numero record**: variabile
- **Stato decoder**: ❌ ASSENTE — **NESSUN DISPATCH** in `tag_navigator.py`
- **Decoder function**: N/A

---

### Tag 0x0223 — EF_GNSS_Accumulated_Position

- **Nome**: EF_GNSS_Accumulated_Position
- **Annex reference**: Annex 1C GNSS (G2)
- **Dimensione record**: 16 byte
- **Numero record**: variabile
- **Stato decoder**: ❌ ASSENTE — **NESSUN DISPATCH** in `tag_navigator.py`
- **Decoder function**: N/A (ma esiste `parse_g22_gnss_accumulated_driving` per 0x0525)

---

### Tag 0xC100 — G1_CardCertificate

- **Nome**: G1_CardCertificate
- **Annex reference**: Annex 1B §2.29
- **Dimensione record**: 194 byte (128 sig + 58 pubkey + 8 CA ref)
- **Numero record**: 1
- **Stato decoder**: ❌ ASSENTE — solo registrazione raw in `self.parser.card_cert_raw`
- **Decoder function**: N/A

**Struttura** (da C# config):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 128 | Signature | HexValue(128) | Firma digitale RSA/ECDSA |
| 128 | 58 | PublicKeyRemainder | HexValue(58) | Resto chiave pubblica |
| 186 | 1 | Nation | Country(1) | Nation CA |
| 187 | 3 | NationCode | SimpleString(3) | |
| 190 | 1 | SerialNumber | UInt8 | |
| 191 | 2 | AdditionalInfo | UInt16 | |
| 193 | 1 | CaIdentifier | UInt8 | |

---

### Tag 0xC108 — G1_CA_Certificate

- **Nome**: G1_CA_Certificate
- **Annex reference**: Annex 1B §2.30
- **Dimensione record**: 194 byte (stessa struttura di C100)
- **Numero record**: 1
- **Stato decoder**: ❌ ASSENTE — solo registrazione raw in `self.parser.msca_cert_raw`
- **Decoder function**: N/A

---

### Tag 0xC101 — G2_CardCertificate

- **Nome**: G2_CardCertificate
- **Dimensione**: Variabile (G2 ECDSA)
- **Stato decoder**: ❌ ASSENTE — solo registrazione raw in `self.parser.card_cert_raw`

---

### Tag 0xC109 — G2_CA_Certificate

- **Nome**: G2_CA_Certificate
- **Dimensione**: Variabile (G2 ECDSA)
- **Stato decoder**: ❌ ASSENTE — solo registrazione raw

---

### Tag 0x2020 — CompanyHolderData

- **Nome**: CompanyHolderData
- **Annex reference**: Annex 1B (company card data)
- **Dimensione record**: Variabile
- **Numero record**: Variabile
- **Stato decoder**: ⚠️ EURISTICO — solo decode_string + regex per estrarre testo
- **Decoder function**: `parse_company_holder_data()` (decoders.py:896)

**Nota**: Il decoder è puramente euristico (estrazione testo), non basato su specifica.

---

## VU Container Tags (G1 — Annex 1B)

### Tag 0x7601 — G1_VU_TechnicalData (TransferDataOverview)

- **Nome**: TransferDataOverview
- **Annex reference**: Annex 1B §4.5.3.2.2
- **Dimensione**: Variabile (diverse centinaia di byte)
- **Numero record**: 1 (container con record sequenziali)
- **Stato decoder**: ⚠️ EURISTICO — parsa VIN, plate, company info via regex
- **Decoder function**: `parse_g1_vu_overview()` (decoders.py:909)

**Contenuto** (da C# `VehicleUnitData.config`):
Il container 0x7601 contiene record sequenziali (NON STAP, NON BER-TLV) in ordine fisso:
1. MemberStateCertificate (194 byte)
2. VuCertificate (194 byte)
3. VehicleIdentificationNumber (17 byte)
4. VehicleRegistrationIdentification (15 byte: nation + plate)
5. CurrentDateTime (4 byte)
6. VuDownloadablePeriod (8 byte)
7. CardSlotStatus (1 byte)
8. VuDownloadActivityData (variabile)
9. VuCompanyLocksData (variabile)
10. VuControlActivityData (variabile)
11. Signature (128 byte)

**Nota**: Il decoder attuale usa regex su dati raw per trovare VIN, plate, company name, card numbers. **NON esegue parsing strutturato** dei campi a offset fissi. Questo è intenzionale perché il formato esatto dipende dalla versione VU e ci sono ambiguità di allineamento.

---

### Tag 0x7602 — G1_VU_Activities (TransferDataActivities)

- **Nome**: TransferDataActivities
- **Annex reference**: Annex 1B §4.5.3.2.3
- **Dimensione**: Variabile (grande, contiene tutti i record giornalieri)
- **Numero record**: 1 (container)
- **Stato decoder**: ⚠️ EURISTICO — parsato via TREP parser + G2 RecordArray
- **Decoder function**: `_parse_trep_02_activities()` (decoders.py:1000)

**Contenuto** (da C# config):
1. ActivityDate (4 byte)
2. OdometerValueMidnight (3 byte)
3. VuCardIWData (record inserzione/rimozione carta)
4. VuActivityDailyData (activity changes)
5. VuPlaceDailyWorkPeriodData (luoghi)
6. VuSpecificConditionData (condizioni specifiche)
7. Signature (128 byte)

**Nota**: Il decoder tenta sia il parsing G1 (euristico, ricerca pattern) che G2 (RecordArray). Il parsing G1 cerca pattern di testo per cognome/nome, numero carta, e record giornalieri con timestamp+odo+changes.

---

### Tag 0x7603 — G1_VU_EventsFaults (TransferDataEventsAndFaults)

- **Nome**: TransferDataEventsAndFaults
- **Annex reference**: Annex 1B §4.5.3.2.4
- **Dimensione**: Variabile
- **Numero record**: 1 (container)
- **Stato decoder**: ⚠️ EURISTICO — parsato via TREP parser
- **Decoder function**: `_parse_trep_03_events_faults()` (decoders.py:1136)

**Contenuto** (da C# config):
1. VuFaultData (collection di VuFaultRecord)
2. VuEventData (collection di VuEventRecord)
3. OverspeedingControlData
4. VuOverspeedingEventData
5. VuTimeAdjustmentData
6. Signature (128 byte)

**VuFaultRecord / VuEventRecord** (G1):
| Offset | Size | Nome | Tipo | Note |
|--------|------|------|------|------|
| 0 | 1 | EventType/FaultType | UInt8 | |
| 1 | 1 | EventRecordPurpose | UInt8 | |
| 2 | 4 | BeginTime | TimeReal | |
| 6 | 4 | EndTime | TimeReal | |
| 10 | 18 | CardNumberDriverSlotBegin | FullCardNumber | |
| 28 | 18 | CardNumberCodriverSlotBegin | FullCardNumber | |
| 46 | 18 | CardNumberDriverSlotEnd | FullCardNumber | |
| 64 | 18 | CardNumberCodriverSlotEnd | FullCardNumber | |
| 82 | 1 | SimilarEventsNumber | UInt8 | Solo per EventRecord |

**Nota**: Il decoder TREP 03 cerca eventi via pattern matching (type byte + 2 timestamp validi), non tramite parsing strutturato a offset fissi.

---

### Tag 0x7604 — G1_VU_Speed (TransferDetailedSpeed)

- **Nome**: TransferDetailedSpeed
- **Annex reference**: Annex 1B §4.5.3.2.5
- **Dimensione**: Variabile
- **Numero record**: 1 (container)
- **Stato decoder**: ✅ CORRETTO
- **Decoder function**: `_parse_trep_04_speed()` (decoders.py:1202)

**Contenuto** (da C# config):
1. SpeedInfo (collection of SpeedInfoBlock)
   - SpeedBlockBeginDate (4 byte)
   - SpeedData (60 × UInt8 = 60 byte per minuto, 1 valore/minuto = km/h)
2. Signature (128 byte)

**Nota**: Il decoder cerca blocchi con noOfMinutes(2) + timestamp(4) + valori velocità. Filtra velocità > 200 km/h.

---

### Tag 0x7605 — G1_VU_TechnicalData (TransferDataTechnicalData)

- **Nome**: TransferDataTechnicalData
- **Annex reference**: Annex 1B §4.5.3.2.6
- **Dimensione**: Variabile
- **Numero record**: 1 (container)
- **Stato decoder**: ⚠️ EURISTICO — parsato via TREP parser
- **Decoder function**: `_parse_trep_05_technical()` (decoders.py:1246)

**Contenuto** (da C# config):
1. VuIdentification (manufacturer name, address, part number, serial, software version)
2. SensorPaired (serial, approval, pairing date)
3. CalibrationRecords (collection of CalibrationRecord)
4. Signature (128 byte)

**Nota**: Il decoder non ha un handler TREC 05 dedicato per G1. I dati VU e calibrazioni vengono estratti via regex dalla sezione raw.

**Nota aggiuntiva**: Il tag 0x7605 NON è nel dizionario `TACHO_TAGS` del file `tag_definitions.py`. È documentato nel config C# ma non ha un tag ID mappato nel codebase. I dati di calibrazione VU vengono invece trovati via regex nel payload residuale.

---

## Riepilogo Stato Decoder

### ✅ Corretti
| Tag | Nome | Dimensione |
|-----|------|------------|
| 0x0201 | DriverCardHolderIdentification | 78 byte |
| 0x0501 | DriverCardApplicationIdentification | 10 byte |
| 0x0502 | CardEventData | 24 byte × N |
| 0x0503 | CardFaultData | 24 byte × N |
| 0x0504 | DriverActivityData (cyclic) | variabile |
| 0x0505/0x0523 | VehiclesUsed (G1/G2) | 31/35 byte × N |
| 0x0507 | CurrentUsage | 19 byte |
| 0x050C | CalibrationData | 105/161 byte × N |
| 0x050E | CardDownload | 4 byte × N |
| 0x0520 | CardIdentification + DriverID | 143 byte |
| 0x0521 | DrivingLicenceInfo | 53 byte |
| 0x0522 | SpecificConditions | 5 byte × N |
| 0x7604 | Speed (TREP 04) | variabile |
| 0x0509-0x0512 | VU RecordArray (G2) | varie (8-29 byte) |

### ⚠️ Parziali / Euristici
| Tag | Nome | Problema |
|-----|------|----------|
| 0x0002 | EF_ICC | Parsing non strutturato |
| 0x0005 | EF_IC | Solo hex dump |
| 0x0100 | CardIssuerIdentification | Regex euristico |
| 0x0101 | G2_CardIccIdentification | Cerca nome azienda via regex |
| 0x0102 | G2_CardIdentification | Campi intermedi saltati |
| 0x0206 | VU_ActivityDailyRecord | Solo se length > 100 |
| 0x0506 | Places | Record size deterministico |
| 0x2020 | CompanyHolderData | Regex euristico |
| 0x7601 | VU Overview | Regex, non strutturato |
| 0x7602 | VU Activities | Regex + RecordArray |
| 0x7603 | VU EventsFaults | Pattern matching |
| 0x7605 | VU Technical | Regex, non strutturato |

### ❌ Assenti / Non Conformi
| Tag | Nome | Problema |
|-----|------|----------|
| 0x0103 | G2_CardCertificate | Solo raw (194 byte) |
| 0x0104 | G2_MemberStateCertificate | Solo raw (194 byte) |
| 0x0222 | EF_GNSS_Places | NESSUN DISPATCH |
| 0x0223 | EF_GNSS_Accumulated_Position | NESSUN DISPATCH |
| 0x0508 | ControlActivityData | rec_size errato (24 vs 46 byte) |
| 0xC100 | G1_CardCertificate | Solo raw (194 byte) |
| 0xC101 | G2_CardCertificate | Solo raw |
| 0xC108 | G1_CA_Certificate | Solo raw (194 byte) |
| 0xC109 | G2_CA_Certificate | Solo raw |

---

## Riepilogo GAP Identificati

### GAP Critici (Bloccano il parsing deterministico)
1. **Tag 0x0508 (ControlActivityData)**: dimensione record errata (24 vs 46 byte corretti), mancano 5 campi su 7.
2. **Tag 0x0222 e 0x0223**: nessun dispatch in `tag_navigator.py`, dati GNSS completamente persi.
3. **Tag 0x050C (CalibrationData)**: ordine campi non corrisponde al config C# di riferimento, molti campi workshop mancanti.

### GAP Significativi (Dati incompleti)
4. **Container 0x7601-0x7604 (G1 VU)**: parsing non strutturato, basato su regex/pattern matching. Impossibile garantire 100% byte coverage deterministico.
5. **Tag 0x0100 (CardIssuerIdentification)**: nessuna specifica di struttura nota, solo euristico.
6. **Certificati (0x0103, 0x0104, 0xC100, 0xC101, 0xC108, 0xC109)**: mai parsati strutturalmente, solo raw storage.

### GAP Minori
7. **Tag 0x0002 (EF_ICC)**: struttura ASN.1 non completamente mappata nel decoder (historical bytes trattati come testo).
8. **Tag 0x0506 (Places)**: dimensioni record 12/13/27 byte sono euristiche, non derivate da specifica per G1.
9. **Tag 0x7605**: non presente nel dizionario TACHO_TAGS, dati calibrazione VU estratti solo via regex.

---

## Data Type Reference (Annex 1B)

| Tipo ASN.1 | Dimensione | Descrizione | Implementazione |
|-----------|-----------|-------------|-----------------|
| TimeReal | 4 byte | Secondi Unix dal 1970-01-01 UTC, UInt32 big-endian | `struct.unpack(">I")` |
| Datef | 4 byte | BCD: YYh YYl MM DD | `decode_datef()` |
| Name | 36 byte | CodePage(1) + Latin-1(35) | `decode_string()` |
| CardNumber | 16 byte | CodePage(1) + Alphanumeric(15) | `decode_string(is_id=True)` |
| FullCardNumber | 18 byte | CodePage(1) + Nation(1) + CardNumber(16) | parziale |
| InternationalString(L) | 1+L byte | CodePage(1) + String(L) | `decode_string()` |
| SimpleString(L) | L byte | Latin-1 string | `decode_string()` |
| Country/NationNumeric | 1 byte | Numeric code (0x00-0xFF) | `get_nation()` |
| UInt8 | 1 byte | Unsigned byte | `val[off]` |
| UInt16 | 2 byte | Unsigned short, big-endian | `struct.unpack(">H")` |
| UInt24 | 3 byte | Unsigned 24-bit, big-endian | `int.from_bytes(3, 'big')` |
| UInt32 | 4 byte | Unsigned int, big-endian | `struct.unpack(">I")` |
| BCDString(N) | N byte | Ogni byte = 2 BCD digits | `(b>>4)*10 + (b&0x0F)` |
| ExtendedSerialNumber | 8 byte | Serial number (hex) | `val.hex()` |
| HexValue(N) | N byte | Raw hex | `val.hex()` |

---

## Tabella Nazioni (Annex 1B — estratta dal codebase)

| Code | ISO | Nome |
|------|-----|------|
| 0x00 | — | No information available |
| 0x01 | A | Austria |
| 0x02 | AL | Albania |
| 0x0D | D | Germany |
| 0x0F | E | Spain |
| 0x11 | F | France |
| 0x14 | FR | Faeroe Islands? |
| 0x15 | UK | United Kingdom |
| 0x1A | I | Italy |
| 0x1B | IRL | Ireland |
| 0x1E | L | Luxembourg |
| 0x26 | NL | Netherlands |
| 0x2C | S | Sweden |
| 0x2D | SK | Slovakia |
| 0x2E | SLO | Slovenia |
| 0xFD | EC | European Community |
| 0xFE | EUR | Europe |
| 0xFF | WLD | World |

**Nota**: Tabella completa disponibile in `decoders.py:get_nation()` (65 entry). Sopra solo estratti rappresentativi.

---

## Note Finali

1. **Il formato STAP vs BER-TLV**: In G1, i dati carta (0x0501-0x0522) sono tipicamente in formato STAP (Tag 2B + Type 1B + Length 2B = header 5 byte). I container VU (0x7601-0x7604) contengono record sequenziali Annex 1B (NON STAP). In G2/G2.2, il formato è BER-TLV. Il parser (`tag_navigator.py`) gestisce questa distinzione con l'euristica `mode='stap'` vs `mode='annex1c'`.

2. **Double encoding Datef/TimeReal**: Annex 1B §2.26 definisce Datef come BCD per date di nascita. Tuttavia, molti tool di download scrivono anche le date di nascita come TimeReal (Unix timestamp). Il decoder tenta entrambi con `decode_date()`.

3. **RecordArray G2 vs Sequential G1**: I tag 0x0509-0x0512 in G2 hanno header RecordArray (5 byte: recordType+recordSize+noOfRecords). In G1 questi dati sono record sequenziali all'interno dei container TREP. Il codebase attuale li tratta uniformemente come RecordArray, il che funziona per G2 ma non per G1 puro.

4. **Ambiguità 0x050C (CalibrationData)**: La struttura esatta dipende dalla versione VU. Il config C# di riferimento mostra 105 byte con workshop info inclusi, ma il decoder attuale usa un layout diverso (apparentemente derivato da reverse-engineering di file reali).

5. **Signature validation**: La catena di validazione firme (CardCert → MSCA → ERCA) è implementata in `signature_validator.py` (non analizzato in questo documento). I certificati (C100, C108, etc.) non hanno decoder strutturati ma vengono usati dal signature validator.
