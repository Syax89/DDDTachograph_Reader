"""Gen2 / Gen2.2 Events&Faults (TREP 23 / 33) and Detailed speed (TREP 24).

The event/fault records themselves are decoded structurally already. What was
missing is the **section version** for the records that carry an
``EventFaultType`` outside the event/fault arrays — ``VuOverSpeedingEventRecord``
(0x1B) and ``VuPowerSupplyInterruptionRecord`` (0x1F) — plus two records whose
length was accepted as a prefix:

* ``VuDetailedSpeedBlock`` is exactly 64 bytes (TimeReal + 60 per-second values,
  Annex 1C §2.188). A 5-byte prefix was decoded with ``confidence: high``.
* ``VuTimeAdjustmentRecord`` is exactly 99 bytes (Annex 1C §2.212). A short
  record was reported ``medium`` but still presented as an adjustment.

Every value below is synthetic.
"""
import struct

from core.parser.vu_dispatcher import (
    decode_overspeeding_event, decode_power_interruption, decode_time_adjustment,
    walk_vu_record_arrays)
from core.utils.event_codes import (
    EVENT_FAULT_VERSION_1, EVENT_FAULT_VERSION_2, describe_event_fault_type)
from tests.unit import vu_synthetic as S

TIME = S.BASE_TIME


def _results():
    return {"metadata": {}, "vehicle": {"vin": "N/A", "plate": "N/A",
                                        "registration_nation": "N/A"}}


def _overspeed_record(event_type=0x07):
    return (bytes([event_type, 0x00]) + struct.pack(">II", TIME, TIME + 300)
            + bytes([0x5A, 0x50]) + S.card_number() + bytes([0x02]))


def _power_record(event_type=0x08):
    return (bytes([event_type, 0x00]) + struct.pack(">II", TIME, TIME + 120)
            + S.card_number() + S.EMPTY_CARD + S.EMPTY_CARD + S.EMPTY_CARD
            + bytes([0x01]))


def _time_adjustment(size=99):
    body = struct.pack(">II", TIME, TIME + 60) + S.coded_string(
        "SYNTH WORKSHOP", code_page=1, length=36) + S.coded_string(
        "SYNTH STREET 1", code_page=1, length=36) + S.card_number(card_type=0x02)
    return (body + b"\x00" * size)[:size]


# ── Section version reaches the sibling event-fault records ─────────────────

def test_overspeed_event_uses_the_section_version_table():
    # '0F'H is defined only by generation 2, version 2 (Reg. 2021/1228).
    out = decode_overspeeding_event(_overspeed_record(0x0F),
                                    version=EVENT_FAULT_VERSION_1)
    assert out["event_fault_version"] == EVENT_FAULT_VERSION_1
    assert out["type_status"] == "reserved"
    assert out["event_type_label"] == describe_event_fault_type(
        0x0F, True, EVENT_FAULT_VERSION_1)

    out_v2 = decode_overspeeding_event(_overspeed_record(0x0F),
                                      version=EVENT_FAULT_VERSION_2)
    assert out_v2["type_status"] == "assigned"
    assert out_v2["event_type_label"] == "GNSS anomaly"


def test_power_interruption_uses_the_section_version_table():
    out = decode_power_interruption(_power_record(0x1C),
                                    version=EVENT_FAULT_VERSION_1)
    assert out["type_status"] == "reserved"
    out_v2 = decode_power_interruption(_power_record(0x1C),
                                      version=EVENT_FAULT_VERSION_2)
    assert out_v2["type_status"] == "assigned"


def test_manufacturer_specific_type_is_never_given_a_meaning():
    out = decode_power_interruption(_power_record(0x8A),
                                    version=EVENT_FAULT_VERSION_2)
    assert out["type_status"] == "manufacturer_specific"
    assert out["event_type_label"].startswith("Manufacturer specific")


def test_version_travels_by_section_not_by_file():
    stream = (S.section(0x23,
                        S.record_array(0x1B, 32, [_overspeed_record(0x0F)]),
                        S.signature_record())
              + S.section(0x33,
                          S.record_array(0x1B, 32, [_overspeed_record(0x0F)]),
                          S.signature_record()))
    results = _results()
    walk_vu_record_arrays(stream, results)
    versions = [r["event_fault_version"] for r in results["overspeeding_events"]]
    statuses = [r["type_status"] for r in results["overspeeding_events"]]
    assert versions == [EVENT_FAULT_VERSION_1, EVENT_FAULT_VERSION_2]
    assert statuses == ["reserved", "assigned"]


# ── Exact record sizes ──────────────────────────────────────────────────────

def test_detailed_speed_block_is_exactly_64_bytes():
    record = struct.pack(">I", TIME) + bytes([0x2A] * 60)
    assert len(record) == 64
    out = walk_vu_record_arrays(
        S.section(0x24, S.record_array(0x12, 64, [record]), S.signature_record()),
        _results())
    assert out  # the section was walked


def test_five_byte_speed_prefix_is_not_a_high_confidence_block():
    stream = S.section(0x24, S.record_array(0x12, 5, [struct.pack(">I", TIME) + b"\x2A"]),
                       S.signature_record())
    results = _results()
    walk_vu_record_arrays(stream, results)
    blocks = results["speed_blocks"]
    assert len(blocks) == 1
    block = blocks[0]
    assert block["confidence"] == "low"
    assert block["record_complete"] is False
    assert block["record_bytes"] == 5
    assert block["raw_tail_hex"] == (struct.pack(">I", TIME) + b"\x2a").hex()


def test_full_speed_block_keeps_every_sample():
    speeds = list(range(60))
    record = struct.pack(">I", TIME) + bytes(speeds)
    results = _results()
    walk_vu_record_arrays(
        S.section(0x24, S.record_array(0x12, 64, [record]), S.signature_record()),
        results)
    block = results["speed_blocks"][0]
    assert block["record_complete"] is True
    assert block["samples"] == 60
    assert block["_chart_speeds_kmh"] == speeds
    assert block["max_speed_kmh"] == 59


def test_canonical_time_adjustment_is_99_bytes():
    record = _time_adjustment()
    assert len(record) == 99
    out = decode_time_adjustment(record)
    assert out["confidence"] == "high"
    assert out["record_complete"] is True
    assert out["workshop_name"] == "SYNTH WORKSHOP"
    assert out["workshop_card"]["card_type"] == 0x02


def test_short_time_adjustment_is_not_reported_as_a_complete_record():
    out = decode_time_adjustment(_time_adjustment(size=40))
    assert out["confidence"] == "low"
    assert out["record_complete"] is False
    assert out["record_bytes"] == 40
    assert out["old_time"] and out["new_time"]
    assert out["raw_tail_hex"]


def test_gnss_time_adjustment_variant_stays_exact_8_bytes():
    from core.parser.vu_dispatcher import decode_time_adj_gnss
    out = decode_time_adj_gnss(struct.pack(">II", TIME, TIME + 1))
    assert out["old_time"] and out["new_time"]
    assert decode_time_adj_gnss(b"\x00" * 7) is None
