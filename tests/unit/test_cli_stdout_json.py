"""CLI-JSON-STDOUT: standard output carries the JSON, and only the JSON.

The documented default invocation prints the compact summary *and* the JSON, and
an explicit ``--json <file>`` writes the file — but there was no way to get the
parsed structure on standard output:

  * ``tacho-cli file.ddd | jq .`` failed with ``JSONDecodeError: Expecting value:
    line 1 column 1`` because the summary came first;
  * ``--json -`` — the usual "write to stdout" spelling — silently created a file
    literally named ``-``.

The fix keeps the human output on screen (it moves to standard error when stdout
carries the JSON) and treats ``-`` as standard output.
"""
import json
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


def test_default_run_puts_parseable_json_on_stdout(tmp_path):
    proc = run_cli(tmp_path)
    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(proc.stdout)
    assert "metadata" in parsed and "driver" in parsed


def test_default_run_keeps_the_summary_visible_on_stderr(tmp_path):
    """The human summary must still be shown — just not in the JSON stream."""
    proc = run_cli(tmp_path)
    assert "DDD TACHOGRAPH READER - SUMMARY" in proc.stderr
    assert "DDD TACHOGRAPH READER - SUMMARY" not in proc.stdout


def test_dash_json_writes_to_stdout_and_creates_no_file(tmp_path):
    proc = run_cli(tmp_path, "--json", "-")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["metadata"]["filename"] == MOCK.name
    assert not (tmp_path / "-").exists(), "--json - must not create a file named '-'"


def test_summary_only_still_prints_on_stdout(tmp_path):
    """``--summary`` on its own is unchanged: the summary is standard output."""
    proc = run_cli(tmp_path, "--summary")
    assert proc.returncode == 0, proc.stderr
    assert "DDD TACHOGRAPH READER - SUMMARY" in proc.stdout
    assert proc.stdout.strip().startswith("=")


def test_json_file_plus_summary_keeps_stdout_clean(tmp_path):
    """With ``--json <file>`` the summary stays on stdout, as documented."""
    out = tmp_path / "out.json"
    proc = run_cli(tmp_path, "--json", str(out), "--summary")
    assert proc.returncode == 0, proc.stderr
    assert out.is_file()
    assert "DDD TACHOGRAPH READER - SUMMARY" in proc.stdout
