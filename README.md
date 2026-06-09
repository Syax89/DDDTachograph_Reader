# DDD Tachograph Reader

> Analizzatore professionale per file `.ddd` di tachigrafi digitali — decoding completo con struttura ad albero.

[![Build and Release](https://github.com/Syax89/ddd-tachograph-reader/actions/workflows/build.yml/badge.svg)](https://github.com/Syax89/ddd-tachograph-reader/actions/workflows/build.yml)
[![Latest Release](https://img.shields.io/github/v/release/Syax89/ddd-tachograph-reader)](https://github.com/Syax89/ddd-tachograph-reader/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.9%2B-blue)

---

## Funzionalita

### Decodifica File
- **Multi-Generazione**: G1 (Annex 1B), G2 Smart (Annex 1C), **Gen 2.2 Smart V2** (Reg. EU 2023/980)
- **Anagrafica completa**: Nome, cognome, data di nascita, numero carta, scadenza, nazione
- **Attivita giornaliere**: Guida, lavoro, disponibilita, riposo
- **Dati veicolo**: VIN, targa, nazione di registrazione, odometro
- **Posizioni GNSS**: Coordinate, attraversamenti confine, luoghi
- **Record VU**: Inserimenti/estrazioni carta, calibrazioni, sensori, eventi/guasti

### Integrita
- Verifica crittografica firme digitali catena ERCA -> MSCA -> Carta/VU
- Parsing ricorsivo BER-TLV e STAP (container annidati)
- Copertura 100% byte su tutti i file testati
- Struttura ad albero per esplorazione dati

### Esportazione
- Export JSON, Excel, CSV
- Report PDF singolo conducente e flotta
- GUI interattiva con navigazione ad albero

---

## Download & Utilizzo

### Eseguibile (consigliato)
Scarica dalla sezione **[Releases](https://github.com/Syax89/ddd-tachograph-reader/releases/latest)**:

| Piattaforma | File |
|------------|------|
| Windows | `TachoReader-Windows.zip` |
| macOS | `TachoReader-Mac.zip` |

Estrai e avvia `TachoReader` — nessuna installazione richiesta.

### Da sorgente (sviluppatori)

```bash
git clone https://github.com/Syax89/ddd-tachograph-reader.git
cd ddd-tachograph-reader
pip install -r requirements.txt

# GUI
python gui_tree.py

# CLI
python tacho_cli.py percorso/file.ddd
```

---

## Struttura Progetto

```
ddd-tachograph-reader/
├── gui_tree.py               # GUI (albero + tabella, tkinter)
├── tacho_cli.py              # CLI principale
├── main.py                   # CLI legacy
├── ddd_parser.py             # Parser principale
├── core/
│   ├── tag_navigator.py      # Navigazione ricorsiva BER-TLV / STAP
│   ├── decoders.py           # Decoder tag (G1, G2, G2.2)
│   ├── decoder_registry.py   # Registro centralizzato tag->decoder
│   ├── deterministic_parser.py # Parser deterministico two-pass
│   ├── g2_decoders.py        # Decoder VU RecordArray G2/G2.2
│   ├── record_array.py       # Parser RecordArray Annex 1C
│   ├── vu_record_dispatcher.py # Dispatcher stream VU
│   ├── vu_signature_verifier.py # Verifica firme ECDSA VU
│   ├── models.py             # Modelli dati (TachoResult)
│   ├── tag_definitions.py    # Tag ID -> nomi
│   ├── constants.py          # Costanti condivise
│   └── logger.py             # Logging centralizzato
├── export_manager.py         # Export Excel/CSV
├── signature_validator.py    # Validazione catena certificati
├── certs/                    # Certificati ERCA radice
├── tests/                    # Suite di test (>150 test)
├── specs/                    # Specifiche e verifica
├── docs/                     # Documentazione
└── .github/workflows/        # CI/CD build Win/Mac
```

---

## Formati Supportati

| Generazione | Standard | Header | Note |
|------------|----------|--------|------|
| G1 Digital | Annex 1B (Reg. 3821/85) | variabile | Tachigrafi classici |
| G2 Smart | Annex 1C (Reg. 2016/799) | `0x7621` | Smart Tachograph V1 |
| **G2.2 Smart V2** | Annex 1C (Reg. 2023/980) | `0x7631` | Smart Tachograph V2 |

---

## Test

```bash
pip install pytest
pytest tests/ -v
```

127+ test: detection multi-generazione, parser G1/G2/G2.2, coverage, firme digitali.

---

## Build Eseguibile

```bash
pip install pyinstaller
pyinstaller build.spec
# Output: dist/TachoReader (Mac) / dist/TachoReader.exe (Windows)
```

---

## Licenza

MIT (c) [Syax89](https://github.com/Syax89)
