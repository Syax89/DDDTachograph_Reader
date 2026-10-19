# G2.2 Verification Status Report

> **Date**: 2026-06-08  
> **Agent**: Agent 2 — Spec G2/G2.2  
> **Purpose**: Stato di verifica delle strutture dati G2.2 rispetto alle specifiche note

> ⚠️ **AGGIORNAMENTO 2026-06-09 — questo report è in gran parte superato.**
> - I Bug #1, #2, #3 elencati sotto risultano **già risolti** nel codice attuale.
> - Soprattutto: i dati VU Gen2/2.2 **non** passano per i tag `0x05xx` (presenti solo
>   nei file carta G1). Nei file VU sono **RecordArray indicizzati per `recordType`**.
>   La premessa "tag → decoder" di questo documento non si applica ai file VU.
> - La decodifica VU corretta è ora in `core/parser/vu_dispatcher.py` (dispatcher per
>   recordType, section-aware). Mappa `recordType→size` empirica e verità di terreno
>   in `scripts/vu_recordtype_map.md`. Bug confermato e risolto: VuBorderCrossingRecord
>   (recordType 0x22, 55 byte) e le attività VU venivano persi e ora sono recuperati
>   (test in `tests/integration/test_vu_dispatcher.py`).
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
- **Codice attuale**: `elif tag == 0x0528 or tag == 0x0225:`
- **Problema**: 0x0225 (`G22_VU_GNSSADRecord` = GNSS Accumulated Driving) viene mappato al decoder `parse_g22_gnss_enhanced_places` (che e' per GNSS Enhanced Places 0x0528).
- **Fix**: `elif tag == 0x0528: decoders.parse_g22_gnss_enhanced_places(...)` e aggiungere `elif tag == 0x0525 or tag == 0x0225: decoders.parse_g22_gnss_accumulated_driving(...)`.

### Bug #2 — Tag 0x052C-0x0533 non in G2_VU_RECORD_DECODERS
- **Problema**: `G2_VU_RECORD_DECODERS` non include entries per i tag 0x052C-0x0533.
- **Conseguenza**: `parse_g2_vu_record` in `core/decoders/vu_g2.py` fa `return` immediato per questi tag.
- **Fix**: Aggiungere le entries mancanti con i decoder appropriati.

### Bug #3 — Discrepanza size VuCardIWRecord
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

---

## 8. Record VU di eventi e guasti (recordType 0x15 / 0x18) — VERIFICATO

> Aggiornamento 2026-10-19. Fonte: Reg. (UE) 2016/799, Allegato 1C, Appendice 1
> (le pagine ASN.1 del PDF ufficiale sono immagini; i tipi sono stati letti via OCR
> 300 dpi delle pagine 113-117, 121 e 152-155).

`VuEventRecord` (§2.198, generazione 2) = 91 byte, `VuFaultRecord` (§2.201,
generazione 2) = 90 byte. Layout verificato campo per campo e confermato su tutti
i 6 download VU Gen2/G2.2 reali in `DDD/` (121 eventi, 14 guasti, nessuna
dimensione diversa):

```
eventType(1) + eventRecordPurpose(1) + eventBeginTime(4) + eventEndTime(4) +
4 x FullCardNumberAndGeneration(19: cardType(1)+nation(1)+cardNumber(16)+generation(1))
  = cardNumberAndGen{Driver,Codriver}Slot{Begin,End}
+ similarEventsNumber(1)              # solo VuEventRecord
+ manufacturerSpecificEventFaultData(4: manufacturerCode(1) + OCTET STRING(3))
```

Cosa e' **verificato** (HIGH, `core/parser/vu_dispatcher.py::decode_event_fault_record`):

- dimensioni 91/90 e offset di ogni campo;
- `FullCardNumberAndGeneration` (§2.74: `FullCardNumber` §2.73 + `Generation` §2.75);
- `EquipmentType` (§2.67): uno slot `FullCardNumber` puo' contenere solo una
  carta tachigrafica, cioe' i valori 1..5 (driver, officina, controllo,
  azienda, produzione). I valori 6..15 sono altre apparecchiature (VU, sensor,
  GNSS, RCM, ITS, plaque, adapter, ERCA, MSCA, GNSS esterno), 16 e' "Unused"
  (solo SealDataVu) e 17..255 sono RFU: uno slot con uno di questi valori non
  e' conforme;
- `EventFaultRecordPurpose` (§2.69: '00'..'07'H definiti, '08'..'7F'H RFU,
  '80'..'FF'H specifici del costruttore);
- `TimeReal` e il caso speciale dell'evento di **time conflict** ('0B'H, §2.70 +
  §2.198): `eventBeginTime` = data/ora dell'apparecchio di registrazione,
  `eventEndTime` = data/ora GNSS (non una fine). Il record viene annotato con
  `end_semantics = "GNSS date and time"` invece di presentare il valore come fine;
- le due codifiche di **slot vuoto** osservate sui file reali: `FF`x19, oppure
  cardType 0 + nation 0 + 16 spazi + generation 0xFF.
- Per ogni record emesso il decoder produce un verdetto esplicito:
  `normative=True` / `confidence="high"` / `spec_reference="Annex 1C App.1 2.198"|"…2.201"`
  quando tutti i campi normativi sono validi; `normative=False` /
  `confidence="low"` + `conformance_reason` quando no (record comunque emesso).
