"""Compile the gettext catalogs: ``locale/<lang>/LC_MESSAGES/tacho.po`` → ``.mo``.

Uses only the standard library: ``msgfmt`` from the gettext tools is not
installed everywhere (and never on the Windows build machine), so the small
subset of the .po format used by this project is compiled here.

The subset is deliberately *singular*: no ``msgctxt``, no ``msgid_plural`` and
no ``msgstr[N]``. Entries that use them are rejected with a clear error instead
of being compiled into a catalog that would silently translate nothing (or the
wrong thing). Fuzzy entries are skipped, exactly like ``msgfmt`` does.

Every entry is validated against its English source (the msgid):

* the msgid and msgstr must carry the same Python ``str.format`` placeholders,
  with the same conversion and format spec (``{percent:.2f}`` may not become
  ``{percent:.2%}``, nor lose a field);
* an empty msgstr (an untranslated entry) is an error — it would blank the UI
  text instead of falling back to English;
* duplicate msgids and non-string fragments (``msgid 42``) are errors.

A translation is allowed to be *identical* to the msgid: technical constants
(``PDF``, ``JSON``, ``VIN``, product names, ...) are legitimately unchanged.

The catalog header (empty msgid) is regenerated here as UTF-8 so a catalog
without one still decodes correctly through ``gettext.GNUTranslations``.

Usage:
    python3 scripts/compile_translations.py          # compile every catalog
    python3 scripts/compile_translations.py --check  # verify, no write

``--check`` recompiles each catalog in memory and compares it byte-for-byte with
the ``.mo`` on disk, so a stale (or missing) ``.mo`` fails CI instead of shipping
a bundle that ignores the last translation update.
"""
import ast
import glob
import os
import string
import struct
import sys
from typing import NoReturn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAGIC = 0x950412DE

#: The language list lives in the application (single source of truth); this
#: script runs from any directory, so make the repository importable.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from app.i18n import DEFAULT_LANGUAGE, LANGUAGES  # noqa: E402

#: Regenerated for every catalog: gettext reads the charset from here, so a
#: catalog without a header would hand back raw bytes for non-ASCII text.
_HEADER = (
    "Project-Id-Version: TachoReader\n"
    "Language: {language}\n"
    "MIME-Version: 1.0\n"
    "Content-Type: text/plain; charset=UTF-8\n"
    "Content-Transfer-Encoding: 8bit\n"
)

_UNSUPPORTED = ("msgctxt", "msgid_plural", "msgstr[")


class CatalogError(ValueError):
    """A catalog problem that must be reported, never silently swallowed."""


def _decode(fragment):
    """Decode one quoted .po string (C escapes via Python's literal parser)."""
    try:
        value = ast.literal_eval(fragment)
    except (ValueError, SyntaxError) as exc:
        raise CatalogError(f"not a quoted string: {fragment!r} ({exc})") from exc
    if not isinstance(value, str):
        raise CatalogError(f"non-string fragment: {fragment!r}")
    return value


def _placeholders(text):
    """Return the sorted ``[(field, conversion, format_spec), ...]`` of a string.

    Literal chunks carry ``field=None`` and are ignored; what remains is the
    exact set of substitutions the string performs.
    """
    try:
        parsed = string.Formatter().parse(text)
        parts = [(field, conversion or "", spec or "")
                 for _literal, field, spec, conversion in parsed
                 if field is not None]
    except ValueError as exc:
        raise CatalogError(f"invalid format string {text!r} ({exc})") from exc
    return sorted(parts)


def _check_entry(msgid, msgstr):
    """Validate one msgid/msgstr pair (structure, emptiness, placeholders)."""
    if not msgstr:
        raise CatalogError(
            f"untranslated entry {msgid!r}: msgstr is empty "
            "(translate it or delete the entry)")
    source, translation = _placeholders(msgid), _placeholders(msgstr)
    if source != translation:
        raise CatalogError(
            f"placeholders differ for {msgid!r}: expected {source}, got {translation}")


