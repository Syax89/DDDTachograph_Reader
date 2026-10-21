"""CLI-NOT-A-TACHO: a file that is not a tachograph must be an error, not a card.

``DeterministicParser`` classifies every byte it cannot structure as *Unknown*,
so a plain text file ended up with ``coverage.unknown_bytes == total_bytes`` and
no decoded section at all — yet the CLI reported it as
``File: garbage.ddd (Driver Card, Gen G1 (Digital))`` and exited ``0``. A script
that loops over downloads read that as success.

A file is only announced as a card/VU when the parser identified *some*
tachograph structure; the tests also pin the healthy path so the guard cannot
start rejecting real files.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOCK_CARD = ROOT / "tests" / "mock_data" / "mock_g1_card.ddd"


def run_cli(path, *args):
    return subprocess.run(
        [sys.executable, "-m", "app.cli", str(path), *args],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )


def test_text_file_is_rejected(tmp_path):
    """36 ASCII bytes are not a tachograph file: exit 1 and say so."""
    junk = tmp_path / "junk.ddd"
    junk.write_bytes(b"hello world not a tacho file at all")
    proc = run_cli(junk, "--summary")
    assert proc.returncode == 1
    assert "not a tachograph file" in proc.stderr.lower()
    # The old behaviour announced a card generation for those bytes.
    assert "Driver Card" not in proc.stdout
    assert "Vehicle Unit" not in proc.stdout


def test_random_bytes_are_rejected(tmp_path):
    """Binary noise must be rejected too, not just printable text."""
    junk = tmp_path / "noise.ddd"
    junk.write_bytes(bytes(range(256)) * 4)
    proc = run_cli(junk, "--summary")
    assert proc.returncode == 1
    assert "not a tachograph file" in proc.stderr.lower()


@pytest.mark.skipif(not MOCK_CARD.exists(), reason="mock corpus not generated")
def test_real_card_is_still_accepted():
    """The guard must not reject a decodable card (exit 0, summary on stdout)."""
    proc = run_cli(MOCK_CARD, "--summary")
    assert proc.returncode == 0, proc.stderr
    assert "Driver Card" in proc.stdout


def _certificate_fragment():
    """The certificate records of the mock card, alone: a real tachograph fragment."""
    data = MOCK_CARD.read_bytes()
    start = 0
    while start + 5 <= len(data):
        tag = int.from_bytes(data[start:start + 2], "big")
        length = int.from_bytes(data[start + 3:start + 5], "big")
        if tag in (0xC100, 0xC101, 0xC108, 0xC109):
            return data[start:]
        start += 5 + length
    raise AssertionError("no certificate record in the mock card")


@pytest.mark.skipif(not MOCK_CARD.exists(), reason="mock corpus not generated")
def test_certificate_records_alone_are_accepted(tmp_path):
    """A fragment that decoded real records is not "nothing decoded".

    The certificate records exist in card *and* VU images, so they are in
    neither ``CARD_ONLY_TAGS`` nor ``VU_ONLY_TAGS``. A card whose header was cut
    away but whose two certificate records parse is a tachograph fragment, not
    arbitrary bytes: the guard must not announce "no tachograph structure was
    decoded" for it.
    """
    fragment = tmp_path / "fragment.ddd"
    fragment.write_bytes(_certificate_fragment())
    out = tmp_path / "out.json"
    proc = run_cli(fragment, "--json", str(out), "-q")
    assert proc.returncode == 0, proc.stderr
    assert "not a tachograph" not in proc.stderr.lower()
    assert out.exists()
    assert json.loads(out.read_text())["metadata"]["origin"] == "driver_card"
