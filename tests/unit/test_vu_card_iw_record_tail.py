"""The VuCardIWRecord tail is normative in both generations and must be decoded.

Annex 1B §2.120 stores, per card insertion/withdrawal cycle, the *previous*
vehicle the driver used, followed by a manual-input flag::

    cardHolderName(72) fullCardNumber(18|19) cardExpiry(4) insertion(4)
    odoInsertion(3) cardSlot(1) withdrawal(4) odoWithdrawal(3)
    previousVehicleInfo(19|20) manualInputFlag(1)            → 129 (G1) / 131 (G2)

``previousVehicleInfo`` (§2.85 G1 / §2.118 G2) is
``vehicleRegistrationIdentification(15) + cardWithdrawalTime(4)`` and generation
2 appends ``vuGeneration(1)``. Both walks used to stop at ``odoWithdrawal`` and
throw those bytes away, and the G1 path additionally reported the flag as
``manual_input: bool(byte)`` — i.e. it mapped a reserved value to "yes".

Every constant here is synthetic (generic fictitious plate/card identifiers,
non-round timestamps); no DDD corpus sample is used or referenced. Each field
carries a *distinct* sentinel so a dropped field or a one-byte offset shift
changes an assertion.
"""
import struct

import pytest

from core.decoders.common import (
    decode_previous_vehicle_info,
    describe_manual_input_flag,
)
from core.decoders.vu_g1 import _parse_trep_02_g1_structured
from core.parser.vu_dispatcher import (
    CARD_IW_RECORD_SIZE,
    decode_card_iw,
    decode_vu_tag_record,
)

# ── synthetic sentinels (distinct per field, deliberately non-round) ────────
TS_EXPIRY = 1_766_982_229
TS_INSERTION = 1_690_431_907
TS_WITHDRAWAL = 1_690_468_913
TS_PREV_WITHDRAWAL = 1_690_406_651
TS_G1_EXPIRY = 1_766_982_230
TS_G1_INSERTION = 1_690_431_908
TS_G1_WITHDRAWAL = 1_690_468_914
TS_G1_PREV_WITHDRAWAL = 1_690_406_652

ODO_INSERTION = 412_399
ODO_WITHDRAWAL = 386_114
ODO_G1_INSERTION = 274_363
ODO_G1_WITHDRAWAL = 318_874

ISO_EXPIRY = "2025-12-29T04:23:49+00:00"
ISO_INSERTION = "2023-07-27T04:25:07+00:00"
ISO_WITHDRAWAL = "2023-07-27T14:41:53+00:00"
ISO_PREV_WITHDRAWAL = "2023-07-26T21:24:11+00:00"
ISO_G1_EXPIRY = "2025-12-29T04:23:50+00:00"
ISO_G1_INSERTION = "2023-07-27T04:25:08+00:00"
ISO_G1_WITHDRAWAL = "2023-07-27T14:41:54+00:00"
ISO_G1_PREV_WITHDRAWAL = "2023-07-26T21:24:12+00:00"

CARD_NUMBER_G2 = "0000000000471123"          # 16 chars of the 19-byte field
CARD_NUMBER_G1 = "0000000000471124"          # 16 chars of the 18-byte field
PREV_PLATE_G2 = "ZZ987ZZ"                   # current vehicle plate is NOT this
PREV_PLATE_G1 = "YY654YY"
CURRENT_PLATE_G2 = "QQ111QQ"
CURRENT_PLATE_G1 = "QQ222QQ"


def _name(text, length=36):
    """One HolderName / Address field: codePage(1) + chars(length-1)."""
    return b"\x01" + text.encode("latin-1").ljust(length - 1, b" ")


