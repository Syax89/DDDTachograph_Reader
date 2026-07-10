"""Golden snapshot regression test for real DDD files.

Parses every file in ``DDD/`` and compares the *semantically decoded* output
against a versioned golden snapshot in ``tests/golden/``. Any change to a
decoded value (not just byte coverage) makes the test fail, so decoder changes
must be reviewed consciously.

Byte-level bookkeeping (``raw_tags``, ``coverage``, ``sections``) is excluded on
purpose: it is already guarded by ``specs/semantic_coverage_audit.py`` and the
semantic-coverage tests. This snapshot watches the *meaning* of the decode.

Regenerate snapshots after an intentional change with::

    UPDATE_GOLDEN=1 .venv/bin/python -m pytest tests/test_golden_snapshot.py
"""
import json
import os
import unittest

from app.engine import TachoParser
from tests.unit.real_data import requires_real_files

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DDD_DIR = os.path.join(ROOT_DIR, "DDD")
GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden")

# Byte-level / volatile keys excluded from the semantic snapshot.
EXCLUDED_KEYS = {"raw_tags", "coverage", "sections"}
# Volatile / verbose metadata fields excluded from the snapshot.
# parsed_at is a timestamp; decoder_failures is a verbose message list whose
# count is kept (decoder_failure_count) but whose text would churn the snapshot;
# app_version changes on every release.
VOLATILE_METADATA = {"parsed_at", "decoder_failures", "app_version"}


def _normalize(value):
    """Make parser output JSON-stable and deterministic."""
    if isinstance(value, bytes):
        return {"__bytes_hex__": value.hex()}
    if isinstance(value, dict):
        return {k: _normalize(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_normalize(v) for v in value)
    return value


def semantic_snapshot(result):
    """Extract the decoded semantic payload, excluding byte-level bookkeeping."""
    payload = {k: v for k, v in result.items() if k not in EXCLUDED_KEYS}
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        payload["metadata"] = {
            k: v for k, v in metadata.items() if k not in VOLATILE_METADATA
        }
    return _normalize(payload)


def _diff_keys(expected, current):
    """Return the top-level keys whose values differ (compact mismatch report)."""
    keys = set(expected) | set(current)
    return sorted(k for k in keys if expected.get(k) != current.get(k)) or ["<none>"]


def list_ddd_files():
    if not os.path.isdir(DDD_DIR):
        return []
    return sorted(
        os.path.join(DDD_DIR, name)
        for name in os.listdir(DDD_DIR)
        if name.lower().endswith(".ddd")
    )


@requires_real_files
class TestGoldenSnapshot(unittest.TestCase):
    def test_real_files_match_golden(self):
        files = list_ddd_files()
        self.assertTrue(files, "No .ddd files found in DDD/ to snapshot")
        update = os.environ.get("UPDATE_GOLDEN") == "1"

        if update:
            os.makedirs(GOLDEN_DIR, exist_ok=True)

        pairs = []
        for path in files:
            golden_path = os.path.join(
                GOLDEN_DIR, os.path.basename(path) + ".golden.json"
            )
            if update or os.path.exists(golden_path):
                pairs.append((path, golden_path))

        if not pairs:
            self.skipTest(
                "No golden snapshots available for the present private DDD fixtures. "
                "Regenerate intentionally with UPDATE_GOLDEN=1."
            )

        for path, golden_path in pairs:
            with self.subTest(file=os.path.basename(path)):
                snapshot = semantic_snapshot(TachoParser(path).parse())

                if update:
                    with open(golden_path, "w", encoding="utf-8") as handle:
                        json.dump(snapshot, handle, indent=2, ensure_ascii=False, sort_keys=True)
                        handle.write("\n")
                    continue

                with open(golden_path, "r", encoding="utf-8") as handle:
                    expected = json.load(handle)

                # Round-trip current snapshot through JSON for a like-for-like compare.
                current = json.loads(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
                # Compare directly instead of self.assertEqual: these snapshots
                # can be several MB, and unittest's rich diff on a mismatch is
                # so large it appears to hang. Emit a compact, per-key summary.
                if current != expected:
                    self.fail(
                        f"Decoded output changed for {os.path.basename(path)}. "
                        f"Differing top-level keys: {_diff_keys(expected, current)}. "
                        f"If intentional, regenerate with UPDATE_GOLDEN=1.")

if __name__ == "__main__":
    unittest.main()
