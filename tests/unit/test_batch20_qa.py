"""Batch 20 — LOW / QA families regression guards.

Covers, one test group per confirmed family:

  QA-REPO-SLUGS        (I-F15)  one repository slug across README and docs/
  QA-STALE-CONFIG      (I-F10)  ruff/mypy config + test-doc paths resolve
  QA-STALE-DOC-MODULES (I-F7)   docs/AGENTS point at modules that exist
  QA-SYNTHETIC-CORPUS  (I-F13)  the generated mock corpus raises no decoder
                                validation warnings
  QA-WEAK-ASSERTIONS   (I-F14)  strengthened in tests/unit/test_coverage.py
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

MOCK_DIR = ROOT / "tests" / "mock_data"

DOC_FILES = [
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "CONTRIBUTING.md",
    *sorted((ROOT / "docs").rglob("*.md")),
    *sorted((ROOT / "scripts").glob("*.md")),
]


# ── QA-REPO-SLUGS (I-F15) ──────────────────────────────────────────────


def test_single_github_slug():
    """README and docs/ must reference exactly one repository slug."""
    slugs = set()
    for path in DOC_FILES:
        for match in re.findall(r"github\.com/Syax89/([A-Za-z0-9_.-]+)",
                                path.read_text(encoding="utf-8")):
            slugs.add(match[:-4] if match.endswith(".git") else match)
    assert slugs == {"DDDTachograph_Reader"}, f"divergent repo slugs: {slugs}"


def test_no_legacy_repo_dir_name():
    """The stale clone-directory name must not survive in any doc."""
    offenders = [str(p.relative_to(ROOT)) for p in DOC_FILES
                 if "ddd-tachograph-reader" in p.read_text(encoding="utf-8")]
    assert offenders == []


# ── QA-STALE-CONFIG (I-F10) ────────────────────────────────────────────


def test_ruff_per_file_ignores_reference_existing_files():
    text = (ROOT / "ruff.toml").read_text(encoding="utf-8")
    for name in re.findall(r'^"([^"]+)"\s*=', text, flags=re.MULTILINE):
        assert (ROOT / name).exists(), f"ruff.toml per-file-ignore targets missing {name}"


def test_mypy_exclude_has_no_missing_dir():
    """There is no ``specs/`` directory; the exclude pattern must not claim one."""
    exclude = next(line for line in (ROOT / "mypy.ini").read_text().splitlines()
                   if line.startswith("exclude"))
    assert "^specs/" not in exclude, "mypy.ini excludes a non-existent specs/ dir"


def test_docs_do_not_reference_missing_test_harness():
    assert "test_det.py" not in (ROOT / "docs/developer/specs.md").read_text(encoding="utf-8")


# ── QA-STALE-DOC-MODULES (I-F7) ────────────────────────────────────────


STALE_MODULE_TOKENS = [
    "tag_navigator.py",
    "g2_decoders.py",
    "g2_dispatch.py",
    "decoder_registry.py",
    "core/decoders/primitives.py",
    "core.vu_record_dispatcher",
    "core/vu_record_dispatcher",
    "g1_vu_walker",
    "architecture_migration_plan.md",
    "compare_parsers.py",
]


def test_docs_do_not_reference_removed_modules():
    offenders = []
    for path in DOC_FILES:
        body = path.read_text(encoding="utf-8")
        for token in STALE_MODULE_TOKENS:
            # Not preceded by an identifier char, so the *valid* reference
            # ``tests/unit/test_decoder_registry.py`` is not flagged.
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(token), body):
                offenders.append(f"{path.relative_to(ROOT)}: {token}")
    assert offenders == [], f"docs reference removed modules: {offenders}"


def test_referenced_modules_exist():
    for rel in ("core/registry/registry.py", "core/parser/deterministic.py",
                "core/parser/vu_dispatcher.py", "core/parser/g1_walker.py",
                "core/decoders/common.py", "core/decoders/vu_g2.py",
                "core/decoders/card_g22.py", "core/utils/tag_defs.py"):
        assert (ROOT / rel).exists(), f"documented module missing: {rel}"


# ── QA-SYNTHETIC-CORPUS (I-F13) ────────────────────────────────────────


@pytest.mark.skipif(
    not MOCK_DIR.is_dir() or len(list(MOCK_DIR.glob("*.ddd"))) < 6,
    reason="mock corpus not generated",
)
def test_mock_corpus_has_no_decoder_validation_warnings():
    """Every decoder the mock corpus targets must actually run: a structurally
    invalid payload is refused by the parser and recorded in
    ``decoder_validation_warnings``. That list must stay empty across the
    corpus (this is the CI gate in .github/workflows/test.yml)."""
    from app.engine import TachoParser

    offenders = {}
    for path in sorted(MOCK_DIR.glob("*.ddd")):
        result = TachoParser(str(path)).parse()
        warnings = result["metadata"].get("decoder_validation_warnings") or []
        if warnings:
            offenders[path.name] = warnings
    assert offenders == {}, f"mock corpus refused by decoders: {offenders}"
