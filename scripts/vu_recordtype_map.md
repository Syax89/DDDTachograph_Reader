# VU RecordArray — mappa recordType empirica (verità di terreno)

> Generato il 2026-06-09 da uno sweep "a tassellatura" sui file reali in `DDD/`.
> Le dimensioni `recordSize` sono lette direttamente dagli header RecordArray
> scritti dalle VU (Annex 1C Appendix 7), quindi sono **autorevoli per quei file**.
> Header RecordArray = recordType(1) + recordSize(2 BE) + noOfRecords(2 BE).

## Perché questo documento

I dati VU Gen2/Gen2.2 non arrivano dai tag `0x05xx` (quelli compaiono solo nei
file **carta** G1). Nei file **VU** i dati sono organizzati in **RecordArray
indicizzati per `recordType`** dentro i container TREP (`0x76xx`). Il parser
attuale **non** ha una tabella `recordType → decoder`: usa parser TREP euristici
(regex/timestamp-scan). Di conseguenza diversi record presenti nei file reali
non vengono decodificati (vedi sotto).

## Mappatura AUTOREVOLE recordType → record (2026-06-09)

Ottenuta incrociando l'ordine osservato dei RecordArray con l'ordine imposto dalla
normativa per ogni TREP (Appendix 7, DDP_029..033), poi confermato per size.
Implementata in `core/parser/vu_dispatcher.py` (`RECORD_TYPES`). Stato decodifica:
**100% dei record VU field-decoded** (high+medium) sui file reali in `DDD/` —
nessun record lasciato raw. Invariante blindata da `tests/test_vu_dispatcher.py`
(`test_no_raw_records_in_real_files`). Le firme ECC (0x08) e i certificati
(0x04/0x0F) sono "decodificati" come blob opachi/raw per design (il parsing
crittografico è del layer `signature_validator`).

| rt | Record | size | decode |
|----|--------|------|--------|
| 0x01 | VuActivityDailyRecord (ActivityChangeInfo) | 2 | ✅ high |
| 0x02 | CardSlotsStatus | 1 | ✅ high |
| 0x03 | CurrentDateTime | 4 | ✅ high |
| 0x04 | MemberStateCertificate | 205 | raw (→ layer firma) |
| 0x05 | OdometerValueMidnight | 3 | ✅ high |
| 0x06 | DateOfDayDownloaded | 4 | ✅ high |
| 0x08 | SignatureRecord (ECC) | 64 | ✅ opaco |
| 0x09 | VuSpecificConditionRecord | 5 | ✅ high |
| 0x0A | VehicleIdentificationNumber | 17 | ✅ high |
| 0x0B | VehicleRegistrationNumber (G2) | 14 | ✅ high |
| 0x0C | VuCalibrationRecord | 222/252 | ✅ medium (officina/VIN) |
| 0x0D | VuCardIWRecord | 131 | ✅ medium (titolare/inserimento) |
| 0x0E | VuCardRecord | 45 | ✅ medium (card number) |
| 0x0F | VUCertificate | 205 | raw (→ layer firma) |
| 0x10 | VuCompanyLocksRecord | 99 | ✅ medium |
| 0x11 | VuControlActivityRecord | 32 | ✅ medium |
| 0x12 | VuDetailedSpeedBlock | 64 | ✅ high (sintesi) |
| 0x13 | VuDownloadablePeriod | 8 | ✅ high |
| 0x14 | VuDownloadActivityData | 59 | ✅ medium |
| 0x15 | VuEventRecord | 91 | ✅ medium (prefisso) |
| 0x16 | VuGNSSADRecord | 56/57 | ✅ high (GPS validato) |
| 0x17 | VuITSConsentRecord | 20 | ✅ high |
| 0x18 | VuFaultRecord | 90 | ✅ medium (prefisso) |
| 0x19 | VuIdentification | 126/138 | ✅ medium (fabbricante) |
| 0x1A | VuOverSpeedingControlData | 9 | ✅ high |
| 0x1B | VuOverSpeedingEventRecord | 32 | ✅ high |
| 0x1C | VuPlaceDailyWorkPeriodRecord | 40/41 | ✅ high |
| 0x1E | VuTimeAdjustmentRecord | 99 | ✅ medium |
| 0x1F | VuPowerSupplyInterruptionRecord | 87 | ✅ medium |
| 0x20 | VuSensorPairedRecord | 28 | ✅ medium |
| 0x21 | VuSensorExternalGNSSCoupledRecord | 28 | ✅ medium |
| 0x22 | VuBorderCrossingRecord | 55 | ✅ high (confermato) |
| 0x23 | VuLoadUnloadRecord | 58 | ✅ high |
| 0x24 | VehicleRegistrationIdentification (G2.2) | 15 | ✅ medium |

---

## recordType osservati nei file reali (size confermate)

