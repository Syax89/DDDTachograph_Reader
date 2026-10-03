"""Batch 8 MEDIA / PARSER (G1+G2 VU structure/normative) regression tests.

One test class per confirmed family from ``FIX-PLAN.md`` batch 8:

* G1-VU-REGEX-UNREACHABLE (B-F6)         — documented empty-field regex recovery
* G1-VU-TRAILER (B-F1)                   — a stray trailing byte drops the last TREP
* G1-VU-TREP03-ALIGNMENT (B-F7/XB-F10)   — TREP03 heuristic off-by-one + no dedup
* G2-VU-CODEPAGE-AS-NATION (C-F1/XB-F1)  — recordType 0x0B fabricates a nation
* G2-VU-DAILY-RECONSTRUCTION (C-F4/XB-F8)— decoded daily activities dropped
* G22-VU-SPEED-TREP-NAME (C-F2)          — G2.2 DetailedSpeed is TREP 0x24, not 0x34

Normative sources: Reg. EU 2016/799 Annex 1C (consolidated 2023-08-21) /
Annex 1B for G1. Assertions are exact expected values (times, counters, names,
field presence), independent of production internals.
"""
import struct

from core.decoders.vu_g1 import (
    _parse_trep_03_events_faults_heuristic,
    parse_g1_vu_overview,
)
from core.parser.g1_walker import walk_g1_vu
from core.parser.record_array import parse_g2_trep02_activities
from core.parser.trep_inventory import trep_name
from core.parser.vu_dispatcher import _decode_record, _emit_section

_SIG = b"\xAA" * 128


# ── G1 VU stream helpers ─────────────────────────────────────────────────────

def _trep04_body():
    # VuDetailedSpeedData: noOfSpeedBlocks(2) = 0
    return struct.pack(">H", 0)


def _trep05_body():
    # VuIdentification(116) + SensorPaired(20) + noOfCalibrationRecords(1)=0
    b = bytearray(137)
    b[136] = 0
    return bytes(b)


def _complete_g1_stream():
    return (b"\x76\x04" + _trep04_body() + _SIG
            + b"\x76\x05" + _trep05_body() + _SIG)


# ── G2 daily-record helpers ──────────────────────────────────────────────────

def _g2_daily_record(counter, day_field, codes, sig_len=0x40):
    """A 112-byte G2 daily activity record (Annex 1C App.7, 0x7622 layout).

    codes are packed ActivityChangeInfo values placed in counters[3:].
    """
    r = bytearray(112)
    struct.pack_into(">H", r, 0, 0x7622)          # pseudo-tag (G2)
    r[2] = 0x01
    struct.pack_into(">H", r, 3, 60)
    struct.pack_into(">I", r, 5, counter)         # daily_counter
    r[9], r[10] = 0x76, 0x05
    struct.pack_into(">H", r, 11, 3)
    struct.pack_into(">H", r, 17, day_field)      # days since 1998-01-01
    r[19] = 0
    struct.pack_into(">H", r, 20, len(codes))     # changes_count
    for i, code in enumerate(codes):
        struct.pack_into(">H", r, 22 + (3 + i) * 2, code)
    r[45] = sig_len
    r[47] = 1
    return bytes(r)


def _g2_activities_body(records):
    # 8-byte 0xFF separator, then the daily records (no driver prefix).
    return b"\xFF" * 8 + b"".join(records)


# ── G1-VU-REGEX-UNREACHABLE (B-F6) ───────────────────────────────────────────