- `ManufacturerCode` (§2.94 / §2.95): risolto contro l'elenco ufficiale che il
  §2.94 affida al laboratorio competente per i test di interoperabilita', che lo
  mantiene e pubblica sul proprio sito (requisito 454 dell'Allegato 1C):
  https://dtc.jrc.ec.europa.eu/dtc_manufacturer_code.php.html — copiato in modo
  statico in `core/utils/manufacturer_codes.py`: **65 codici assegnati**, nessun
  accesso di rete a runtime. Un codice registrato viene mostrato con il nome
  dell'azienda (colonna `Manufacturer`, header gia' tradotto) e non e' piu'
  marcato come non interpretato; i byte non assegnati o sentinella ('00'H,
  'FF'H, ...) restano esplicitamente sconosciuti
  (`manufacturer_status = "not_registered"`) e a bassa confidenza. L'elenco
  identifica il costruttore, non i suoi codici diagnostici.

Cosa resta **NON verificato** (dichiarato, non dedotto):

- I **3 byte** di `manufacturerSpecificErrorCode` (§2.95) restano opachi: non e'
  stata ottenuta una mappatura verificata del formato a 3 byte, quindi vengono
  esportati verbatim (`manufacturer_error_code`, esadecimale minuscolo) e restano
  a bassa confidenza (`low_confidence_fields`). Non sono i numeri di avviso/DTC
  che la documentazione di un costruttore elenca e '000000' **non** viene letto
  come "nessun errore".
- `SimilarEventsNumber` (§2.151) dice "0 non e' usato", ma record reali hanno 0
  (52 dei 121 eventi del corpus): il valore viene mostrato senza far fallire la
  conformita', perche' la VU lo scrive davvero.
- La value assignment di `EventFaultType` (punto 2.70) e' stata **verificata** sul
  testo degli atti di modifica: Reg. (UE) 2018/502 Allegato (29)(h) ("Generation
  2, version 1") e Reg. (UE) 2021/1228 Allegato (30)(n)(i)/(ii) ("Generation 2,
  version 2"), che assegna '00'..'0F'H (incl. '0C' RCM, '0D' assenza di posizione
  GNSS, '0E' GNSS esterno, '0F' GNSS anomaly), '10'..'1C'H ('19' tamper GNSS,
  '1A'/'1B' GNSS esterno, '1C' incoerenza dati di moto), '20'..'25'H, '30'..'3A'H
  ('36' GNSS
  interno, '37' GNSS esterno, '38' RCM, '39' ITS, '3A' sensore interno) e '40'H;
  sono RFU '1D'..'1F'H, '26'..'2F'H, '3B'..'3F'H, '41'..'4F'H, '50'..'7F'H, e
  '80'..'FF'H e' specifico del costruttore. Le due tabelle in
  `core/utils/event_codes.py` corrispondono esattamente alla tabella v2 (test:
  `test_type_tables_match_the_amended_regulation`).
  Un codice fuori da questo insieme non rende non conforme il record: viene
  segnalato in `low_confidence_fields` (`event_type_code` / `fault_type_code`),
  perche' il testo non ne definisce il significato.
- La tabella applicata e' quella della **sezione**, non del file (il vecchio
  limite `shortcut:` e' stato rimosso). L'Allegato 7 assegna il tipo di
  trasferimento "Events and faults" a TRTP '03'H (generazione 1), '23'H
  ("generation 2, version 1", Reg. 2018/502 Allegato (29)(h)) e '33'H
  ("generation 2, version 2", Reg. 2021/1228 Allegato (30)(n)(i)/(ii)): DDP_011
  e' la tabella delle richieste, DDP_031 definisce le strutture dati per TREP
  ("under the SID 76 Hex, the TREP 03, 23 or 33 Hex") e DDP_034 conserva SID e
  TREP nel file scaricato. `event_fault_version_for_trep` traduce il marker di
  sezione e `decode_event_fault_record(version=...)` usa la tabella
  corrispondente:
  - sezione '23'H: '0F'/'1C'/'3A' sono "Reserved for future use", come dice quella
    versione (`type_status = "reserved"`), mai "GNSS anomaly"/"internal sensor
    fault"/"incoerenza dati di moto";
  - sezione '33'H: valgono le descrizioni v2 (`type_status = "assigned"`);
  - contesto non risolto (record isolato, array per-tag senza sezione, TREP '03'
    di generazione 1, altra sezione): la descrizione e'
    "Unknown event"/"Unknown fault" con `type_status = "unknown_version"` — non
    "reserved" e mai un default v2;
  - `metadata.generation` non viene mai usato per decidere: una VU v2 puo'
    produrre download in formato v1 e un file puo' contenere entrambe le sezioni.
  Ogni record esporta `event_fault_version` e `type_status` (entrambi nascosti
  dalle tabelle, come `normative`).
- Storico: nel testo originale del 2016 (il PDF dell'Allegato 1C non ancora
  modificato) quei codici risultano RFU. E' la ragione per cui la tabella era
  stata marcata "non verificata": oggi lo e', contro gli atti di modifica.
- `VuOverSpeedingEventRecord` (0x1B) e `VuPowerSupplyInterruptionRecord` (0x1F)
  non sono stati ri-verificati qui.
