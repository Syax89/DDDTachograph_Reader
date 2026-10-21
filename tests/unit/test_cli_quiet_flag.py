"""CLI-QUIET: ``-q`` suppresses the summary too.

The guide promises that ``-q`` / ``--quiet`` "suppresses everything on screen, so
only the files are written", but the summary branch was evaluated before the
quiet check, so ``--summary -q`` still printed the whole summary — the one
combination a batch script uses to keep its log clean.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOCK = ROOT / "tests" / "mock_data" / "mock_g1_card.ddd"

pytestmark = pytest.mark.skipif(not MOCK.exists(), reason="mock corpus not generated")


def run_cli(cwd, *args):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.run(
        [sys.executable, "-m", "app.cli", str(MOCK), *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=120, env=env,
    )


def test_quiet_suppresses_an_explicit_summary(tmp_path):
    proc = run_cli(tmp_path, "--summary", "-q")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", proc.stdout
    assert proc.stderr == "", proc.stderr


def test_quiet_still_writes_the_requested_files(tmp_path):
    out = tmp_path / "out.json"
    proc = run_cli(tmp_path, "--json", str(out), "--summary", "-q")
    assert proc.returncode == 0, proc.stderr
    assert out.is_file()
    assert proc.stdout == "" and proc.stderr == ""


def test_summary_without_quiet_is_unaffected(tmp_path):
    proc = run_cli(tmp_path, "--summary")
    assert proc.returncode == 0, proc.stderr
    assert "DDD TACHOGRAPH READER - SUMMARY" in proc.stdout
