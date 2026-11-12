"""Tests for parse-error propagation to application callers."""
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from app import cli
from app.engine import TachoParser


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_missing_file_returns_structured_parse_error(tmp_path):
    result = TachoParser(str(tmp_path / "missing.ddd")).parse()

    assert result["metadata"]["parse_error"] == {
        "code": "file_not_found",
        "message": "File not found",
    }


def test_empty_file_returns_structured_parse_error(tmp_path):
    path = tmp_path / "empty.ddd"
    path.touch()

    result = TachoParser(str(path)).parse()

    assert result["metadata"]["parse_error"] == {
        "code": "empty_file",
        "message": "File is empty",
    }


def test_unexpected_parse_exception_returns_structured_parse_error(tmp_path):
    path = tmp_path / "valid.ddd"
    path.write_bytes(b"\x00")

    with patch.object(TachoParser, "_open_file", side_effect=RuntimeError("broken parser")):
        result = TachoParser(str(path)).parse()

    assert result["metadata"]["parse_error"] == {
        "code": "parse_exception",
        "message": "broken parser",
        "exception_type": "RuntimeError",
    }


def test_cli_returns_failure_and_does_not_export_parse_errors(tmp_path, monkeypatch, capsys):
    source = tmp_path / "input.ddd"
    source.write_bytes(b"\x00")
    destination = tmp_path / "report.json"

    class FailedParser:
        def __init__(self, _path):
            pass

        def parse(self):
            return {"metadata": {"parse_error": {"message": "broken parser"}}}

    monkeypatch.setattr("app.engine.TachoParser", FailedParser)
    monkeypatch.setattr("sys.argv", ["tacho-cli", str(source), "--json", str(destination)])

    with pytest.raises(SystemExit) as error:
        cli.main()

    assert error.value.code == 1
    assert not destination.exists()
    # The CLI prefixes diagnostics with a word instead of a glyph: a terminal
    # has no icon set, and the emoji it used to print was drawn by whatever
    # console font was installed.
    assert "Error: parsing failed: broken parser" in capsys.readouterr().err


def test_cli_module_returns_nonzero_for_missing_file(tmp_path):
    completed = subprocess.run(
        [sys.executable, "-m", "app.cli", str(tmp_path / "missing.ddd")],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert "Error: file not found" in completed.stderr


def test_smoke_check_rejects_structured_parse_error(monkeypatch, tmp_path):
    pytest.importorskip("tkinter")
    from app import gui

    class FailedParser:
        def __init__(self, _path):
            pass

        def parse(self):
            return {
                "metadata": {"parse_error": {"code": "empty_file", "message": "File is empty"}},
                "raw_tags": {"decoded": []},
            }

    messages = []
    monkeypatch.setattr("app.engine.TachoParser", FailedParser)
    monkeypatch.setattr(gui, "_emit", messages.append)

    assert gui._smoke_check(str(tmp_path / "input.ddd")) == 1
    assert messages[-1] == "SMOKE FAIL: parse error File is empty"


def test_oversized_file_fails_fast_with_structured_parse_error(tmp_path, monkeypatch):
    from app import engine
    path = tmp_path / "huge.ddd"
    path.write_bytes(b"\x76\x21" * 64)
    monkeypatch.setattr(engine, "MAX_FILE_SIZE_BYTES", 100)
    with patch.object(TachoParser, "_open_file") as opened:
        result = TachoParser(str(path)).parse()

    opened.assert_not_called()
    assert result["metadata"]["parse_error"]["code"] == "file_too_large"
    assert "128 bytes" in result["metadata"]["parse_error"]["message"]
    assert result["metadata"]["integrity_check"] == "File Too Large"


def test_size_cap_is_generous():
    from app.engine import MAX_FILE_SIZE_BYTES
    assert MAX_FILE_SIZE_BYTES >= 16 * 1024 * 1024