def _g2_record(previous_plate=PREV_PLATE_G2, prev_nation=0x1A,
               prev_code_page=0x01, prev_withdrawal=TS_PREV_WITHDRAWAL,
               vu_generation=0x02, manual_flag=0x01):
    """A canonical 131-byte Generation 2 VuCardIWRecord (Annex 1C §2.177)."""
    rec = bytearray()
    rec += _name("ALPHA")                                    # [0:36]'
    rec += _name("BETA GAMMA")                               # [36:72]
    rec += bytes([0x01, 0x0D]) + CARD_NUMBER_G2.encode()   # [72:91] type+nation+16
    rec += bytes([0x02])                                     # [91] FullCardNumber generation
    rec += struct.pack(">I", TS_EXPIRY)                      # [91:95]
    rec += struct.pack(">I", TS_INSERTION)                   # [95:99]
    rec += ODO_INSERTION.to_bytes(3, "big")                  # [99:102]
    rec += bytes([0x01])                                     # [102] card slot
    rec += struct.pack(">I", TS_WITHDRAWAL)                  # [103:107]
    rec += ODO_WITHDRAWAL.to_bytes(3, "big")                 # [107:110]
    # PreviousVehicleInfo (§2.118), 20 bytes
    rec += bytes([prev_nation, prev_code_page])
    rec += previous_plate.encode("latin-1").ljust(13, b"\x00")  # [112:125]
    rec += struct.pack(">I", prev_withdrawal)                # [125:129]
    rec += bytes([vu_generation])                            # [129]
    rec += bytes([manual_flag])                              # [130]
    assert len(rec) == CARD_IW_RECORD_SIZE, len(rec)
    return bytes(rec)


def _g1_record(previous_plate=PREV_PLATE_G1, prev_nation=0x0F,
               prev_code_page=0x01, prev_withdrawal=TS_G1_PREV_WITHDRAWAL,
               manual_flag=0x00, card_number=CARD_NUMBER_G1):
    """A canonical 129-byte Generation 1 VuCardIWRecord (Annex 1B §2.120)."""
    rec = bytearray()
    rec += _name("DELTA")                                    # [0:36]
    rec += _name("EPSILON ZETA")                             # [36:72]
    rec += bytes([0x01, 0x1A]) + card_number.encode()        # [72:90]
    rec += struct.pack(">I", TS_G1_EXPIRY)                   # [90:94]
    rec += struct.pack(">I", TS_G1_INSERTION)                # [94:98]
    rec += ODO_G1_INSERTION.to_bytes(3, "big")               # [98:101]
    rec += bytes([0x00])                                     # [101] card slot
    rec += struct.pack(">I", TS_G1_WITHDRAWAL)               # [102:106]
    rec += ODO_G1_WITHDRAWAL.to_bytes(3, "big")              # [106:109]
    # PreviousVehicleInfo (§2.85), 19 bytes
    rec += bytes([prev_nation, prev_code_page])
    rec += previous_plate.encode("latin-1").ljust(13, b"\x00")  # [111:124]
    rec += struct.pack(">I", prev_withdrawal)                # [124:128]
    rec += bytes([manual_flag])                              # [128]
    assert len(rec) == 129, len(rec)
    return bytes(rec)


def _g1_trep02_body(*records):
    """A G1 TREP 02 body (Annex 1B §2.2.6.2) carrying *records*."""
    out = bytearray()
    out += struct.pack(">I", TS_G1_INSERTION)        # dateOfDay
    out += ODO_G1_WITHDRAWAL.to_bytes(3, "big")      # odometerValueMidnight
    out += struct.pack(">H", len(records))           # noOfIWRecords
    for rec in records:
        out += rec
    out += struct.pack(">H", 1)                      # noOfActivityChanges
    out += struct.pack(">H", (5 << 2) | 3)
    out += bytes([0])                                # noOfPlaceRecords
    out += struct.pack(">H", 0)                      # noOfSpecificConditionRecords
    return bytes(out)


# ── Generation 2: exact 131-byte record ────────────────────────────────────

