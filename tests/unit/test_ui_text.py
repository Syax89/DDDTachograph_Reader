"""One display-text layer: every readable label is humanised *and* translated.

Before this layer the GUI produced display text in three places and only one of
them was translatable: literals in ``app/gui.py`` went through ``_()``, while

* raw CamelCase section names out of ``core/registry/models.py``
  (``CalibrationData``, ``EventsData``, ``VU_TechnicalInfo``, ``CalibrationVINs``
  …) were inserted into the tree verbatim, and
* ``snake_case`` record keys run through ``humanize_key()`` produced English
  headers (``Card Driver Begin``, ``Begin Time`` …) that never met ``_()``.

So an Italian user read ``EventsData`` in the tree and ``Card Driver Begin``
above the events table. ``app/ui_text.py`` is now the single place that turns a
raw key into a translated label, and these tests pin both halves of it: the
humanising rules (CamelCase, snake_case, acronyms, acronym plurals, non-strings)
and one *real* render of a mock download, where no tree label may still hold
CamelCase and no table heading may still hold an underscore.

``tests/unit/conftest.py`` pins the process-global translator and the settings
file for every test here (``isolate_i18n``), and the render closes the window
through ``_on_close()`` the way the product does.
"""
import re
from pathlib import Path
from unittest.mock import Mock

import pytest

import app.i18n as i18n
from app.ui_text import humanize, label

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_DIR = REPO_ROOT / "locale"

#: A raw identifier leaking into a label: a lowercase letter followed by an
#: uppercase one (``EventsData``, ``RecordArray``).
CAMEL_CASE = re.compile(r"[a-z][A-Z]")

#: The section names ``core/registry/models.py`` inserts into the tree.
SECTION_NAMES = (
    ("CalibrationData", "Calibration Data"),
    ("EventsData", "Events Data"),
    ("FaultsData", "Faults Data"),
    ("ControlActivityData", "Control Activity Data"),
    ("VehicleIdentification", "Vehicle Identification"),
    ("VU_TechnicalInfo", "VU Technical Info"),
    ("InsertedCardNumbers", "Inserted Card Numbers"),
    ("CardIWRecords", "Card IW Records"),
    ("CompanyInfo", "Company Info"),
    ("CompanyLocks", "Company Locks"),
    ("OverspeedingEvents", "Overspeeding Events"),
    ("OverspeedingControl", "Overspeeding Control"),
    ("SpecificConditions", "Specific Conditions"),
    ("TimeAdjustments", "Time Adjustments"),
    ("SensorDailyRecords", "Sensor Daily Records"),
    ("SensorInfo", "Sensor Info"),
    ("PreviousVehicle", "Previous Vehicle"),
    ("CalibrationWorkshops", "Calibration Workshops"),
    ("CalibrationVINs", "Calibration VINs"),
    ("CurrentUsage", "Current Usage"),
    ("TechnicalInfo", "Technical Info"),
    ("Certificates", "Certificates"),
    ("InsertedDrivers", "Inserted Drivers"),
    ("Places", "Places"),
)