class TestG1VuRegexUnreachable:
    def _overview(self, plate):
        val = bytearray(700)
        val[0] = 0x30
        val[160:167] = b"AB123CD"          # plate-like token visible to the regex
        val[167:171] = b"    "             # regex needs >=3 trailing spaces
        val[388:405] = b"VALIDVIN000000001"  # 17 alphanumeric -> body validates
        val[405] = ord("I")
        val[406:420] = plate
        val[420:424] = struct.pack(">I", 1700000000)  # plausible TimeReal
        return bytes(val)

    def _results(self):
        return {
            "vehicle": {"vin": "N/A", "plate": "N/A", "registration_nation": "N/A"},
            "metadata": {},
            "vu_overview": {},
            "company_info": {"name": "ACME"},
            "card_numbers": ["I000000168598002"],
        }

    def test_validating_body_with_empty_plate_recovers_via_regex(self):
        """A body that validates but has an empty plate offset must trigger the
        documented empty-field recovery (and be flagged heuristic)."""
        results = self._results()
        parse_g1_vu_overview(self._overview(b"\x00" * 14), results)
        assert results["vehicle"]["plate"] == "AB123CD"
        assert results["metadata"]["heuristic_fields"]["vu_overview_TREP01"] == ["plate"]

    def test_fully_populated_validating_body_is_not_heuristic(self):
        """Control: when every fixed-offset field is present the regex must not
        run and nothing is flagged heuristic."""
        results = self._results()
        parse_g1_vu_overview(self._overview(b"XY12345" + b"\x00" * 7), results)
        assert results["vehicle"]["plate"] == "XY12345"
        assert results["vehicle"]["vin"] == "VALIDVIN000000001"
        assert results["metadata"].get("heuristic_fields") is None

    def test_company_name_recovered_when_fixed_parse_left_it_empty(self):
        results = self._results()
        results["company_info"] = {}
        body = bytearray(self._overview(b"XY12345" + b"\x00" * 7))
        body[200:232] = b"TRANSPORTI S.R.L.               "  # >=5 chars + 2 spaces
        parse_g1_vu_overview(bytes(body), results)
        assert results["company_info"]["name"].startswith("TRANSPORTI")
        assert "company_name" in results["metadata"]["heuristic_fields"]["vu_overview_TREP01"]


# ── G1-VU-TRAILER (B-F1) ─────────────────────────────────────────────────────

class TestG1VuTrailer:
    def test_trailing_byte_keeps_last_message_and_stays_complete(self):
        """A single trailing byte after the last RSA signature must not discard
        the last TREP block nor report the download as partial."""
        stream = _complete_g1_stream()
        for trailer in (b"\x00", b"\x76", b"\x00\x00"):
            messages, complete = walk_g1_vu(stream + trailer, {})
            assert [m["trep"] for m in messages] == [0x04, 0x05], trailer
            assert complete is True, trailer

    def test_clean_stream_is_complete(self):
        messages, complete = walk_g1_vu(_complete_g1_stream(), {})
        assert [m["trep"] for m in messages] == [0x04, 0x05]
        assert complete is True

    def test_real_marker_after_trailer_still_reports_incomplete(self):
        """Control: if a genuine TREP marker follows the stray byte, the walk
        must not claim completeness (the mismatch is a real boundary error)."""
        stream = _complete_g1_stream() + b"\x00" + b"\x76\x05" + _trep05_body() + _SIG
        messages, complete = walk_g1_vu(stream, {})
        assert complete is False
        assert 0x04 in [m["trep"] for m in messages]


# ── G1-VU-TREP03-ALIGNMENT (B-F7 / XB-F10) ───────────────────────────────────

class TestG1VuTrep03Alignment:
    def _body(self):
        fault = bytearray(82)
        fault[0] = 0x05
        fault[1] = 0x01
        struct.pack_into(">I", fault, 2, 1600000000)
        struct.pack_into(">I", fault, 6, 1600000100)
        event = bytearray(83)
        event[0] = 0x02
        event[1] = 0x01
        struct.pack_into(">I", event, 2, 1600000500)
        struct.pack_into(">I", event, 6, 1600000550)
        # [n_faults=1 @0][fault 82B @1..82][n_events=1 @83][event 83B @84..166]
        return bytes([1]) + bytes(fault) + bytes([1]) + bytes(event) + b"\x00" * 16

    def test_heuristic_alignment_reads_the_real_first_record(self):
        """Attempt-1 must start at offset 1 (after the fault count), not 2."""
        results = {}
        _parse_trep_03_events_faults_heuristic(self._body(), results)
        faults = results.get("faults", [])
        assert [f["fault_type"] for f in faults] == [0x05]
        assert faults[0]["begin_time"] == "2020-09-13T12:26:40+00:00"
        # The 1-byte-shifted phantom fault must be gone.
        assert "2020-01-04T03:02:55+00:00" not in [f["begin_time"] for f in faults]

    def test_heuristic_rerun_does_not_duplicate_records(self):
        results = {}
        _parse_trep_03_events_faults_heuristic(self._body(), results)
        before = (len(results.get("faults", [])), len(results.get("events", [])))
        _parse_trep_03_events_faults_heuristic(self._body(), results)
        after = (len(results.get("faults", [])), len(results.get("events", [])))
        assert before == after == (1, 0)


