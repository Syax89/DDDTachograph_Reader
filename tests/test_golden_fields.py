"""Cross-file invariants for all real DDD files.

Per-file field-level assertions are covered by the golden snapshot
(tests/test_golden_snapshot.py). This module guards invariants that must hold
across every file in the dataset regardless of naming.
"""
import os
import pytest
from app.engine import TachoParser
from tests.unit.real_data import real_ddd_files, require_real_file


def _parse(name):
    return TachoParser(require_real_file(name)).parse()


def _gen(r):
    return r["metadata"]["generation"]


def _cov(r):
    return r["metadata"].get("coverage_pct", 0)


def _raw_tag_keys(r):
    return sorted(r.get("raw_tags", {}).keys())


class TestGlobalInvariants:
    """Properties that must hold for every real file in the dataset."""

    _ALL_FILES = [os.path.basename(path) for path in real_ddd_files()]

    @pytest.mark.parametrize("name", _ALL_FILES)
    def test_every_file_decoded_without_errors(self, name):
        r = _parse(name)
        assert r["metadata"].get("integrity_check", "") != ""
        assert "Error" not in r["metadata"].get("integrity_check", "")

    @pytest.mark.parametrize("name", _ALL_FILES)
    def test_every_file_has_full_coverage(self, name):
        r = _parse(name)
        assert _cov(r) == 100.0, f"{name}: coverage {_cov(r)}%"

    @pytest.mark.parametrize("name", _ALL_FILES)
    def test_every_file_has_non_empty_raw_tags(self, name):
        r = _parse(name)
        tags = _raw_tag_keys(r)
        assert len(tags) > 0, f"{name}: raw_tags is empty"

    @pytest.mark.parametrize("name", _ALL_FILES)
    def test_every_file_has_generation(self, name):
        r = _parse(name)
        gen = _gen(r)
        assert gen in ("G1 (Digital)", "G2 (Smart)", "G2.2 (Smart V2)")
