"""Unit tests for nation full-name expansion (core.decoders.common +
report_format table rendering)."""
from core.decoders.common import nation_full_name
from core.utils.report_format import records_to_table


def test_short_codes_expand_to_english_names():
    assert nation_full_name("I") == "Italy"
    assert nation_full_name("D") == "Germany"
    assert nation_full_name("F") == "France"
    assert nation_full_name("UK") == "United Kingdom"
    assert nation_full_name("MNE") == "Montenegro"


def test_numeric_code_expands():
    assert nation_full_name(0x1A) == "Italy"
    assert nation_full_name(0x0D) == "Germany"


def test_placeholders_and_unknown_pass_through():
    assert nation_full_name("") == ""
    assert nation_full_name(None) == ""
    assert nation_full_name("N/A") == "N/A"
    assert nation_full_name("No information available") == "No information available"
    assert nation_full_name("ZZ") == "ZZ"


def test_supranational_codes():
    assert nation_full_name("EC") == "European Community"
    assert nation_full_name("EUR") == "Europe"
    assert nation_full_name("WLD") == "World"


def test_records_table_expands_nation_columns():
    headers, rows = records_to_table([
        {"nation": "I", "plate": "AB123CD"},
        {"nation": "EC"},
        {"vehicle_nation": "D"},
    ])
    assert "Nation" in headers
    nation_idx = headers.index("Nation")
    assert rows[0][nation_idx] == "Italy"
    assert rows[1][nation_idx] == "European Community"
    vn_idx = headers.index("Vehicle Nation")
    assert rows[2][vn_idx] == "Germany"
