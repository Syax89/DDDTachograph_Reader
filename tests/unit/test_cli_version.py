"""CLI-VERSION: ``--version`` names the reader, not the calling script.

``argparse`` fills ``%(prog)s`` from ``sys.argv[0]``, so the documented check
printed ``cli.py 2.8.0`` — and ``main.py 2.8.0`` through the compatibility entry
point, i.e. the version string depended on how the CLI was started. The GUI and
both user guides name the reader (``TachoReader 2.9.1`` in this release); the
usage line should show the command the help text itself documents
(``tacho-cli``).
"""
import subprocess
import sys
from pathlib import Path

from core.utils.version import __version__

ROOT = Path(__file__).resolve().parents[2]


def run(module, *args):
    return subprocess.run([sys.executable, "-m", module, *args],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)


def test_version_names_the_reader():
    proc = run("app.cli", "--version")
    assert proc.returncode == 0
    assert proc.stdout.strip() == f"TachoReader {__version__}"


def test_compatibility_entry_point_prints_the_same_version():
    proc = run("app.main", "--version")
    assert proc.returncode == 0
    assert proc.stdout.strip() == f"TachoReader {__version__}"


def test_help_uses_the_documented_command_name():
    proc = run("app.cli", "--help")
    assert proc.returncode == 0
    assert proc.stdout.startswith("usage: tacho-cli")
