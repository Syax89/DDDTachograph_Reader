"""Remove the emoji prefixes from the catalogs' msgids and msgstrs.

The interface used to draw its icons with emoji glued to the front of the
label ("📊  TOTALS"), which meant the emoji also ended up inside the *msgid* of
every translated string — and inside every ``msgstr``, where a translator had
copied it. The labels are now plain text and the icon is drawn from the
commissioned set (``app/icons.py``), so both sides of each entry lose the same
prefix and nothing else: this is a mechanical prefix removal, never a
re-translation, and the rest of every translation is left byte-for-byte alone.

Only the leading ``[spaces] <emoji> [spaces]`` run is touched. An entry whose
``msgstr`` does not carry the msgid's prefix is *not* guessed at: the file and
line are reported and the run fails, because a translation that dropped or moved
the emoji needs a human to look at it.

Usage:
    python3 scripts/strip_msgid_emoji.py            # rewrite the catalogs
    python3 scripts/strip_msgid_emoji.py --check    # report only, non-zero if any
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Leading ``[spaces] <emoji> [spaces]``. The ranges are the pictographic
#: blocks plus the handful of dingbats and clock faces the UI used (⚠ ✅ ❌ ❓
#: ⏱ ℹ); arrows (→) and dashes (—) are not emoji and are untouched.
_EMOJI = (
    "\U0001F000-\U0001FAFF"        # pictographs: transport, faces, symbols, cards
    "\u2600-\u27BF"                # dingbats and misc symbols: ⚠ ✅ ❌ ❓
    "\u2139"                       # ℹ information source
    "\u231a\u231b\u23f0-\u23f3"    # ⌚ ⏰ ⏱ ⏲ ⏳: watch and clock faces
)
_PREFIX = re.compile(
    r"^(?P<lead>[ \t]*)(?P<emoji>[" + _EMOJI + r"])"
    r"[\ufe0f\ufe0e\U0001F3FB-\U0001F3FF]?(?P<gap>[ \t]*)"
)


def split_prefix(text):
    """``(lead, marker, rest)`` for *text*.

    ``lead`` is the indentation the string is aligned with, ``marker`` the emoji
    and the spaces after it, ``rest`` the label. Only ``marker`` is the icon:
    the indentation is layout, so it survives (the summary panel's value cells
    are indented by two spaces and must stay indented).
    """
    match = _PREFIX.match(text)
    if not match:
        return "", "", text
    return match.group("lead"), match.group(0)[len(match.group("lead")):], \
        text[match.end():]


def _entry_literal(line, keyword):
    """The value of a ``msgid "..."`` line, unescaped, or ``None``.

    Only the escapes these catalogs actually use are decoded. The *prefix* this
    module looks for is made of spaces and emoji, which are never escaped, so
    the decoded prefix is always also the source prefix and can be sliced
    straight out of the line.
    """
    if not line.startswith(keyword + " "):
        return None
    literal = line[len(keyword) + 1:].strip()
    if not (literal.startswith('"') and literal.endswith('"')):
        return None
    return literal[1:-1].replace('\\"', '"').replace("\\\\", "\\")


def prefix_of_line(line, keyword):
    """``(lead, marker)`` of an entry line; ``("", "")`` when it has no icon."""
    literal = _entry_literal(line, keyword)
    if literal is None:
        return "", ""
    lead, marker, _rest = split_prefix(literal)
    return lead, marker


def strip_text(text):
    """Strip every emoji prefix from one catalog's source text.

    Returns ``(new_text, changed_entries, problems)``, where ``problems`` are
    ``(line number, message)`` pairs for entries the run must not guess at.
    """
    lines = text.split("\n")
    changed = 0
    problems = []
    index = 0
    while index < len(lines):
        source_lead, source_marker = prefix_of_line(lines[index], "msgid")
        if not source_marker:
            index += 1
            continue
        # The msgstr belongs to this msgid: skip comments and blank lines, then
        # the first msgstr line (no plurals/contexts in these catalogs).
        cursor = index + 1
        while cursor < len(lines) and (not lines[cursor].strip()
                                       or lines[cursor].startswith("#")):
            cursor += 1
        if cursor >= len(lines) or not lines[cursor].startswith("msgstr "):
            problems.append((index + 1, "msgid with an emoji prefix has no msgstr"))
            index += 1
            continue
        target_lead, target_marker = prefix_of_line(lines[cursor], "msgstr")
        if target_marker != source_marker:
            problems.append((
                cursor + 1,
                "msgstr does not carry the msgid's icon prefix %r (it has %r)"
                % (source_marker, target_marker)))
            index = cursor + 1
            continue
        for line_no, keyword, lead in ((index, "msgid", source_lead),
                                       (cursor, "msgstr", target_lead)):
            line = lines[line_no]
            # ``<keyword> "`` and the indentation are kept verbatim; only the
            # icon prefix after them is removed, so the closing quote and every
            # escape beyond it stay exactly where they were.
            keep = len(keyword) + 2 + len(lead)
            lines[line_no] = line[:keep] + line[keep + len(source_marker):]
        changed += 1
        index = cursor + 1
    return "\n".join(lines), changed, problems


def _block_value(block, keyword):
    """The decoded value of *keyword* in one blank-line separated block."""
    lines = block.split("\n")
    for index, line in enumerate(lines):
        if not line.startswith(keyword + " "):
            continue
        parts = [_entry_literal(line, keyword) or ""]
        for extra in lines[index + 1:]:
            if not extra.startswith('"'):
                break
            parts.append((extra[1:-1] if extra.endswith('"') else extra[1:])
                         .replace('\\"', '"').replace("\\\\", "\\"))
        return "".join(parts)
    return None


def dedupe_text(text):
    """Drop entries that the prefix stripping made identical.

    Removing the icon prefix can turn two entries into one: "❓  Incomplete
    certificates" already existed as "Incomplete certificates", and the locked
    and unlocked "CURRENT LOCK" headers lose their only textual difference in
    English. A catalog may not carry the same msgid twice, so the later entry is
    dropped and the first one kept.

    Returns ``(new_text, removed, conflicts)``; ``conflicts`` names the entries
    whose translations differed, i.e. the ones a human should look at (the
    catalogs have no msgctxt, so one English text can only have one
    translation).
    """
    blocks = text.split("\n\n")
    kept = []
    seen = {}
    removed = []
    conflicts = []
    line_no = 1
    for block in blocks:
        msgid = _block_value(block, "msgid")
        if msgid:
            if msgid in seen:
                first_msgstr = seen[msgid][0]
                msgstr = _block_value(block, "msgstr")
                removed.append((line_no, msgid))
                if msgstr != first_msgstr:
                    conflicts.append((line_no, msgid, first_msgstr, msgstr))
                line_no += block.count("\n") + 2
                continue
            seen[msgid] = (_block_value(block, "msgstr"), line_no)
        kept.append(block)
        line_no += block.count("\n") + 2
    return "\n\n".join(kept), removed, conflicts


def strip_catalog(path):
    """Rewrite one catalog in place; return ``(changed, problems)``."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    new_text, changed, problems = strip_text(text)
    new_text, removed, conflicts = dedupe_text(new_text)
    for line_no, msgid in removed:
        print("%s:%d: duplicate msgid %r dropped" % (path, line_no, msgid))
    for line_no, msgid, kept_msgstr, dropped_msgstr in conflicts:
        print("%s:%d: duplicate msgid %r keeps %r, dropped %r"
              % (path, line_no, msgid, kept_msgstr, dropped_msgstr))
    if changed or removed:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(new_text)
    return changed, problems


def catalogs():
    """Every catalog in the repository, sorted."""
    return sorted(glob.glob(os.path.join(ROOT, "locale", "*", "LC_MESSAGES", "tacho.po")))


def main(argv):
    check_only = "--check" in argv[1:]
    total = 0
    failures = []
    for path in catalogs():
        rel = os.path.relpath(path, ROOT)
        if check_only:
            with open(path, encoding="utf-8") as handle:
                pending = sum(1 for line in handle
                              if prefix_of_line(line, "msgid")[1])
            if pending:
                failures.append("%s: %d msgid(s) still carry an emoji prefix"
                                % (rel, pending))
            total += pending
            continue
        changed, problems = strip_catalog(path)
        total += changed
        for line_no, message in problems:
            failures.append("%s:%d: %s" % (rel, line_no, message))
        print("%-45s %3d entries" % (rel, changed))

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print("%d entries %s" % (total, "still prefixed" if check_only else "stripped"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
