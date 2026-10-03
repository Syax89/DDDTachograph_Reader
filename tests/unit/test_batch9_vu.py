"""Batch 9 MEDIA / PARSER (VU structure/normative) regression tests.

One test class per confirmed family from ``FIX-PLAN.md`` batch 9:

* VU-GHOST-CONTAINER          (XD-F1)     — phantom 0x76xx container rejected
* VU-GNSS-ERASURE             (XB-F5)     — half-erased GNSS is not a fix
* VU-PHANTOM-RECORDS          (XB-F7)     — tag-keyed array expansion is capped
* VU-RFU-029                  (XB-F6/D2-006) — 0x29 co-driver activity surfaced
* VU-SELECTIVE-DOWNLOAD       (C-F3/D2-004)  — only Overview is mandatory
* VU-TREP02-HEURISTIC-BOUNDARY(XB-F9)     — each day labelled with its own time

Normative source: Reg. EU 2016/799 Annex 1C (consolidated 2023-08-21), App.7
(TRTP / DDP_054), Annex 1B App.7 for Gen1. Assertions use exact values / keys
and are independent of production internals.
"""
import struct

from core.decoders.vu_g1 import _parse_trep_02_activities
from core.decoders.vu_g2 import parse_g2_vu_record
from core.parser.deterministic import DeterministicParser
from core.parser.trep_inventory import MANDATORY_TREPS, build_trep_report
from core.parser.vu_dispatcher import (
    VU_RECORD_RESULT_KEYS,
    _decode_record,
    decode_geo_coordinates,
    walk_vu_record_arrays,
)
from core.registry.registry import DecoderRegistry
from core.utils.constants import RECORD_ARRAY_MAX_RECORDS


# ── shared helpers ───────────────────────────────────────────────────────────

def _array(rt, record_size, records):
    return (bytes([rt]) + struct.pack(">H", record_size)
            + struct.pack(">H", len(records)) + b"".join(records))


def _wrap_container(cluster_tag, inner):
    """A synthetic ``0x76xx`` container: payload[0:2] == 00 00 then inner TLV."""
    payload = b"\x00\x00" + inner
    return cluster_tag + b"\x00" + struct.pack(">H", len(payload)) + payload


def _control_activity_record():
    rec = bytearray(46)
    rec[0] = 0x01
    struct.pack_into(">I", rec, 1, 1600000000)
    rec[5], rec[6] = 0x01, 0x0A
    rec[7:13] = b"ABC123"
    rec[23] = 0x0D
    rec[24:30] = b"XY9999"
    struct.pack_into(">I", rec, 38, 1600000000)
    struct.pack_into(">I", rec, 42, 1600000000)
    return bytes(rec)


def _stopped_control_inner():
    # STAP inner record 0x0508 (ControlActivityData) wrapping the 46-byte body.
    return b"\x05\x08" + b"\x00" + struct.pack(">H", 46) + _control_activity_record()


# ── VU-GHOST-CONTAINER (XD-F1) ───────────────────────────────────────────────

class TestVuGhostContainer:
    def test_unregistered_76xx_tag_is_not_a_container(self):
        reg = DecoderRegistry.instance()
        assert reg.is_container(0x76AA, generation="G1", is_vu=False) is False
        assert reg.is_container(0x7607, generation="G1", is_vu=False) is False

    def test_registered_and_marked_vu_containers_still_container(self):
        reg = DecoderRegistry.instance()
        assert reg.is_container(0x7601, generation="G1", is_vu=True) is True
        assert reg.is_container(0x7621, generation="G2", is_vu=True) is True
        assert reg.is_container(0x7625, generation="G2", is_vu=True) is True
        assert reg.is_container(0x7635, generation="G2.2", is_vu=True) is True

    def test_ghost_record_inside_unregistered_container_is_dropped(self):
        """A 0x0508 smuggled inside a phantom 0x76AA container must not be
        published as a roadside control-activity record."""
        data = _wrap_container(b"\x76\xAA", _stopped_control_inner())
        results = DeterministicParser().parse(data, is_vu=False)
        assert results.get("control_activities", []) == []

    def test_registered_container_is_still_walked(self):
        """Negative control: the same payload inside a legitimate 0x7601 VU
        container IS walked, so the fix targets only unregistered markers."""
        data = _wrap_container(b"\x76\x01", _stopped_control_inner())
        results = DeterministicParser().parse(data, is_vu=False)
        assert [r["control_card"] for r in results.get("control_activities", [])] == ["CHABC123"]


