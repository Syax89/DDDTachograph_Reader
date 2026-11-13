"""``--gpx`` / ``--kml`` on the CLI, single file and batch (synthetic mocks)."""
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from tests.integration import generate_mock_ddd as mock

ROOT = Path(__file__).resolve().parents[2]


def run_cli(*args, cwd=ROOT):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    return subprocess.run([sys.executable, "-m", "app.cli", *map(str, args)],
                          cwd=cwd, env=env, capture_output=True, text=True, timeout=300)


def test_single_file_gpx_is_written_and_stdout_is_not_json(tmp_path):
    source = tmp_path / "g2_card.ddd"
    mock.generate_g2_card(str(source))
    target = tmp_path / "route.gpx"
    proc = run_cli(source, "--gpx", target)
    assert proc.returncode == 0, proc.stderr
    assert ET.parse(target).getroot().tag.endswith("gpx")
    assert not proc.stdout.lstrip().startswith("{"), "a map export must not stream JSON"
    assert "GPX" in proc.stdout


def test_batch_kml_writes_one_file_per_input(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    mock.generate_g1_card(str(folder / "a.ddd"))
    mock.generate_g22_vu(str(folder / "b.ddd"))
    out = tmp_path / "maps"
    proc = run_cli(folder, "--kml", out, "-q")
    assert proc.returncode == 0, proc.stderr
    files = sorted(p.name for p in out.glob("*.kml"))
    assert len(files) == 2
    for name in files:
        ET.parse(out / name)


def test_bare_gpx_with_all_lands_in_the_all_directory(tmp_path):
    source = tmp_path / "g22_vu.ddd"
    mock.generate_g22_vu(str(source))
    out = tmp_path / "reports"
    proc = run_cli(source, "--all", out, "--gpx", "-q", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert len(list(out.glob("*.gpx"))) == 1
    assert not list(tmp_path.glob("*.gpx"))
    # --all alone still makes exactly the four report formats.
    out2 = tmp_path / "reports2"
    run_cli(source, "--all", out2, "-q", cwd=tmp_path)
    assert sorted(p.suffix for p in out2.iterdir()) == [".csv", ".json", ".pdf", ".xlsx"]