def test_g2_tail_fields_are_decoded_at_their_exact_offsets():
    """Each tail field must land on its own sentinel (no drop, no shift)."""
    out = decode_card_iw(_g2_record())

    assert out["record_bytes"] == CARD_IW_RECORD_SIZE
    assert out["record_complete"] is True
    assert out["confidence"] == "high"
    assert "raw_tail_hex" not in out

    prev = out["previous_vehicle"]
    assert prev["registration_nation"] == "I"          # 0x1A
    assert prev["registration_nation_code"] == 0x1A
    assert prev["registration_code_page"] == 0x01
    assert prev["registration_plate"] == PREV_PLATE_G2
    assert prev["card_withdrawal_time"] == ISO_PREV_WITHDRAWAL
    assert prev["card_withdrawal_timestamp"] == TS_PREV_WITHDRAWAL
    assert prev["vu_generation"] == 0x02               # generation 2 only

    assert out["manual_input_flag"] == 0x01
    assert out["manual_input_flag_meaning"] == "manualEntries"


def test_g2_tail_is_distinct_from_the_record_body_fields():
    """A shifted read (e.g. off-by-one or the G1 19-byte tail) cannot pass."""
    out = decode_card_iw(_g2_record())

    assert out["previous_vehicle"]["registration_plate"] != CURRENT_PLATE_G2
    assert out["previous_vehicle"]["card_withdrawal_time"] != out["withdrawal_time"]
    assert out["previous_vehicle"]["card_withdrawal_timestamp"] != TS_WITHDRAWAL
    assert out["odometer_insertion_km"] == ODO_INSERTION
    assert out["odometer_withdrawal_km"] == ODO_WITHDRAWAL
    assert out["card_expiry"] == ISO_EXPIRY
    assert out["insertion_time"] == ISO_INSERTION
    assert out["withdrawal_time"] == ISO_WITHDRAWAL
    assert out["card_slot"] == 1
    assert out["card"]["card_number"] == CARD_NUMBER_G2
    assert out["card"]["generation"] == 0x02


@pytest.mark.parametrize("code_page, plate, expected", [
    (0x01, "AB123CD", "AB123CD"),                  # latin-1
    (0x02, "\u017b\u00d3\u0141\u0106", "\u017b\u00d3\u0141\u0106"),   # iso-8859-2
    (0x05, "\u0416\u0414", "\u0416\u0414"),        # iso-8859-5 (Cyrillic)
    (0x00, "AB123CD", "AB123CD"),                  # undefined code page → latin-1
])
def test_g2_previous_plate_honours_the_declared_code_page(code_page, plate, expected):
    """The VRN has its own codePage byte; non-ASCII letters must survive."""
    rec = bytearray(_g2_record(prev_code_page=code_page))
    encoded = plate.encode({0x02: "iso-8859-2", 0x05: "iso-8859-5"}.get(code_page, "latin-1"))
    rec[112:125] = encoded.ljust(13, b"\x00")

    out = decode_card_iw(bytes(rec))

    assert out["previous_vehicle"]["registration_code_page"] == code_page
    assert out["previous_vehicle"]["registration_plate"] == expected


def test_g2_no_previous_vehicle_is_reported_as_sentinels_not_invented():
    """An unused previous vehicle keeps its sentinels: nothing is inferred."""
    rec = bytearray(_g2_record(prev_nation=0xFF, prev_code_page=0xFF,
                               prev_withdrawal=0))
    rec[112:125] = b"\xff" * 13

    out = decode_card_iw(bytes(rec))

    prev = out["previous_vehicle"]
    assert prev["registration_nation"] == "WLD"
    assert prev["registration_plate"] == ""
    assert prev["card_withdrawal_time"] is None


