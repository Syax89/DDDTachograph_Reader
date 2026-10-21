"""The opt-in load trace (DDD_TRACE_LOAD=1): off it is a no-op, on it never names the file."""
import shutil
import time
from pathlib import Path

import pytest

from core.utils import load_trace
from tests.unit.test_gui_summary_default import close, new_explorer

MOCK = Path(__file__).resolve().parents[2] / "tests" / "mock_data" / "mock_g2_card.ddd"


def test_off_is_a_no_op_and_creates_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(load_trace, "ENABLED", False)
    load_trace.event("x", a=1)
    load_trace.opened(str(MOCK))
    with load_trace.span("y"):
        pass
    load_trace.pump_report()
    assert list(tmp_path.iterdir()) == []


def test_on_traces_two_opens_without_name_or_directory(tmp_path, monkeypatch, capsys):
    if not MOCK.is_file():
        pytest.skip("mocks not generated (tests/integration/generate_mock_ddd.py)")
    home = tmp_path / "home"
    secret_dir = tmp_path / "secretdir"
    home.mkdir()
    secret_dir.mkdir()
    target = secret_dir / "SECRETNAME.ddd"
    shutil.copy(MOCK, target)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(load_trace, "ENABLED", True)
    monkeypatch.setattr(load_trace, "_opens", 0)
    app = new_explorer(monkeypatch)
    try:
        trace = home / load_trace.FILE_NAME
        for number in (1, 2):
            app._start_parse(str(target))
            end = time.monotonic() + 60
            while time.monotonic() < end and (
                    not trace.exists() or trace.read_text().count("\tidle\t") < number):
                app.update()
                time.sleep(0.01)
    finally:
        close(app)
    text = (home / load_trace.FILE_NAME).read_text(encoding="utf-8")
    for stage in ("startup\t", "open number=1", "open number=2", "worker_parse.start",
                  "worker_parse.end", "phase.", "parse_result_delivered",
                  "parse_done.start", "parse_done.end", "populate_tree.start",
                  "populate_tree.nodes", "tree_delete_previous.end",
                  "fit_tree_column.measure_calls", "update_top_bar.end",
                  "check_integrity.end", "tree_select.start", "pump_render", "\tidle\t"):
        assert stage in text, stage
    assert "SECRETNAME" not in text and str(secret_dir) not in text and str(tmp_path) not in text
    assert "ext=.ddd" in text and "size_bytes=%d" % target.stat().st_size in text
    measure = [line for line in text.splitlines() if "measure_calls" in line][0]
    print("font.measure:", measure)       # reported, visible with -s
    assert int(measure.rsplit("=", 1)[1]) > 0
    assert f"writing {home / load_trace.FILE_NAME}" in capsys.readouterr().err
