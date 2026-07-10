import struct

from core.registry.registry import DecoderRegistry, TagDecoder
from core.parser.deterministic import DeterministicParser
from scripts.tag_decoding_matrix import rows


def test_registry_selects_card_or_vu_decoder_for_same_tag():
    tag = 0x6EEE
    registry = DecoderRegistry.instance()

    def card_decoder(payload, results):
        results["selected_decoder"] = "card"

    def vu_decoder(payload, results):
        results["selected_decoder"] = "vu"

    registry.register_decoder(TagDecoder(
        tag, "SyntheticCard", card_decoder, generation="G1", card_only=True))
    registry.register_decoder(TagDecoder(
        tag, "SyntheticVU", vu_decoder, generation="G1", vu_only=True))

    raw = struct.pack(">HBH", tag, 0x00, 1) + b"\x42"

    card_result = DeterministicParser(registry=registry).parse(raw, is_vu=False)
    vu_result = DeterministicParser(registry=registry).parse(raw, is_vu=True)

    assert card_result["selected_decoder"] == "card"
    assert vu_result["selected_decoder"] == "vu"
    assert "6EEE_SyntheticCard" in card_result["raw_tags"]
    assert "6EEE_SyntheticVU" in vu_result["raw_tags"]


def test_registry_prefers_dtype_and_parent_specific_decoder():
    tag = 0x6EEF
    registry = DecoderRegistry.instance()
    registry.register_decoder(TagDecoder(tag, "Default", generation="G1"))
    registry.register_decoder(TagDecoder(
        tag, "ParentDtypeSpecific", generation="G1",
        dtypes=(0x02,), parent_tags=(0x1234,)))

    assert registry.get_decoder(tag, generation="G1", dtype=0x01).name == "Default"
    assert registry.get_decoder(
        tag, generation="G1", dtype=0x02, parent_tag=0x1234).name == "ParentDtypeSpecific"


def test_registry_rejects_context_without_a_compatible_decoder():
    registry = DecoderRegistry.instance()
    registry.register_decoder(TagDecoder(0x6EF1, "DtypeOnly", dtypes=(0x02,)))
    registry.register_decoder(TagDecoder(0x6EF2, "ParentOnly", parent_tags=(0x1234,)))

    assert registry.get_decoder(0x6EF1, dtype=0x01) is None
    assert registry.get_decoder(0x6EF2, parent_tag=0x9999) is None


def test_registry_generation_match_beats_priority():
    tag = 0x6EF0
    registry = DecoderRegistry.instance()
    registry.register_decoder(TagDecoder(tag, "G1Decoder", generation="G1"))
    registry.register_decoder(TagDecoder(tag, "G2Decoder", generation="G2", priority=99))

    assert registry.get_decoder(tag, generation="G1").name == "G1Decoder"
    assert registry.get_decoder(tag, generation="G2").name == "G2Decoder"


def test_registered_decoders_have_normative_references():
    registry = DecoderRegistry.instance()
    missing = [f"0x{d.tag:04X} {d.name}" for d in registry.iter_decoders()
               if not d.annex_ref.strip()]

    assert missing == []


def test_generated_matrix_covers_every_registry_variant():
    registry = DecoderRegistry.instance()
    expected = {(f"0x{d.tag:04X}", d.name, d.generation) for d in registry.iter_decoders()}
    actual = {(item["tag"], item["name"], item["generation"]) for item in rows()}

    assert actual == expected
