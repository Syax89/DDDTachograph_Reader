"""Batch 14 — QA MEDIA families (CI/packaging/doc, meta-level).

Families:
  QA-DROPPED-CORPUS   (AUDIT-DROPPED-BASELINE) ``scripts/semantic_coverage_audit.py``
                      must fail when baseline corpus files disappear, not only
                      when per-file unparsed bytes grow.
  QA-FROZEN-CERT-GATE (I-F5) ``app/gui.py::_smoke_check`` must fail the frozen
                      bundle gate when the ERCA root store is empty (missing or
                      broken ``certs/``) instead of silently reporting OK.
  QA-SCREENSHOT-PII   (SELF-PUBLISH-PII) ``scripts/make_screenshots.py::anonymize``
                      must scrub ``driver.card_number`` and the holder identities
                      in ``card_iw_records`` before images are published.

These are dev/CI-tooling fixes: no parser/decoder/crypto change, so the parse
result (and the real-corpus fingerprint) is untouched. The GUI-dependent tests
skip cleanly when ``tkinter`` is unavailable.
"""
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from scripts.semantic_coverage_audit import compare_to_baseline  # noqa: E402


# ── QA-DROPPED-CORPUS (AUDIT-DROPPED-BASELINE) ─────────────────────────

class TestDroppedCorpus:
    def test_baseline_file_absent_from_corpus_is_a_regression(self):
        """A file present in the baseline but gone from the corpus must fail."""
        baseline = {"a.ddd": {"unparsed_bytes": 0}, "b.ddd": {"unparsed_bytes": 0}}
        metrics = {"a.ddd": {"unparsed_bytes": 0}}

        comparison = compare_to_baseline(metrics, baseline)

        assert comparison["dropped_from_corpus"] == ["b.ddd"]
        assert comparison["passed"] is False

    def test_empty_corpus_against_nonempty_baseline_fails(self):
        """The exact trigger: an empty/missing corpus used to iterate zero
        times and report a green gate."""
        comparison = compare_to_baseline({}, {"a.ddd": {"unparsed_bytes": 0}})

        assert comparison["dropped_from_corpus"] == ["a.ddd"]
        assert comparison["passed"] is False

    def test_full_corpus_match_still_passes(self):
        """The fix must not turn a healthy corpus red."""
        baseline = {"a.ddd": {"unparsed_bytes": 3}}
        metrics = {"a.ddd": {"unparsed_bytes": 3}}

        comparison = compare_to_baseline(metrics, baseline)

        assert comparison["dropped_from_corpus"] == []
        assert comparison["passed"] is True

    def test_missing_baseline_semantics_unchanged(self):
        """Regression guard for the pre-existing opposite direction: a current
        file that is *not* in the baseline still fails as before."""
        comparison = compare_to_baseline({"new.ddd": {"unparsed_bytes": 0}}, {})

        assert comparison["missing_baseline"] == ["new.ddd"]
        assert comparison["dropped_from_corpus"] == []
        assert comparison["passed"] is False

    def test_cli_gate_fails_on_dropped_corpus(self, tmp_path):
        """End-to-end: the CI command shape exits non-zero when the corpus is
        empty, naming the dropped baseline files."""
        empty = tmp_path / "empty_corpus"
        empty.mkdir()
        completed = subprocess.run(
            [sys.executable, "scripts/semantic_coverage_audit.py",
             "--ddd-dir", str(empty),
             "--baseline", "scripts/mock_semantic_baseline.json",
             "--fail-on-regression"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, check=False,
        )

        assert completed.returncode == 1
        assert "dropped from the corpus" in completed.stdout
        assert "mock_g2_card.ddd" in completed.stdout


# ── QA-FROZEN-CERT-GATE (I-F5) ─────────────────────────────────────────

@pytest.fixture
def gui():
    pytest.importorskip("tkinter")
    from app import gui as gui_module
    return gui_module


def _stub_parser(roots):
    """TachoParser stand-in carrying a validator with ``roots`` as its root
    store; ``parse`` returns a plausible non-error result."""
    class StubParser:
        def __init__(self, _path):
            self.validator = SimpleNamespace(root_certificates=dict(roots))

        def parse(self):
            return {
                "metadata": {"generation": "G2 (Smart)"},
                "raw_tags": {"decoded": [1]},
            }
    return StubParser


class TestFrozenCertGate:
    def test_smoke_fails_when_erca_store_is_empty(self, gui, monkeypatch):
        """A bundle whose certs/ is missing loads 0 roots; the old smoke test
        returned 0 regardless. It must now fail closed."""
        messages = []
        monkeypatch.setattr(gui, "_emit", messages.append)
        monkeypatch.setattr("app.engine.TachoParser", _stub_parser({}))

        assert gui._smoke_check("whatever.ddd") == 1
        assert any("ERCA root store empty" in m for m in messages)

    def test_smoke_passes_when_erca_roots_are_loaded(self, gui, monkeypatch):
        """With a populated root store the gate stays green."""
        messages = []
        monkeypatch.setattr(gui, "_emit", messages.append)
        monkeypatch.setattr("app.engine.TachoParser",
                            _stub_parser({"ERCA_RAW_EC_PK.bin": b"x"}))

        assert gui._smoke_check("whatever.ddd") == 0
        assert messages[-1].startswith("SMOKE OK")
        assert "erca_roots=1" in messages[-1]

    def test_smoke_fails_closed_when_validator_missing(self, gui, monkeypatch):
        """A parser without a validator must not slip through the gate."""
        class NoValidator:
            def __init__(self, _path):
                pass

            def parse(self):
                return {"metadata": {}, "raw_tags": {"decoded": [1]}}

        monkeypatch.setattr(gui, "_emit", lambda *_a: None)
        monkeypatch.setattr("app.engine.TachoParser", NoValidator)

        assert gui._smoke_check("whatever.ddd") == 1

    def test_real_certs_load_roots(self):
        """Guard against a future store layout that loads nothing: the repo
        ``certs/`` must yield at least one ERCA root. Pure core.crypto — no
        tkinter/display needed, so it runs even on a headless runner."""
        from core.crypto.signature import SignatureValidator
        validator = SignatureValidator()
        assert len(validator.root_certificates) > 0


# ── QA-SCREENSHOT-PII (SELF-PUBLISH-PII) ───────────────────────────────

@pytest.fixture
def screenshots():
    pytest.importorskip("tkinter")
    from scripts import make_screenshots
    return make_screenshots


def _realistic_data():
    return {
        "driver": {
            "surname": "ROSSI", "firstname": "MARIO",
            "card_number": "IT0000000000001234",
            "issuing_authority": "MC", "licence_number": "RO1234567",
        },
        "card_iw_records": [
            {"holder_surname": "ROSSI", "holder_first_names": "MARIO",
             "card": {"present": True, "card_number": "IT0000000000001234"}},
            {"holder_surname": "BIANCHI", "holder_first_names": "LUCA",
             "card": {"present": True, "card_number": "IT0000000000005678"}},
        ],
        "inserted_drivers": [
            {"surname": "ROSSI", "firstname": "MARIO",
             "card": {"card_number": "IT0000000000001234"}},
        ],
        "card_numbers": ["IT0000000000001234", "IT0000000000005678"],
        "activities": [
            {"time": "06:00",
             "card_driver": {"present": True, "card_number": "IT0000000000001234"},
             "card_codriver": {"present": True, "card_number": "IT0000000000005678"}},
        ],
        "vu_card_record": {"present": True,
                           "card": {"card_number": "IT0000000000004321"}},
    }


class TestScreenshotPii:
    def test_driver_card_number_is_anonymized(self, screenshots):
        """driver.card_number is rendered by the File Info panel and was left
        untouched by the previous anonymize()."""
        data = _realistic_data()

        screenshots.anonymize(data)

        assert data["driver"]["card_number"] == screenshots.FAKE_CARD_NUMBER
        assert data["driver"]["card_number"] != "IT0000000000001234"
        assert data["driver"]["surname"] != "ROSSI"

    def test_card_iw_record_holder_names_are_anonymized(self, screenshots):
        """The parser key is card_iw_records; the old code iterated a
        nonexistent card_iw key, so holder identities were never replaced."""
        data = _realistic_data()

        screenshots.anonymize(data)

        for iw in data["card_iw_records"]:
            assert iw["holder_surname"] in ("SMITH", "BROWN", "TAYLOR")
            assert iw["holder_first_names"] in ("JOHN", "MICHAEL", "DAVID")

    def test_card_iw_record_nested_card_number_is_anonymized(self, screenshots):
        """The holder's full card number lives in the nested card dict."""
        data = _realistic_data()

        screenshots.anonymize(data)

        for iw in data["card_iw_records"]:
            assert iw["card"]["card_number"] == screenshots.FAKE_CARD_NUMBER
        assert data["inserted_drivers"][0]["card"]["card_number"] == \
            screenshots.FAKE_CARD_NUMBER

    def test_card_numbers_list_is_anonymized(self, screenshots):
        """The model's top-level ``card_numbers`` list must be scrubbed too."""
        data = _realistic_data()

        screenshots.anonymize(data)

        assert data["card_numbers"] == [screenshots.FAKE_CARD_NUMBER,
                                        screenshots.FAKE_CARD_NUMBER]

    def test_event_and_vu_card_numbers_are_anonymized(self, screenshots):
        """Event ``card_driver``/``card_codriver`` and ``vu_card_record.card``
        carry the same FullCardNumber shape and must be scrubbed."""
        data = _realistic_data()

        screenshots.anonymize(data)

        assert data["activities"][0]["card_driver"]["card_number"] == \
            screenshots.FAKE_CARD_NUMBER
        assert data["activities"][0]["card_codriver"]["card_number"] == \
            screenshots.FAKE_CARD_NUMBER
        assert data["vu_card_record"]["card"]["card_number"] == \
            screenshots.FAKE_CARD_NUMBER
