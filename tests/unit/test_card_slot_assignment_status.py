"""An empty card slot is not an assigned one.

``CardSlotsStatus`` (§2.28 in Annex 1B, §2.152 in Annex 1C) is one octet
``'ccccdddd'B``: ``0000`` is "no card in the slot", ``0001``..``0100`` are the
four assigned card types and ``0101``..``1111`` are unassigned codes. The typed
companion therefore reports ``assigned`` only for the four assigned values — the
octet ``0x00`` (both slots empty) must not read as two assigned slots.

Every value below is synthetic.
"""
from core.decoders.vu_g1 import _g1_card_slots
from core.parser.vu_dispatcher import decode_card_slots_status


def test_generation_1_empty_slots_are_not_assigned():
    slots = _g1_card_slots(0x00)
    assert slots["driver_slot"] == "empty"
    assert slots["codriver_slot"] == "empty"
    assert slots["driver_slot_status"] == "unassigned"
    assert slots["codriver_slot_status"] == "unassigned"


def test_generation_2_empty_slots_are_not_assigned():
    slots = decode_card_slots_status(0x00)
    assert slots["driver_slot"] == "empty"
    assert slots["driver_slot_status"] == "unassigned"
    assert slots["codriver_slot_status"] == "unassigned"


def test_one_occupied_and_one_empty_slot_keep_their_own_status():
    slots = _g1_card_slots(0x01)          # driver card in, co-driver slot empty
    assert (slots["driver_slot_status"], slots["codriver_slot_status"]) == (
        "assigned", "unassigned")
    slots_g2 = decode_card_slots_status(0x01)
    assert (slots_g2["driver_slot_status"], slots_g2["codriver_slot_status"]) == (
        "assigned", "unassigned")


def test_an_unassigned_nibble_code_is_neither_type_nor_assignment():
    for value in (0x05, 0x0A, 0xFF):
        slots = _g1_card_slots(value)
        assert slots["driver_slot"] == "reserved"
        assert slots["driver_slot_type"] == "unassigned"
        assert slots["driver_slot_status"] == "unassigned"