#: A mock download: one card, the CamelCase section names the registry emits,
#: unparsed byte ranges (the only path that shows the Location/Offset/Length/Hex
#: headings) and a signature summary so the security group renders too.
MOCK_DDD = {
    "metadata": {
        "generation": "Generation 2",
        "is_vu": False,
        "origin": "driver_card",
        "file_size_bytes": 8192,
        "parsed_at": "2024-11-26 08:00:00",
        "app_version": "2.7.1",
        "integrity_check": "Verified",
    },
    "coverage": {},
    "driver": {
        "card_number": "IT1234567890",
        "surname": "ROSSI",
        "firstname": "MARIO",
        "birth_date": "01/01/1980",
        "expiry_date": "01/01/2030",
        "issuing_nation": "I",
    },
    "generations": {
        "Generation 1": {
            "EventsData": [
                {"event_type": 1, "event_purpose": "begin",
                 "begin_time": "2024-11-26T00:00:00Z",
                 "end_time": "2024-11-26T01:00:00Z",
                 "card_driver_begin": "IT1234567890"},
                {"event_type": 2, "event_purpose": "end",
                 "begin_time": "2024-11-26T02:00:00Z",
                 "end_time": "2024-11-26T03:00:00Z",
                 "card_driver_begin": "IT1234567890"},
            ],
            "FaultsData": [{"fault_type": 1, "begin_time": "2024-11-26T00:00:00Z",
                            "end_time": "2024-11-26T01:00:00Z"}],
            "ControlActivityData": [{"control_type": "roadside",
                                     "begin_time": "2024-11-26T04:00:00Z"}],
            "CalibrationData": [{"calibration_purpose": "periodic",
                                 "workshop_name": "OFFICINA"}],
            "CalibrationVINs": [{"vin": "WVWZZZ1JZXW000001"}],
            "Places": [{"daily_work_period": 1,
                        "begin_time": "2024-11-26T05:00:00Z"}],
            "VehicleIdentification": {"vin": "WVWZZZ1JZXW000001",
                                      "plate": "AB123CD"},
            "VU_TechnicalInfo": {"manufacturer": "STONERIDGE",
                                 "serial_number": "1234"},
            "InsertedCardNumbers": {"driver": "IT1234567890"},
            "CardIWRecords": [{"card_slot": "driver",
                               "begin_time": "2024-11-26T00:00:00Z"}],
            # A nested dict exercises the "Field › Subfield" flattening path.
            "CompanyInfo": {"company_name": "TRASPORTI SRL",
                            "company_address": {"street": "Via Roma"}},
            "CompanyLocks": {"company_lock": "AB12"},
            "OverspeedingEvents": [{"begin_time": "2024-11-26T06:00:00Z",
                                    "max_speed": 98}],
            "OverspeedingControl": {"speed_limit": 90},
            "SpecificConditions": [{"condition": "ferry",
                                    "begin_time": "2024-11-26T07:00:00Z"}],
            "TimeAdjustments": [{"old_time": "2024-11-26T08:00:00Z",
                                 "new_time": "2024-11-26T09:00:00Z"}],
            "SensorDailyRecords": [{"day": "2024-11-26", "distance": 12}],
            "SensorInfo": {"sensor_serial": "S1"},
            "PreviousVehicle": {"plate": "XY999ZZ"},
            "CalibrationWorkshops": [{"workshop_name": "TACHO SERVICE"}],
            "CurrentUsage": {"vehicle_plate": "AB123CD",
                             "begin_time": "2024-11-26T00:00:00Z"},
            "TechnicalInfo": {"recording_equipment_serial": "1"},
            "Certificates": [{"issuer": "ERCA"}],
            "InsertedDrivers": [{"card_number": "IT1234567890",
                                 "surname": "ROSSI"}],
        },
        "Security": {
            "CompanyLocks": {"company_lock": "AB12"},
        },
    },
    "raw_tags": {"Unparsed Data": [
        {"container": "EF_EventsData", "offset": 128, "length": 4,
         "data_hex": "DEADBEEF"},
        {"offset": 512, "length": 2, "data_hex": "FFFF"},
    ]},
    "signature_verification": {
        "available": True,
        "msca_to_vu": True,
        "root_anchored": True,
        "all_treps_valid": True,
        "summary": "1/1 valid",
        "treps": [{"trep": "0x01", "signature_valid": True}],
    },
}


# ── humanize(): raw key → space separated English label ────────────────────

@pytest.mark.parametrize("key,expected", SECTION_NAMES)
def test_camel_case_section_names_are_split_into_words(key, expected):
    assert humanize(key) == expected


@pytest.mark.parametrize("key,expected", [
    ("card_driver_begin", "Card Driver Begin"),
    ("begin_time", "Begin Time"),
    ("manufacturer", "Manufacturer"),
    ("card_number", "Card Number"),
    ("company_name", "Company Name"),
    ("type_code", "Type Code"),
    ("daily_work_period", "Daily Work Period"),
])
def test_snake_case_keys_are_split_into_words(key, expected):
    assert humanize(key) == expected


@pytest.mark.parametrize("key,expected", [
    ("gnss_accuracy", "GNSS Accuracy"),
    ("max_speed_kmh", "Max Speed KMH"),
    ("company_id", "Company ID"),
    ("ic_chip", "IC Chip"),
    ("card_iw_records", "Card IW Records"),
    # An all-caps key is an acronym by construction and must stay untouched.
    ("DAC", "DAC"),
    ("VU", "VU"),
])
def test_acronyms_keep_their_capitals(key, expected):
    """``humanize_key('vins')`` would give ``Vins``; known acronyms stay upper."""
    assert humanize(key) == expected


@pytest.mark.parametrize("key,expected", [
    ("CalibrationVINs", "Calibration VINs"),
    ("InsertedCardNumbers", "Inserted Card Numbers"),
    ("vehicle_ids", "Vehicle IDs"),
    ("gnss_vus", "GNSS VUs"),
])
def test_plural_acronyms_keep_the_acronym_and_the_plural(key, expected):
    """``humanize_key('vins')`` would give ``Vins`` — the layer keeps ``VINs``."""
    assert humanize(key) == expected


@pytest.mark.parametrize("key,expected", [
    ("Daily Activities", "Daily Activities"),
    ("Origin details", "Origin details"),
    ("Byte-accounted coverage", "Byte-accounted coverage"),
    ("Security & Certificates", "Security & Certificates"),
    ("Field \u203a Value", "Field \u203a Value"),
    ("  Card present: {from_time} \u2013 {to_time}",
     "  Card present: {from_time} \u2013 {to_time}"),
])
def test_already_display_text_is_returned_unchanged(key, expected):
    """``_kv_rows`` receives keys that are already ``_()``-translated labels.

    Re-humanising one of those must be a no-op, or an Italian "Nome file" would
    come back as "Nome File" and stop matching its catalog entry.
    """
    assert humanize(key) == expected


def test_a_camel_case_word_inside_a_label_still_gets_split():
    """A registry name that is mostly display text keeps its words and spaces."""
    assert humanize("VU RecordArray Summary") == "VU Record Array Summary"
    assert humanize("Detailed Speed (0x052C)") == "Detailed Speed (0x052C)"
    assert humanize("GNSS Authentication (0x960F)") == "GNSS Authentication (0x960F)"


