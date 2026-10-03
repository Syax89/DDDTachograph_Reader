"""Batch 16 LOW / PARSER regression tests (red->green).

One test class per confirmed family from ``FIX-PLAN.md`` batch 16
(reference: Reg. EU 2016/799 Annex 1C, consolidated 2023):

* CARD-COMPANY-HEURISTIC (XA-F4)   — code-page split presented as deterministic
* CARD-DATEF-VALIDITY (XA-F5)      — ``decode_datef`` accepted impossible dates
* CARD-NATION-CODE (A-F5)          — NationNumeric 0x14 rendered as "FR"
* CARD-NATION-VALIDITY (XA-F6)     — dead ``> 0xFF`` places nation guard
* CARD-SPECIFIC-CONDITION (B-F5/XA-F7) — Gen1 conditions labelled with the Gen2
  meaning and 0x04 (RFU in Gen1) accepted

Assertions use exact expected values/strings rather than snapshots so a
reintroduced defect (or a wrong constant) fails the test.
"""
import os
import struct
import tempfile

import pytest

from app.engine import TachoParser
from core.decoders.card_ef import parse_company_holder_data, parse_g1_places
from core.decoders.common import decode_date, decode_datef, get_nation, nation_full_name
from core.utils.event_codes import specific_condition_label


# ── helpers ────────────────────────────────────────────────────────────────

