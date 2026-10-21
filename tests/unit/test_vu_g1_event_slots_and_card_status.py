"""G1 VU structures completed in the normative batch, through the real parser.

**N2 — VuEventRecord keeps all four FullCardNumber slots.** Annex 1B Appendix 1
§2.132 (DDP_031) lays the record out as
``eventType eventPurpose begin end driverBegin coDriverBegin driverEnd
coDriverEnd similarEvents``; the G1 emitter used to copy only ``driverBegin``,
so three of the four cards a VU recorded were dropped. The Gen2 emitter already
publishes all four under these names, so completing the G1 record introduces no
new column label.

**N3 — CardSlotsStatus is two nibbles.** Annex 1B Appendix 1 §2.28: one octet,
octet aligned ``'ccccdddd'B``, the high nibble being the card type in the
*co-driver* slot and the low nibble the type in the *driver* slot (``0000`` no
card, ``0001`` driver, ``0010`` workshop, ``0011`` control, ``0100`` company
card, ``0101``..``1111`` unassigned). The old reading tested bits 0 and 1, so
``0x41`` (both slots occupied) reported the co-driver slot as empty.

Both are exercised through ``TachoParser`` on a synthetic G1 VU download — the
same builders the other G1 regression suites use — so the walker, the dispatch
table and the emitters are all in the path. Every value below is synthetic.
"""
import struct

import pytest

from app.engine import TachoParser

# ── synthetic constants (fictitious cards/plates; non-round timestamps) ─────
TS = 1_690_431_907
TS_END = 1_690_468_913
VIN = "VALIDVIN000000001"
PLATE = "AB123CD"
OVERRUN = b"\xAA" * 128            # the RSA signature slot the walker skips

#: (key, card type, nation code, 16-char number) — distinct in every component,
#: so a swapped pair or a one-slot offset shift changes an assertion.
SLOTS = (
    ("card_driver_begin", 0x01, 0x1A, "1000000000000041"),
    ("card_codriver_begin", 0x02, 0x0D, "2000000000000042"),
    ("card_driver_end", 0x03, 0x0F, "3000000000000043"),
    ("card_codriver_end", 0x04, 0x11, "4000000000000044"),
)
NATION = {0x1A: "I", 0x0D: "D", 0x0F: "E", 0x11: "F"}


# ── stream builders ────────────────────────────────────────────────────────

def _full_card_number(card_type, nation, number):
    """FullCardNumber (Annex 1B §2.73): type(1) + nation(1) + number(16)."""
    return bytes([card_type, nation]) + number.encode()


def event_record(begin=TS, end=TS_END, event_type=0x01, purpose=0x00):
    """One 83-byte VuEventRecord with four card slots at 10/28/46/64."""
    rec = bytearray(83)
    rec[0] = event_type
    rec[1] = purpose
    struct.pack_into(">I", rec, 2, begin)
    struct.pack_into(">I", rec, 6, end)
    for offset, (_, card_type, nation, number) in zip((10, 28, 46, 64), SLOTS,
                                                     strict=True):
        rec[offset:offset + 18] = _full_card_number(card_type, nation, number)
    rec[82] = 1
    return bytes(rec)


def trep03_body(records):
    """Count-prefixed TREP 03 body: faults(1)=0, events(1)=N, then N × 83."""
    body = bytearray()
    body += bytes([0])                      # noOfVuFaults
    body += bytes([len(records)])           # noOfVuEvents
    for rec in records:
        body += rec
    body += b"\x00" * 9                     # VuOverSpeedingControlData
    body += bytes([0])                      # noOfVuOverSpeedingEvents
    body += bytes([0])                      # noOfVuTimeAdjustments
    return bytes(body)


def overview_body(slot_status):
    """A validating 493-byte TREP 01 body with *slot_status* at offset 432."""
    body = bytearray(493)
    body[388:405] = VIN.encode()                     # VIN (validates the body)
    body[405] = ord("I")                             # registration nation
    body[406:420] = PLATE.encode().ljust(14, b"\x00")
    struct.pack_into(">I", body, 420, TS)            # currentDateTime
    struct.pack_into(">I", body, 424, TS)            # minDownloadable
    struct.pack_into(">I", body, 428, TS_END)        # maxDownloadable
    body[432] = slot_status                          # CardSlotsStatus
    body[433:491] = b"\x00" * 58                     # VuDownloadActivityData(58)
    body[491] = 0                                    # noOfLocks
    body[492] = 0                                    # noOfControls
    return bytes(body)


def g1_stream(slot_status=0x00, events=None):
    """A G1 VU download: TREP 01 Overview + TREP 03 Events/Faults."""
    stream = bytearray()
    stream += b"\x76\x01" + overview_body(slot_status) + OVERRUN
    stream += b"\x76\x03" + trep03_body(events or []) + OVERRUN
    return bytes(stream)


def parse(tmp_path, stream):
    path = tmp_path / "g1-normative.ddd"
    path.write_bytes(stream)
    return TachoParser(str(path)).parse()


# ── N2: all four FullCardNumber slots survive ─────────────────────────────

