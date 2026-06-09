# G2.2 Verification Status Report

> **Date**: 2026-06-08  
> **Agent**: Agent 2 — Spec G2/G2.2  
> **Purpose**: Stato di verifica delle strutture dati G2.2 rispetto alle specifiche note

> ⚠️ **AGGIORNAMENTO 2026-06-09 — questo report è in gran parte superato.**
> - I Bug #1, #2, #3 elencati sotto risultano **già risolti** nel codice attuale.
> - Soprattutto: i dati VU Gen2/2.2 **non** passano per i tag `0x05xx` (presenti solo
>   nei file carta G1). Nei file VU sono **RecordArray indicizzati per `recordType`**.
>   La premessa "tag → decoder" di questo documento non si applica ai file VU.
> - La decodifica VU corretta è ora in `core/vu_record_dispatcher.py` (dispatcher per
>   recordType, section-aware). Mappa `recordType→size` empirica e verità di terreno
>   in `specs/vu_recordtype_map.md`. Bug confermato e risolto: VuBorderCrossingRecord
>   (recordType 0x22, 55 byte) e le attività VU venivano persi e ora sono recuperati
>   (test in `tests/test_vu_dispatcher.py`).
> Le tabelle sottostanti restano utili solo come riferimento storico sulla campologia.

---

## 1. Tag con dimensione CONFERMATA da specifica (HIGH confidence)

| Tag | Nome | Dimensione Record | Fonte |
|-----|------|-------------------|-------|
| 0x0509 | VuCardRecord | 29 byte | Annex 1C §4.5.3.2.8 |
| 0x050A | VuCardIWRecord | 28 byte | Annex 1C §4.5.3.2.9 |
| 0x050B | VuDownloadablePeriod | 8 byte | Annex 1C §4.5.3.2.10 |
| 0x050F | VuCompanyLocksData | 25 byte | Annex 1C §4.5.3.2.14 |
| 0x0510 | SensorPairedData | 24 byte | Annex 1C §4.5.3.2.15 |
| 0x0511 | SensorExternalGNSSCoupledData | 20 byte | Annex 1C §4.5.3.2.16 |
| 0x0512 | VuITSConsentData | 23 byte | Annex 1C §4.5.3.2.17 |
| 0x052C | VuDetailedSpeedData | 64 byte | Annex 1C §2.190-2.191 |
| 0x0532 | G22_SensorExternalGNSSCoupledData | 20 byte | Annex 1C §2.242 (stessa struttura 0x0511) |
| 0x0533 | G22_SensorPairedData | 24 byte | Annex 1C §2.243 (stessa struttura 0x0510) |

Questi 10 tag hanno struttura e dimensione nota dalla specifica pubblica.

---

## 2. Tag basati su EURISTICA / reverse-engineering (MEDIUM confidence)

| Tag | Nome | Dimensione Record | Fonte |
|-----|------|-------------------|-------|
| 0x050D | VuTimeAdjustmentData | 9 byte minimo (variabile) | Annex 1C §4.5.3.2.12 (campi noti, parte variabile dedotta) |
| 0x0525 | GNSSAccumulatedDriving | 16 byte (stima) | Codice euristico + GNSSAccumulatedDrivingRecord §2.79 |
| 0x0528 | GNSSEnhancedPlaces | 14 byte (da spec) | GNSSPlaceAuthRecord §2.79c (2021/1228) |
| 0x052B | VuControllerIdentification | Variabile | CodedString parser euristico |
| 0x052D | VuOverSpeedingEventData | 33 byte (stima) | Campologia nota da §2.215, dimensioni campi stimate |
| 0x052E | VuOverSpeedingControlData | 10 byte (stima) | Campologia nota da §2.212 |
| 0x052F | VuTimeAdjustmentGNSSRecord | 8 byte (stima) | Campologia nota da §2.230 |
| 0x0530 | VuPowerSupplyInterruptionData | 90 byte (stima) | Campologia nota da §2.240, dimensioni FullCardNumber+Gen stimate |

Questi 8 tag hanno la campologia (elenco dei campi) nota dalla specifica, ma le dimensioni esatte in byte sono dedotte/stimate. Il codice li gestisce in modo euristico o parziale.

---

## 3. Tag basati su EURISTICA / reverse-engineering (LOW confidence)

| Tag | Nome | Dimensione Record | Fonte |
|-----|------|-------------------|-------|
| 0x0526 | LoadUnloadOperations | 9-13 byte (stima) | Solo codice euristico |
| 0x0527 | TrailerRegistrations | 20-24 byte (stima) | Solo codice euristico |
| 0x0529 | LoadSensorData | Variabile (stima) | Solo codice euristico |
| 0x052A | BorderCrossings | 10-14 byte (stima) | Solo codice euristico |
| 0x0531 | VuSensorFaultData | ~90 byte (stima) | Nessuna fonte pubblica |
| 0x960F | G22_GNSS_Auth_Data | Sconosciuto | Nessuna fonte pubblica |
| 0x6399 | G22_Load_Unload_Auth | Sconosciuto | Nessuna fonte pubblica |

Questi 7 tag hanno dimensioni puramente stimate dal codice euristico, senza conferma da specifica pubblica. Le strutture dei record interni sono state dedotte dai pattern nei file `.ddd`.

