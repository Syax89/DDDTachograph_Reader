"""Codes a person can read, and signatures that say what they mean.

* EF_ICC (CardIccIdentification, Annex 1B/1C §2.23) is 25 octets: its
  embedderIcAssemblerId has 5 (countryCode 2 + moduleEmbedder 2 +
  manufacturerInformation 1), so icIdentifier sits at octets 23-24. Reading the
  embedder as 4 octets moved icIdentifier one octet early.
* Equipment types, code pages, nations under any key, position authentication
  and a bare manufacturer code read as words.
* A signature part reads as its verdict, what it signs, the algorithm and the
  signer, with the value itself behind the Bytes switch.
"""
import struct

import pytest

from app.gui import fmt_val
from app.gui_explorer_structure import StructureMixin, _hash_for, is_signature
from core.decoders.card_ef import _icc_fields
from core.structure import build_layout, signed_range

#: clockStop, extended serial (serial 0x001E7521, 08/21, driver card, 0xA5),
#: approval "e31003  ", personaliser 0xA5, embedder "IT" 41 35 32, icIdentifier B8 02
ICC = bytes.fromhex("00" "001e7521082101a5" "6533313030332020" "a5"
                    "4954413532" "b802")


def test_the_icc_identifier_follows_a_five_octet_embedder_id():
    assert len(ICC) == 25
    fields = _icc_fields(ICC)
    assert fields["embedder_ic_assembler_id"] == "4954413532"
    assert fields["ic_identifier"] == "0xB802"
    assert "historical_bytes" not in fields and "historical_info" not in fields


def test_icc_fields_in_words_keep_the_raw_values():
    fields = _icc_fields(ICC)
    assert fields["approval_number"] == "6533313030332020"
    assert fields["approval_number_label"] == "e31003"
    assert fields["personaliser_id"] == "0xA5"
    assert fields["personaliser_id_label"].startswith("STMicroelectronics")
    assert fields["extended_serial_number_label"].startswith("1996065 · 08/2021")
    assert fields["embedder_ic_assembler_id_label"] == "IT · 4135 · 0x32"


@pytest.mark.parametrize("value, key, shown", [
    (6, "equipment_type", "Vehicle unit"),
    (7, "equipment_type", "Motion sensor"),
    (1, "card_driver_end_card_type", "Driver card"),
    (1, "code_page", "ISO/IEC 8859-1"),
    (85, "registration_code_page", "KOI8-U"),
    (1, "authentication_status", "Authenticated"),
    ("I", "card_driver_nation", "Italy"),
    (2, "card_driver_end_generation", "Generation 2"),
    (6, "fault_purpose", None),
    (99, "equipment_type", "99"),
])
def test_codes_read_as_words(value, key, shown):
    text = fmt_val(value, key=key)
    if shown is None:
        assert not text.isdigit()
    else:
        assert text == shown


def test_a_bare_manufacturer_code_reads_as_its_registered_name():
    assert fmt_val(0xA1, key="manufacturer_code").endswith("(0xA1)")
    assert fmt_val(0x01, key="manufacturer_code") == "1"      # not registered


@pytest.mark.parametrize("curve, digest", [
    ("brainpoolP256r1", "SHA-256"), ("brainpoolP384r1", "SHA-384"),
    ("brainpoolP512r1", "SHA-512"), ("NIST P-256", "SHA-256"),
    ("NIST P-521", "SHA-512")])
def test_the_hash_follows_the_curve_size(curve, digest):
    assert _hash_for(curve) == digest


def _array(rt, records):
    return struct.pack(">BHH", rt, len(records[0]), len(records)) + b"".join(records)


def test_a_vu_signature_reads_in_words():
    section = (b"\x76\x32" + _array(0x06, [struct.pack(">I", 1_700_006_400)])
               + _array(0x08, [bytes(64)]))
    results = {"metadata": {"is_vu": True, "generation": "G2 (Smart)"},
               "signature_verification": {"msca_to_vu": True, "root_anchored": True,
                                          "treps": [{"trep": "0x32",
                                                     "signature_valid": True}]}}
    units = build_layout(section, results)
    sig = units[0].children[-1]
    assert is_signature(sig)
    assert signed_range(sig) == (2, 9)              # the date array, not the marker

    class View(StructureMixin):
        _opened_data = results
        _layout_units = units

    rows = dict((str(k), str(v)) for k, v in View()._signature_rows(sig))
    assert rows["Result"] == "Signature verified"
    assert "9 bytes" in rows["Signed data"]
    assert rows["Algorithm"].startswith("ECDSA") and "SHA-256" in rows["Algorithm"]
    assert rows["Signature"] == "64 bytes"
    assert rows["Certificate chain"].endswith("verified")
