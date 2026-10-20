#!/usr/bin/env bash
# Full local gate set, in the order that matters.
#
# Step 0 is NOT optional: `tests/mock_data/` is generated and git-ignored, so a gate
# run without it silently SKIPS every mock-dependent test (that is how a GUI
# regression once reached CI green-but-local-skipped). Generate the mocks first,
# then run the same commands CI runs, and print every real exit.
#
# Usage: scripts/run_gates.sh [--fast]   (--fast skips the Xvfb run)
set -u
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
fail=0
run() {
    local name="$1"; shift
    echo "=== $name"
    "$@"
    local code=$?
    echo "--- $name exit=$code"
    [ "$code" -ne 0 ] && fail=1
    return 0
}

run "generate mock downloads" "$PY" tests/integration/generate_mock_ddd.py
run "pytest (headless)" env PYTHONPATH=. "$PY" -m pytest -q -p no:cacheprovider
if [ "${1:-}" != "--fast" ]; then
    run "pytest (xvfb)" env PYTHONPATH=. xvfb-run -a "$PY" -m pytest -q -p no:cacheprovider
fi
run "ruff" "$PY" -m ruff check .
run "mypy" "$PY" -m mypy .
run "translations" "$PY" scripts/compile_translations.py --check
run "semantic coverage (corpus)" env PYTHONPATH=. "$PY" scripts/semantic_coverage_audit.py --fail-on-regression
run "semantic coverage (mock, CI form)" env PYTHONPATH=. "$PY" scripts/semantic_coverage_audit.py \
    --ddd-dir tests/mock_data --baseline scripts/mock_semantic_baseline.json --fail-on-regression
run "git diff --check" git diff --check

echo "=== gates overall exit=$fail"
exit $fail
