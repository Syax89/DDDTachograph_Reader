"""Gen2 / Gen2.2 Overview (TREP 21 / 31) publication and TREP 00.

Two confirmed omissions this file pins down:

* **TREP 00 (DDP_028a, generation 2 version 2 only)** carries the two transfer
  bytes of ``DownloadInterfaceVersion`` (Annex 1C §2.60a, inserted by Reg. (EU)
  2021/1228). The section iterator had no handler, so the bytes were treated as
  resynchronisation junk and never published. One real local G2.2 download ends
  with exactly ``76 00 01 01`` — the values of §2.60a's ``'aa'``/``'bb'``
  assignments, which contradicts the *comment* column of DDP_028a ("02,02 Hex").
  Both readings are recorded; neither is invented.
* **Overview records decoded but lost**: ``CurrentDateTime`` (0x03) and
  ``CardSlotsStatus`` (0x02) were decoded per record and then dropped by
  ``_emit_section``. ``CardSlotsStatus`` is two card-type nibbles ('ccccdddd'B),
  so publishing the raw octet is not a decoded slot state.

Every value below is synthetic.
"""
import struct

from app import gui
from core.parser import vu_dispatcher
from core.parser.vu_dispatcher import iter_vu_sections, walk_vu_record_arrays
from core.utils import report_format
from tests.unit import vu_synthetic as S


def _results():
    return {"metadata": {}, "vehicle": {"vin": "N/A", "plate": "N/A",
                                        "registration_nation": "N/A"}}


def _overview_stream(slots=S.SLOTS_DRIVER_AND_COMPANY):
    """A synthetic 76 31 Overview in the order Appendix 7 prescribes."""
    return S.section(
        0x31,
        S.record_array(0x24, 15, [bytes([0x1A]) + S.coded_string(
            S.PLATE.encode("latin-1").decode("latin-1"), code_page=1, length=14)]),
        S.record_array(0x0A, 17, [S.VIN.encode("ascii")]),
        S.record_array(0x02, 1, [bytes([slots])]),
        S.record_array(0x03, 4, [struct.pack(">I", S.BASE_TIME)]),
        S.record_array(0x13, 8, [struct.pack(">II", S.BASE_TIME - 86400,
                                            S.BASE_TIME + 86400)]),
        S.signature_record(),
    )


# ── TREP 00: DownloadInterfaceVersion ────────────────────────────────────────

def test_interface_version_section_is_recognised_and_consumed():
    """``76 00`` opens a two-byte section; it must not fall into resync."""
    stream = S.interface_version(0x01, 0x01) + _overview_stream()
    state = {}
    sections = list(iter_vu_sections(stream, state))

    assert [s["trep"] for s in sections] == [0x00, 0x31]
    # counted as a section of the download (corpus effect: one G2.2 file goes
    # from 35 to 36 sections, because the interface transfer is a real TREP)
    results = _results()
    walk_vu_record_arrays(stream, results)
    assert len(results["vu_record_arrays"]) == 2
    assert sections[0]["interface"] == b"\x01\x01"
    assert state["truncated"] is False


def test_interface_version_is_published_as_raw_with_source_conflict():
    results = _results()
    walk_vu_record_arrays(S.interface_version(0x01, 0x01) + _overview_stream(),
                          results)

    published = results["metadata"]["download_interface_version"]
    assert published["raw"] == "0101"
    # Annex 1C §2.60a: 'aa' 01 = generation 2 VU, 'bb' 01 = version 2 of gen 2.
    assert published["generation_code"] == 0x01
    assert published["version_code"] == 0x01
    assert published["generation_status"] == "Generation 2 vehicle unit"
    assert published["version_status"] == "version 2 of the Generation 2 vehicle unit"
    # DDP_028a's comment says "02,02 Hex" instead: the conflict is recorded,
    # never silently resolved in favour of one of the two sources.
    assert published["source_conflict"] is True
    assert published["status"] == "raw (DDP_028a comment vs Annex 1C §2.60a)"


def test_without_a_interface_section_nothing_is_invented():
    results = _results()
    walk_vu_record_arrays(_overview_stream(), results)
    assert "download_interface_version" not in results["metadata"]


# ── Overview publication ─────────────────────────────────────────────────────

def test_overview_publishes_current_datetime():
    results = _results()
    walk_vu_record_arrays(_overview_stream(), results)
    assert results["metadata"]["current_datetime"] == (
        vu_dispatcher._iso(S.BASE_TIME))


def test_overview_publishes_typed_card_slots_per_nibble():
    results = _results()
    walk_vu_record_arrays(_overview_stream(), results)

    slots = results["vu_overview"]["card_slot_status"]
    assert slots["raw"] == "0x41"
    # 'ccccdddd'B: low nibble is the driver slot, high nibble the co-driver one.
    # Same vocabulary the generation-1 panel publishes (§2.28).
    assert slots["driver_slot"] == "occupied"
    assert slots["codriver_slot"] == "occupied"
    assert slots["driver_slot_card_type"] == "driver"
    assert slots["codriver_slot_card_type"] == "company"
    # Complete typing is model-only: the nibble code and its label travel in the
    # JSON, not in a new visible column.
    assert slots["driver_slot_code"] == 0x01
    assert slots["codriver_slot_code"] == 0x04
    assert slots["driver_slot_status"] == "assigned"
    assert slots["codriver_slot_status"] == "assigned"


def test_overview_slot_nibbles_report_unassigned_and_empty():
    results = _results()
    walk_vu_record_arrays(_overview_stream(slots=0xF0), results)
    slots = results["vu_overview"]["card_slot_status"]
    assert slots["driver_slot"] == "empty"
    assert slots["codriver_slot"] == "reserved"
    assert slots["codriver_slot_status"] == "unassigned"
    assert slots["driver_slot_status"] == "assigned"

    results = _results()
    walk_vu_record_arrays(_overview_stream(slots=0x00), results)
    slots = results["vu_overview"]["card_slot_status"]
    assert slots["driver_slot"] == "empty"
    assert slots["driver_slot_code"] == 0x00


def test_overview_registration_keeps_the_declared_code_page():
    """A VRN is codePage + 13 characters: accented letters are legal."""
    results = _results()
    stream = S.section(
        0x31,
        S.record_array(0x0B, 14, [S.coded_string("T\u00c9\u00c8ST1234", code_page=1,
                                                length=14)]),
        S.record_array(0x0A, 17, [S.VIN.encode("ascii")]),
        S.signature_record(),
    )
    walk_vu_record_arrays(stream, results)
    assert results["vehicle"]["plate"] == "T\u00c9\u00c8ST1234"


def test_overview_model_only_slot_keys_are_hidden():
    for key in ("driver_slot_code", "codriver_slot_code",
                "driver_slot_status", "codriver_slot_status"):
        assert key in report_format.HIDDEN_KEYS
        assert key in gui.HIDDEN_KEYS