def test_g1_event_keeps_all_four_card_slots(tmp_path):
    """Each slot must land on its own card: type, nation and number differ."""
    results = parse(tmp_path, g1_stream(events=[event_record()]))

    events = results["events"]
    assert len(events) == 1
    event = events[0]
    for key, card_type, nation, number in SLOTS:
        card = event[key]
        assert card["card_type"] == card_type, key
        assert card["nation"] == NATION[nation], key
        assert card["card_number"] == number, key
    # A shifted read cannot pass: no two slots share a card.
    assert len({str(event[key]) for key, *_ in SLOTS}) == 4


def test_g1_event_keeps_the_rest_of_the_record(tmp_path):
    """Completing the record must not move the fields it already had."""
    results = parse(tmp_path, g1_stream(events=[event_record()]))

    event = results["events"][0]
    assert event["type_code"] == 0x01
    assert event["begin_time"] == "2023-07-27T04:25:07+00:00"
    assert event["end_time"] == "2023-07-27T14:41:53+00:00"
    assert event["similar_events"] == 1
    assert event["record_purpose"] == 0x00


def test_g1_identical_stored_records_are_both_kept(tmp_path):
    """Corrected (F5): the counter declares two stored events, so two are kept.

    The old assertion collapsed byte-identical records to one, but a record's
    identity is its position in the download, never a subset of its fields — the
    VU may store the same event twice (same type, same clocks).
    """
    results = parse(tmp_path, g1_stream(events=[event_record(), event_record()]))

    assert len(results["events"]) == 2
    assert [e["type_code"] for e in results["events"]] == [0x01, 0x01]


def test_g1_distinct_events_are_both_kept(tmp_path):
    """Control for the dedup test: a different type is a different event."""
    results = parse(tmp_path, g1_stream(
        events=[event_record(), event_record(event_type=0x02)]))

    assert [e["type_code"] for e in results["events"]] == [0x01, 0x02]
    for event in results["events"]:
        # The G1 decoder reports the raw shape (no "present" flag, unlike Gen2).
        assert event["card_codriver_begin"]["card_type"] == 0x02
        assert event["card_codriver_end"]["card_type"] == 0x04


def test_the_four_slot_columns_already_exist_for_gen2():
    """No new column text appears: the names are the Gen2 emitter's own."""
    from core.utils.report_format import humanize_key

    for key, *_ in SLOTS:
        assert humanize_key(key) in {
            "Card Driver Begin", "Card Codriver Begin",
            "Card Driver End", "Card Codriver End"}


# ── N3: CardSlotsStatus = 'ccccdddd'B ─────────────────────────────────────

@pytest.mark.parametrize("status, driver, codriver", [
    (0x00, "empty", "empty"),        # nothing inserted
    (0x01, "occupied", "empty"),     # driver card only
    (0x02, "occupied", "empty"),     # workshop card in the driver slot
    (0x04, "occupied", "empty"),     # company card in the driver slot
    (0x10, "empty", "occupied"),     # co-driver slot only
    (0x14, "occupied", "occupied"),  # company card in the driver slot
    (0x40, "empty", "occupied"),     # company card in the co-driver slot
    (0x0F, "reserved", "empty"),     # unassigned type in the driver slot
    (0x41, "occupied", "occupied"),  # both slots used (old code: co-driver empty)
    (0x44, "occupied", "occupied"),
    (0x5F, "reserved", "reserved"),  # 5..15 are unassigned in both nibbles
    (0xF0, "empty", "reserved"),     # unassigned type in the co-driver slot
])
def test_overview_card_slots_status_reads_both_nibbles(tmp_path, status, driver, codriver):
    """'ccccdddd'B: high nibble = co-driver slot, low nibble = driver slot."""
    results = parse(tmp_path, g1_stream(slot_status=status))

    slot_status = results["vu_overview"]["card_slot_status"]
    assert slot_status["driver_slot"] == driver
    assert slot_status["codriver_slot"] == codriver
    # The raw byte and the two keys are unchanged — nothing new on screen.
    assert slot_status["raw"] == f"0x{status:02X}"
    # Complete per-nibble typing added later must stay model-only: every key
    # beyond the three published ones has to be in HIDDEN_KEYS.
    from core.utils.report_format import HIDDEN_KEYS
    published = {"codriver_slot", "driver_slot", "raw"}
    assert published <= set(slot_status)
    for key in set(slot_status) - published:
        assert key in HIDDEN_KEYS, key


def test_overview_card_slots_keys_and_values_stay_in_the_published_vocabulary():
    """No new key and no new value string, for every possible status byte."""
    from core.decoders.vu_g1 import parse_g1_vu_overview

    for status in range(0x100):
        results = {"vehicle": {}, "metadata": {}, "vu_overview": {},
                   "company_info": {}, "card_numbers": []}
        parse_g1_vu_overview(overview_body(status), results)
        slot_status = results["vu_overview"]["card_slot_status"]
        from core.utils.report_format import HIDDEN_KEYS
        published = {"driver_slot", "codriver_slot", "raw"}
        assert published <= set(slot_status)
        assert set(slot_status) - published <= HIDDEN_KEYS
        assert slot_status["driver_slot"] in {"empty", "occupied", "reserved"}
        assert slot_status["codriver_slot"] in {"empty", "occupied", "reserved"}
        assert slot_status["raw"] == f"0x{status:02X}"
