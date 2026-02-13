# Piano di Sviluppo Semplificato: Tacho Explorer

Obiettivo: Creare un'applicazione cross-platform (Windows/Mac) per la lettura completa di file tachigrafici (.ddd) e la visualizzazione del contenuto in formato ad albero.

## ✅ Obiettivi Core

### 1. Lettura al 100% (Parsing Engine)
- Garantire che ogni byte del file venga identificato o mostrato come "Dati Grezzi".
- Mappare tutti i tag G1, G2 e G2.2 (Smart V2).
- Gestire in modo robusto i file corrotti o parziali.

### 2. Interfaccia "Regedit Style" (GUI)
- Visualizzazione gerarchica di tutti i tag e sotto-tag.
- Pannello laterale per i dettagli del valore (Hex, Decodificato, Descrizione).
- Ricerca rapida tra i tag.

### 3. Distribuzione (Build)
- Configurazione PyInstaller per generare eseguibili standalone:
    - `.exe` per Windows.
    - `.app` / DMG per macOS.

## 🛑 Feature Sospese (Backlog)
- Analisi flotta avanzata.
- Calcolatore sanzioni.
- Geocoding e mappe.
- Domain-Driven Design complesso (manterremo una struttura semplice focalizzata sul parser).

---
*Aggiornato il 13/02/2026 seguendo le nuove direttive.*
