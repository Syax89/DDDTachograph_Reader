"""``tacho-cli --rules``: the indicative Regulation (EC) No 561/2006 analysis.

The parser is replaced by a stub returning a synthetic driver-card result, so
these tests need no sample file: the flag's wiring is what is under test (the
analysis itself is covered by test_regulation_561.py).
"""
import json
import sys

import pytest

import app.cli as cli
import app.engine as engine

DAY = {"date": "01/01/2024", "changes": [
    {"time": "00:00", "activity": "REST", "slot": "First", "crew": False, "card_inserted": True},
    {"time": "06:00", "activity": "DRIVE", "slot": "First", "crew": False, "card_inserted": True},
    {"time": "11:00", "activity": "REST", "slot": "First", "crew": False, "card_inserted": True},
]}


class _StubParser:
    def __init__(self, path):
        self.path = path

    def parse(self):
        return {"metadata": {"filename": "stub.ddd", "is_vu": False, "generation": "G2"},
                "driver": {}, "vehicle": {}, "activities": [DAY]}


@pytest.fixture
def run(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(engine, "TachoParser", _StubParser)
    monkeypatch.setattr(cli, "_has_tachograph_structure", lambda result: True)
    source = tmp_path / "stub.ddd"
    source.write_bytes(b"\x00")

    def invoke(*args):
        monkeypatch.setattr(sys, "argv", ["tacho-cli", str(source), *args])
        try:
            cli.main()
        except SystemExit as exc:
            assert not exc.code, exc.code
        return capsys.readouterr()
    return invoke


def test_rules_prints_the_analysis_and_no_json(run):
    out = run("--rules")
    assert "561/2006" in out.out
    assert "[INFRINGEMENT] Art. 7" in out.out          # 5 h of driving without a break
    assert "not a legal determination" in out.out
    assert "DDD TACHOGRAPH READER - SUMMARY" not in out.out
    assert not out.out.lstrip().startswith("{")


def test_rules_with_summary_prints_both(run):
    out = run("--rules", "--summary")
    assert "DDD TACHOGRAPH READER - SUMMARY" in out.out
    assert "561/2006" in out.out


def test_rules_joins_the_json_on_stdout(run):
    out = run("--rules", "--json", "-")
    parsed = json.loads(out.out)
    report = parsed["regulation_561"]
    assert report["status"] == "analysed"
    assert report["summary"]["infringements"] == 1
    assert "561/2006" in out.err                        # the text follows the JSON to stderr


def test_rules_joins_a_json_file(run, tmp_path):
    target = tmp_path / "out.json"
    run("--rules", "--json", str(target))
    assert "regulation_561" in json.loads(target.read_text(encoding="utf-8"))


def test_json_without_rules_keeps_its_shape(run):
    parsed = json.loads(run("--json", "-").out)
    assert "regulation_561" not in parsed


def test_quiet_rules_prints_nothing(run, tmp_path):
    target = tmp_path / "out.json"
    out = run("-q", "--rules", "--json", str(target))
    assert out.out == "" and out.err == ""
    assert "regulation_561" in json.loads(target.read_text(encoding="utf-8"))
