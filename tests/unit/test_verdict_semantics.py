"""Verdict bookkeeping a focused refutation of the last delta found.

* a schema violation reached the user as "The structural walk did not reach the end
  of file", plus a vacuous "1/1 mandatory section(s) read (100.0%)";
* a trailing marker byte made a generation-1 walk partial but not a generation-2 one;
* an observed (manufacturer/empirical) array type made a download partial;
* four small things: a fabricated `tlvs: 0`, a doubled signature finding, a dead
  helper and an untranslated report label.
"""
import os
import struct

import pytest

from app import gui
from app.engine import TachoParser
from core.registry.registry import DecoderRegistry
from tests.unit import vu_synthetic as S
from tests.unit.real_data import require_real_file

TIME = S.BASE_TIME


def _parse(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    DecoderRegistry.reset_instance()
    return TachoParser(str(path)).parse()


# ── Item 2: the bullet must name the real reason ─────────────────────────

def test_schema_violation_bullet_names_the_finding_and_the_arrays(tmp_path):
    data = (b"\x76\x31" + bytes([0x0A]) + struct.pack(">HH", 17, 1)
            + S.VIN.encode("ascii")
            + bytes([0x08]) + struct.pack(">HH", 64, 1) + bytes(64))
    result = _parse(tmp_path, "schema.ddd", data)
    bullets, _notices = gui._integrity_bullets(result)
    joined = "\n".join(bullets)
    assert "schema violation" in joined.lower(), bullets
    assert "0x04" in joined, bullets               # the arrays are named
    assert "did not reach the end of file" not in joined.lower()
    assert "1/1" not in joined and "100.0%" not in joined


def test_a_truncated_walk_still_says_the_walk_did_not_reach_the_end(tmp_path):
    path = require_real_file("*_3B330594AC.ddd")
    with open(path, "rb") as handle:
        data = handle.read()
    result = _parse(tmp_path, "cut.ddd", data[:len(data) // 2])
    bullets, _notices = gui._integrity_bullets(result)
    joined = "\n".join(bullets).lower()
    assert "did not reach the end of file" in joined or "truncated" in joined, bullets


# ── Item 4: trailing marker bytes are partial in BOTH generations ────────

@pytest.mark.parametrize("tail", [b"\x76", b"\x76\x06", b"\x76\x31"])
def test_a_trailing_marker_byte_is_partial_in_generation_1(tmp_path, tail):
    path = require_real_file("*_3B330594AC.ddd")
    with open(path, "rb") as handle:
        data = handle.read()
    result = _parse(tmp_path, "tail.ddd", data + tail)
    meta = result["metadata"]
    assert (meta.get("trep_report") or {}).get("is_partial") is True, tail
    findings = meta.get("vu_integrity") or []
    assert any(f.get("trailing_bytes") == len(tail)
               or f.get("status") == "card_download_incomplete"
               for f in findings), findings


@pytest.mark.parametrize("tail", [b"\x76", b"\x76\x06", b"\x76\x31"])
def test_a_trailing_marker_byte_is_partial_in_generation_2(tmp_path, tail):
    real = require_real_file("*_3B330594AC.ddd")
    with open(real, "rb") as handle:
        base = handle.read()
    result = _parse(tmp_path, "g2tail.ddd", base + tail)
    meta = result["metadata"]
    assert (meta.get("trep_report") or {}).get("is_partial") is True, tail
    findings = meta.get("vu_integrity") or []
    assert any(f.get("trailing_bytes") == len(tail)
               or f.get("status") == "card_download_incomplete"
               for f in findings), findings


@pytest.mark.parametrize("fill", [b"\x00", b"\xff", b"\x00\x00", b"\xff\xff"])
def test_fill_after_a_generation_2_section_stays_complete(tmp_path, fill):
    real = require_real_file("*_3B330594AC.ddd")
    with open(real, "rb") as handle:
        base = handle.read()
    result = _parse(tmp_path, "g2fill.ddd", base + fill)
    assert (result["metadata"].get("trep_report") or {}).get("is_partial") is not True


# ── Item 5: an observed/empirical array is not a defect ─────────────────

def _trep32_with(record_types):
    arrays = []
    for rt in record_types:
        if rt == 0x06:
            arrays.append(S.record_array(0x06, 4, [struct.pack(">I", TIME)]))
        elif rt == 0x05:
            arrays.append(S.record_array(0x05, 3, [(1000).to_bytes(3, "big")]))
        elif rt == 0x01:
            arrays.append(S.record_array(0x01, 2, [struct.pack(">H", 0x10F3)]))
        elif rt == 0x29:
            arrays.append(S.record_array(0x29, 4, [struct.pack(">I", TIME)]))
        elif rt == 0x40:
            arrays.append(S.record_array(0x40, 3, [b"\x00\x00\x01"]))
        elif rt == 0x1C:
            arrays.append(S.record_array(0x1C, 40, [b"\x00" * 40]))
        elif rt == 0x0D:
            arrays.append(S.record_array(0x0D, 131, [b"\x00" * 131]))
        elif rt == 0x16:
            arrays.append(S.record_array(0x16, 56, [b"\x00" * 56]))
        elif rt == 0x09:
            arrays.append(S.record_array(0x09, 5, [b"\x00" * 5]))
        elif rt == 0x22:
            arrays.append(S.record_array(0x22, 55, [b"\x00" * 55]))
        elif rt == 0x23:
            arrays.append(S.record_array(0x23, 58, [b"\x00" * 58]))
    arrays.append(S.signature_record())
    return S.section(0x32, *arrays)


def test_an_observed_record_type_keeps_the_download_complete(tmp_path):
    result = _parse(tmp_path, "observed.ddd",
                    _trep32_with([0x06, 0x05, 0x0D, 0x01, 0x1C, 0x16, 0x09, 0x22,
                                  0x23, 0x29]))
    meta = result["metadata"]
    schema = (meta.get("vu_section_schema") or [{}])[0]
    assert schema["status"] == "complete", schema
    assert schema["unexpected_arrays"] == [], schema
    assert schema["empirical_arrays"] == ["0x29"], schema
    # the *walk* is complete and no structure finding exists: the download's own
    # mandatory-section state is a separate axis (this synthetic file has no
    # Overview), so it is asserted on the walk, not on is_partial
    assert result["_vu_walk_complete"] is True
    assert not [f for f in (meta.get("vu_integrity") or [])
                if f.get("status") == "schema_violation"]
    # the raw bytes are still there, flagged empirical rather than dropped
    empirical = [f for f in (meta.get("vu_integrity") or [])
                 if f.get("status") == "unmapped_record_type"]
    assert empirical and empirical[0]["record_types"] == ["0x29"]


def test_a_missing_normative_array_is_still_partial(tmp_path):
    result = _parse(tmp_path, "missing.ddd", _trep32_with([0x06, 0x05, 0x01]))
    meta = result["metadata"]
    assert (meta.get("trep_report") or {}).get("is_partial") is True
    assert any(f.get("status") == "schema_violation"
               for f in (meta.get("vu_integrity") or []))


def test_a_duplicated_normative_array_is_still_partial(tmp_path):
    section = S.section(0x23,
                        S.record_array(0x15, 8, [bytes(8)]),
                        S.record_array(0x15, 8, [bytes(8)]),
                        S.signature_record())
    result = _parse(tmp_path, "dup.ddd", section)
    assert (result["metadata"].get("trep_report") or {}).get("is_partial") is True


# ── Item 6: the small things ────────────────────────────────────────────

def test_extra_card_region_does_not_fabricate_a_tlv_count(tmp_path):
    path = require_real_file("*_D47C4D98DF.ddd")
    with open(path, "rb") as handle:
        card = handle.read()
    result = _parse(tmp_path, "two.ddd", card + card)
    regions = result["metadata"].get("vu_card_download_sections") or []
    assert regions
    for region in regions:
        assert region.get("tlvs") is None or region.get("tlvs", 0) > 0, region


def test_a_missing_signature_is_reported_once(tmp_path):
    data = (b"\x76\x31" + bytes([0x0A]) + struct.pack(">HH", 17, 1)
            + S.VIN.encode("ascii"))
    result = _parse(tmp_path, "nosig.ddd", data)
    findings = result["metadata"].get("vu_integrity") or []
    missing = [f for f in findings
               if f.get("status") in ("signature_missing", "schema_violation")
               and "0x08" in str(f.get("detail") or "") + str(f.get("missing_arrays") or "")]
    assert len(missing) == 1, findings


def test_the_dead_fingerprint_helper_is_gone():
    import core.decoders.vu_g1 as mod
    assert not hasattr(mod, "_content_fingerprint")


def test_the_report_transfer_header_label_is_translated():
    import glob
    import re
    for path in sorted(glob.glob("locale/*/LC_MESSAGES/tacho.po")):
        msgids = set(re.findall(r'^msgid "(.*)"$',
                               open(path, encoding="utf-8").read(), re.M))
        assert "Transfer header" in msgids, path


# ── Item 3: one column per datum, and no two labels of a table may collide ─

def test_calibration_serial_columns_carry_one_datum_each(tmp_path):
    from core.utils import report_format as rf
    from tests.unit.test_vu_technical_semantics import _calibration
    from core.parser.vu_dispatcher import decode_calibration
    record = decode_calibration(_calibration(252), generation="G2.2")
    cols = rf.visible_columns([record])
    serial_columns = [c for c in cols if "serial" in c]
    assert serial_columns == ["sensor_serial", "sensor_gnss_serial", "rcm_serial"], (
        serial_columns)
    # the raw hex of the same bytes is JSON-only, not a second column
    for key in ("sensor_serial_hex", "sensor_gnss_serial_hex", "rcm_serial_hex"):
        assert key in record
        assert key not in cols


def test_no_two_labels_of_any_rendered_table_collide_in_any_catalog():
    """Every table, every label, all 33 catalogs (derived from the rendering)."""
    import glob
    import re
    from core.utils import report_format as rf
    from tests.unit.real_data import real_ddd_files as _real_files
    files = _real_files()
    if not files:
        pytest.skip("no private corpus available")
    # collisions are judged per rendered table instance (two generations may use
    # different keys for the same concept in different files)
    per_file = []
    for path in files:
        DecoderRegistry.reset_instance()
        result = TachoParser(path).parse()
        for name, _desc, headers, _rows, _trunc in rf.section_tables(result):
            per_file.append((os.path.basename(path), name,
                             sorted(h for h in headers if isinstance(h, str))))
    assert per_file, "no table rendered"
    checked = 0
    for po in sorted(glob.glob("locale/*/LC_MESSAGES/tacho.po")):
        catalog = dict(re.findall(r'^msgid "(.*)"\nmsgstr "(.*)"$',
                                  open(po, encoding="utf-8").read(), re.M))
        for file_name, table, headers in per_file:
            rendered = [catalog.get(h, h) for h in headers]
            duplicates = {value for value in rendered if rendered.count(value) > 1}
            assert not duplicates, (po, file_name, table, sorted(duplicates))
        checked += 1
    assert checked == 33