| recordType | recordSize | Significato (confermato/ipotesi) | Gen | Note |
|-----------:|-----------:|----------------------------------|-----|------|
| 0x02 | 1 | CardSlotsStatus | G2/2.2 | |
| 0x03 | 4 | TimeReal (currentDateTime) | G2/2.2 | |
| 0x04 | 205 | Certificate (MemberState/CA) | G2/2.2 | |
| 0x05 | 3 | OdometerShort | G2/2.2 | |
| 0x06 | 4 | TimeReal | G2/2.2 | |
| 0x08 | 64 | SignatureRecord (ECC r‖s) | G2/2.2 | chiude ogni TREP |
| 0x09 | 5 | (da identificare) | G2/2.2 | |
| 0x0A | 17 | VehicleIdentificationNumber+ | G2/2.2 | |
| 0x0B | 14 | VuDownloadActivityData? | G2 | |
| 0x0C | 222/252 | (da identificare) | G2/2.2 | |
| 0x0D | 131 | VuCalibrationRecord | G2/2.2 | |
| 0x0E | 45 | (da identificare) | G2/2.2 | |
| 0x0F | 205 | Certificate (VU) | G2/2.2 | |
| 0x10 | 99 | VuCompanyLocksRecord | G2/2.2 | spesso noOfRecords=0 |
| 0x11 | 32 | VuControlActivityRecord | G2/2.2 | spesso noOfRecords=0 |
| 0x13 | 8 | VuDownloadablePeriod ✓ | G2/2.2 | **size 8 = spec** |
| 0x14 | 59 | (da identificare) | G2/2.2 | |
| 0x15 | 91 | VuEventRecord | G2/2.2 | |
| 0x16 | 56/57 | VuActivityDailyRecord / faults | G2/2.2 | size G2=56, G2.2=57 |
| 0x17 | 20 | SensorExternalGNSSCoupledRecord | G2/2.2 | size 20 = spec |
| 0x18 | 90 | VuFaultRecord | G2 | |
| 0x19 | 126/138 | (da identificare) | G2/2.2 | |
| 0x1A | 9 | VuTimeAdjustmentRecord | G2/2.2 | |
| 0x1B | 32 | (da identificare) | G2/2.2 | |
| 0x1C | 40/41 | VuPlaceDailyWorkPeriodRecord | G2/2.2 | size G2=40, G2.2=41 |
| 0x1F | 87 | (da identificare) | G2/2.2 | |
| 0x20 | 28 | VuCardIWRecord / SensorPaired | G2/2.2 | |
| 0x21 | 28 | (da identificare) | G2/2.2 | noOfRecords=0 osservato |
| **0x22** | **55** | **VuBorderCrossingRecord ✓** | **G2.2** | **CONFERMATO su dati reali** |
| **0x23** | **58** | **VuLoadUnloadRecord** | **G2.2** | size = somma componenti spec |
| 0x24 | 15 | VehicleRegistrationIdentification | G2/2.2 | nation(1)+14 |
| 0x29 | 2 | (da identificare, G2.2) | G2.2 | 282 record in un file |
| 0x40 | 1 | VuDetailedSpeed sample (G1 TREP) | G1 | 15816 campioni |
| 0x60 | 0 | terminatore/padding | G2.2 | |

## VuBorderCrossingRecord — struttura confermata (recordType 0x22, 55 byte)

Decodifica reale di un record da `V600625842504021733...ddd` (offset 0x5AF):

```
cardNumberAndGenDriverSlot    19 byte  FullCardNumberAndGeneration
                                       (type=0x01, nation=0x1A, num="I100000114613001", gen=0x02)
cardNumberAndGenCodriverSlot  19 byte  tutto 0xFF (nessun secondo conducente)
countryLeft                    1 byte  NationNumeric (0x0F)
countryEntered                 1 byte  NationNumeric (0x11)
gnssPlaceAuthRecord           12 byte  timeStamp(4)=2025-03-03T16:26:57Z +
                                       gnssAccuracy(1) + geoCoordinates(6) + authStatus(1)
vehicleOdometerValue           3 byte  OdometerShort
```

Totale: 19+19+1+1+12+3 = **55 byte**. ✓

## Bug confermato

`V600625842504021733...ddd` contiene **13 record VuBorderCrossingRecord**
(recordType 0x22) ma il parser produce `border_crossings: []`. Il decoder
attuale `parse_g22_border_crossings` stima record di 10-14 byte e dispatcha per
tag `0x052A`, mai raggiunto dal path RecordArray-per-recordType dei file VU.
Stesso problema per `VuLoadUnloadRecord` (0x23, 58 byte) e altri recordType non
in tabella.

## Implicazione architetturale

La decodifica VU corretta richiede un **dispatcher RecordArray keyed per
recordType** (Appendix 7 + enumerazione RecordType di Appendix 2), non i parser
TREP euristici attuali. Questo documento fornisce la mappa size→recordType
empirica necessaria per costruirlo in modo deterministico.
