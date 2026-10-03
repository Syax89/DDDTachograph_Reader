# Batch 17 Author — LOW / SEMANTIC (6 families report/CLI/log)

Work in /home/simone/ddd-review-r1/integration/batch17-author, HEAD 36b866a. Time 90 min, max steps 120.

## Families (6, total 9 ID)

Read CONFIRMATION_REPORT.md: **CLI-BOGUS-SENTINELS**, **CLI-VERBOSE-SILENT**, **LOG-PII**, **REPORT-ERROR-COUNT**, **REPORT-TIME-VALIDITY**, **REPORT-TIMEZONE**

Gravità LOW: cosmetic, internal message, dev/CI only.

## Task

1. Read confirmation report + trace
2. Fix (likely message/CLI tweaks)
3. Optional tests
4. Optional mutations

Tests in `tests/unit/test_batch17_semantic.py` if needed.

## Gate

- Full suite green (xvfb-run)
- ruff, mypy, semantic audit
- CLI smoke 6/6
- 19 real: verdicts + fingerprints IDENTICAL

## Deliverables

1. Fixes
2. Commit: `git add <files>; git commit -m "fix(batch17): 6 SEMANTIC LOW families"`
3. `.verify/FIX_R1.md`

Reference: R2016-0799 Annex 1C.
