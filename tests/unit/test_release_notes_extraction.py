r"""RELEASE-NOTES: the workflow's extraction step must actually run.

``.github/workflows/release.yml`` publishes the GitHub release body by running
an inline shell snippet over ``CHANGELOG.md``: it takes the requested version's
section and, when that section carries ``<!-- release-notes:start/end -->``
markers, keeps only the short summary between them. The snippet is awk, so it is
never executed by the test suite, and a broken awk program inside a workflow is
invisible until a tag is pushed — which is exactly how it broke once: the
flag-reset line used an awk *regex literal* ``/^## \\[/`` (a literal backslash
followed by an unterminated ``[`` class) instead of ``/^## \[/``, so awk exited
with ``runaway regular expression`` and the release job died before publishing.

This module therefore runs the step's own shell text — read out of the workflow
and dedented, never duplicated here — with the same ``bash -e -o pipefail``
GitHub uses, against version-distinct fixture changelogs. Editing the workflow
back to a broken program makes these tests fail; fixing it makes them pass.
"""
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
STEP_NAME = "Extract release notes from CHANGELOG"

_BASH = shutil.which("bash")
_AWK = shutil.which("awk")

pytestmark = pytest.mark.skipif(
    not (_BASH and _AWK),
    reason="release-note extraction is a bash+awk snippet (absent on plain Windows)",
)


def extraction_script():
    """Return the extraction step's shell text, dedented, from the workflow."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if STEP_NAME in line)
    run_line = next(i for i in range(start, len(lines))
                    if lines[i].strip() == "run: |")
    indent = len(lines[run_line]) - len(lines[run_line].lstrip())
    body = []
    for line in lines[run_line + 1:]:
        if line.strip() and (len(line) - len(line.lstrip())) <= indent:
            break
        body.append(line)
    while body and not body[-1].strip():
        body.pop()
    return textwrap.dedent("\n".join(body))


SCRIPT = extraction_script()


def extract(tmp_path, changelog, ref_name):
    """Run the workflow step verbatim in ``tmp_path``; return the release body."""
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    script = tmp_path / "extract.sh"
    script.write_text(SCRIPT + "\n", encoding="utf-8")
    proc = subprocess.run([_BASH, "-e", "-o", "pipefail", str(script)],
                          cwd=tmp_path,
                          env={**os.environ, "GITHUB_REF_NAME": ref_name},
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, (
        f"workflow extraction step failed (exit {proc.returncode})\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    return (tmp_path / "release_notes.md").read_text(encoding="utf-8")


SHORT = ("- **Fixed** six field labels across the 33 interfaces.\n"
         "- Decoding and exports are unchanged.\n\n"
         "[Full changelog](https://example.invalid/blob/v7.1.0/CHANGELOG.md).\n")

DETAIL = ("The **Identification** and **Driving Licence Info** panels built "
          "their headings from record keys, and six catalog entries were "
          "missing from every catalog.\n")

MARKED_CHANGELOG = f"""\
## [7.1.0] - 2031-03-04

<!-- release-notes:start -->
{SHORT}<!-- release-notes:end -->

### Fixed

{DETAIL}
---

## [7.0.0] - 2031-02-02

<!-- release-notes:start -->
- Older generation release body, which must never leak.
<!-- release-notes:end -->

### Fixed

- Older generation detail, which must never leak.
"""

PLAIN_CHANGELOG = """\
## [7.2.0] - 2031-04-05

### Fixed

- Markerless detail for 7.2.0 only.

---

## [7.0.0] - 2031-02-02

### Fixed

- Older generation detail, which must never leak.
"""


def test_marked_section_publishes_only_the_short_summary(tmp_path):
    body = extract(tmp_path, MARKED_CHANGELOG, "v7.1.0")
    assert body == SHORT
    assert "Identification" not in body          # markerless detail stays out
    assert "missing from every catalog" not in body
    assert "7.0.0" not in body                   # adjacent version stays out
    assert "must never leak" not in body


def test_markerless_section_falls_back_to_the_whole_version(tmp_path):
    body = extract(tmp_path, PLAIN_CHANGELOG, "v7.2.0")
    assert "Markerless detail for 7.2.0 only." in body
    assert "must never leak" not in body
    assert "7.0.0" not in body


def test_absent_version_falls_back_to_a_bare_release_title(tmp_path):
    assert extract(tmp_path, MARKED_CHANGELOG, "v9.9.9") == "Release v9.9.9\n"
