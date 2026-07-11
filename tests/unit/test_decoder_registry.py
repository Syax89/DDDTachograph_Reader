import struct

import pytest

from app.engine import TachoParser
from core.registry.registry import DecoderRegistry, TagDecoder
from core.registry.models import TachoResult, build_generations_tree
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


@pytest.mark.parametrize(
    ("requested_generation", "decoder_generation", "compatible"),
    [
        ("G1", "G1", True),
        ("G1", "G2", False),
        ("G1", "G2.2", False),
        ("G1", "all", True),
        ("G2", "G1", False),
        ("G2", "G2", True),
        ("G2", "G2.2", False),
        ("G2", "all", True),
        ("G2.2", "G1", False),
        ("G2.2", "G2", True),
        ("G2.2", "G2.2", True),
        ("G2.2", "all", True),
    ],
)
def test_registry_generation_compatibility_filter(
    requested_generation, decoder_generation, compatible,
):
    registry = DecoderRegistry.instance()
    registry.register_decoder(TagDecoder(
        0x6EF3, "OnlyCandidate", generation=decoder_generation))

    decoder = registry.get_decoder(0x6EF3, generation=requested_generation)

    if compatible:
        assert decoder.name == "OnlyCandidate"
    else:
        assert decoder is None


def test_registry_omitted_generation_preserves_legacy_selection():
    tag = 0x6EF4
    registry = DecoderRegistry.instance()
    registry.register_decoder(TagDecoder(tag, "G1Decoder", generation="G1"))
    registry.register_decoder(TagDecoder(tag, "G2Decoder", generation="G2", priority=1))

    assert registry.get_decoder(tag).name == "G2Decoder"


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


def test_engine_tree_uses_registered_display_name(tmp_path):
    registry = DecoderRegistry.instance()
    registry.register_decoder(TagDecoder(
        0x0526, "G22_RegistryDrivenName", generation="G2.2", priority=1))

    parser = TachoParser(str(tmp_path / "input.ddd"))
    result = TachoResult().to_dict()
    result["load_unload_records"] = [{"operation": "load"}]
    tree = build_generations_tree(result, parser.TAGS)

    assert parser.TAGS[0x0526] == "G22_RegistryDrivenName"
    assert "RegistryDrivenName" in tree["Generation 2.2"]


def test_generation_tree_uses_readable_fallback_for_unregistered_tag(tmp_path):
    parser = TachoParser(str(tmp_path / "input.ddd"))
    result = TachoResult().to_dict()
    result["gnss_auth"] = [{"status": "available"}]
    tree = build_generations_tree(result, parser.TAGS)

    assert 0x0000 not in parser.TAGS
    assert "GNSS Authentication" in tree["Generation 2.2"]