@pytest.mark.parametrize("flag, meaning", [
    (0x00, "noEntry"),
    (0x01, "manualEntries"),
    (0x02, describe_manual_input_flag(0x02)),
    (0x7F, describe_manual_input_flag(0x7F)),
    (0xFF, describe_manual_input_flag(0xFF)),
])
def test_g2_manual_input_flag_keeps_its_numeric_value(flag, meaning):
    """RFU values stay RFU: no non-zero byte may mean «manual entries»."""
    out = decode_card_iw(_g2_record(manual_flag=flag))

    assert out["manual_input_flag"] == flag
    assert out["manual_input_flag_meaning"] == meaning
    if flag not in (0x00, 0x01):
        assert out["manual_input_flag_meaning"] != "manualEntries"


# ── Generation 2: non-canonical lengths ────────────────────────────────────

def test_g2_truncated_record_keeps_the_prefix_and_preserves_the_raw_tail():
    """A short record is decoded as far as it goes, and never past it."""
    full = _g2_record()
    for length in (110, 111, 124, 128, 129, 130):
        out = decode_card_iw(full[:length])

        assert out["record_bytes"] == length
        assert out["record_complete"] is False
        assert out["confidence"] == "low"
        assert out["missing_bytes"] == CARD_IW_RECORD_SIZE - length
        assert out["raw_tail_hex"] == full[110:length].hex()
        # Nothing the bytes cannot prove: the 20-byte tail is incomplete.
        assert "previous_vehicle" not in out
        assert "manual_input_flag" not in out
        # The unchanged prefix is still there.
        assert out["odometer_withdrawal_km"] == ODO_WITHDRAWAL
        assert out["withdrawal_time"] == ISO_WITHDRAWAL


def test_g2_prefix_shorter_than_the_withdrawal_odometer_is_not_decoded():
    """Below the 110-byte prefix the record is not a VuCardIWRecord at all."""
    assert decode_card_iw(_g2_record()[:109]) is None


def test_g2_extension_beyond_131_is_preserved_raw_and_never_interpreted():
    """Unknown trailing bytes: kept verbatim, the record is not canonical."""
    full = _g2_record()
    out = decode_card_iw(full + b"\xde\xad\xbe\xef")

    assert out["record_bytes"] == CARD_IW_RECORD_SIZE + 4
    assert out["record_complete"] is False
    assert out["confidence"] == "low"           # not a canonical 131-byte record
    assert out["raw_tail_bytes"] == 4
    assert out["raw_tail_hex"] == "deadbeef"
    # The normative 131-byte prefix is still decoded exactly.
    assert out["previous_vehicle"]["card_withdrawal_timestamp"] == TS_PREV_WITHDRAWAL
    assert out["manual_input_flag"] == 0x01


# ── Generation 1: exact 129-byte record, through the TREP 02 walk ──────────

def test_g1_tail_fields_are_decoded_at_their_exact_offsets():
    results = {}
    assert _parse_trep_02_g1_structured(_g1_trep02_body(_g1_record()), results) is True

    records = results["card_iw_records"]
    assert len(records) == 1
    rec = records[0]

    assert rec["record_complete"] is True
    assert rec["manual_input_flag"] == 0x00
    assert rec["manual_input_flag_meaning"] == "noEntry"
    assert rec["manual_input"] is False            # backwards-compatible value

    prev = rec["previous_vehicle"]
    assert prev["registration_nation"] == "E"      # 0x0F
    assert prev["registration_nation_code"] == 0x0F
    assert prev["registration_code_page"] == 0x01
    assert prev["registration_plate"] == PREV_PLATE_G1
    assert prev["card_withdrawal_time"] == ISO_G1_PREV_WITHDRAWAL
    assert prev["card_withdrawal_timestamp"] == TS_G1_PREV_WITHDRAWAL
    assert "vu_generation" not in prev             # generation 1 has no such byte


