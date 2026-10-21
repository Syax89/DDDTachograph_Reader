"""ENVELOPE-SIZE: the reported file size must be the file on disk.

A card image relayed in a VU ``Card Download`` (TREP 06) starts with a two-byte
envelope header; the card is decoded from ``raw[delta:]``, so the parse reports
the size of the *card image* (``len(data)``) rather than the size of the file.
``_shift_envelope_offsets`` moved every offset and the coverage total onto the
real file but skipped ``metadata``, so the GUI's file-size line and the report's
"File size" row were short by the envelope bytes.
"""
import os

import pytest

from app.engine import TachoParser
from tests.integration import generate_mock_ddd as mock


def _wrapped_card(tmp_path, kind):
    """A mock card wrapped in a TREP 06 envelope (``76 06`` + card image)."""
    plain = tmp_path / f"mock_{kind}.ddd"
    {"g1": mock.generate_g1_card, "g2": mock.generate_g2_card}[kind](str(plain))
    wrapped = tmp_path / f"wrapped_{kind}.ddd"
    wrapped.write_bytes(b"\x76\x06" + plain.read_bytes())
    return wrapped


@pytest.mark.parametrize("kind", ["g1", "g2"])
def test_reported_file_size_includes_the_envelope(tmp_path, kind):
    path = _wrapped_card(tmp_path, kind)
    result = TachoParser(str(path)).parse()
    on_disk = os.path.getsize(str(path))
    assert result["metadata"].get("envelope", {}).get("bytes") == 2
    assert result["metadata"]["file_size_bytes"] == on_disk
    assert result["coverage"]["total_bytes"] == on_disk


def test_plain_card_size_is_unchanged(tmp_path):
    """A card without an envelope keeps its own size byte for byte."""
    plain = tmp_path / "mock_g1_card.ddd"
    mock.generate_g1_card(str(plain))
    result = TachoParser(str(plain)).parse()
    assert result["metadata"]["file_size_bytes"] == os.path.getsize(str(plain))