def _bcd_date(year, month, day):
    """4-byte Datef BCD: YY YY MM DD (Annex 1B §2.26)."""
    hi, lo = divmod(year, 100)
    return bytes([(hi // 10) << 4 | hi % 10,
                  (lo // 10) << 4 | lo % 10,
                  (month // 10) << 4 | month % 10,
                  (day // 10) << 4 | day % 10])


def _stap(tag, dtype, data):
    return struct.pack(">HBH", tag, dtype, len(data)) + data


def _parse_card_file(data):
    tmp = tempfile.NamedTemporaryFile(suffix=".dsc", delete=False)
    try:
        tmp.write(data)
        tmp.close()
        return TachoParser(tmp.name).parse()
    finally:
        os.unlink(tmp.name)


_TS = 1700000000  # 2023-11-14T22:13:20Z

# Card EF SpecificConditions (0x0522), G1 layout = records only.
_SPECIFIC_CONDITIONS = 0x0522
# Gen2 driver-card marker: the Gen2 copy of Application_Identification.
_G2_MARKER = _stap(0x0501, 0x02, b"\x00" * 17)


def _specific_conditions_card(cond_types, g2=False):
    """A card image containing one SpecificConditions EF with *cond_types*."""
    payload = b"".join(struct.pack(">I", _TS + i) + bytes([c])
                       for i, c in enumerate(cond_types))
    data = _stap(_SPECIFIC_CONDITIONS, 0x00, payload)
    return _parse_card_file((_G2_MARKER + data) if g2 else data)


# ── CARD-COMPANY-HEURISTIC (XA-F4) ─────────────────────────────────────────

class TestCardCompanyHeuristic:
    def test_code_page_split_is_marked_heuristic(self):
        """CodePage(1)+name+CodePage(1)+address must be flagged as inferred."""
        val = b"\x01ACME S.R.L." + b"\x01Via Roma 1, Milano"
        results = {}
        parse_company_holder_data(val, results)
        assert results["company_holders"] == [{
            "company_name": "ACME S.R.L.",
            "company_address": "Via Roma 1, Milano",
        }]
        assert results["metadata"]["heuristic_fields"]["company_holder_0x2020"] \
            == ["company_address", "company_name"]

    def test_raw_fallback_still_marked(self):
        results = {}
        parse_company_holder_data(b"just some free text here", results)
        assert results["metadata"]["heuristic_fields"]["company_holder_0x2020"] \
            == ["raw_text"]


# ── CARD-DATEF-VALIDITY (XA-F5) ────────────────────────────────────────────

class TestCardDatefValidity:
    def test_impossible_calendar_dates_rejected(self):
        # 31 February, 30 February, 31 April are all BCD-range-valid but unreal.
        assert decode_datef(_bcd_date(2025, 2, 31)) == "N/A"
        assert decode_datef(_bcd_date(2025, 2, 30)) == "N/A"
        assert decode_datef(_bcd_date(2025, 4, 31)) == "N/A"

    def test_valid_dates_accepted(self):
        assert decode_datef(_bcd_date(2024, 2, 29)) == "29/02/2024"  # leap year
        assert decode_datef(_bcd_date(2025, 6, 15)) == "15/06/2025"
        assert decode_datef(_bcd_date(2025, 1, 31)) == "31/01/2025"

    def test_out_of_range_still_not_a_date(self):
        assert decode_datef(_bcd_date(2025, 13, 1)) == "N/A"
        assert decode_datef(_bcd_date(2025, 0, 1)) == "N/A"
        assert decode_datef(_bcd_date(1899, 1, 1)) == "N/A"

    def test_decode_date_never_returns_impossible_string(self):
        # decode_date prefers the Datef interpretation but must not emit an
        # impossible calendar date even when the TimeReal bytes are nonsense.
        out = decode_date(_bcd_date(2025, 2, 31), prefer_datef=True)
        assert out == "N/A"


# ── CARD-NATION-CODE (A-F5) ────────────────────────────────────────────────

class TestCardNationCode:
    def test_nation_0x14_is_faroe_islands(self):
        assert get_nation(0x14) == "FO"
        assert nation_full_name(0x14) == "Faroe Islands"

    def test_france_keeps_its_own_code(self):
        assert get_nation(0x11) == "F"


# ── CARD-NATION-VALIDITY (XA-F6) ───────────────────────────────────────────

def _place_record(nation):
    """PlaceRecord base (10 B): entryTime(4)+entryType(1)+country(1)+region(1)+odo(3)."""
    return struct.pack(">I", _TS) + bytes([0x00, nation, 0x01]) + (123).to_bytes(3, "big")


def _places(nation):
    val = bytes([0]) + _place_record(nation)  # 1-byte pointer + one G1 record
    results = {"places": [], "metadata": {"generation": "G1"}}
    parse_g1_places(val, results)
    return results["places"]


class TestCardNationValidity:
    def test_undefined_nation_code_drops_the_record(self):
        assert _places(0x80) == []
        assert _places(0x36) == []

    def test_defined_country_codes_are_kept(self):
        assert [p["nation"] for p in _places(0x0D)] == ["D"]

    def test_defined_special_codes_are_kept(self):
        assert [p["nation"] for p in _places(0xFD)] == ["EC"]
        assert [p["nation"] for p in _places(0xFE)] == ["EUR"]
        assert [p["nation"] for p in _places(0xFF)] == ["WLD"]


# ── CARD-SPECIFIC-CONDITION (B-F5 / XA-F7) ─────────────────────────────────

class TestCardSpecificCondition:
    def test_label_helper_is_generation_aware(self):
        assert specific_condition_label(0x03, generation="G1") == "Ferry/Train crossing"
        assert specific_condition_label(0x03, generation="G2") == "Ferry/Train Begin"
        assert specific_condition_label(0x04, generation="G2") == "Ferry/Train End"

    def test_g1_type_03_is_a_single_crossing(self):
        result = _specific_conditions_card([0x03, 0x03])
        assert result["metadata"]["generation"] == "G1 (Digital)"
        assert [c["condition"] for c in result["specific_conditions"]] \
            == ["Ferry/Train crossing", "Ferry/Train crossing"]

    def test_g1_type_04_is_rfu_and_dropped(self):
        result = _specific_conditions_card([0x04, 0x04])
        assert result["metadata"]["generation"] == "G1 (Digital)"
        assert result["specific_conditions"] == []

    def test_g1_out_of_scope_labels_are_unchanged(self):
        result = _specific_conditions_card([0x01, 0x02])
        assert [c["condition"] for c in result["specific_conditions"]] \
            == ["OutOfScope Begin", "OutOfScope End"]

    def test_g2_keeps_begin_end_semantics(self):
        result = _specific_conditions_card([0x03, 0x04], g2=True)
        assert result["metadata"]["generation"] == "G2 (Smart)"
        assert [c["condition"] for c in result["specific_conditions"]] \
            == ["Ferry/Train Begin", "Ferry/Train End"]

    def test_g1_crossing_label_has_a_gui_display_name(self):
        # The GUI maps the raw ``condition`` string to a display name; the new
        # generation-1 label must not fall through to "Condition: …".
        pytest.importorskip("tkinter")
        from app.gui import _condition_label
        assert _condition_label("Ferry/Train crossing") == "Ferry / Train crossing"
