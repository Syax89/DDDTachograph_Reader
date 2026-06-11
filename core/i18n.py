"""Minimal i18n layer for user-facing labels (GUI and exports).

Internal data keys and values are always English; only *display labels* go
through :func:`tr`. The language defaults to English and can be switched with
the ``TACHO_LANG`` environment variable (e.g. ``TACHO_LANG=it``) or at runtime
via :func:`set_language`.

Adding a language = adding a dictionary to ``_TRANSLATIONS``; unknown labels
fall back to the English text, so partial dictionaries are safe.
"""
import os

_TRANSLATIONS = {
    "it": {
        # ── Section labels ──
        "Daily Activities": "Attività giornaliere",
        "Vehicles Used": "Veicoli utilizzati",
        "Vehicle Units Used": "Unità veicolo utilizzate",
        "Events": "Eventi",
        "Faults": "Guasti",
        "Places": "Luoghi",
        "Specific Conditions": "Condizioni specifiche",
        "Calibrations": "Calibrazioni",
        "Control Activities": "Attività di controllo",
        "Card Downloads": "Scarichi carta",
        "GNSS Accumulated Driving": "Guida accumulata GNSS",
        "GNSS Places": "Luoghi GNSS",
        "Border Crossings": "Attraversamenti frontiera",
        "Load / Unload": "Carico / Scarico",
        "Load Sensor Data": "Dati sensore di carico",
        "Trailer Registrations": "Registrazioni rimorchio",
        "Overspeeding Events": "Eventi eccesso velocità",
        "Overspeeding Control": "Controllo eccesso velocità",
        "Power Interruptions": "Interruzioni alimentazione",
        "Power Supply Interruptions": "Interruzioni alimentazione",
        "Company Locks": "Blocchi aziendali",
        "VU Identification": "Identificazione VU",
        "VU Identifications": "Identificazioni VU",
        "Sensor Pairing": "Abbinamento sensore",
        "Sensor Pairings": "Abbinamenti sensore",
        "Sensor GNSS Coupling": "Accoppiamento GNSS",
        "Sensor GNSS Couplings": "Accoppiamenti GNSS",
        "Card Insertion / Withdrawal": "Inserimenti / Estrazioni carta",
        "Card Records": "Record carta",
        "Time Adjustments": "Regolazioni orario",
        "ITS Consents": "Consensi ITS",
        "Download Activities": "Attività di scarico",
        "Downloads": "Scarichi",
        "Detailed Speed": "Velocità dettagliata",
        "Detailed Speed Blocks": "Blocchi velocità dettagliata",
        "Calibration Workshops": "Officine di calibrazione",
        "Inserted Drivers": "Conducenti inseriti",
        "Company Holders": "Titolari azienda",
        "Signed Daily Records": "Record giornalieri firmati",
        "GPS Locations": "Posizioni GPS",
        "EF Card Data Signatures": "Firme dati EF carta",
        "Previous Vehicle": "Veicolo precedente",
        "TREP Signatures": "Firme TREP",
        "VU Certificates": "Certificati VU",
        # ── Table headers / summary fields ──
        "Date": "Data",
        "Time": "Ora",
        "Activity": "Attività",
        "Odometer km": "Odometro km",
        "Slot": "Slot",
        "Crew": "Equipaggio",
        "Card": "Carta",
        "Driver": "Conducente",
        "Description": "Descrizione",
        "Field": "Campo",
        "Value": "Valore",
        "File": "File",
        "Generation": "Generazione",
        "Source": "Origine",
        "File size": "Dimensione file",
        "Coverage": "Copertura",
        "Integrity": "Integrità",
        "Parsed at": "Analizzato il",
        "Reader version": "Versione reader",
        "Signature verification": "Verifica firme",
        "EF card data signatures": "Firme dati EF carta",
        "Card Number": "Numero carta",
        "Issuing Nation": "Nazione emittente",
        "Expiry Date": "Data scadenza",
        "Birth Date": "Data di nascita",
        "Licence Number": "Numero patente",
        "Preferred Language": "Lingua preferita",
        "Vehicle Plate": "Targa veicolo",
        "Vehicle VIN": "VIN veicolo",
        "Vehicle Registration Nation": "Nazione immatricolazione",
        "Vehicle Unit (VU)": "Unità veicolo (VU)",
        "Driver Card": "Carta conducente",
        "Begin": "Inizio",
        "End": "Fine",
        "Timestamp": "Marca temporale",
        "Nation": "Nazione",
        "Condition": "Condizione",
        "Workshop": "Officina",
        "Workshop Name": "Nome officina",
        "Workshop Address": "Indirizzo officina",
        "Inserted": "Inserita",
        "Not inserted": "Non inserita",
        "(no event)": "(nessun evento)",
    },
}

_lang = (os.environ.get("TACHO_LANG") or "en").strip().lower()[:2]


def set_language(lang: str):
    """Switch the display language at runtime ('en', 'it', ...)."""
    global _lang
    _lang = (lang or "en").strip().lower()[:2]


def get_language() -> str:
    return _lang


def tr(text):
    """Translate a display label; falls back to the English text."""
    if not isinstance(text, str):
        return text
    table = _TRANSLATIONS.get(_lang)
    if not table:
        return text
    return table.get(text, text)