# ── VU-GNSS-ERASURE (XB-F5) ──────────────────────────────────────────────────

class TestVuGnssErasure:
    def test_half_erased_coordinates_are_not_a_fix(self):
        assert decode_geo_coordinates(b"\x00\x00\x00\xff\xff\xff", 0) == {"fix": False}
        assert decode_geo_coordinates(b"\xff\xff\xff\x00\x00\x00", 0) == {"fix": False}

    def test_all_zero_record_is_not_null_island(self):
        assert decode_geo_coordinates(b"\x00\x00\x00\x00\x00\x00", 0) == {"fix": False}

    def test_unknown_sentinel_per_coordinate_is_not_a_fix(self):
        assert decode_geo_coordinates(b"\x7f\xff\xff\x00\x00\x00", 0) == {"fix": False}
        assert decode_geo_coordinates(b"\xff\xff\xff\xff\xff\xff", 0) == {"fix": False}

    def test_real_coordinate_still_decodes(self):
        # DDMM.M x10: latitude 45 deg 30.4' -> 45304, longitude 11 deg 30.4' -> 11304.
        lat = struct.pack(">i", 45304)[1:4]
        lon = struct.pack(">i", 11304)[1:4]
        out = decode_geo_coordinates(lat + lon, 0)
        assert out["fix"] is True
        assert out["latitude_deg"] == 45.50667
        assert out["longitude_deg"] == 11.50667


# ── VU-PHANTOM-RECORDS (XB-F7) ───────────────────────────────────────────────

class TestVuPhantomRecords:
    def test_corrupt_tag_keyed_array_is_capped(self):
        # rt=0x0E rs=1, noOfRecords=65535 but only 65535 payload bytes available.
        payload = bytes([0x0E, 0x00, 0x01, 0xFF, 0xFF]) + b"\x41" * 65535
        results = {}
        parse_g2_vu_record(payload, results, 0x0509)
        assert len(results["card_records"]) == RECORD_ARRAY_MAX_RECORDS

    def test_small_tag_keyed_array_is_unchanged(self):
        payload = _array(0x0E, 1, [b"\x41", b"\x42", b"\x43"])
        results = {}
        parse_g2_vu_record(payload, results, 0x0509)
        assert len(results["card_records"]) == 3

    def test_cap_matches_the_stream_path(self):
        assert RECORD_ARRAY_MAX_RECORDS == 20000


# ── VU-RFU-029 (XB-F6 / D2-006) ──────────────────────────────────────────────

class TestVuRfu029:
    def _activities_stream(self, rt_records):
        ts = struct.pack(">I", 1600000000)
        body = _array(0x06, 4, [ts]) + _array(0x05, 3, [b"\x00\x27\x10"])
        for rt, recs in rt_records:
            body += _array(rt, 2, recs)
        return b"\x76\x32" + body

    def test_codriver_activity_is_emitted_to_a_result_list(self):
        data = self._activities_stream([(0x01, [struct.pack(">H", 0x0800)]),
                                        (0x29, [struct.pack(">H", 0x1000)])])
        results = {}
        walk_vu_record_arrays(data, results)
        slot2 = results.get("co_driver_activities", [])
        assert [r["record_type"] for r in slot2] == ["0x29"]
        assert slot2[0]["activity"]["activity"] == "WORK"

    def test_codriver_activity_reaches_daily_activities(self):
        data = self._activities_stream([(0x29, [struct.pack(">H", 0x1000)])])
        results = {}
        walk_vu_record_arrays(data, results)
        assert "co_driver_activities" in results
        day = results["activities"][0]
        assert [c["activity"] for c in day["changes"]] == ["WORK"]

    def test_result_key_is_registered(self):
        assert VU_RECORD_RESULT_KEYS[0x29] == "co_driver_activities"

    def test_decoder_still_names_the_record(self):
        out = _decode_record(0x29, struct.pack(">H", 0x1000))
        assert out["record_type"] == "0x29"
        assert out["activity"]["activity"] == "WORK"


