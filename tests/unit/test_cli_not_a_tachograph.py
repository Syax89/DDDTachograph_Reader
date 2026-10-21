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
