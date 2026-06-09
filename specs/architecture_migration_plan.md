# Architecture Migration Plan
# From Heuristic Pattern Matching to Schema-Driven Deterministic Parser
# Agent 5 — Architecture Redesign

## Status Attuale

Il parser attuale (`ddd_parser.py` → `core/tag_navigator.py`) usa:

| Meccanismo | Descrizione | Problema |
|-----------|-------------|----------|
| **Pattern matching euristico** | STAP parsing sequenziale + BER-TLV sliding window | Nessuna garanzia di copertura completa |
| **Deep scan fallback** | `deep_scan()` scansiona blocchi "unparsed" per tag conosciuti | Non deterministico, può trovare falsi positivi |
| **Regex su dati raw** | `parse_g1_vu_overview()`, `_parse_trep_05_technical()` usano regex per estrarre VIN, nomi, numeri carta | Byte non contabilizzati individualmente |
| **Dispatch a cascata** | `record_and_dispatch()` con if/elif a catena per 30+ tag | Difficile manutenere, non esaustivo |
| **Tag 0x0222, 0x0223 non dispatchati** | Nessun handler per EF_GNSS_Places e EF_GNSS_Accumulated_Position | Dati GNSS persi |
| **Tag 0x0508 dimensione errata** | ControlActivityData usa rec_size=24 anziché 46 | 5 campi su 7 mancanti |

### Coverage attuale
- `bytes_covered` viene incrementato per header + payload quando un tag è identificato
- `record_unparsed()` copre byte non identificati come "Unparsed Data" o "Padding"
- Il deep scan tenta di recuperare tag nei blocchi unparsed
- **Risultato**: coverage ~70-90% sui file DDD tipici, ma non deterministico

## Stato Target

| Caratteristica | Implementazione |
|---------------|-----------------|
| **Decoder Registry** | `core/decoder_registry.py` — mappa centralizzata tag→decoder con metadata (Annex ref, record size, priorità) |
| **Parser deterministico** | `core/deterministic_parser.py` — due passaggi (strutturale + semantico), nessun deep scan |
| **100% byte coverage** | `CoverageTracker` traccia ogni byte: classificato (tag), padding (0x00/0xFF/0x55), o unknown |
| **Schema ASN.1** | `specs/tachograph.asn` — definizioni formali per tutti i tipi |
| **Coverage report** | Per sezione file (header, driver data, vehicle data, certificates, tail) |

## Passi di Migrazione (Incrementale)

### Step 1: Decoder Registry (Effort: 2h) ✅ COMPLETATO
**File**: `core/decoder_registry.py`
- Centralizzare TUTTI i tag (da `tag_definitions.py` + `g1_complete_structures.md`) in un unico registry
- Aggiungere metadata: Annex ref, record_size, container flag, generation, priorità
- Ref attuale: `record_and_dispatch()` in `tag_navigator.py:187-322`
- **Nessuna modifica al parser esistente**: il registry è un modulo standalone

### Step 2: Coverage Tracker (Effort: 1h) ✅ INTEGRATO in deterministic_parser.py
**Moduli**: `core/deterministic_parser.py` (classe `CoverageTracker`)
- Range merging per evitare double-counting
- Classificazione byte: Tag_XXXX, Padding(0x00), Padding(0xFF), Padding(0x55), Unknown
- Report per sezioni file

### Step 3: Aggiungere `is_spec_verified` ai tag esistenti (Effort: 1h)
**File**: `core/tag_navigator.py`
- Aggiungere flag `is_spec_verified` a `record_raw_tag()`:
  - `True` se il tag ha un decoder basato su specifica (es. 0x0501, 0x0502, 0x0503, 0x0504, 0x0505, 0x0520, 0x0521, 0x0522, 0x050C)
  - `False` se il decoder è euristico (es. 0x0100 regex, 0x7601 regex, 0x2020 regex)
- Aggiungere `annex_ref` e `generation` ai record raw

### Step 4: Fix tag non dispatchati (Effort: 1h)
**File**: `core/tag_navigator.py` → `record_and_dispatch()`
- Aggiungere dispatch per 0x0222 (EF_GNSS_Places)
- Aggiungere dispatch per 0x0223 (EF_GNSS_Accumulated_Position)  
- Fixare 0x0508 (ControlActivityData) dimensione record: 24→46

### Step 5: Coverage Report per sezioni (Effort: 1h)
**File**: `core/tag_navigator.py` → `get_section_report()`
- Generare report di coverage per sezioni del file:
  - Header (0-256)
  - Driver Data (256 - file_size/2)
  - Vehicle Data (file_size/2 - 3*file_size/4)
  - Certificates (3*file_size/4 - file_size-512)
  - Signature/Tail (file_size-512 - file_size)

### Step 6: Integrare CoverageTracker nel parser esistente (Effort: 2h)
**File**: `ddd_parser.py`
- Importare `CoverageTracker` da `core.deterministic_parser`
- Affiancare al `bytes_covered` corrente
- Generare report di coverage post-parse

### Step 7: Validazione incrociata (Effort: 2h)
- Confrontare risultati parser esistente vs deterministico su 10+ file DDD reali
- Verificare che il coverage sia ≥ attuale
- Identificare edge case dove il deterministico fallisce

### Step 8: Switch al deterministico (Effort: 2h)
**File**: `ddd_parser.py`
- Opzione `use_deterministic=True` (default False)
- Quando attivo, usa `DeterministicParser` invece di `TagNavigator`
- Mantenere entrambi i path per retrocompatibilità

### Step 9: Rimuovere deep scan (Effort: 1h)
- Quando `use_deterministic=True`, saltare `deep_scan()`
- Verificare che il coverage non peggiori

### Step 10: Rimozione codice legacy (Futuro, opzionale)
- Rimuovere `deep_scan()` da `tag_navigator.py`
- Rimuovere regex euristici da `decoders.py` per VU overview
- Sostituire con parsing strutturato basato su ASN.1

## Riepilogo Effort

| Step | Descrizione | Effort | Stato |
|------|-------------|--------|-------|
| 1 | Decoder Registry | 2h | ✅ Completato |
| 2 | Coverage Tracker | 1h | ✅ Completato |
| 3 | is_spec_verified flag | 1h | Da fare |
| 4 | Fix tag non dispatchati | 1h | Da fare |
| 5 | Coverage report per sezioni | 1h | Da fare |
| 6 | Integrazione CoverageTracker | 2h | Da fare |
| 7 | Validazione incrociata | 2h | Da fare |
| 8 | Switch deterministico | 2h | Da fare |
| 9 | Rimuovere deep scan | 1h | Da fare |
| 10 | Rimozione legacy | — | Futuro |
| **Totale** | | **13h** | |

## Principi di Migrazione

1. **Nessun breaking change**: I nuovi moduli sono additivi, il parser esistente continua a funzionare
2. **Feature flag**: `use_deterministic=True` per attivare il nuovo parser
3. **Validazione**: Confronto automatico output vecchio vs nuovo su ogni file
4. **Rollback facile**: Basta impostare `use_deterministic=False`