def test_g1_body_fields_stay_where_they_were():
    """The tail decoding must not move the pre-existing offsets."""
    results = {}
    assert _parse_trep_02_g1_structured(_g1_trep02_body(_g1_record()), results) is True
    rec = results["card_iw_records"][0]

    assert rec["odometer_insertion_km"] == ODO_G1_INSERTION
    assert rec["odometer_withdrawal_km"] == ODO_G1_WITHDRAWAL
    assert rec["card_expiry"] == "29/12/2025"
    assert rec["insertion_time"] == ISO_G1_INSERTION
    assert rec["withdrawal_time"] == ISO_G1_WITHDRAWAL
    assert rec["card_slot"] == 0
    # The 16-character cardNumber field, as stored (§2.73): the issuing nation is
    # its own field, never a prefix glued onto the number.
    assert rec["card"]["card_number"] == CARD_NUMBER_G1
    assert rec["card"]["nation"] == "I"
    assert rec["previous_vehicle"]["registration_plate"] != CURRENT_PLATE_G1


def test_g1_previous_vehicle_is_per_record_not_the_current_vehicle():
    """Two insertion cycles keep two different previous vehicles."""
    first = _g1_record()
    # A different card, so the walk's (insertion_time, card) dedup keeps both.
    second = bytearray(_g1_record(prev_nation=0x0D, prev_code_page=0x01,
                                  prev_withdrawal=TS_INSERTION,
                                  card_number="0000000000471125"))
    second[111:124] = b"XY321XY".ljust(13, b"\x00")
    vehicle = {"vin": "CURRENTVIN0000001", "plate": CURRENT_PLATE_G1,
               "registration_nation": "I"}

    results = {"vehicle": dict(vehicle)}
    assert _parse_trep_02_g1_structured(
        _g1_trep02_body(first, bytes(second)), results) is True

    records = results["card_iw_records"]
    assert len(records) == 2
    assert records[0]["previous_vehicle"]["registration_plate"] == PREV_PLATE_G1
    assert records[1]["previous_vehicle"]["registration_plate"] == "XY321XY"
    assert records[1]["previous_vehicle"]["registration_nation"] == "D"
    assert records[1]["previous_vehicle"]["card_withdrawal_time"] == ISO_INSERTION
    # The file-level vehicle is untouched by any per-record previous vehicle.
    assert results["vehicle"] == vehicle


@pytest.mark.parametrize("flag", [0x00, 0x01, 0x05, 0xFF])
def test_g1_manual_input_flag_is_numeric_and_disclosed(flag):
    """A reserved flag must not be presented as a confident «yes»."""
    results = {}
    assert _parse_trep_02_g1_structured(
        _g1_trep02_body(_g1_record(manual_flag=flag)), results) is True
    rec = results["card_iw_records"][0]

    assert rec["manual_input_flag"] == flag
    assert rec["manual_input_flag_meaning"] == describe_manual_input_flag(flag)
    if flag > 1:
        assert rec["manual_input_flag_meaning"] != "manualEntries"
        # The legacy boolean keeps its old (over-broad) meaning, unchanged.
        assert rec["manual_input"] is True


def test_g1_non_ascii_previous_plate_keeps_its_letters():
    """Generation 1 also honours the VRN codePage (iso-8859-2 here)."""
    rec = bytearray(_g1_record(prev_code_page=0x02))
    rec[111:124] = "\u017b\u00d3\u0141\u0106".encode("iso-8859-2").ljust(13, b"\x00")

    results = {}
    assert _parse_trep_02_g1_structured(_g1_trep02_body(bytes(rec)), results) is True

    assert results["card_iw_records"][0]["previous_vehicle"]["registration_plate"] == (
        "\u017b\u00d3\u0141\u0106")


# ── the isolated / tag-keyed adapter shares the same semantics ─────────────

def test_tag_keyed_card_iw_record_decodes_the_same_tail():
    """``0x050A`` comes through ``decode_vu_tag_record``, not the stream walk."""
    out = decode_vu_tag_record(0x050A, _g2_record())

    assert out["previous_vehicle"]["registration_plate"] == PREV_PLATE_G2
    assert out["previous_vehicle"]["card_withdrawal_timestamp"] == TS_PREV_WITHDRAWAL
    assert out["manual_input_flag"] == 0x01
    assert out["record_complete"] is True
    assert out["confidence"] == "high"