# ── VU-SELECTIVE-DOWNLOAD (C-F3 / D2-004) ────────────────────────────────────

class TestVuSelectiveDownload:
    def test_only_overview_is_mandatory(self):
        assert MANDATORY_TREPS == {"G1": {0x01}, "G2": {0x21}, "G2.2": {0x31}}

    def test_overview_only_download_is_complete(self):
        report = build_trep_report("G1 (Digital)", [0x01])
        assert report["is_partial"] is False
        assert report["completeness_pct"] == 100.0
        assert report["mandatory_missing"] == []

    def test_sensor_only_selective_download_is_not_partial(self):
        # The real-corpus row that used to be mislabelled "partial".
        report = build_trep_report("G1 (Digital)", [0x01, 0x11, 0x14])
        assert report["is_partial"] is False
        assert report["mandatory_total"] == 1
        assert report["mandatory_ok"] == 1

    def test_missing_overview_is_partial(self):
        report = build_trep_report("G1 (Digital)", [0x02, 0x03, 0x05])
        assert report["is_partial"] is True
        assert [t["name"] for t in report["mandatory_missing"]] == ["Overview"]

    def test_full_download_is_complete(self):
        report = build_trep_report("G2 (Smart)", [0x21, 0x22, 0x23, 0x25])
        assert report["is_partial"] is False
        assert report["mandatory_total"] == 1


# ── VU-TREP02-HEURISTIC-BOUNDARY (XB-F9) ─────────────────────────────────────

def _daily_block(ts, n_changes):
    b = struct.pack(">I", ts) + b"\x00\x27\x10" + b"\x01" + struct.pack(">H", n_changes)
    for i in range(n_changes):
        b += struct.pack(">H", (i + 1) * 60) + struct.pack(">H", 3)  # minute, activity=drive
    return b + b"\x00\x00\x00\x00"                                   # terminator


def _heuristic_body(blocks):
    hdr = struct.pack(">I", 1600000000) + b"\x00" * 6
    name = b"\x01SMITH" + b" " * 30 + b"\x01JOHN" + b" " * 31
    body = bytearray(hdr + name + b"\x00" * 30)
    for blk in blocks:
        body += b"\x00" * 20 + blk
    return bytes(body + b"\x00" * 20)


class TestVuTrep02HeuristicBoundary:
    def test_each_day_is_labelled_with_its_own_timestamp(self):
        body = _heuristic_body([_daily_block(1600000000, 2), _daily_block(1600100000, 3)])
        results = {}
        _parse_trep_02_activities(body, results)
        days = results.get("activities", [])
        assert [d["date"] for d in days] == ["13/09/2020", "14/09/2020"]
        assert [d["timestamp"] for d in days] == [
            "2020-09-13T12:26:40+00:00", "2020-09-14T16:13:20+00:00"]

    def test_heuristic_changes_carry_a_slot(self):
        body = _heuristic_body([_daily_block(1600000000, 2)])
        results = {}
        _parse_trep_02_activities(body, results)
        changes = results["activities"][0]["changes"]
        assert all("slot" in c for c in changes)
        assert [c["time"] for c in changes] == ["01:00", "02:00"]

    def test_repeated_block_is_not_duplicated(self):
        body = _heuristic_body([_daily_block(1600000000, 2), _daily_block(1600000000, 2)])
        results = {}
        _parse_trep_02_activities(body, results)
        assert len(results.get("activities", [])) == 1
