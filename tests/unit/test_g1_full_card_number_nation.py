"""A G1 FullCardNumber publishes its 16-character number, and its nation once.

``FullCardNumber`` (Annex 1B §2.73) is cardType(1) + cardIssuingMemberState(1) +
cardNumber(16). The numbering of a smart card already opens with the Member State
letter, so prepending the decoded nation again produced a 17-character "card
number" that matches neither the card's own ``card_number`` nor the generation-2
path (``decode_full_card_number_gen``), which keeps the two fields apart.

Every value below is synthetic.
"""
from core.decoders.vu_g1 import _parse_full_card_number
from core.parser.vu_dispatcher import decode_full_card_number_gen

#: 16 characters, the first being the Member State letter (the layout real
#: driver cards use); every digit below is synthetic filler.
NUMBER = b"I" + b"0" * 15


def test_the_number_is_published_as_stored():
    card = _parse_full_card_number(bytes([0x01, 0x1A]) + NUMBER, 0)
    assert card["card_number"] == NUMBER.decode()
    assert len(card["card_number"]) == 16
    assert card["nation"] == "I"
    assert card["card_type"] == 0x01


def test_the_generation_2_path_reads_the_same_bytes_the_same_way():
    g2 = decode_full_card_number_gen(bytes([0x01, 0x1A]) + NUMBER + bytes([0x02]), 0)
    g1 = _parse_full_card_number(bytes([0x01, 0x1A]) + NUMBER, 0)
    assert g1["card_number"] == g2["card_number"]
    assert g1["nation"] == g2["nation"]
