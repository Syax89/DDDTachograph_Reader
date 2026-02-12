# Report di Conformità Tecnica — ddd-tachograph-reader

**Data**: 12 Febbraio 2026  
**Verificato da**: Compliance Engine automatico  
**Riferimenti normativi**: Reg. CE 1360/2002 (Annex 1B), Reg. UE 2016/799 (Annex 1C), Reg. UE 2023/980, Reg. CE 561/2006  
**Fonte di riferimento**: Specifiche Annex 1B (ECE/TRANS/SC.1/2006/2/Add.1), implementazione di riferimento [jugglingcats/tachograph-reader](https://github.com/jugglingcats/tachograph-reader)

---

## 1. Tag principali G1 (Annex 1B)

### 1.1 Tag `0x0502` — CardEventData (EF_EventsData)

**Stato: ⚠️ NON CONFORME**

**Problema critico**: Nel `tag_navigator.py`, il tag `0x0502` viene erroneamente dispatchato a `parse_g1_identification()`:

```python
# tag_navigator.py, riga ~78
if tag == 0x0501 or tag == 0x0502 or tag == 0x0520:
    decoders.parse_g1_identification(val, self.parser.results)
```

Secondo Annex 1B (e confermato dal file di configurazione di riferimento `DriverCardData.config`):
- **`0x0502`** = `CardEventData` (eventi della carta: 6 tipi × N record per tipo)
- **`0x0520`** = `CardIdentification` + `DriverCardHolderIdentification`

Il tag 0x0502 contiene record di eventi (EventType + BeginTime + EndTime + VehicleRegistration), NON dati di identificazione. Il parsing attuale scarta completamente tutti gli eventi della carta.

**Struttura corretta** (Annex 1B, §2.20):
```
CardEventData ::= SEQUENCE (SIZE(6)) OF {
    SEQUENCE (SIZE(noOfEventsPerType)) OF CardEventRecord
}

CardEventRecord ::= SEQUENCE {
    eventType        EventFaultType,    -- 1 byte
    eventBeginTime   TimeReal,          -- 4 bytes
    eventEndTime     TimeReal,          -- 4 bytes
    vehicleRegistration VehicleRegistrationIdentification  -- 15 bytes
}
```

### 1.2 Tag `0x0501` — DriverCardApplicationIdentification

**Stato: ⚠️ NON CONFORME**

Stesso problema del punto 1.1. Il tag `0x0501` è `DriverCardApplicationIdentification`, non `CardIccIdentification`. Contiene:
- Type (1 byte)
- Version (2 bytes)
- noOfEventsPerType (1 byte)
- noOfFaultsPerType (1 byte)
- activityStructureLength (2 bytes)
- noOfCardVehicleRecords (2 bytes)
- noOfCardPlaceRecords (1 byte)

Viene erroneamente parsato come dati di identificazione del conducente.

Anche il nome nel dizionario TAGS è errato: `"G1_CardIccIdentification"` → dovrebbe essere `"G1_DriverCardApplicationIdentification"`.

### 1.3 Tag `0x0504` — CardDriverActivity (buffer ciclico attività)

**Stato: ✅ CONFORME**

Il parsing del buffer ciclico (`parse_cyclic_buffer_activities`) è corretto:
- Header: 2 byte oldest pointer + 2 byte newest pointer
- Record giornaliero: previousRecordLength(2) + currentRecordLength(2) + timestamp(4) + dailyPresenceCounter(2) + dayDistance(2) + ActivityChangeInfo(2 bytes ciascuno)
- Navigazione all'indietro tramite previousRecordLength ✓
- Wrap-around gestito da `get_cyclic_data()` ✓

### 1.4 Tag `0x0505` — CardVehiclesUsed

**Stato: ❌ NON CONFORME (Bug critico)**

L'ordine dei campi nel record da 31 byte è **completamente sbagliato**.

**Ordine nel codice attuale** (`parse_g1_vehicles_used`):
```
[0:4]   firstUse (TimeReal)
[4:8]   lastUse (TimeReal)
[8]     nation
[9:23]  plate (14 bytes)
[23:26] odometerBegin (3 bytes)
[26:29] odometerEnd (3 bytes)
```

**Ordine corretto** (Annex 1B, §2.19 — confermato dal riferimento):
```
[0:3]   VehicleOdometerBegin    (3 bytes, UInt24)
[3:6]   VehicleOdometerEnd      (3 bytes, UInt24)
[6:10]  VehicleFirstUse         (4 bytes, TimeReal)
[10:14] VehicleLastUse          (4 bytes, TimeReal)
[14]    VehicleRegistrationNation (1 byte)
[15:29] VehicleRegistrationNumber (14 bytes)
[29:31] VuDataBlockCounter      (2 bytes, BCD)
```

Questo bug causa la lettura di dati completamente errati per tutti i veicoli usati.

### 1.5 Tag `0x0506` — CardPlaceDailyWorkPeriod

**Stato: ⚠️ NON VERIFICABILE**

Il tag 0x0506 è nel dizionario TAGS come `"G1_Places"` ma non ha un decoder dedicato nel `tag_navigator.py`. I dati dei luoghi di inizio/fine giornata lavorativa non vengono parsati.

### 1.6 Struttura ActivityChangeInfo (2 byte)

**Stato: ✅ CONFORME**

Il layout bitwise è corretto (confermato dal riferimento C#):
```
Bit 15:     Slot (0=primo, 1=secondo)
Bit 14:     Driving status (0=single, 1=crew)
Bit 13:     Card status (0=inserita, 1=non inserita)
Bit 12-11:  Activity (0=REST, 1=AVAILABILITY, 2=WORK, 3=DRIVING)
Bit 10-0:   Minuti dall'inizio della giornata (0-1439)
```

Il codice `decode_activity_val()` implementa correttamente questo schema.

### 1.7 Timestamp — Epoch

**Stato: ✅ CONFORME**

I timestamp `TimeReal` sono correttamente decodificati come secondi dal 1 Gennaio 1970 00:00:00 UTC (Unix epoch), big-endian unsigned 32-bit. Conforme ad Annex 1B §2.162.

### 1.8 Tag `0x0521` — CardDrivingLicenceInformation

**Stato: ✅ CONFORME**

Offset corretti:
- [0:36] DrivingLicenceIssuingAuthority (Name, 36 bytes) ✓
- [36] DrivingLicenceIssuingNation (1 byte) ✓
- [37:53] DrivingLicenceNumber (16 bytes) ✓

### 1.9 Datef per CardHolderBirthDate

**Stato: ⚠️ POTENZIALE BUG**

In Annex 1B §2.26, `Datef` è definito come:
```
Datef ::= SEQUENCE {
    yearHighByte  BCDString(SIZE(1)),
    yearLowByte   BCDString(SIZE(1)),
    month         BCDString(SIZE(1)),
    day           BCDString(SIZE(1))
}
```

Es: 15 marzo 1985 → `0x19 0x85 0x03 0x15`

Il codice usa `decode_date()` che interpreta i 4 byte come un Unix timestamp (`struct.unpack(">I")`). Questo è **corretto per `TimeReal`** ma **potenzialmente errato per `Datef`** (data di nascita). Tuttavia, nella pratica molti VU e software di download scrivono la birth_date come TimeReal. Questo è un caso ambiguo nella catena di implementazione reale.

---

## 2. Tag principali G2 (Annex 1C)

### 2.1 Container `0x7621`

**Stato: ✅ CONFORME**

Il container G2 `0x7621` è riconosciuto come container (flag `is_container` esplicito) e il suo contenuto viene parsato ricorsivamente con `parse_annex1c()`. La logica di skip dei primi 2 byte (quando il primo byte è 0x00) è una gestione pragmatica dei padding osservati in file reali.

### 2.2 Tag `0x0201` — DriverCardHolderIdentification (G2)

**Stato: ✅ CONFORME**

Il decoder `parse_driver_card_holder_identification()` gestisce correttamente:
- [0:36] CardHolderSurname (36 bytes) ✓
- [36:72] CardHolderFirstNames (36 bytes) ✓
- [72:76] CardHolderBirthDate (4 bytes) ✓ (vedi nota su Datef)
- [76:78] CardHolderPreferredLanguage (2 bytes) ✓

Lunghezza minima verificata: 78 bytes ✓

### 2.3 Tag `0x0524` — G2 DriverActivityData (buffer ciclico)

**Stato: ✅ CONFORME**

Dispatchato correttamente a `parse_cyclic_buffer_activities()` quando `length > 100`. La struttura del buffer ciclico G2 è identica a G1 per il formato dei record giornalieri.

### 2.4 Struttura ActivityChangeInfo G2

**Stato: ✅ CONFORME**

In Annex 1C, la struttura `ActivityChangeInfo` rimane identica a 2 byte con lo stesso layout bitwise di G1. Il decoder `decode_activity_val()` è valido per entrambe le generazioni.

---

## 3. Compliance EU 561/2006

### 3.1 Limite guida giornaliera: 9h (estendibile a 10h, max 2 volte/settimana)

**Stato: ⚠️ NON IMPLEMENTATO**

Il `compliance_engine.py` **non verifica il limite di guida giornaliera di 9h/10h**. Verifica solo la guida continua (4.5h senza pausa) e il riposo giornaliero. L'Art. 6.1 del Reg. 561/2006 ("il periodo di guida giornaliero non deve superare le nove ore") non ha un controllo dedicato.

**Fix suggerito**: Aggiungere un metodo `_check_daily_driving_limit()` che calcoli il totale guida in ogni turno di 24h e verifichi il rispetto delle 9h (con max 2 estensioni a 10h per settimana).

### 3.2 Pausa obbligatoria: 45 min dopo 4.5h di guida

**Stato: ⚠️ PARZIALMENTE CONFORME**

La logica della pausa frazionata (15+30 minuti) è implementata ma con un bug:

**Bug**: `DISPONIBILITÀ` è trattata come `RIPOSO` per il reset dell'accumulatore di guida:
```python
elif tipo in ["RIPOSO", "DISPONIBILITÀ"]:
```

Secondo EU 561/2006 Art. 4(d), una **pausa** è esclusivamente un periodo in cui il conducente non può guidare né svolgere altro lavoro, usato esclusivamente per il recupero. La `DISPONIBILITÀ` (POA - Period of Availability) **non è una pausa** ai sensi del Regolamento. Solo `RIPOSO` dovrebbe contare.

### 3.3 Riposo giornaliero: 11h (o 9h ridotto)

**Stato: ⚠️ PARZIALMENTE CONFORME**

Il codice verifica solo se il riposo massimo è < 540 min (9h). Manca la distinzione tra:
- **Riposo regolare**: ≥ 11h (660 min)
- **Riposo ridotto**: ≥ 9h e < 11h (max 3 volte tra due riposi settimanali)
- **Riposo frazionato**: 3h + 9h (Art. 8.2)

Il conteggio dei riposi ridotti (max 3 per periodo inter-settimanale) non è implementato.

### 3.4 Guida settimanale: max 56h

**Stato: ✅ CONFORME**

Implementato correttamente in `_check_weekly_compliance()`:
```python
if driving_by_week[w1] > 56 * 60:
```

### 3.5 Guida bisettimanale: max 90h

**Stato: ✅ CONFORME**

Implementato correttamente:
```python
BIWEEKLY_DRIVING_LIMIT = 90 * 60
```

### 3.6 Riposo settimanale e compensazione

**Stato: ✅ CONFORME**

La logica di:
- Identificazione riposi settimanali (≥ 24h ridotto, ≥ 45h regolare)
- Verifica compensazione entro la 3ª settimana successiva
- Controllo dei 6 periodi di 24h tra riposi settimanali

è implementata e ragionevolmente corretta.

---

## 4. Gen 2.2 (Reg. EU 2023/980)

### 4.1 Header `0x7631` — Container G2.2

**Stato: ⚠️ NON VERIFICABILE CON CERTEZZA**

Il tag `0x7631` è usato come container G2.2. Nelle specifiche pubbliche del Reg. 2023/980, il formato esatto dei nuovi container non è completamente documentato in risorse open-access. Il tag è plausibile (segue la convenzione `76xx` per application containers), ma non è possibile confermare formalmente senza accesso al documento tecnico JRC completo.

**Nota**: L'identificazione della generazione basata sui primi 2 byte del file (`0x7631` → G2.2, `0x7621` → G2) è un approccio pratico ma non è formalizzato nelle specifiche. Il header del file DDD non contiene un campo "generation" esplicito.

### 4.2 Tag G2.2 implementati

**Stato: ⚠️ NON VERIFICABILE**

I seguenti tag sono implementati per Gen 2.2:
- `0x0525` — GNSS Accumulated Driving
- `0x0526`/`0x0226` — Load/Unload Operations
- `0x0527`/`0x0227` — Trailer Registrations
- `0x0528`/`0x0225` — GNSS Enhanced Places
- `0x0529` — Load Sensor Data
- `0x052A`/`0x0228` — Border Crossings

Le strutture dei record (dimensioni, campi) sembrano ragionevoli ma non verificabili senza il documento tecnico JRC completo. I decoder usano approcci euristici (es. `if len(val) % 13 == 0: rec_size = 13`) che suggeriscono reverse-engineering piuttosto che implementazione da specifica.

### 4.3 Coordinate GNSS

**Stato: ✅ PLAUSIBILE**

La decodifica GNSS come signed 32-bit con divisione per 10.000.000 (gradi decimali) è coerente con il formato WGS84 tipico delle specifiche GNSS del tachigrafo.

---

## 5. Bug trovati — Riepilogo

| # | Severità | File | Descrizione |
|---|----------|------|-------------|
| B1 | 🔴 CRITICO | `tag_navigator.py:78` | Tag 0x0502 (EventsData) e 0x0501 (AppIdentification) dispatchati erroneamente a `parse_g1_identification()` |
| B2 | 🔴 CRITICO | `decoders.py:parse_g1_vehicles_used` | Ordine campi record G1 completamente errato (timestamp prima di odometro) |
| B3 | 🟡 MEDIO | `compliance_engine.py:_check_driving_and_breaks` | DISPONIBILITÀ contata come pausa (viola definizione EU 561/2006 Art. 4d) |
| B4 | 🟡 MEDIO | `compliance_engine.py` | Manca verifica limite guida giornaliera 9h/10h (Art. 6.1) |
| B5 | 🟡 MEDIO | `compliance_engine.py:_check_daily_rest_cycles` | Manca distinzione riposo regolare (11h) vs ridotto (9h) e limite 3 ridotti per periodo |
| B6 | 🟠 BASSO | `decoders.py:parse_g1_identification` | `CardHolderBirthDate` (Datef/BCD) decodificato come TimeReal (Unix epoch) |
| B7 | 🟠 BASSO | `ddd_parser.py:TAGS` | Nome errato: 0x0501 → "G1_CardIccIdentification" dovrebbe essere "G1_DriverCardApplicationIdentification" |
| B8 | 🟠 BASSO | `tag_navigator.py` | Nessun parser per tag 0x0502 (eventi) e 0x0503 (guasti) come dati strutturati |

---

## 6. Fix suggeriti

### Fix B1 + B7 + B8: Correzione dispatch tag 0x0501, 0x0502

```python
# tag_navigator.py — sostituire il blocco dispatch

# RIMUOVERE la riga:
# if tag == 0x0501 or tag == 0x0502 or tag == 0x0520:
#     decoders.parse_g1_identification(val, self.parser.results)

# SOSTITUIRE con:
if tag == 0x0520:
    decoders.parse_g1_identification(val, self.parser.results)
elif tag == 0x0501:
    decoders.parse_g1_app_identification(val, self.parser.results)
elif tag == 0x0502:
    decoders.parse_g1_events_data(val, self.parser.results)
```

```python
# decoders.py — aggiungere

def parse_g1_app_identification(val, results):
    """Parse DriverCardApplicationIdentification (tag 0x0501)."""
    if len(val) < 10: return
    app_type = val[0]
    version = struct.unpack(">H", val[1:3])[0]
    no_events = val[3]
    no_faults = val[4]
    activity_len = struct.unpack(">H", val[5:7])[0]
    no_vehicles = struct.unpack(">H", val[7:9])[0]
    no_places = val[9]
    results.setdefault("card_application", {}).update({
        "type": app_type,
        "version": version,
        "no_events_per_type": no_events,
        "no_faults_per_type": no_faults,
        "activity_structure_length": activity_len,
        "no_vehicle_records": no_vehicles,
        "no_place_records": no_places
    })

def parse_g1_events_data(val, results):
    """Parse CardEventData (tag 0x0502) — 6 gruppi di eventi."""
    if len(val) < 24: return
    off = 0
    event_types = [
        "TimeOverlap", "LastCardSession", "PowerSupplyInterruption",
        "CardConflict", "TimeDifference", "DrivingWithoutCard"
    ]
    for group_idx, etype in enumerate(event_types):
        # Ogni record: eventType(1) + beginTime(4) + endTime(4) + nation(1) + plate(14) = 24 bytes
        rec_size = 24
        while off + rec_size <= len(val):
            ev_type = val[off]
            if ev_type == 0xFF:
                off += rec_size
                continue
            begin_ts = struct.unpack(">I", val[off+1:off+5])[0]
            end_ts = struct.unpack(">I", val[off+5:off+9])[0]
            if begin_ts == 0 or begin_ts == 0xFFFFFFFF:
                off += rec_size
                break
            nation = get_nation(val[off+9])
            plate = decode_string(val[off+10:off+24], is_id=True)
            results["events"].append({
                "event_group": etype,
                "event_type_code": ev_type,
                "begin": datetime.fromtimestamp(begin_ts, tz=timezone.utc).isoformat(),
                "end": datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat() if end_ts != 0xFFFFFFFF else "N/A",
                "vehicle_nation": nation,
                "vehicle_plate": plate
            })
            off += rec_size
```

### Fix B2: Ordine campi CardVehicleRecord G1

```python
# decoders.py — parse_g1_vehicles_used, blocco G1 (rec_size == 31)

if rec_size == 31:
    # Annex 1B — ordine CORRETTO
    odo_begin = int.from_bytes(chunk[0:3], byteorder='big')
    odo_end = int.from_bytes(chunk[3:6], byteorder='big')
    first_use_ts = struct.unpack(">I", chunk[6:10])[0]
    last_use_ts = struct.unpack(">I", chunk[10:14])[0]
    nation_code = chunk[14]
    plate = decode_string(chunk[15:29], is_id=True)
    # chunk[29:31] = VuDataBlockCounter (BCD, ignorato)
```

### Fix B3: DISPONIBILITÀ non è una pausa

```python
# compliance_engine.py — _check_driving_and_breaks

# Sostituire:
# elif tipo in ["RIPOSO", "DISPONIBILITÀ"]:

# Con:
elif tipo == "RIPOSO":
    # Solo RIPOSO conta come pausa ai sensi EU 561/2006 Art. 4(d)
```

### Fix B4: Aggiungere controllo limite guida giornaliera

```python
# compliance_engine.py — aggiungere metodo

def _check_daily_driving_limit(self, timeline):
    """Art. 6.1 EU 561/2006: max 9h guida per turno, estendibile a 10h max 2 volte/settimana."""
    # Calcolo guida per turno di 24h (tra riposi giornalieri)
    shifts = self._identify_shifts(timeline)
    
    weekly_extensions = {}  # {week_monday: count}
    
    for shift in shifts:
        driving_total = sum(ev["durata"] for ev in shift if ev["tipo"] == "GUIDA")
        shift_date = shift[0]["start"]
        monday = (shift_date - timedelta(days=shift_date.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0)
        
        if driving_total > 600:  # > 10h = sempre infrazione
            self.infractions.append({
                "data": shift_date.strftime("%d/%m/%Y"),
                "tipo": "ECCESSO_GUIDA_GIORNALIERA",
                "severita": self.SI if driving_total <= 660 else self.MSI,
                "descrizione": f"Guida giornaliera di {driving_total/60:.1f}h supera il limite massimo di 10h."
            })
        elif driving_total > 540:  # > 9h, ammesso max 2 volte/settimana
            weekly_extensions[monday] = weekly_extensions.get(monday, 0) + 1
            if weekly_extensions[monday] > 2:
                self.infractions.append({
                    "data": shift_date.strftime("%d/%m/%Y"),
                    "tipo": "ECCESSO_ESTENSIONI_GUIDA_SETTIMANALI",
                    "severita": self.MI,
                    "descrizione": f"Guida giornaliera di {driving_total/60:.1f}h: 3ª estensione a 10h nella stessa settimana (max 2)."
                })
```

---

## 7. Tabella riassuntiva conformità

| Punto | Elemento | Stato |
|-------|----------|-------|
| 1.1 | Tag 0x0502 (EventsData) | ❌ NON CONFORME |
| 1.2 | Tag 0x0501 (AppIdentification) | ❌ NON CONFORME |
| 1.3 | Tag 0x0504 (DriverActivity cyclic) | ✅ CONFORME |
| 1.4 | Tag 0x0505 (VehiclesUsed) — ordine campi | ❌ NON CONFORME |
| 1.5 | Tag 0x0506 (Places) | ⚠️ NON IMPLEMENTATO |
| 1.6 | ActivityChangeInfo (2 byte, bit layout) | ✅ CONFORME |
| 1.7 | TimeReal epoch (Unix 1970) | ✅ CONFORME |
| 1.8 | Tag 0x0521 (DrivingLicence) | ✅ CONFORME |
| 1.9 | Datef per BirthDate | ⚠️ POTENZIALE BUG |
| 2.1 | Container 0x7621 (G2) | ✅ CONFORME |
| 2.2 | Tag 0x0201 (DriverCardHolder G2) | ✅ CONFORME |
| 2.3 | Tag 0x0524 (DriverActivity G2) | ✅ CONFORME |
| 2.4 | ActivityChangeInfo G2 | ✅ CONFORME |
| 3.1 | Limite guida giornaliera 9h/10h | ❌ NON IMPLEMENTATO |
| 3.2 | Pausa 45min dopo 4.5h | ⚠️ PARZIALMENTE CONFORME |
| 3.3 | Riposo giornaliero 11h/9h | ⚠️ PARZIALMENTE CONFORME |
| 3.4 | Guida settimanale 56h | ✅ CONFORME |
| 3.5 | Guida bisettimanale 90h | ✅ CONFORME |
| 4.1 | Header 0x7631 (G2.2) | ⚠️ NON VERIFICABILE |
| 4.2 | Tag G2.2 nuovi | ⚠️ NON VERIFICABILE |

---

## 8. Note e ambiguità

1. **Datef vs TimeReal**: La specifica Annex 1B definisce `Datef` come BCD, ma nell'ecosistema reale molti software di download serializzano le date come TimeReal. Verificare con file DDD reali.

2. **G2.2 Tag IDs**: I tag 0x0525–0x052A non sono pubblicamente documentati in modo completo. L'implementazione attuale sembra basata su reverse-engineering di file reali, il che è pragmatico ma non garantisce completezza.

3. **STAP vs BER-TLV**: Il parser gestisce correttamente entrambi i formati (STAP per G1 con header 5 byte: tag(2)+type(1)+len(2), e BER-TLV per G2/G2.2). La logica di fallback (prova BER-TLV multi-byte, poi Tag2+Len2, poi BER-TLV single-byte) è robusta.

4. **Calibration Data (0x050C)**: Il parser gestisce record di 105 e 161 byte, coerente con le diverse versioni di VU.

5. **Firma digitale**: La catena di validazione RSA/ECDSA (CardCert → MSCA → ERCA) è implementata nel `signature_validator.py`, non analizzato in questo report.