---

## 4. Tag COMPLETAMENTE ASSENTI (non implementati)

| Tag | Nome | Motivazione |
|-----|------|-------------|
| 0x052C | VuDetailedSpeedData | Struttura nota (64 byte) ma decoder non implementato |
| 0x052D | VuOverSpeedingEventData | Struttura parzialmente nota ma decoder non implementato |
| 0x052E | VuOverSpeedingControlData | Struttura parzialmente nota ma decoder non implementato |
| 0x052F | VuTimeAdjustmentGNSSRecord | Struttura parzialmente nota ma decoder non implementato |
| 0x0530 | VuPowerSupplyInterruptionData | Struttura parzialmente nota ma decoder non implementato |
| 0x0531 | VuSensorFaultData | Struttura sconosciuta, decoder non implementato |
| 0x0532 | G22_SensorExternalGNSSCoupledData | Struttura nota ma decoder non registrato in dispatch table |
| 0x0533 | G22_SensorPairedData | Struttura nota ma decoder non registrato in dispatch table |
| 0x960F | G22_GNSS_Auth_Data | Completamente sconosciuto |
| 0x6399 | G22_Load_Unload_Auth | Completamente sconosciuto |

**Totale: 10 tag completamente non implementati** (di cui 2 con struttura nota ma non connessi al dispatch).

---

## 5. Bug identificati

### Bug #1 — Tag 0x0225 mappato a decoder errato
- **File**: `core/tag_navigator.py:302`
- **Codice attuale**: `elif tag == 0x0528 or tag == 0x0225:`
- **Problema**: 0x0225 (`G22_VU_GNSSADRecord` = GNSS Accumulated Driving) viene mappato al decoder `parse_g22_gnss_enhanced_places` (che e' per GNSS Enhanced Places 0x0528).
- **Fix**: `elif tag == 0x0528: decoders.parse_g22_gnss_enhanced_places(...)` e aggiungere `elif tag == 0x0525 or tag == 0x0225: decoders.parse_g22_gnss_accumulated_driving(...)`.

### Bug #2 — Tag 0x052C-0x0533 non in G2_VU_RECORD_DECODERS
- **File**: `core/g2_decoders.py:309-318`
- **Problema**: `G2_VU_RECORD_DECODERS` non include entries per i tag 0x052C-0x0533.
- **Conseguenza**: `parse_g2_vu_record` in `decoders.py:167` fa `return` immediato per questi tag.
- **Fix**: Aggiungere le entries mancanti con i decoder appropriati.

### Bug #3 — Discrepanza size VuCardIWRecord
- **File**: `core/g2_decoders.py:49-94`
- **Problema**: Il decoder si aspetta 28 byte e poi legge `renew_idx` a offset 28 opzionalmente (linea 81: `rec[28] if len(rec) > 28 else 0`). Ma la dimensione dichiarata e' 28, quindi `len(rec)` sara' sempre 28 e `renew_idx` sara' sempre 0 (non letto).
- **Impatto**: Minore — `cardRenewalIndex` non viene mai popolato correttamente.
- **Fix**: Dichiarare la dimensione record a 29 byte o rimuovere il campo.

---

## 6. Riepilogo per priorita' di fix

| Priorita' | Azione | Impatto |
|-----------|--------|---------|
| **CRITICAL** | Fix Bug #2: Aggiungere 0x0532, 0x0533 in G2_VU_RECORD_DECODERS | Questi tag sono presenti in file reali ma vengono ignorati |
| **HIGH** | Fix Bug #1: Correggere mapping 0x0225 | Dati GNSS Accumulated Driving interpretati come Places |
| **HIGH** | Aggiungere decoder per 0x052C (VuDetailedSpeed) | Struttura nota, usato in TREP 04/24 |
| **MEDIUM** | Aggiungere decoder per 0x052D-0x0531 | Struttura parzialmente nota, utile per analisi VU |
| **LOW** | Migliorare stime dimensioni per 0x0526-0x052A | Richiede analisi di piu' dati reali |
| **LOW** | Fix Bug #3: VuCardIWRecord renewal index | Impatto minimo |

---

## 7. Metodologia

Questo report e' stato generato tramite:

1. **Analisi statica del codebase**: lettura integrale di `g2_decoders.py`, `record_array.py`, `decoders.py`, `tag_definitions.py`, `tag_navigator.py`
2. **Ricerca normativa**: fetching di Reg. EU 2016/799, 2021/1228, 2023/980 da EUR-Lex
3. **Analisi dati reali**: scansione di 9 file `.ddd`/`.DDD` (825 KB totali) alla ricerca di tag G2/G2.2
4. **Cross-referencing**: verifica dei decoder esistenti contro la tabella di dispatch

I riferimenti normativi provengono principalmente da:
- Annex 1C Data Dictionary (Reg. 2016/799) per la campologia G2 originale
- Amendment 2021/1228 per i nuovi data element G2.2 (VuBorderCrossingRecord, VuLoadUnloadRecord, GNSSAuthStatusADRecord, GNSSPlaceAuthRecord, VehicleRegistrationIdentificationRecordArray)
- Appendix 7 per la definizione del formato RecordArray
- Appendix 2 Tachograph Cards Specification per la struttura TREP

---

*Report generato il 2026-06-08*