# ── G2-VU-CODEPAGE-AS-NATION (C-F1 / XB-F1) ──────────────────────────────────

class TestG2VuCodepageAsNation:
    def test_vehicle_registration_number_has_no_nation(self):
        """Annex 1C Table 42: 0x0B is CodePage(1) + VRN(13) — there is no nation."""
        rec = bytes([0x01]) + b"AB123CD" + b"\x00" * 6  # 14 bytes
        out = _decode_record(0x0B, rec)
        assert "nation" not in out
        assert out["code_page"] == 0x01
        assert out["plate"] == "AB123CD"

    def test_emit_section_does_not_source_nation_from_0x0b(self):
        record = _decode_record(0x0B, bytes([0x02]) + b"XY98765" + b"\x00" * 6)
        results = {"vehicle": {"vin": "N/A", "plate": "N/A", "registration_nation": "N/A"}}
        _emit_section({"name": "Overview", "records": {0x0B: [record]}}, results)
        assert results["vehicle"]["registration_nation"] == "N/A"
        assert results["vehicle"]["plate"] == "XY98765"

    def test_xb_f1_standard_codepage_yields_no_spurious_nation(self):
        """The real-file code page 0x01 must not surface as "A" (Austria)."""
        out = _decode_record(0x0B, bytes([0x01]) + b"FW847FB" + b"\x00" * 6)
        assert out.get("nation") != "A"
        assert "nation" not in out


# ── G2-VU-DAILY-RECONSTRUCTION (C-F4 / XB-F8) ────────────────────────────────

class TestG2VuDailyReconstruction:
    def test_decoded_daily_activities_are_emitted(self):
        body = _g2_activities_body([
            _g2_daily_record(5, 100, [0x1000, 0x1001]),
            _g2_daily_record(6, 101, [0x1100]),
        ])
        results = {}
        parse_g2_trep02_activities(body, results)
        activities = results["activities"]
        assert [a["date"] for a in activities] == ["12/04/1998", "11/04/1998"]
        assert all(a["source"] == "vu_trep02" for a in activities)
        assert activities[0]["changes_count"] == 1
        assert activities[1]["changes_count"] == 2
        assert activities[0]["changes"][0]["activity"] == "WORK"

    def test_bogus_zero_signature_length_does_not_drop_days(self):
        """A record whose sig_len byte is 0x00 must not mis-size the record and
        swallow every following day."""
        body = _g2_activities_body([
            _g2_daily_record(5, 100, [0x1000], sig_len=0x00),
            _g2_daily_record(6, 101, [0x1100], sig_len=0x40),
        ])
        results = {}
        parse_g2_trep02_activities(body, results)
        assert [d["daily_counter"] for d in results["signed_daily_records"]] == [5, 6]
        assert [a["date"] for a in results["activities"]] == ["12/04/1998", "11/04/1998"]

    def test_non_monotonic_counter_does_not_discard_later_days(self):
        body = _g2_activities_body([
            _g2_daily_record(5, 100, [0x1000]),
            _g2_daily_record(4, 101, [0x1100]),  # out of order -> resync
            _g2_daily_record(6, 102, [0x1200]),
        ])
        results = {}
        parse_g2_trep02_activities(body, results)
        assert [d["daily_counter"] for d in results["signed_daily_records"]] == [5, 6]


# ── G22-VU-SPEED-TREP-NAME (C-F2) ────────────────────────────────────────────

class TestG22VuSpeedTrepName:
    def test_g22_detailed_speed_is_trep_0x24(self):
        # Annex 1C App.7 §2.2.6.5 DDP_032: "the TREP 04 or 24 Hex".
        assert trep_name("G2.2 (Smart V2)", 0x24) == "DetailedSpeed"

    def test_g22_has_no_phantom_trep_0x34(self):
        assert trep_name("G2.2 (Smart V2)", 0x34) == "TREP_0x34"

    def test_g1_and_g2_detailed_speed_unchanged(self):
        assert trep_name("G1 (Digital)", 0x04) == "DetailedSpeed"
        assert trep_name("G2 (Smart)", 0x24) == "DetailedSpeed"
