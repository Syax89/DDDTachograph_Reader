"""Behavioural contract for the shared FullCardNumberAndGeneration decoder.

Annex 1C (Reg. (EU) 2016/799, consolidated 2023-08-21) Appendix 1:

* §2.73/§2.74 — ``FullCardNumberAndGeneration`` is ``cardType(1)`` +
  ``cardIssuingMemberState``/nation ``(1)`` + ``cardNumber(16)`` +
  ``generation(1)`` = 19 octets.
* §2.26 — ``CardNumber`` is a *fixed* 16-octet ``IA5String`` sequence
  (``driverIdentification`` 14 + replacement + renewal, or
  ``ownerIdentification`` 13 + consecutive + replacement + renewal).
* §2.75 — ``generation`` is ``0x01`` = Generation 1, ``0x02`` = Generation 2.
  The trailing byte is a generation code, NOT a ``0x02`` terminator.

``decode_full_card_number_gen`` is the shared entry point for the supported
Generation 2 / Generation 2.2 VU-record callers in this module (VuCardRecord,
card insertion/withdrawal, download activity, control activity, border
crossing, power interruption, …); they read the number with the shared
``_ascii`` helper. Generation 1 card data is decoded by other decoders, not
this function.

Every expected value below is an independent literal; none is recomputed by
calling the production helper.
"""
import struct

from core.parser.vu_dispatcher import (
    decode_full_card_number_gen,
    decode_vu_card_record,
    walk_vu_record_arrays,
)

# A normative driver card number: driverIdentification(14) + replacement +
# renewal = 16 IA5String characters (Annex 1C §2.26).
DRIVER_NUMBER = b"I100000114613001"


def _fcng(card_type, nation, number, generation):
    """Build a 19-octet FullCardNumberAndGeneration field (Annex 1C §2.74)."""
    assert len(number) == 16, "cardNumber is a fixed 16-octet IA5String (§2.26)"
    return bytes([card_type, nation]) + number + bytes([generation])


def _vu_card_record(card_gen, tail_number):
    """Build a 45-octet VuCardRecord (VuCardRecord, recordType 0x0E)."""
    return card_gen + bytes(range(8)) + b"\x02\x01" + tail_number


def test_full_19_byte_structure():
    out = decode_full_card_number_gen(_fcng(0x01, 0x1A, DRIVER_NUMBER, 0x02), 0)
    assert out == {
        "present": True,
        "card_type": 0x01,
        "nation": "I",            # 0x1A = Italy (Annex 1B nation code)
        "card_number": "I100000114613001",
        "generation": 2,          # 0x02 = Generation 2 (§2.75)
    }


def test_nonzero_caller_offset():
    # Nation + cardType must be read from *off*, not from byte 0.
    data = b"\xAA" * 7 + _fcng(0x01, 0x0D, b"D123456789012345", 0x01)
    out = decode_full_card_number_gen(data, 7)
    assert out["present"] is True
    assert out["card_type"] == 0x01
    assert out["nation"] == "D"                # 0x0D = Germany
    assert out["card_number"] == "D123456789012345"
    assert out["generation"] == 1              # 0x01 = Generation 1 (§2.75)


def test_second_card_type_and_nation():
    # ownerIdentification shape (13 chars + 3 indices) is still 16 octets (§2.26).
    out = decode_full_card_number_gen(_fcng(0x02, 0x0F, b"E0000000000000AB", 0x02), 0)
    assert out["card_type"] == 0x02
    assert out["nation"] == "E"                # 0x0F = Spain
    assert out["card_number"] == "E0000000000000AB"
    assert out["generation"] == 2


def test_case_is_preserved():
    out = decode_full_card_number_gen(_fcng(0x01, 0x1A, b"I1aBcD0000461300", 0x02), 0)
    assert out["card_number"] == "I1aBcD0000461300"


def test_embedded_control_byte_is_dropped_not_a_terminator():
    # NON-NORMATIVE input: §2.74 has no terminator, but that neither makes 0x02
    # a valid printable identification character nor mandates stripping it.
    # This pins the decoder's existing best-effort behaviour on such input: a
    # control byte inside the 16-octet field is dropped (not treated as a stop)
    # and the following octets are still read.
    out = decode_full_card_number_gen(_fcng(0x01, 0x1A, b"AB\x02CDEFGHIJKLMNO", 0x02), 0)
    assert out["present"] is True
    assert out["card_number"] == "ABCDEFGHIJKLMNO"


def test_short_input_returns_none():
    assert decode_full_card_number_gen(b"\x00" * 18, 0) is None
    assert decode_full_card_number_gen(b"", 0) is None
    # 19 bytes present but the caller offset pushes the window past the end.
    assert decode_full_card_number_gen(_fcng(0x01, 0x1A, DRIVER_NUMBER, 0x02), 1) is None


def test_all_ff_is_absent():
    assert decode_full_card_number_gen(b"\xff" * 19, 0) == {"present": False}


def test_partial_filler_is_absent():
    # cardType 0 + blank IA5String field + generation 0xFF: empty slot.
    blank = bytes([0x00, 0x00]) + b"\x00" * 16 + bytes([0xFF])
    assert decode_full_card_number_gen(blank, 0) == {"present": False}
    # Non-zero cardType/nation but an all-NUL number is still an empty slot.
    nul_number = bytes([0x01, 0x1A]) + b"\x00" * 16 + bytes([0x02])
    assert decode_full_card_number_gen(nul_number, 0) == {"present": False}


def test_decode_vu_card_record_reaches_shared_helper():
    # Real public caller: VuCardRecord (recordType 0x0E) decodes its leading
    # FullCardNumberAndGeneration through the shared helper, plus a separate
    # 16-octet trailing cardNumber field at offset 29.
    rec = _vu_card_record(_fcng(0x01, 0x1A, DRIVER_NUMBER, 0x02), DRIVER_NUMBER)
    assert len(rec) == 45
    out = decode_vu_card_record(rec)
    assert out["confidence"] == "high"
    assert out["card"]["present"] is True
    assert out["card"]["card_number"] == "I100000114613001"
    assert out["card"]["generation"] == 2
    assert out["card_number"] == "I100000114613001"   # trailing 16-octet field


def test_walk_record_arrays_dispatches_card_record():
    # Minimal synthetic ROUTE test (not a complete signed normative download):
    # the public stream walker (used by app.engine.TachoParser) dispatches
    # recordType 0x0E to the same decoder and surfaces the number.
    # Annex 1C Appendix 7 §2.2.6.6 places VuCardRecordArray in the Technical
    # Data structure, served by TREP 05/25/35; 0x76 0x35 is the Generation 2
    # version 2 TechnicalData section marker (TRTP 35). The Gen2 v2 section
    # markers per Appendix 7 are TRTP 00/31/32/33/35 — 0x34 is not one of them.
    rec = _vu_card_record(_fcng(0x02, 0x0F, b"E0000000000000AB", 0x01), b"E0000000000000AB")
    stream = b"\x76\x35" + bytes([0x0E]) + struct.pack(">HH", 45, 1) + rec
    results = {}
    walk_vu_record_arrays(stream, results)
    cards = results["card_records"]
    assert len(cards) == 1
    assert cards[0]["card"]["card_number"] == "E0000000000000AB"
    assert cards[0]["card"]["card_type"] == 0x02
