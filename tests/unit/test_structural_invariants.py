"""Focused structural-parser invariants and dispatch validation tests."""
import struct

from core.parser.deterministic import CoverageTracker, DeterministicParser
from core.parser.g1_walker import iter_g1_vu_messages
from core.registry.registry import DecoderRegistry, TagDecoder


def _stap(tag, payload):
    return struct.pack(">HBH", tag, 0x00, len(payload)) + payload


def _warning_for(result, tag):
    return next(
        warning
        for warning in result["metadata"]["decoder_validation_warnings"]
        if warning["tag_id"] == f"0x{tag:04X}"
    )


def test_decoder_length_constraints_skip_dispatch_and_preserve_structural_coverage():
    registry = DecoderRegistry.instance()
    calls = []

    def decoder(payload, results):
        calls.append(payload)

    min_tag, max_tag, record_tag = 0x6F01, 0x6F02, 0x6F03
    registry.register_decoder(TagDecoder(min_tag, "Minimum", decoder, generation="G1", min_length=2))
    registry.register_decoder(TagDecoder(max_tag, "Maximum", decoder, generation="G1", max_length=2))
    registry.register_decoder(TagDecoder(
        record_tag, "Records", decoder, generation="G1", min_length=2, record_size=2
    ))

    raw = _stap(min_tag, b"\x01") + _stap(max_tag, b"\x01\x02\x03") + _stap(record_tag, b"\x01\x02\x03")
    result = DeterministicParser(registry=registry).parse(raw, is_vu=False)

    assert calls == []
    assert result["coverage"]["covered_pct"] == 100.0
    assert _warning_for(result, min_tag)["code"] == "decoder_min_length_violation"
    assert _warning_for(result, max_tag)["code"] == "decoder_max_length_violation"
    assert _warning_for(result, record_tag)["code"] == "decoder_record_size_violation"


def test_record_array_wrapper_satisfies_registered_record_size():
    registry = DecoderRegistry.instance()
    tag = 0x6F04
    calls = []

    def decoder(payload, results):
        calls.append(payload)

    registry.register_decoder(TagDecoder(tag, "WrappedRecords", decoder, generation="G1", record_size=2))
    wrapper = b"\x11\x00\x02\x00\x02" + b"\xAA\xBB\xCC\xDD"
    result = DeterministicParser(registry=registry).parse(_stap(tag, wrapper), is_vu=False)

    assert calls == [wrapper]
    assert "decoder_validation_warnings" not in result["metadata"]


def test_coverage_classifications_and_sections_are_non_overlapping():
    tracker = CoverageTracker(4096)
    tracker.mark_classified(0, 4096, "Container")
    tracker.mark_classified(100, 300, "Container > Child")

    classifications = tracker.get_non_overlapping_classifications()
    assert classifications == {"Container": 3896, "Container > Child": 200}
    assert sum(classifications.values()) == 4096

    for file_size in (100, 600, 4096):
        sections = tracker.get_section_report(file_size)
        intervals = [
            (int(section["start"], 16), int(section["end"], 16), section["size"])
            for section in sections.values()
        ]
        assert all(start < end and size == end - start for start, end, size in intervals)
        assert all(left[1] == right[0] for left, right in zip(intervals, intervals[1:], strict=False))
        assert sum(size for _, _, size in intervals) == file_size


def test_coverage_report_uses_neutral_byte_range_labels():
    tracker = CoverageTracker(1536)
    tracker.mark_covered(0, 1536)

    report = tracker.get_section_report(1536)

    assert list(report) == [
        "Bytes [0x000000, 0x000100)",
        "Bytes [0x000100, 0x000300)",
        "Bytes [0x000300, 0x000480)",
        "Bytes [0x000480, 0x000600)",
    ]
    assert [
        (entry["start"], entry["end"], entry["size"], entry["covered"], entry["coverage_pct"])
        for entry in report.values()
    ] == [
        ("0x000000", "0x000100", 256, 256, 100.0),
        ("0x000100", "0x000300", 512, 512, 100.0),
        ("0x000300", "0x000480", 384, 384, 100.0),
        ("0x000480", "0x000600", 384, 384, 100.0),
    ]
    semantic_labels = {"Header", "Driver Data", "Vehicle Data", "Certificates", "Signature/Tail"}
    assert semantic_labels.isdisjoint(report)


def test_g1_card_download_chain_validation_handles_thousands_of_messages():
    # The first valid marker after the opaque TREP 06 payload requires the
    # validator to inspect the complete long TREP 04 chain.
    chain = (b"\x76\x04\x00\x01" + b"\x00" * 64) * 1_500
    messages = list(iter_g1_vu_messages(b"\x76\x06payload" + chain))

    assert len(messages) == 1_501
    assert messages[0]["trep"] == 0x06
    assert messages[-1]["end"] == len(b"\x76\x06payload" + chain)
