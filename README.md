# 🚛 DDD Tachograph Reader

> Analizzatore professionale per file `.ddd` di tachigrafi digitali — GUI moderna, analisi flotte, conformità legale EU.

[![Build and Release](https://github.com/Syax89/ddd-tachograph-reader/actions/workflows/build.yml/badge.svg)](https://github.com/Syax89/ddd-tachograph-reader/actions/workflows/build.yml)
[![Latest Release](https://img.shields.io/github/v/release/Syax89/ddd-tachograph-reader)](https://github.com/Syax89/ddd-tachograph-reader/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)

---

## ✨ Funzionalità Principali

### 📄 Analisi File Singolo
- **Multi-Generazione**: G1 (Annex 1B), G2 Smart (Annex 1C), **Gen 2.2 Smart V2** (Reg. EU 2023/980)
- **Anagrafica completa**: Nome, cognome, data di nascita, numero carta, scadenza, nazione emittente
- **Attività giornaliere**: Guida, lavoro, disponibilità, riposo — con timeline visuale 24h
- **Dati veicolo**: VIN, targa, nazione di registrazione, odometro
- **Posizioni GNSS**: Reverse geocoding dei percorsi su mappa (OpenStreetMap)

### ⚖️ Compliance & Infrazioni
- **Rilevamento automatico** infrazioni ai sensi del Reg. EU 561/2006 e Art. 174 C.d.S.
- **Calcolo sanzioni** stimate (MSI / SI / MI) con range min–max
- **Registro eventi e guasti**: guida senza carta, interruzioni alimentazione, manipolazioni
- **Validazione firme digitali**: catena ERCA → MSCA → Carta (RSA + ECDSA)

### 🚛 Analisi Flotta (Fase 13)
- Analisi parallela di **cartelle intere** con file `.ddd` multipli
- Dashboard KPI: conducenti, KM totali, ore guida, infrazioni aggregate
- **Export PDF** report flotta (landscape A4, color-coded)
- **Export CSV/Excel** per integrazione con sistemi gestionali

### 🔐 Integrità Forense
- Verifica crittografica delle firme digitali (Reg. EU 2016/799)
- Parsing ricorsivo BER-TLV (container annidati)
- Stato: `Verified`, `Verified (Local Chain)`, `Incomplete Certificates`

---

## 🖥️ Screenshot

| Benvenuto | Attività | Infrazioni | Flotta |
|-----------|----------|------------|--------|
| Dashboard principale con KPI | Timeline giornaliera | Dettaglio sanzioni | Analisi multi-conducente |

---

## 🚀 Download & Utilizzo

### ▶️ Eseguibile (consigliato)
Scarica l'ultima versione dalla sezione **[Releases](https://github.com/Syax89/ddd-tachograph-reader/releases/latest)**:

| Piattaforma | File |
|-------------|------|
| 🪟 Windows | `TachoReader-Windows.zip` |
| 🍎 macOS | `TachoReader-Mac.zip` |

Estrai e avvia `TachoReader` — nessuna installazione richiesta.

### 🐍 Da sorgente (sviluppatori)

```bash
git clone https://github.com/Syax89/ddd-tachograph-reader.git
cd ddd-tachograph-reader
pip install -r requirements.txt

# GUI
python gui_tree.py

# CLI (output JSON)
python main.py percorso/file.ddd

# Analisi flotta
python fleet_analytics.py /cartella/con/ddd/
```

---

## 📦 Struttura Progetto

```
ddd-tachograph-reader/
├── gui_tree.py               # Interfaccia grafica (albero + tabella, tkinter)
├── main.py                   # Entry point CLI
├── ddd_parser.py             # Parser principale
├── core/
│   ├── tag_navigator.py      # Navigazione ricorsiva BER-TLV
│   ├── decoders.py           # Decoder tag (G1, G2, G2.2)
│   └── models.py             # Modelli dati risultato
├── fleet_analytics.py        # Analisi flotta multi-file
├── fleet_pdf_exporter.py     # Export PDF report flotta
├── compliance_engine.py      # Motore infrazioni EU 561/2006
├── fines_calculator.py       # Calcolo sanzioni Art. 174 C.d.S.
├── export_manager.py         # Export Excel/CSV
├── export_pdf.py             # Export PDF singolo conducente
├── geocoding_engine.py       # Reverse geocoding + mappe statiche
├── signature_validator.py    # Validazione firme ERCA/MSCA
├── certs/                    # Certificati ERCA radice (G1/G2)
├── tests/                    # Suite di test automatici
└── .github/workflows/        # CI/CD build automatico Win/Mac
```

---

## 🗂️ Formati Supportati

| Generazione | Standard | Header | Note |
|-------------|----------|--------|------|
| G1 Digital | Annex 1B (Reg. 3821/85) | `0x0002` | Tachigrafi analogici/digitali classici |
| G2 Smart | Annex 1C (Reg. 2016/799) | `0x7621` | Smart Tachograph V1 |
| **G2.2 Smart V2** | Annex 1C (Reg. 2023/980) | `0x7631` | Smart Tachograph V2 — **nuovo** |

---

## 🧪 Test

```bash
pip install pytest
pytest tests/ -v
```

**52 test** — detection multi-generazione, parser G1/G2/G2.2, fleet analytics, PDF export, firme digitali.

---

## 🔧 Build Eseguibile

```bash
pip install pyinstaller
pyinstaller build.spec
# Output: dist/TachoReader (Mac) / dist/TachoReader.exe (Windows)
```

Il build automatico è gestito da **GitHub Actions** ad ogni release taggata.

---

## 📋 Roadmap

- [x] Parser G1 / G2 / G2.2
- [x] GUI con dark mode
- [x] Compliance engine (EU 561/2006)
- [x] Validazione firme digitali (ERCA chain)
- [x] Analisi flotta multi-file
- [x] Export PDF / Excel / CSV
- [x] GNSS + mappe statiche
- [ ] Supporto completo Gen 2.2 (nuovi campi specifici)
- [ ] Enterprise connectors (fleet management API)
- [ ] Dashboard analytics aggregata

---

## ⚖️ Note Legali

Le sanzioni indicate sono **stime** basate sull'Art. 174 del Codice della Strada italiano e sul Reg. EU 561/2006. I report generati non hanno valore legale autonomo e devono essere verificati da un professionista abilitato.

---

## 📄 Licenza

MIT © [Syax89](https://github.com/Syax89)
