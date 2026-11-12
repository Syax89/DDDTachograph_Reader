"""CLI-BATCH: several files and folders in one ``tacho-cli`` run.

Several PATH arguments, or any directory, make a batch: directories contribute
their ``.ddd`` files (``--recursive`` descends), an explicit output FILE names a
directory, ``--summary`` prints one summary per file, a final table lists every
input, and one bad file is reported without stopping the others (exit 1).
The inputs are synthetic mock downloads written into a temporary directory.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.cli import _collect_inputs
from app.engine import TachoParser
from core.utils.report_format import integrity_verdict
from tests.integration import generate_mock_ddd as mock

ROOT = Path(__file__).resolve().parents[2]
SUMMARY_BANNER = "DDD TACHOGRAPH READER - SUMMARY"


def run_cli(*args, cwd=ROOT):
    return subprocess.run(
        [sys.executable, "-m", "app.cli", *map(str, args)],
        cwd=cwd, capture_output=True, text=True, timeout=300,
    )


@pytest.fixture
def corpus(tmp_path):
    """``in/`` holds a G1 card and a G2 VU, ``in/sub/`` a G2.2 card."""
    folder = tmp_path / "in"
    (folder / "sub").mkdir(parents=True)
    mock.generate_g1_card(str(folder / "g1_card.ddd"))
    mock.generate_g2_vu(str(folder / "g2_vu.DDD"))
    mock.generate_g22_card(str(folder / "sub" / "g22_card.ddd"))
    (folder / "notes.txt").write_text("not a download")
    return folder


def _table_rows(stdout):
    """The batch table's data lines, keyed by the file column."""
    lines = stdout.split("BATCH SUMMARY:", 1)[1].splitlines()
    header = next(i for i, line in enumerate(lines) if line.startswith("File"))
    return {line.split()[0]: line for line in lines[header + 1:] if line.strip()}


def test_folder_prints_one_summary_per_file_and_a_table(corpus):
    proc = run_cli(corpus, "--summary")
    assert proc.returncode == 0, proc.stderr
    # Only the top level: both letter cases of the extension, no .txt, no sub/.
    assert proc.stdout.count(SUMMARY_BANNER) == 2
    assert "BATCH SUMMARY: 2 inputs, 2 OK, 0 failed" in proc.stdout
    rows = _table_rows(proc.stdout)
    assert set(rows) == {str(corpus / "g1_card.ddd"), str(corpus / "g2_vu.DDD")}
    assert " Card " in rows[str(corpus / "g1_card.ddd")]
    assert " VU " in rows[str(corpus / "g2_vu.DDD")]


def test_folder_without_output_flag_does_not_stream_json(corpus):
    """A batch has no single JSON to put on standard output: summaries instead."""
    proc = run_cli(corpus)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count(SUMMARY_BANNER) == 2
    assert not proc.stdout.lstrip().startswith("{")


def test_recursive_descends_into_subdirectories(corpus):
    proc = run_cli(corpus, "--recursive", "--summary")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count(SUMMARY_BANNER) == 3
    assert str(corpus / "sub" / "g22_card.ddd") in _table_rows(proc.stdout)


def test_table_reports_the_canonical_verdict_and_days(corpus):
    path = corpus / "g1_card.ddd"
    result = TachoParser(str(path)).parse()
    days = len({b["date"] for b in result["activities"] if b.get("date")})
    proc = run_cli(path, corpus / "g2_vu.DDD", "-q")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == ""          # -q also holds back the table
    proc = run_cli(path, corpus / "g2_vu.DDD")
    cells = _table_rows(proc.stdout)[str(path)].split()
    assert integrity_verdict(result) in cells
    assert str(days) in cells


def test_bad_inputs_are_reported_and_the_batch_continues(corpus, tmp_path):
    empty = tmp_path / "empty.ddd"
    empty.write_bytes(b"")
    garbage = tmp_path / "garbage.ddd"
    garbage.write_bytes(bytes(range(256)) * 4)
    missing = tmp_path / "missing.ddd"
    empty_dir = tmp_path / "nothing_here"
    empty_dir.mkdir()
    out = tmp_path / "json_out"
    good = corpus / "g1_card.ddd"

    proc = run_cli(empty, garbage, good, missing, empty_dir, "--json", out)
    assert proc.returncode == 1
    for bad in (empty, garbage, missing, empty_dir):
        assert f"Error: {bad}: " in proc.stderr
    assert "no tachograph structure was decoded" in proc.stderr
    assert "file not found" in proc.stderr
    assert "no .ddd files found" in proc.stderr
    # The good file after the bad ones was still exported, into the directory.
    written = list(out.glob("*.json"))
    assert [p.name.startswith("g1_card_") for p in written] == [True]
    assert json.loads(written[0].read_text(encoding="utf-8"))["metadata"]
    assert "BATCH SUMMARY: 5 inputs, 1 OK, 4 failed" in proc.stdout


def test_all_writes_every_file_into_one_directory(corpus, tmp_path):
    twin = tmp_path / "other"
    twin.mkdir()
    mock.generate_g1_card(str(twin / "g1_card.ddd"))      # same basename
    out = tmp_path / "reports"
    proc = run_cli(corpus / "g1_card.ddd", twin / "g1_card.ddd", "--all", out, "-q")
    assert proc.returncode == 0, proc.stderr
    for ext in ("json", "pdf", "xlsx", "csv"):
        # Two inputs with one basename get two files, never one overwritten.
        assert len(list(out.glob(f"g1_card_*.{ext}"))) == 2, ext


def test_explicit_targets_are_directories_in_a_batch(corpus, tmp_path):
    out = tmp_path / "csv_out"
    proc = run_cli(corpus, "--csv", out, "--excel", out, "-q")
    assert proc.returncode == 0, proc.stderr
    assert len(list(out.glob("*.csv"))) == 2
    assert len(list(out.glob("*.xlsx"))) == 2


def test_target_that_is_a_file_fails_before_parsing(corpus, tmp_path):
    clash = tmp_path / "report.pdf"
    clash.write_text("x")
    proc = run_cli(corpus, "--pdf", clash)
    assert proc.returncode == 1
    assert "is not a directory" in proc.stderr
    assert SUMMARY_BANNER not in proc.stdout


def test_json_to_stdout_needs_a_single_input(corpus):
    proc = run_cli(corpus, "--json", "-")
    assert proc.returncode == 2
    assert "needs a single input file" in proc.stderr


def test_single_file_keeps_json_on_stdout(corpus):
    """One file path is still the classic run: JSON on stdout, no batch table."""
    proc = run_cli(corpus / "g1_card.ddd")
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["metadata"]
    assert "BATCH SUMMARY" not in proc.stdout + proc.stderr


def test_single_directory_is_a_batch_even_with_one_file(corpus):
    proc = run_cli(corpus / "sub", "--summary")
    assert proc.returncode == 0, proc.stderr
    assert "BATCH SUMMARY: 1 input, 1 OK, 0 failed" in proc.stdout


def test_collect_inputs_order_extension_case_and_dedup(corpus):
    files = [str(corpus / "g1_card.ddd")]
    entries = _collect_inputs([str(corpus), files[0]], recursive=False)
    assert entries == [(str(corpus / "g1_card.ddd"), None),
                       (str(corpus / "g2_vu.DDD"), None)]
    deep = _collect_inputs([str(corpus)], recursive=True)
    assert [Path(p).name for p, _ in deep] == ["g1_card.ddd", "g2_vu.DDD", "g22_card.ddd"]