def test_humanize_is_idempotent():
    for key, _expected in SECTION_NAMES:
        once = humanize(key)
        assert humanize(once) == once
    assert not any(CAMEL_CASE.search(humanize(key)) for key, _expected in SECTION_NAMES)


@pytest.mark.parametrize("key,expected", [
    (None, "None"),
    (0, "0"),
    (3.5, "3.5"),
    (b"raw", "b'raw'"),
    ("", ""),
])
def test_non_string_and_empty_keys_never_raise(key, expected):
    assert humanize(key) == expected


def test_humanize_never_raises_on_awkward_payloads():
    """Whatever a decoder produced, the label layer is not the thing that breaks."""
    for key in ({}, [], {"a": 1}, "\u200b", "\U0001f510", "_", "__", "0x052C", "A" * 500):
        assert isinstance(humanize(key), str)


# ── label(): humanise, then translate ──────────────────────────────────────

def test_label_falls_back_to_english_without_a_catalog():
    assert i18n.install("en") == "en"
    assert label("CalibrationVINs") == "Calibration VINs"
    assert label("card_driver_begin") == "Card Driver Begin"


def _install_italian(monkeypatch):
    """Point the translator at the shipped catalogs and load Italian."""
    catalog = CATALOG_DIR / "it" / "LC_MESSAGES" / "tacho.mo"
    if not catalog.exists():
        pytest.skip("the Italian catalog is not built in this checkout")
    monkeypatch.setattr(i18n, "locale_dir", lambda: str(CATALOG_DIR))
    assert i18n.install("it") == "it"


def test_label_returns_the_catalog_string_when_a_catalog_is_installed(monkeypatch):
    """The whole point of the layer: a raw key reaches the catalogs."""
    _install_italian(monkeypatch)

    assert label("events") == "Eventi"           # "Events" is a catalog msgid
    assert label("places") == "Luoghi"           # "Places" too
    assert label("Field") == "Campo"
    # A raw snake_case record key is humanised and then translated.
    assert label("card_driver_begin") == "Inizio carta conducente"


# ── the real render ────────────────────────────────────────────────────────

def _require_display():
    """Return ``tkinter``, skipping *before* the code under test runs."""
    tkinter = pytest.importorskip("tkinter")
    try:
        probe = tkinter.Tk()
    except tkinter.TclError:
        pytest.skip("no display available")
    probe.destroy()
    return tkinter


@pytest.fixture
def explorer(monkeypatch):
    """A real, English ``TachoExplorer``; closed the way the product closes it."""
    tkinter = _require_display()
    import app.gui as gui

    # No modal dialog may block a headless run (integrity banner, error paths).
    monkeypatch.setattr(gui, "messagebox", Mock())
    window = gui.TachoExplorer()
    try:
        yield window
    finally:
        try:
            for after_id in window.tk.call("after", "info"):
                window.tk.call("after", "cancel", after_id)
        except tkinter.TclError:
            pass
        try:
            window._on_close()
        except tkinter.TclError:
            pass


def _tree_labels(window):
    """Every label actually shown in the section tree."""
    labels, pending = [], list(window.tree.get_children())
    while pending:
        iid = pending.pop()
        labels.append(window.tree.item(iid, "text"))
        pending.extend(window.tree.get_children(iid))
    return labels


def _table_headings(window):
    """Every column heading handed to the tables (``_add_section`` payloads)."""
    headings = []
    for payload in window._payloads.values():
        if isinstance(payload, tuple) and len(payload) == 5 and isinstance(payload[1], list):
            headings.extend(str(column) for column in payload[1])
    return headings


def test_mock_download_renders_without_a_single_raw_key(explorer):
    """The regression the layer exists for: a real render of a real shape."""
    explorer._parse_done(MOCK_DDD, "mock.ddd")
    explorer.update()

    labels = _tree_labels(explorer)
    headings = _table_headings(explorer) + [str(c) for c in explorer.table._cols]

    # The render really happened (no vacuous pass over an empty window).
    assert len(labels) > 20, labels
    assert len(headings) > 10, headings

    # 1. No tree label may still be a CamelCase identifier.
    assert [text for text in labels if CAMEL_CASE.search(text)] == []
    # 2. No table heading may still be a snake_case key.
    assert [heading for heading in headings if "_" in heading] == []

    # …and the humanised names are the ones that replaced them.
    assert "Events Data" in labels
    assert "VU Technical Info" in labels
    assert "Calibration VINs" in labels
    assert "Company Info" in labels
    assert "Card Driver Begin" in headings
    assert "Begin Time" in headings
    # The one heading the unparsed-bytes table shows for a containerised range.
    assert "Location" in headings


def test_mock_download_keeps_the_labels_english_until_catalogs_cover_them(explorer):
    """Step 3 extends the catalogs; until then the English msgid is the label."""
    assert i18n.install("en") == "en"
    explorer._parse_done(MOCK_DDD, "mock.ddd")
    explorer.update()

    assert label("events") == "Events"
    assert "Events Data" in _tree_labels(explorer)
