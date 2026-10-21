"""CLI-LOG-NOISE: a CLI run must not chatter on stderr, and ``-q`` must silence it.

``core/crypto/signature.py`` gives ``SignatureValidator`` its own console handler
pinned at INFO *and* leaves ``propagate`` on, while ``app/cli.py`` installs a root
handler through ``logging.basicConfig``. Every message therefore reached the
terminal twice, and ``basicConfig`` only raises/lowers the *root* level, so the
validator's INFO chatter survived ``-q`` — contradicting the CLI guide ("writes
nothing except the files you ask for", "``-q`` suppresses everything on screen").

The tests run the real entry point in a subprocess: the duplicate only shows up
with a real ``basicConfig`` + handler pair, which in-process tests do not install.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MOCK = ROOT / "tests" / "mock_data" / "mock_g1_card.ddd"

# "LEVEL:" plus the optional "LoggerName:" segment that a per-module handler adds.
_PREFIX = re.compile(r"^[A-Z]+:(?:[A-Za-z_.]+:)?")

pytestmark = pytest.mark.skipif(not MOCK.exists(), reason="mock corpus not generated")


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "app.cli", str(MOCK), *args],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )


def test_summary_run_writes_nothing_to_stderr(capsys):
    """A plain ``--summary`` run must leave stderr empty (no INFO chatter)."""
    proc = run_cli("--summary")
    assert proc.returncode == 0
    assert proc.stderr == "", proc.stderr


def test_quiet_json_run_writes_nothing_to_stderr(tmp_path):
    """``-q`` must hold back the validator's INFO lines too."""
    out = tmp_path / "out.json"
    proc = run_cli("--json", str(out), "-q")
    assert proc.returncode == 0
    assert proc.stderr == "", proc.stderr
    assert out.is_file()


def test_verbose_prints_each_log_line_once():
    """``-v`` raises verbosity but must not print every line twice."""
    proc = run_cli("--summary", "-v")
    assert proc.returncode == 0
    lines = [line for line in proc.stderr.splitlines() if line.strip()]
    assert lines, "-v must still produce diagnostic output"
    # The duplicated form differed only by the ``Name:`` segment the validator's
    # own handler adds ("INFO:SignatureValidator:msg" vs "INFO: msg"), so compare
    # the rendered message with the level/logger prefix stripped.
    tails = [_PREFIX.sub("", line).strip() for line in lines]
    duplicates = {tail for tail in tails if tails.count(tail) > 1}
    assert not duplicates, f"each log line must appear once, got {lines}"