# ── the shared PreviousVehicleInfo helper ─────────────────────────────────

def test_previous_vehicle_helper_refuses_a_partial_structure():
    """No guesswork over a truncated structure."""
    block = _g2_record()[110:130]
    assert decode_previous_vehicle_info(block, 0) is not None             # 20 ≥ 19
    assert decode_previous_vehicle_info(block[:18], 0) is None
    assert decode_previous_vehicle_info(block[:19], 0) is not None
    assert decode_previous_vehicle_info(block, 0, with_vu_generation=True) is not None
    assert decode_previous_vehicle_info(block[:19], 0, with_vu_generation=True) is None


# ── the PreviousVehicleInfo time window and the plate's text filter ────────

#: Synthetic bounds of the accepted TimeReal window (its two ends).
TS_MIN = 946_684_800
TS_MAX = 4_102_444_800


def _previous_vehicle_block(nation=0x1A, code_page=0x01, plate=b"AB123CD",
                            withdrawal=TS_MIN):
    """One raw PreviousVehicleInfo block (nation + VRN + cardWithdrawalTime)."""
    block = bytes([nation, code_page]) + plate.ljust(13, b"\x00")
    block += struct.pack(">I", withdrawal)
    return block + b"\x02"                      # + vuGeneration


@pytest.mark.parametrize("withdrawal", [TS_MIN, TS_MAX])
def test_previous_vehicle_accepts_the_window_boundaries(withdrawal):
    """Both ends of the accepted TimeReal window are inside it (inclusive)."""
    out = decode_previous_vehicle_info(_previous_vehicle_block(withdrawal=withdrawal), 0)

    assert out["card_withdrawal_time"] is not None
    assert out["card_withdrawal_timestamp"] == withdrawal


@pytest.mark.parametrize("withdrawal", [
    TS_MIN - 1,          # one second before the window
    900_000_017,         # 1998 — well before it, non-round
    TS_MAX + 1,          # one second after the window
    4_200_003_113,       # well after it, non-round
    0,                   # the "not set" sentinel
    0xFFFFFFFF,          # all bits set
])
def test_previous_vehicle_rejects_a_time_outside_the_window_but_keeps_the_raw_value(withdrawal):
    """An implausible TimeReal becomes ``None``; the integer itself is preserved.

    Dropping either bound would let a nonsense date through as if it were a
    recorded withdrawal time, so both ends are pinned here.
    """
    out = decode_previous_vehicle_info(_previous_vehicle_block(withdrawal=withdrawal), 0)

    assert out["card_withdrawal_time"] is None
    assert out["card_withdrawal_timestamp"] == withdrawal


def test_previous_vehicle_plate_drops_control_characters_and_keeps_the_letters():
    """A plate is text: control bytes are removed, letters are not."""
    block = _previous_vehicle_block(plate=b"AB\x07CD\x1fEF12345")

    out = decode_previous_vehicle_info(block, 0)

    assert out["registration_plate"] == "ABCDEF12345"
    assert "\x07" not in out["registration_plate"]
    assert "\x1f" not in out["registration_plate"]


def test_previous_vehicle_plate_keeps_plain_letters():
    """Control for the filter test: nothing is stripped when nothing is odd."""
    out = decode_previous_vehicle_info(_previous_vehicle_block(plate=b"AB123CD"), 0)

    assert out["registration_plate"] == "AB123CD"


def test_manual_input_flag_meaning_table_is_the_regulation_one():
    assert describe_manual_input_flag(0) == "noEntry"
    assert describe_manual_input_flag(1) == "manualEntries"
    for rfu in (2, 3, 0x10, 0xFE, 0xFF, None, "x"):
        assert describe_manual_input_flag(rfu) not in ("noEntry", "manualEntries")