def parse_po(path):
    """Return ordered ``[(msgid, msgstr), ...]`` for a .po file.

    Fuzzy entries and the empty-msgid header are dropped (the header is
    regenerated at compile time). Raises :class:`CatalogError` with the file and
    line of the offending entry.
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    entries = []
    seen = set()
    current = {}
    fuzzy = False
    key = None
    lineno = 0

    def fail(message) -> NoReturn:
        raise CatalogError(f"{path}:{lineno}: {message}")

    def decode(fragment):
        try:
            return _decode(fragment)
        except CatalogError as exc:
            fail(str(exc))

    def flush():
        nonlocal current, fuzzy, key
        if not current:
            key = None
            return
        if "msgid" not in current:
            fail("'msgstr' without a 'msgid'")
        if "msgstr" not in current:
            fail(f"entry {current['msgid']!r} has no 'msgstr'")
        msgid, msgstr = current["msgid"], current["msgstr"]
        was_fuzzy = fuzzy
        # Reset the continuation target together with the entry: a stale key
        # would append the next entry's leading string to the entry just closed.
        current, fuzzy, key = {}, False, None
        if was_fuzzy:
            return
        if not msgid:
            return  # header: regenerated in compile_catalog()
        try:
            _check_entry(msgid, msgstr)
        except CatalogError as exc:
            fail(str(exc))
        if msgid in seen:
            fail(f"duplicate msgid {msgid!r}")
        seen.add(msgid)
        entries.append((msgid, msgstr))

    for index, raw in enumerate(lines):
        lineno = index + 1
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("#"):
            # A comment (and its flags) belongs to the entry *below* it, so a
            # completed entry must be closed before the flags are read: a
            # trailing "#, fuzzy" must not mark the entry above it fuzzy.
            if current:
                flush()
            if line.startswith("#,") and "fuzzy" in line:
                fuzzy = True
            continue
        for keyword in _UNSUPPORTED:
            if line.startswith(keyword):
                fail(f"{keyword!r} entries are not supported "
                     "(this project uses singular messages only)")
        if line == "msgid" or line.startswith("msgid "):
            if current:
                # Missing blank separator: a new entry starts right here.
                flush()
            key = "msgid"
            current[key] = decode(line[len("msgid"):].strip())
            continue
        if line == "msgstr" or line.startswith("msgstr "):
            if "msgstr" in current:
                fail("duplicate 'msgstr' in one entry")
            key = "msgstr"
            current[key] = decode(line[len("msgstr"):].strip())
            continue
        if not line.startswith('"'):
            fail(f"unexpected line {line!r}")
        if key is None:
            fail("string continuation without a 'msgid'/'msgstr'")
        current[key] += decode(line)

    lineno = len(lines)
    flush()
    return entries


def compile_catalog(pairs, language=""):
    """Return the ``.mo`` bytes for ``pairs`` (``[(msgid, msgstr), ...]``)."""
    items = [(msgid.encode("utf-8"), msgstr.encode("utf-8")) for msgid, msgstr in pairs]
    items.append((b"", _HEADER.format(language=language).encode("utf-8")))
    items.sort()
    offset = 28 + 16 * len(items)
    positions, body = [], b""
    for msgid, msgstr in items:
        positions.append((len(msgid), offset + len(body)))
        body += msgid + b"\0"
        positions.append((len(msgstr), offset + len(body)))
        body += msgstr + b"\0"
    count = len(items)
    header = struct.pack("<7I", MAGIC, 0, count, 28, 28 + 8 * count, 0, 0)
    original = b"".join(struct.pack("<2I", *positions[i * 2]) for i in range(count))
    translated = b"".join(struct.pack("<2I", *positions[i * 2 + 1]) for i in range(count))
    return header + original + translated + body


def build_catalog(po_path):
    """Return ``(mo_bytes, entry_count)`` for one .po file."""
    pairs = parse_po(po_path)
    language = os.path.basename(os.path.dirname(os.path.dirname(po_path)))
    return compile_catalog(pairs, language), len(pairs)


def catalog_paths():
    """Every ``locale/*/LC_MESSAGES/*.po`` in the source tree, sorted."""
    return sorted(glob.glob(os.path.join(ROOT, "locale", "*", "LC_MESSAGES", "*.po")))


def expected_languages():
    """Language codes that must ship a catalog (every language but English)."""
    return {code for code in LANGUAGES if code != DEFAULT_LANGUAGE}


def main(argv):
    check = "--check" in argv
    unexpected = [arg for arg in argv if arg != "--check"]
    if unexpected:
        print(f"usage: {os.path.basename(__file__)} [--check]", file=sys.stderr)
        return 2
    catalogs = catalog_paths()
    if not catalogs:
        # Every language in app.i18n.LANGUAGES (except English, the msgid
        # language) needs a catalog; none at all means the UI would silently
        # stay English, so this is a failure, not a no-op.
        print("error: no catalogs found under locale/ "
              "(expected locale/<code>/LC_MESSAGES/tacho.po per language)",
              file=sys.stderr)
        return 1
    failed = False
    found = {os.path.basename(os.path.dirname(os.path.dirname(path))) for path in catalogs}
    missing = sorted(expected_languages() - found)
    if missing:
        # A language offered in the menu without a catalog is a menu entry that
        # silently does nothing: a missing catalog must fail the build.
        print(f"error: no catalog for {len(missing)} language(s): "
              f"{', '.join(missing)}", file=sys.stderr)
        failed = True
    for po_path in catalogs:
        mo_path = po_path[:-3] + ".mo"
        try:
            data, count = build_catalog(po_path)
        except (CatalogError, OSError, UnicodeDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            failed = True
            continue
        if check:
            try:
                with open(mo_path, "rb") as fh:
                    on_disk = fh.read()
            except OSError:
                on_disk = None
            if on_disk != data:
                print(f"stale catalog: {mo_path} does not match {po_path}",
                      file=sys.stderr)
                failed = True
            else:
                print(f"{po_path}: {count} entries OK")
            continue
        with open(mo_path, "wb") as fh:
            fh.write(data)
        print(f"{po_path} -> {mo_path} ({count} entries)")
    if failed:
        print("catalogs not up to date: run "
              f"{os.path.relpath(__file__, ROOT)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
