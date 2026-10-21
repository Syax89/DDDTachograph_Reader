"""Export of parsed tachograph data to Excel, CSV and PDF.

All exports share the formatting in :mod:`core.report_format` (readable
timestamps, humanised column names, nested structures rendered as text), so the
three formats present the same facts and the same text. They present those
facts differently: the PDF is a paginated summary report, the CSV is one text
block per section, and the workbook is the working copy — it adds typed cells
for the columns with a known semantics, moves the monthly activity subtotals to
their own sheet, and indexes its sheets from the Summary.
"""
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta
from xml.sax.saxutils import escape

from core.utils.report_format import (
    DICT_SECTIONS, VERDICT_CORRUPT, integrity_verdict, records_to_table,
    section_tables, summary_rows,
)
from core.utils.activity_stats import compute_activity_totals

_log = logging.getLogger("export")

_EXCEL_MAX_ROWS = 50000
_PDF_MAX_ROWS = 1500

#: Record sections with more visible columns than this are printed as one
#: field/value card per record (a 20-column calibration table squeezed into A4
#: loses its header and wraps every value into a column a few characters wide).
_PDF_WIDE_COLUMNS = 10

#: Sections that describe how the file was produced and verified rather than
#: what the driver did. The PDF prints them after all operational data, in a
#: clearly named Technical Appendix; Excel/CSV keep the shared section order.
#: Labels match ``core.utils.report_format.EXPORT_SECTIONS``/``DICT_SECTIONS``.
_PDF_APPENDIX_SECTIONS = frozenset({
    # Signature material and certificates.
    "EF Card Data Signatures",
    "Driver Card Certificates",
    # Calibrations and workshops.
    "Calibrations",
    "Calibration Workshops",
    # Technical identification / configuration of the unit, its sensors and the
    # card application itself.
    "VU Identifications",
    "VU Overview",
    "VU Information",
    "VU Company Info",
    "Sensor Identification",
    "Sensor Pairings",
    "Sensor GNSS Couplings",
    "Card Issuer",
    "Card Application",
    "Card Application V2",
    "IC Chip",
    "ICC Identification",
})

#: ``summary_rows`` labels that belong on the cover, split by role so a long
#: summary cannot push the totals off the page: identity facts, the file's
#: state/integrity warnings, and (everything else) file/parse details that move
#: to the appendix. No row is dropped — unknown labels default to the details
#: block.
_PDF_COVER_IDENTITY_LABELS = frozenset({
    "Driver", "Card Number", "Issuing Nation", "Expiry Date", "Birth Date",
    "Licence Number", "Preferred Language", "Vehicle Plate", "Vehicle VIN",
    "Vehicle Registration Nation",
})
_PDF_COVER_STATE_LABELS = frozenset({
    "Integrity", "Download completeness", "Missing mandatory sections",
    "Corrupted sections (data discarded)", "Structural walk",
    "Recovered data (low confidence)", "Parse warnings", "Decoder failures",
    "Origin", "Signature verification", "EF card data signatures",
})
#: Already stated by the cover's title block, so the details block repeats none
#: of them (no duplicated identity).
_PDF_SUBTITLE_LABELS = frozenset({"File", "Generation", "Source", "Parsed at"})

#: Day-date formats a daily activity record can carry (``dd/mm/yyyy`` from the
#: report formatter, ISO from raw decoders).
_PDF_DAY_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d")


_ILLEGAL_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _cell_safe(value):
    """Strip characters the XLSX writer (XML 1.0) rejects.

    A decoded field can carry control bytes (a malformed string in the file);
    openpyxl raises on them and would abort the whole export. They are unprintable
    anyway, so they are dropped rather than replaced.
    """
    if isinstance(value, str):
        return _ILLEGAL_XML.sub("", value)
    return value


def _excel_text(value):
    """A value written to a worksheet cell: formula-guarded and XML-safe.

    Every write path goes through here — a decoded field can carry a control
    byte wherever it appears, not only in a data cell.
    """
    return _cell_safe(_spreadsheet_value(value))


def _pdf_number(value):
    """An integer with thin-space grouping, as the report tables print them."""
    return f"{value:,}".replace(",", " ")


def _pdf_day_date(value):
    """A daily record's date as :class:`datetime.date`, or ``None`` if unusable.

    Only a real, complete date is accepted: a malformed or empty field must not
    leak into the cover's activity period (and must never raise).
    """
    if not isinstance(value, str):
        return None
    text = value.strip()[:10]
    if not text:
        return None
    for fmt in _PDF_DAY_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None

_SHEET_NAME_RE = re.compile(r"[\[\]*?:/\\]")
_NUMBER_TEXT_RE = re.compile(
    r"^[+-]?(?:\d{1,3}(?: \d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?$"
)


#: Characters the PDF's own font (Helvetica) cannot draw: reportlab prints a
#: black square for them, so the PDF gets a plain stand-in. The shared report
#: rows keep the original (Excel and CSV show it fine).
_PDF_STAND_INS = {"\u26a0": "!"}


def _pdf_plain(value):
    """*value* as text the PDF's font can draw."""
    text = str(value)
    for char, stand_in in _PDF_STAND_INS.items():
        text = text.replace(char, stand_in)
    return text


#: Bundled face for the characters the PDF's own font cannot encode. Helvetica is
#: a Type1 font with a single-byte WinAnsi encoding, and the official registry
#: name of code 0xB1 carries the Lithuanian "Ė" (U+0116), which it has no
#: glyph for — reportlab draws a black square. The file ships with the
#: application (``assets/fonts``, see ``build.spec``) with its upstream licence,
#: so the report never depends on a font installed on the reader's machine.
_PDF_FALLBACK_FONT = "TachoDejaVuSans"

#: The font the report is normally set in (see :func:`_pdf_markup`).
_PDF_BASE_FONT = "Helvetica"


def _register_fallback_font(value):
    """Register the bundled face and return its font name.

    *value* only appears in the failure message: a font that cannot be found
    must fail the export rather than print a boxed name.
    """
    from reportlab.pdfbase import pdfmetrics

    if _PDF_FALLBACK_FONT in pdfmetrics.getRegisteredFontNames():
        return _PDF_FALLBACK_FONT
    # Resolved like app/i18n.locale_dir: against the package, and against
    # _MEIPASS when frozen.
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    # DejaVu Sans 2.37, official dejavu-fonts-ttf-2.37.tar.bz2 —
    # https://github.com/dejavu-fonts/dejavu-fonts/releases/tag/version_2_37
    path = os.path.join(base, "assets", "fonts", "DejaVuSans.ttf")
    if not os.path.isfile(path):
        # Fail closed: a boxed identity in a report that looks complete is
        # worse than a failed export (the callers already report this).
        raise FileNotFoundError(
            f"PDF export cannot draw {value!r}: the bundled fallback font "
            f"{path} is missing from this installation")
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont(_PDF_FALLBACK_FONT, path))
    return _PDF_FALLBACK_FONT


def _pdf_canvas_font(value):
    """The font a plain canvas ``drawString`` can draw *value* with.

    Paragraphs get a per-character fallback from :func:`_pdf_markup`; canvas
    text has no markup, so a string the report's own font cannot encode is set
    in the bundled face as a whole — otherwise reportlab prints a black square
    for every character it cannot encode.
    """
    from reportlab.pdfbase import pdfmetrics

    text = str(value)
    encoding = pdfmetrics.getFont(_PDF_BASE_FONT).encName
    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        return _register_fallback_font(text)
    return _PDF_BASE_FONT


def _pdf_markup(value):
    """*value* as escaped paragraph markup the report's font can really draw.

    Representable text is escaped and returned unchanged, so an ordinary report
    keeps Helvetica, its metrics and its pagination. Only a character outside the
    font's encoding is set in the bundled fallback face — a font choice, never a
    transliteration, an ASCII repair or a stand-in.
    """
    text = str(value)
    from reportlab.pdfbase import pdfmetrics

    # The encoding reportlab itself encodes paragraphs with decides what is
    # drawable: no hand-kept character table that could drift from the font.
    encoding = pdfmetrics.getFont("Helvetica").encName
    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        pass
    else:
        return escape(text)
    if _PDF_FALLBACK_FONT not in pdfmetrics.getRegisteredFontNames():
        _register_fallback_font(text)
    parts = []
    for char in text:
        try:
            char.encode(encoding)
        except UnicodeEncodeError:
            parts.append(f'<font name="{_PDF_FALLBACK_FONT}">{escape(char)}</font>')
        else:
            parts.append(escape(char))
    return "".join(parts)


def _spreadsheet_value(value):
    """Prevent text from being interpreted as a spreadsheet formula."""
    if not isinstance(value, str):
        return value
    formula_candidate = value.lstrip(" \t\r\n")
    if (formula_candidate.startswith(("=", "+", "-", "@"))
            and not _NUMBER_TEXT_RE.fullmatch(formula_candidate)):
        return "'" + value
    return value


# ── Excel presentation ───────────────────────────────────────────────────────
#
# The workbook is the format a reader works *with*: it filters, sorts and sums.
# That only works if a cell carries a value a spreadsheet understands, so a
# column is typed when — and only when — its semantics are known here, and a
# value is converted only when it is exactly the canonical shape the shared
# report formatter prints. Identifiers, codes, sentinels (``N/A``), malformed
# values and every unknown column stay protected text: a card number with a
# leading zero, a 16-digit serial or a VIN must never be rounded or re-shaped
# by a number cell.

#: Worksheet colours — the same restrained navy/blue pair the PDF cover uses.
_EXCEL_NAVY = "1F4E79"
_EXCEL_STRIPE = "EFF4FA"
_EXCEL_SUBTOTAL = "D6E4F0"
_EXCEL_ALERT = "FFF2CC"
_EXCEL_BAD = "F8D7DA"

#: ``summary_rows`` labels whose value reports a parse/integrity problem. The
#: summary tints them so a partial download cannot be mistaken for a clean one.
_EXCEL_PROBLEM_LABELS = frozenset({
    "Missing mandatory sections",
    "Corrupted sections (data discarded)",
    "Structural walk",
    "Recovered data (low confidence)",
    "Parse warnings",
    "Decoder failures",
    "Origin",
})

#: Marker ``core.utils.report_format`` prefixes to an unattributed-time
#: duration (``"⚠ 08:00"``). Excel moves it to a Notes column so the duration
#: column stays numeric, and states in words what it means.
_EXCEL_UNKNOWN_MARK = "\u26a0"
_EXCEL_UNKNOWN_NOTE = "Unknown time: not attributed to Drive, Work, Rest or Available"

#: The shared activity report marks a monthly subtotal row with this suffix on
#: its first cell; that exact marker is what splits the two activity sheets.
_EXCEL_MONTH_TOTAL_SUFFIX = " TOTAL"
_EXCEL_MONTHLY_SHEET = "Monthly Activities"

#: Excel shows nine hours as ``09:31``, not ``9.53``: the shared ``(h)`` unit
#: would be a lie in a duration-formatted cell.
_EXCEL_DURATION_SUFFIX = " (h:mm)"
_EXCEL_DURATION_FORMAT = "[h]:mm"
#: A UTC timestamp keeps its zone in the cell: the shared formatter only appends
#: ``Z`` for a real UTC offset, and Excel itself has no time zones.
_EXCEL_UTC_FORMAT = 'yyyy-mm-dd hh:mm"Z"'

#: Columns whose values are a time or a date — an explicit allow-list of the
#: labels the shared formatter derives from real time/date fields, inventoried
#: over the real corpus *and* over the labels the decoders/parser generate for
#: columns the corpus does not exercise (``Coupling Date``, ``GNSS Timestamp``).
#: A suffix rule (``… Begin``/``… End``) also matches identifier columns ("Card
#: Driver Begin" holds a card number, not a time), so the semantics of a time
#: column are named here instead: a label that is not listed stays protected
#: text, which is lossless — a date-shaped identifier keeps its exact
#: characters. ``_EXCEL_NUMBER_LABELS`` is checked first, so an ``Odometer …``
#: column called ``Begin``/``End`` stays a number.
_EXCEL_TIME_LABELS = frozenset({
    "Begin", "Begin Time", "Calibration Country Timestamp", "Card Expiry",
    "Control Time", "Coupling Date", "Date", "Download Period Begin",
    "Download Period End", "Download Time", "Downloading Time", "End",
    "End Time", "First Overspeed Since", "GNSS Timestamp", "Insertion Time",
    "Last Control Time", "Lock In Time", "Lock Out Time", "Manufacturing Date",
    "New Time", "Next Calibration Date", "Old Time", "Pairing Date",
    "Software Installation Date", "Start", "Timestamp", "Withdrawal Time",
})

#: Odometer readings and measured metrics, published as numbers so they can be
#: summed and sorted. Everything else (codes, counters, sizes, serials, hex)
#: stays text on purpose.
_EXCEL_NUMBER_LABELS = frozenset({
    "Odometer km", "Odometer KM", "Odometer", "New Odometer", "Old Odometer",
    "Odometer Begin", "Odometer End",
    "Odometer Insertion KM", "Odometer Withdrawal KM",
    "Odometer Value", "Odometer Midnight",
    "Distance", "Max Speed KMH", "Average Speed KMH", "Speed Limit",
})

#: Canonical value shapes (see the note above).
_EXCEL_UTC_STAMP_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})Z$")
_EXCEL_DAY_DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_EXCEL_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
#: A date-only cell displays the shape of the text it came from, so the
#: workbook does not silently reshape ``04/03/2026`` into ``2026-03-04``.
_EXCEL_DAY_DATE_FORMAT = "dd/mm/yyyy"
_EXCEL_ISO_DATE_FORMAT = "yyyy-mm-dd"
_EXCEL_INT_RE = re.compile(r"^-?(?:\d{1,3}(?: \d{3})+|\d+)$")
_EXCEL_DECIMAL_RE = re.compile(r"^-?\d+\.\d{1,6}$")
_EXCEL_DURATION_RE = re.compile(r"^(\d+):([0-5]\d)$")

#: An auto-filter button sits on the right of its header cell and eats about
#: three characters of it, so every filtered column gets that much extra.
_EXCEL_FILTER_PADDING = 3

#: A sheet's note row (the section description and, on a capped section, the
#: row-limit disclosure) must be readable in *any* table width, so the merged
#: note span is guaranteed to hold at least this many characters (the table's
#: last column is widened when a narrow table cannot reach it).
_EXCEL_NOTE_MIN_WIDTH = 60
#: Excel refuses a row height above 409.5pt: a longer note cannot be shown in
#: full, so it is elided (visibly) from the front and keeps its disclosure.
_EXCEL_MAX_ROW_HEIGHT = 409.5
_EXCEL_NOTE_LINE_HEIGHT = 15
#: Width of the Summary's value / Contents column, in characters. The wrapped
#: rows are sized from this same number, so text and height cannot drift apart.
_EXCEL_SUMMARY_VALUE_WIDTH = 78

#: Sections exposed as key/value sheets are never row-capped (they are a few
#: dozen facts, not a record list) — see ``report_format.DICT_SECTIONS``.
_EXCEL_UNCAPPED_LABELS = frozenset(label for _key, label in DICT_SECTIONS)

_EXCEL_SCOPE_NOTE = (
    "Excel workbook — every sheet is one table from the parsed report. Tables are "
    "previews: nested values are shown as compact text, not as the full decoded "
    "structure, and the JSON export carries the complete parsed results."
)
_EXCEL_MONTHLY_DESCRIPTION = (
    "Monthly subtotals from the Daily Activities report — same slot-aware "
    "arithmetic, one highlighted row per month. These subtotal rows count against "
    "the same row limit as the day rows, so a month whose subtotal fell past the "
    "limit has no row here; nothing is totalled that the preview did not retain."
)


def _excel_count(value):
    """A row count as the reports print numbers: ``12 345``."""
    return f"{value:,}".replace(",", " ")


def _excel_per_line(width):
    """Characters a *width*-column merged span shows per line (conservative)."""
    return max(int(width) - 2, 10)


def _excel_wrapped_lines(text, width):
    """Lines *text* needs in a *width*-column span, so nothing is clipped.

    A hard linebreak is a displayed line of its own — ``os.path.basename`` can
    hand the Summary a file name that contains one — and ``\\r\\n``/``\\r``
    break too; each hard line then wraps on its own.
    """
    per_line = _excel_per_line(width)
    return sum(
        max(-(-len(line) // per_line), 1)
        for line in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    )


def _excel_word_wrapped_lines(text, width):
    """Lines *text* really needs in a *width*-column cell, breaking on words.

    Excel wraps a cell at word boundaries, so counting characters
    (:func:`_excel_wrapped_lines`) under-sizes a row of short words and its tail
    is cut off on screen. The greedy simulation below uses the same per-line
    budget: a word joins the current line only when it still fits with one
    space, and a word longer than a line is broken, exactly as the cell breaks
    it. Hard linebreaks split the text first, as in the character count.
    """
    per_line = _excel_per_line(width)
    lines = 0
    for hard in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        count, used = 1, 0
        for word in hard.split(" "):
            size = len(word)
            if used + (1 if used else 0) + size <= per_line:
                used += (1 if used else 0) + size
                continue
            if used:                      # no room left: the word starts a line
                count += 1
                used = 0
            if size > per_line:           # wider than a line: the cell breaks it
                broken = -(-size // per_line)
                count += broken - 1
                used = size - per_line * (broken - 1)
            else:
                used = size
        lines += count
    # A row is only ever made taller than the character count, never shorter.
    return max(lines, _excel_wrapped_lines(text, width))


def _excel_note_height(text, width):
    """Row height (points) that shows all of *text* at *width*, up to Excel's cap."""
    return min(_EXCEL_NOTE_LINE_HEIGHT * _excel_wrapped_lines(text, width),
               _EXCEL_MAX_ROW_HEIGHT)


def _excel_note_text(text, width):
    """*text* trimmed to what a 409.5pt row can show, keeping its disclosure.

    Excel cannot grow a row past 409.5pt. A note longer than that many lines is
    elided from the *front* — the row-limit disclosure the exporter appends last
    is the part that must survive — and the elision is marked, so the cut is
    visible rather than silent.

    The cut point is measured on the kept text itself: the longest suffix that
    really fits is kept. Subtracting an estimated line width instead would
    over-delete a note built from short hard lines — each break costs a whole
    line whether it holds 3 characters or 300 — taking the disclosure with it.
    """
    text = str(text)
    capacity = int(_EXCEL_MAX_ROW_HEIGHT) // _EXCEL_NOTE_LINE_HEIGHT
    if _excel_wrapped_lines(text, width) <= capacity:
        return text
    low, high = 0, len(text)      # low never fits; an empty tail always does
    while high - low > 1:
        middle = (low + high) // 2
        if _excel_wrapped_lines("\u2026 " + text[middle:].lstrip(), width) <= capacity:
            high = middle
        else:
            low = middle
    return "\u2026 " + text[high:].lstrip()


def _excel_verdict(data):
    """The shared integrity verdict, or ``None`` when it cannot be read.

    Tinting a summary row is decoration. A result container the shared
    classifier cannot walk (a malformed ``metadata``/``ef_signature_verification``
    shape) must still export — every fact is written either way — and must not
    be tinted as if it had been classified: no tint is never a trust claim.
    ``core.utils.report_format.integrity_verdict`` is shared with the other
    exports and is not changed for this.
    """
    try:
        return integrity_verdict(data)
    except (AttributeError, TypeError, ValueError):
        _log.debug("No summary integrity tint: unreadable result container",
                   exc_info=True)
        return None


def _excel_row_limit_note(exported, available):
    """The in-workbook disclosure of the row limit (never only in the log)."""
    return (
        f"Row limit: {_excel_count(exported)} of {_excel_count(available)} rows "
        f"exported — this preview stops at the {_excel_count(_EXCEL_MAX_ROWS)}-row "
        "report limit. The JSON export (or the original DDD file) holds the "
        "complete data."
    )


def _excel_contents(description, sheet_name, *, key_value):
    """A one-line index entry for a sheet, never blank.

    The shared section descriptions are the source; a section that has none
    (card certificates, the card-application tables) gets a fallback derived
    from what the sheet *is* — its kind and its name — not invented content.
    The text is never truncated: the Summary wraps it and sizes the row, so a
    long entry is fully visible instead of being cut at the column edge.
    """
    text = str(description or "").strip().split(". ")[0].rstrip(".")
    if text:
        return text
    if key_value:
        return f"Key/value table — {sheet_name}: field and value pairs, one per row."
    return f"Records table — {sheet_name}: one row per exported record."


def _excel_sheet_link(sheet_name):
    """Internal hyperlink location for *sheet_name* (quoted, ``'`` doubled)."""
    return "'" + str(sheet_name).replace("'", "''") + "'!A1"


def _excel_sheet_name(label, used):
    """A unique worksheet name Excel accepts, honouring *used* (mutable).

    Excel caps a sheet name at 31 characters and forbids ``[ ] * ? : / \\``; a
    name may not start or end with an apostrophe either. The existing
    ``_2``/``_3`` disambiguation is kept, so two sections whose labels only
    differ in a forbidden character still get their own sheet.
    """
    base = _SHEET_NAME_RE.sub("_", str(label)).strip().strip("'").strip()
    name = base[:31] or "Sheet"
    if name not in used:
        used.add(name)
        return name
    stem = name[:28].rstrip("_") or "Sheet"
    suffix = 2
    while f"{stem}_{suffix}"[:31] in used:
        suffix += 1
    name = f"{stem}_{suffix}"[:31]
    used.add(name)
    return name


def _excel_column_kinds(headers):
    """Per-column value semantics of one table (``see the constants above``)."""
    kinds = []
    for header in headers:
        label = str(header)
        if label.endswith(_EXCEL_DURATION_SUFFIX):
            kinds.append("duration")
        elif label in _EXCEL_NUMBER_LABELS:
            kinds.append("number")
        elif label in _EXCEL_TIME_LABELS:
            kinds.append("time")
        else:
            kinds.append("text")
    return kinds


def _excel_typed_value(kind, value):
    """``(cell value, number format)`` for one cell of a typed column.

    A value that is not exactly the canonical shape stays protected text, so a
    sentinel, a placeholder, a malformed value or an unknown column never turns
    into an invented number or date.
    """
    if kind == "text" or not isinstance(value, str):
        return _spreadsheet_value(value), None
    text = value.strip()
    if kind == "duration":
        match = _EXCEL_DURATION_RE.fullmatch(text)
        if match:
            minutes = int(match.group(1)) * 60 + int(match.group(2))
            return timedelta(minutes=minutes), _EXCEL_DURATION_FORMAT
        return _spreadsheet_value(value), None
    if kind == "number":
        if _EXCEL_INT_RE.fullmatch(text):
            return int(text.replace(" ", "")), None
        if _EXCEL_DECIMAL_RE.fullmatch(text):
            return float(text), None
        return _spreadsheet_value(value), None
    stamp = _EXCEL_UTC_STAMP_RE.fullmatch(text)
    if stamp:
        try:
            # Excel cannot store a time zone, so the zone lives in the format
            # (``…"Z"``) and the displayed text stays what the report printed.
            return datetime(*(int(part) for part in stamp.groups())), _EXCEL_UTC_FORMAT
        except ValueError:
            return _spreadsheet_value(value), None
    for pattern, order, number_format in (
            (_EXCEL_DAY_DATE_RE, (3, 2, 1), _EXCEL_DAY_DATE_FORMAT),
            (_EXCEL_ISO_DATE_RE, (1, 2, 3), _EXCEL_ISO_DATE_FORMAT)):
        match = pattern.fullmatch(text)
        if match:
            parts = [int(part) for part in match.groups()]
            try:
                return date(*(parts[position - 1] for position in order)), number_format
            except ValueError:
                return _spreadsheet_value(value), None
    return _spreadsheet_value(value), None


def _excel_split_activity_rows(rows):
    """Split the shared activity report rows into day rows and subtotals.

    ``build_monthly_activity_report`` interleaves each day with the subtotal of
    its month, the subtotal marked by an exact ``"MM/YYYY TOTAL"`` first cell.
    Daily Activities keeps the day rows, Monthly Activities the subtotals — the
    rows themselves are never recomputed here.

    The unattributed-time marker the shared report prefixes to an Unknown
    duration moves out of that cell into a per-row note, so the duration column
    stays numeric and the warning still travels with the row.

    Returns ``(day_rows, month_rows, has_notes)``.
    """
    days, notes, months = [], [], []
    has_notes = False
    for row in rows:
        cells = list(row)
        first = cells[0] if cells else None
        if isinstance(first, str) and first.endswith(_EXCEL_MONTH_TOTAL_SUFFIX):
            months.append(cells)
            continue
        note = ""
        for index, cell in enumerate(cells):
            if isinstance(cell, str) and cell.startswith(_EXCEL_UNKNOWN_MARK):
                duration = cell[len(_EXCEL_UNKNOWN_MARK):].strip()
                if _EXCEL_DURATION_RE.fullmatch(duration):
                    cells[index] = duration
                    note = _EXCEL_UNKNOWN_NOTE
                    has_notes = True
        days.append(cells)
        notes.append(note)
    if has_notes:
        days = [cells + [note] for cells, note in zip(days, notes, strict=True)]
    return days, months, has_notes


class ExportManager:

    # ── Excel ────────────────────────────────────────────────────────────

    @staticmethod
    def export_to_excel(data, filepath):
        """Multi-sheet .xlsx: a navigable Summary, the VU signature material and
        one sheet per data section.

        Every table is rectangular and built for reading and filtering: wrapped
        navy header band, frozen header row, auto-filter, hidden gridlines,
        landscape fit-to-width printing with the header repeated on each page,
        and column widths that leave room for the filter button. A cell is typed
        only where the column's semantics are known (day dates, UTC timestamps,
        odometers and measured speeds, activity durations) — identifiers, codes,
        ``N/A`` sentinels and malformed values stay protected text.

        Daily Activities keeps the day rows only; the shared report's monthly
        subtotal rows move to their own Monthly Activities sheet, highlighted as
        the subtotals they are. The 50 000-row report limit is unchanged and is
        still applied to the shared rows — subtotal rows included — *before*
        that split, so the monthly sheet can only show subtotals the preview
        retained. A capped section says so on its own sheet and in the Summary,
        with the exported/available row counts and the JSON alternative.
        """
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
        from openpyxl.worksheet.hyperlink import Hyperlink

        TITLE_FONT = Font(bold=True, size=14, color=_EXCEL_NAVY)
        SUBTITLE_FONT = Font(italic=True, size=9, color="595959")
        SECTION_FONT = Font(bold=True, size=11, color=_EXCEL_NAVY)
        HEADER_FONT = Font(bold=True, color="FFFFFF")
        HEADER_FILL = PatternFill("solid", fgColor=_EXCEL_NAVY)
        STRIPE_FILL = PatternFill("solid", fgColor=_EXCEL_STRIPE)
        SUBTOTAL_FILL = PatternFill("solid", fgColor=_EXCEL_SUBTOTAL)
        ALERT_FILL = PatternFill("solid", fgColor=_EXCEL_ALERT)
        BAD_FILL = PatternFill("solid", fgColor=_EXCEL_BAD)
        SUBTOTAL_FONT = Font(bold=True)
        LINK_FONT = Font(color="0563C1", underline="single")
        TOP = Alignment(vertical="top")
        TOP_RIGHT = Alignment(vertical="top", horizontal="right")
        #: For a value too wide for its column (see ``_write_table_sheet``).
        TOP_WRAP = Alignment(vertical="top", wrap_text=True)

        wb = Workbook()
        #: ``(sheet name, exported data rows, one-line contents)`` per sheet.
        index = []
        #: ``(section label, exported rows, available rows)`` for capped sections.
        limited = []
        #: Sections with no displayable column: stated in the Summary, not only
        #: in the log, so a missing sheet is never silent.
        skipped = []

        def _print_setup(ws, *, title_row=None, orientation="landscape"):
            """Print-ready table: hidden gridlines, landscape, fit to one page
            wide, and the header row repeated on every printed page."""
            ws.sheet_view.showGridLines = False
            if title_row:
                ws.print_title_rows = f"{title_row}:{title_row}"
            ws.page_setup.orientation = orientation
            ws.page_setup.fitToWidth = 1
            ws.page_setup.fitToHeight = 0
            ws.sheet_properties.pageSetUpPr.fitToPage = True

        def _write_table_sheet(ws, headers, rows, description="", *, subtotal_rows=()):
            """One rectangular table sheet: description, header, rows."""
            kinds = _excel_column_kinds(headers)
            widths = []
            for idx, header in enumerate(headers, start=1):
                width = len(str(header))
                for row in rows[:200]:
                    if idx <= len(row) and row[idx - 1] is not None:
                        width = max(width, len(str(row[idx - 1])))
                widths.append(min(max(width + _EXCEL_FILTER_PADDING + 2, 9), 55))
                ws.column_dimensions[get_column_letter(idx)].width = widths[-1]

            header_row = 1
            if description:
                # The note must be readable at *any* table width — a one-column
                # table is the narrow case. The table's last column is widened
                # until the merged note span holds _EXCEL_NOTE_MIN_WIDTH
                # characters (the table itself stays rectangular: no phantom
                # columns, no data column but the last one touched), and the
                # row is sized from that real width with no line cap, so
                # "Row limit: N of M rows exported … JSON … complete data."
                # cannot be cut off inside the cell.
                deficit = _EXCEL_NOTE_MIN_WIDTH - sum(widths)
                if deficit > 0:
                    widths[-1] += deficit
                    ws.column_dimensions[get_column_letter(len(widths))].width = widths[-1]
                note_width = sum(widths)
                note = _excel_note_text(description, note_width)
                ws.merge_cells(start_row=1, start_column=1, end_row=1,
                               end_column=len(headers))
                cell = ws.cell(row=1, column=1, value=_excel_text(note))
                cell.font = SUBTITLE_FONT
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                ws.row_dimensions[1].height = _excel_note_height(note, note_width)
                header_row = 2

            for col, header in enumerate(headers, start=1):
                cell = ws.cell(row=header_row, column=col,
                               value=_excel_text(str(header)))
                cell.font = HEADER_FONT
                cell.fill = HEADER_FILL
                cell.alignment = Alignment(vertical="center", wrap_text=True)
            header_lines = 1
            for idx, header in enumerate(headers):
                per_line = max(int(widths[idx]) - 1, 1)
                header_lines = max(header_lines, -(-len(str(header)) // per_line))
            ws.row_dimensions[header_row].height = 15 * min(header_lines, 3)

            def _cell_clips(row, col):
                """Does a populated cell right of *col* clip a too-wide value?

                Text spills across empty neighbours and prints in full, so only
                a value that something on its right would cover is wrapped.
                """
                return any(other is not None and other != ""
                           for other in row[col:len(headers)])

            clipped = False
            for offset, row in enumerate(rows):
                excel_row = header_row + 1 + offset
                is_subtotal = offset in subtotal_rows
                row_lines = 1
                for col in range(1, len(headers) + 1):
                    raw = row[col - 1] if col <= len(row) else None
                    value, number_format = _excel_typed_value(kinds[col - 1], raw)
                    # A malformed string in the file can carry control bytes, which
                    # XML 1.0 forbids: drop them instead of aborting the export.
                    cell = ws.cell(row=excel_row, column=col, value=_cell_safe(value))
                    if number_format:
                        cell.number_format = number_format
                    typed = isinstance(value, (int, float, date, datetime, timedelta))
                    cell.alignment = TOP_RIGHT if typed else TOP
                    if is_subtotal:
                        cell.font = SUBTOTAL_FONT
                        cell.fill = SUBTOTAL_FILL
                    elif offset % 2 == 1:
                        cell.fill = STRIPE_FILL
                    if isinstance(value, str) and _cell_clips(row, col):
                        # A populated neighbour cell on the right clips text
                        # wider than its column, so wrap it and grow the row for
                        # the lines real word wrapping needs. The cell keeps its
                        # exact text (no newline, ellipsis or shortening); cells
                        # that fit, and cells with empty space to their right
                        # (the value spills across it, as it always did), are
                        # left alone with their own alignment and row height.
                        lines = _excel_word_wrapped_lines(value, widths[col - 1])
                        if lines > 1:
                            cell.alignment = TOP_WRAP
                            row_lines = max(row_lines, lines)
                if row_lines > 1:
                    # Height is per row: the tallest wrapped value sets it.
                    # Excel's own ceiling is 409.5pt, so a value beyond ~27
                    # lines still cannot be shown in a cell — logged once per
                    # sheet rather than passed over (the JSON carries it).
                    ws.row_dimensions[excel_row].height = min(
                        _EXCEL_NOTE_LINE_HEIGHT * row_lines, _EXCEL_MAX_ROW_HEIGHT)
                    if (_EXCEL_NOTE_LINE_HEIGHT * row_lines > _EXCEL_MAX_ROW_HEIGHT
                            and not clipped):
                        clipped = True
                        _log.warning("Excel: a value on sheet '%s' is taller than "
                                     "Excel's maximum row height; the JSON export "
                                     "holds it in full", ws.title)

            ws.freeze_panes = f"A{header_row + 1}"
            if rows:
                last_col = get_column_letter(len(headers))
                ws.auto_filter.ref = f"A{header_row}:{last_col}{header_row + len(rows)}"
            _print_setup(ws, title_row=header_row)

        def _add_sheet(label, description, headers, rows, *, subtotal_rows=(),
                       key_value=False):
            name = _excel_sheet_name(label, used_names)
            sheet = wb.create_sheet(name)
            _write_table_sheet(sheet, headers, rows, description,
                               subtotal_rows=subtotal_rows)
            index.append((name, len(rows),
                          _excel_contents(description, name, key_value=key_value)))

        # ── Summary (the facts and the scope note; the warnings and the sheet
        # index are appended once every sheet exists) ────────────────────
        summary = wb.active
        summary.title = "Summary"
        _print_setup(summary, orientation="portrait")
        summary.column_dimensions["A"].width = 30
        summary.column_dimensions["B"].width = _EXCEL_SUMMARY_VALUE_WIDTH
        summary.column_dimensions["C"].width = 9
        summary.cell(row=1, column=1, value="DDD Tachograph Report").font = TITLE_FONT
        note = summary.cell(row=2, column=1, value=_excel_text(_EXCEL_SCOPE_NOTE))
        note.font = SUBTITLE_FONT
        note.alignment = Alignment(wrap_text=True, vertical="top")
        summary.merge_cells(start_row=2, start_column=1, end_row=2, end_column=3)
        summary.row_dimensions[2].height = _excel_note_height(
            _EXCEL_SCOPE_NOTE, 30 + _EXCEL_SUMMARY_VALUE_WIDTH + 9)

        verdict = _excel_verdict(data)
        row = 4
        summary.cell(row=row, column=1, value="File Summary").font = SECTION_FONT
        row += 1
        for field, value in summary_rows(data):
            if not (field or value):
                row += 1
                continue
            label_cell = summary.cell(row=row, column=1, value=_excel_text(field))
            label_cell.font = Font(bold=True)
            label_cell.alignment = TOP
            value_cell = summary.cell(row=row, column=2, value=_excel_text(value))
            value_cell.alignment = Alignment(vertical="top", wrap_text=True)
            if field in _EXCEL_PROBLEM_LABELS:
                label_cell.fill = ALERT_FILL
                value_cell.fill = ALERT_FILL
            elif field == "Integrity" and verdict == VERDICT_CORRUPT:
                value_cell.fill = BAD_FILL
            summary.row_dimensions[row].height = _excel_note_height(
                "" if value is None else value, _EXCEL_SUMMARY_VALUE_WIDTH)
            row += 1

        # ── TREP signature material and VU certificates (kept, uncapped) ──
        used_names = {"Summary"}
        sv = data.get("signature_verification")
        treps = (sv.get("treps") or []) if isinstance(sv, dict) else []
        if treps:
            headers, rows = records_to_table(treps)
            if headers:
                _add_sheet("TREP Signatures",
                           "Signature verification of each TREP block (VU files).",
                           headers, rows)
            else:
                _log.warning("Skipping 'TREP Signatures': no visible export columns")
                skipped.append("TREP Signatures")
        certs = data.get("vu_certificates") or []
        if certs:
            headers, rows = records_to_table(certs)
            if headers:
                _add_sheet("VU Certificates",
                           "Certificates found in the file (VU files).",
                           headers, rows)
            else:
                _log.warning("Skipping 'VU Certificates': no visible export columns")
                skipped.append("VU Certificates")

        # ── Data sections ────────────────────────────────────────────────
        for label, desc, headers, rows, _truncated in section_tables(data):
            if not headers:
                _log.warning("Skipping '%s': no visible export columns", label)
                skipped.append(label)
                continue
            if label in _EXCEL_UNCAPPED_LABELS:
                retained = rows
            else:
                retained = rows[:_EXCEL_MAX_ROWS]
            if len(retained) < len(rows):
                limited.append((label, len(retained), len(rows)))
                _log.warning("Truncating '%s' to %d rows (Excel limit)",
                             label, _EXCEL_MAX_ROWS)
                desc = f"{desc} {_excel_row_limit_note(len(retained), len(rows))}".strip()

            if label == "Daily Activities":
                day_rows, month_rows, has_notes = _excel_split_activity_rows(retained)
                duration_headers = [
                    header.replace(" (h)", _EXCEL_DURATION_SUFFIX)
                    if str(header).endswith(" (h)") else header
                    for header in headers
                ]
                daily_note = ("Monthly subtotal rows are listed on the separate "
                              "Monthly Activities sheet.")
                if has_notes:
                    daily_note = (f"{daily_note} The Notes column carries the status "
                                  "text that is kept out of the numeric durations.")
                _add_sheet(label, f"{desc} {daily_note}".strip(), duration_headers + (
                    ["Notes"] if has_notes else []), day_rows)
                if month_rows:
                    monthly_desc = _EXCEL_MONTHLY_DESCRIPTION
                    if len(retained) < len(rows):
                        monthly_desc = (f"{monthly_desc} "
                                        f"{_excel_row_limit_note(len(retained), len(rows))}")
                    _add_sheet(_EXCEL_MONTHLY_SHEET, monthly_desc,
                               ["Month"] + duration_headers[1:], month_rows,
                               subtotal_rows=range(len(month_rows)))
                continue

            _add_sheet(label, desc, headers, retained,
                       key_value=label in _EXCEL_UNCAPPED_LABELS)

        # ── Summary: warnings, limits and the sheet index ────────────────
        row += 1
        summary.cell(row=row, column=1, value="Warnings and limits").font = SECTION_FONT
        row += 1
        limit_rows = [
            (f"Row limit — {label}",
             f"{_excel_count(exported)} of {_excel_count(available)} rows exported. "
             "The JSON export (or the original DDD file) holds the complete data.")
            for label, exported, available in limited
        ] or [("Row limit",
               f"No section reached the {_excel_count(_EXCEL_MAX_ROWS)}-row report "
               "limit: every table is complete.")]
        limit_rows.append((
            "Nested values",
            "Shown as compact report text rather than the full decoded structure — "
            "the JSON export carries that."))
        limit_rows.append((
            "Uncapped sheets",
            "Key/value sheets (card application, VU information, sensor "
            "identification, …), the TREP signature list and the VU certificate "
            "list are not row-capped."))
        for label in skipped:
            limit_rows.append((
                f"No visible columns — {label}",
                "Every value this section carries is internal bookkeeping, so no "
                "sheet was written for it. The JSON export keeps the raw values."))
        if any(name == _EXCEL_MONTHLY_SHEET for name, _count, _contents in index):
            limit_rows.append((
                "Monthly Activities",
                "Holds only the monthly subtotal rows the row limit retained; a "
                "month cut before its subtotal has no total row, and Daily "
                "Activities holds the day rows only."))
        for label, value in limit_rows:
            label_cell = summary.cell(row=row, column=1, value=_excel_text(label))
            label_cell.font = Font(bold=True)
            label_cell.alignment = TOP
            value_cell = summary.cell(row=row, column=2, value=_excel_text(value))
            value_cell.alignment = Alignment(vertical="top", wrap_text=True)
            summary.row_dimensions[row].height = _excel_note_height(
                value, _EXCEL_SUMMARY_VALUE_WIDTH)
            row += 1

        row += 1
        summary.cell(row=row, column=1,
                     value="Sheets in this workbook").font = SECTION_FONT
        row += 1
        for col, title in ((1, "Sheet"), (2, "Contents"), (3, "Rows")):
            cell = summary.cell(row=row, column=col, value=title)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(vertical="center",
                                       horizontal="right" if col == 3 else "left")
        row += 1
        for name, count, contents in index:
            link_cell = summary.cell(row=row, column=1, value=_excel_text(name))
            # An internal jump to this workbook's own sheet — never an external
            # target and never a HYPERLINK() formula. The location is quoted and
            # its apostrophes doubled exactly as Excel's own reference syntax
            # requires, so a sheet called "Driver's Card" still resolves.
            link_cell.hyperlink = Hyperlink(ref=link_cell.coordinate,
                                            location=_excel_sheet_link(name),
                                            display=name)
            link_cell.font = LINK_FONT
            link_cell.alignment = TOP
            contents_cell = summary.cell(row=row, column=2,
                                         value=_excel_text(contents))
            # Wrapped and sized to the real column width: an index entry is
            # always fully visible, never cut at the column edge.
            contents_cell.alignment = Alignment(vertical="top", wrap_text=True)
            summary.row_dimensions[row].height = _excel_note_height(
                contents, _EXCEL_SUMMARY_VALUE_WIDTH)
            count_cell = summary.cell(row=row, column=3, value=count)
            count_cell.alignment = TOP_RIGHT
            row += 1

        wb.save(filepath)

    # ── CSV ──────────────────────────────────────────────────────────────

    @staticmethod
    def export_to_csv(data, filepath):
        """Section-block CSV: every section gets a title row, its own header
        and rows, separated by a blank line — readable in any spreadsheet."""
        import csv

        with open(filepath, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")

            def _write_row(row, *, protect=True):
                # ``protect`` is off only for the section markers this function
                # writes itself: a marker is not data, and ``=== X ===`` starts
                # with ``=``, so the formula guard would rename every section
                # (``'=== DAILY ACTIVITIES ===``) and break the documented
                # marker. Data, headers and descriptions stay protected.
                writer.writerow([_spreadsheet_value(value) for value in row]
                                if protect else row)

            _write_row(["DDD TACHOGRAPH REPORT"])
            for field, value in summary_rows(data):
                if field or value:
                    _write_row([field, value])
            _write_row([])

            wrote_any = False
            for label, desc, headers, rows, truncated in section_tables(data):
                _write_row([f"=== {label.upper()} ==="], protect=False)
                if desc:
                    _write_row([desc])
                _write_row(headers)
                for row in rows:
                    _write_row(row)
                if truncated:
                    _write_row(["… (truncated)"])
                _write_row([])
                wrote_any = True

            if not wrote_any:
                _write_row(["No data found"])

    # ── PDF ──────────────────────────────────────────────────────────────

    @staticmethod
    def export_to_pdf(data, filepath):
        """A4 landscape summary report (reportlab).

        Three parts, in order: a cover (title, source/generation, activity
        period, identity, file state, activity totals), the populated
        operational sections in their shared order, then a clearly labelled
        Technical Appendix (signature material, certificates, calibrations, VU
        configuration, file-level parse details).

        Durations are ``h:mm`` everywhere, numeric activity columns are
        right-aligned paragraphs, a section wider than
        :data:`_PDF_WIDE_COLUMNS` visible columns becomes one field/value card
        per record instead of a squeezed table, and every section stops at
        :data:`_PDF_MAX_ROWS` rows with a visible warning that points at the
        JSON export for the complete parsed results.
        """
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            CondPageBreak, HRFlowable, LongTable, Paragraph, SimpleDocTemplate,
            TableStyle,
        )

        from core.utils.version import __version__

        def _pdf_text(value):
            # Drawable text is unchanged; unsupported characters use the bundled
            # face instead of a black square (see :func:`_pdf_markup`).
            return _pdf_markup(_pdf_plain(value))

        def _cell_text(value):
            """A cell's text: ``None`` is blank, but ``0``/``False`` stay visible."""
            return "" if value is None else str(value)

        PRIMARY = colors.HexColor("#1F4E79")
        STRIPE = colors.HexColor("#EFF4FA")
        GRID = colors.HexColor("#B8C7D9")
        TOTAL_BG = colors.HexColor("#D6E4F0")
        LIGHT_GRAY = colors.HexColor("#888888")
        TEXT_GRAY = colors.HexColor("#4A4A4A")

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("TachoTitle", parent=styles["Title"],
                                     textColor=PRIMARY, fontSize=22, spaceAfter=2,
                                     leading=26)
        subtitle_style = ParagraphStyle("TachoSubtitle", parent=styles["Normal"],
                                        fontSize=9, textColor=LIGHT_GRAY, spaceAfter=2)
        cover_line_style = ParagraphStyle("TachoCoverLine", parent=styles["BodyText"],
                                          fontSize=9.5, leading=12.5, textColor=PRIMARY,
                                          spaceAfter=1)
        cover_note_style = ParagraphStyle("TachoCoverNote", parent=styles["BodyText"],
                                          fontSize=7.5, leading=9.5, textColor=TEXT_GRAY,
                                          spaceBefore=1.5, spaceAfter=1)
        # keepWithNext groups a heading (and the description under it) with the
        # first flowable of its section, so a pagination boundary can never leave
        # "VU Identifications" alone above a card that starts on the next page.
        section_style = ParagraphStyle("TachoSection", parent=styles["Heading2"],
                                       textColor=PRIMARY, fontSize=13, spaceBefore=10,
                                       spaceAfter=4, leading=16, keepWithNext=1)
        cover_heading_style = ParagraphStyle("TachoCoverHeading", parent=section_style,
                                             fontSize=10.5, spaceBefore=9,
                                             spaceAfter=3, leading=13)
        month_style = ParagraphStyle("TachoMonth", parent=styles["Heading3"],
                                     textColor=PRIMARY, fontSize=11, spaceBefore=5,
                                     spaceAfter=2, leading=14, keepWithNext=1)
        cell_style = ParagraphStyle("TachoCell", parent=styles["BodyText"],
                                    fontSize=8, leading=10)
        cell_right_style = ParagraphStyle("TachoCellRight", parent=cell_style,
                                          alignment=2)
        head_style = ParagraphStyle("TachoHead", parent=cell_style,
                                    textColor=colors.white, fontName="Helvetica-Bold",
                                    fontSize=8, leading=10)
        head_right_style = ParagraphStyle("TachoHeadRight", parent=head_style,
                                          alignment=2)
        total_style = ParagraphStyle("TachoTotal", parent=cell_style,
                                     fontName="Helvetica-Bold", fontSize=8)
        total_right_style = ParagraphStyle("TachoTotalRight", parent=total_style,
                                           alignment=2)
        # The activity table is set a point larger than the generic record
        # tables: it is the section most readers print and read row by row,
        # while still fitting a normal full month on one page.
        act_cell_style = ParagraphStyle("TachoActCell", parent=styles["BodyText"],
                                        fontSize=8.5, leading=9.2)
        act_cell_right_style = ParagraphStyle("TachoActCellRight",
                                              parent=act_cell_style, alignment=2)
        act_head_style = ParagraphStyle("TachoActHead", parent=head_style,
                                        fontSize=8.5, leading=9.2)
        act_head_right_style = ParagraphStyle("TachoActHeadRight",
                                              parent=act_head_style, alignment=2)
        act_total_style = ParagraphStyle("TachoActTotal", parent=act_cell_style,
                                         fontName="Helvetica-Bold")
        act_total_right_style = ParagraphStyle("TachoActTotalRight",
                                               parent=act_total_style, alignment=2)
        card_title_style = ParagraphStyle("TachoCardTitle", parent=cell_style,
                                          fontName="Helvetica-Bold",
                                          textColor=PRIMARY, fontSize=8.5, leading=11)
        note_style = ParagraphStyle("TachoNote", parent=styles["BodyText"],
                                    fontSize=7.2, leading=9, textColor=colors.grey,
                                    spaceBefore=2, spaceAfter=1, keepWithNext=1)

        #: Left-aligned style → its right-aligned twin (numeric cells).
        _RIGHT_OF = {
            cell_style: cell_right_style,
            head_style: head_right_style,
            total_style: total_right_style,
            act_cell_style: act_cell_right_style,
            act_head_style: act_head_right_style,
            act_total_style: act_total_right_style,
        }

        def _right_style(style):
            return _RIGHT_OF.get(style, style)

        page_w, page_h = landscape(A4)
        doc = SimpleDocTemplate(
            filepath, pagesize=(page_w, page_h),
            leftMargin=15 * mm, rightMargin=15 * mm,
            topMargin=15 * mm, bottomMargin=15 * mm,
            title="DDD Tachograph Report",
        )
        avail_width = page_w - doc.leftMargin - doc.rightMargin
        avail_height = page_h - doc.topMargin - doc.bottomMargin

        # ── header/row helpers ────────────────────────────────────────────

        def _header_row(labels, style=head_style, right_from=None):
            return [Paragraph(
                _pdf_text(label),
                _right_style(style) if right_from is not None and i >= right_from else style)
                for i, label in enumerate(labels)]

        def _value_cell(value, style=cell_style):
            text = _cell_text(value)
            return Paragraph(_pdf_text(text), style) if text else ""

        def _build_table(data, col_widths, right_from_column=(), stripe=True,
                         shade_rows=(), pad=3):
            table = LongTable(data, colWidths=col_widths, repeatRows=1)
            cmds = [
                ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
                ("GRID", (0, 0), (-1, -1), 0.3, GRID),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), pad),
                ("RIGHTPADDING", (0, 0), (-1, -1), pad),
                ("TOPPADDING", (0, 0), (-1, -1), pad),
                ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
            ]
            if stripe:
                for idx in range(1, len(data)):
                    cmds.append(("BACKGROUND", (0, idx), (-1, idx),
                                 STRIPE if (idx - 1) % 2 == 0 else colors.white))
            for idx in shade_rows:
                cmds.append(("BACKGROUND", (0, idx), (-1, idx), TOTAL_BG))
            for col in right_from_column:
                cmds.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
            table.setStyle(TableStyle(cmds))
            return table

        # ── column sizing (record tables) ─────────────────────────────────

        def _compute_col_widths(headers, rows, max_chars_per_col=42):
            ncols = len(headers)
            if ncols == 0:
                return []
            widths = [len(str(h)) * 0.55 for h in headers]
            for row in rows[:300]:
                for i, value in enumerate(row):
                    if i >= ncols:
                        break
                    widths[i] = max(widths[i], min(len(str(value)) * 0.55,
                                                   max_chars_per_col * 0.55))
            total = sum(widths)
            if total == 0:
                return [avail_width / ncols] * ncols
            scale = avail_width / total
            return [max(w * scale, 30) for w in widths]

        def _is_total_row(row):
            return bool(row) and isinstance(row[0], str) and row[0].endswith(" TOTAL")

        def _has_content(rows):
            """False when every cell of a section is blank (nothing to report)."""
            return any(_cell_text(value).strip() for row in rows for value in row)

        def _table(headers, rows, is_activity=False):
            """A record/activity table with a repeating header row."""
            col_widths = _compute_col_widths(headers, rows)
            if not col_widths:
                return None
            h_style = act_head_style if is_activity else head_style
            c_style = act_cell_style if is_activity else cell_style
            t_style = act_total_style if is_activity else total_style
            right_from = 1 if is_activity else None

            data = [_header_row(headers, h_style, right_from)]
            shade_rows = []
            for idx, row in enumerate(rows, start=1):
                is_total = _is_total_row(row)
                style = t_style if is_total else c_style
                if is_total:
                    shade_rows.append(idx)
                cells = []
                for col, value in enumerate(row):
                    column_style = (_right_style(style)
                                    if right_from is not None and col >= right_from
                                    else style)
                    cells.append(_value_cell(value, column_style))
                cells.extend([""] * (len(headers) - len(cells)))
                data.append(cells)
            return _build_table(
                data, col_widths,
                right_from_column=list(range(1, len(headers))) if is_activity else [],
                shade_rows=shade_rows, pad=1.6 if is_activity else 3)

        def _pair_table(items):
            """Field/value rows laid out two pairs per line (cover blocks)."""
            data = [[Paragraph(_pdf_text("Field"), head_style),
                     Paragraph(_pdf_text("Value"), head_style),
                     Paragraph(_pdf_text("Field"), head_style),
                     Paragraph(_pdf_text("Value"), head_style)]]
            for idx in range(0, len(items), 2):
                left = items[idx]
                right = items[idx + 1] if idx + 1 < len(items) else ("", "")
                data.append([
                    _value_cell(left[0]),
                    _value_cell(left[1]),
                    _value_cell(right[0]),
                    _value_cell(right[1]),
                ])
            widths = [avail_width * 0.16, avail_width * 0.34,
                      avail_width * 0.16, avail_width * 0.34]
            return _build_table(data, widths, pad=2.5)

        def _field_table(items):
            """Field/value rows, one pair per line (appendix details)."""
            data = [[Paragraph(_pdf_text("Field"), head_style),
                     Paragraph(_pdf_text("Value"), head_style)]]
            for field, value in items:
                data.append([_value_cell(field), _value_cell(value)])
            return _build_table(data, [avail_width * 0.28, avail_width * 0.72], pad=2.5)

        def _record_cards(headers, rows):
            """One field/value card per record (very wide technical tables).

            A wide table squeezed into the page loses its header and its
            values to wrapping. Each record becomes its own small table
            instead: record number and the Field/Value header repeat when a
            long record splits across pages, and no record is forced into one
            unsplittable block.
            """
            flowables = []
            total = len(rows)
            widths = [avail_width * 0.17, avail_width * 0.33,
                      avail_width * 0.17, avail_width * 0.33]
            for idx, row in enumerate(rows, start=1):
                data = [
                    [Paragraph(_pdf_text(f"Record {idx} of {total}"), card_title_style),
                     "", "", ""],
                    [Paragraph(_pdf_text("Field"), head_style),
                     Paragraph(_pdf_text("Value"), head_style),
                     Paragraph(_pdf_text("Field"), head_style),
                     Paragraph(_pdf_text("Value"), head_style)],
                ]
                for col in range(0, len(headers), 2):
                    left_label = headers[col]
                    left_value = row[col] if col < len(row) else ""
                    has_right = col + 1 < len(headers)
                    right_label = headers[col + 1] if has_right else ""
                    right_value = row[col + 1] if has_right and col + 1 < len(row) else ""
                    data.append([
                        _value_cell(left_label),
                        _value_cell(left_value),
                        _value_cell(right_label),
                        _value_cell(right_value),
                    ])
                # splitInRow keeps a value taller than the page: reportlab
                # fragments the row itself, so the record number and Field/Value
                # header repeat instead of raising LayoutError.
                table = LongTable(data, colWidths=widths, repeatRows=2, splitInRow=1)
                table.spaceBefore = 3
                cmds = [
                    ("SPAN", (0, 0), (-1, 0)),
                    ("BACKGROUND", (0, 0), (-1, 0), TOTAL_BG),
                    ("BACKGROUND", (0, 1), (-1, 1), PRIMARY),
                    ("GRID", (0, 0), (-1, -1), 0.3, GRID),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, -1), (-1, -1), 6),
                ]
                table.setStyle(TableStyle(cmds))
                flowables.append(table)
            return flowables

        def _stats_table(buckets, counts):
            """Compact cover stats: the duration buckets and the record counts."""
            data = [[Paragraph(_pdf_text("Activity"), head_style),
                     Paragraph(_pdf_text("(h:mm)"), head_right_style),
                     Paragraph(_pdf_text("Activity"), head_style),
                     Paragraph(_pdf_text("(h:mm)"), head_right_style),
                     Paragraph(_pdf_text("Record"), head_style),
                     Paragraph(_pdf_text("Count"), head_right_style)]]
            pairs = [buckets[start:start + 2] for start in range(0, len(buckets), 2)]
            for index, pair in enumerate(pairs):
                left = pair[0]
                right = pair[1] if len(pair) > 1 else ("", "")
                is_total = "Total" in (left[0], right[0])
                style = total_style if is_total else cell_style
                count = counts[index] if index < len(counts) else ("", "")
                data.append([
                    _value_cell(left[0], style),
                    _value_cell(_duration(left[1]), _right_style(style)),
                    _value_cell(right[0], style),
                    _value_cell(_duration(right[1]) if right[0] else "",
                                _right_style(style)),
                    _value_cell(count[0]),
                    _value_cell(count[1], cell_right_style),
                ])
            widths = [avail_width * fraction
                      for fraction in (0.11, 0.10, 0.13, 0.10, 0.33, 0.23)]
            shaded = [1 + index for index, pair in enumerate(pairs)
                      if any(label == "Total" for label, _minutes in pair)]
            return _build_table(data, widths, right_from_column=[1, 3, 5],
                                stripe=False, shade_rows=shaded, pad=2.5)

        def _row_limit_note(showed_rows=True):
            limit = _pdf_number(_PDF_MAX_ROWS)
            if showed_rows:
                lead = (f"Showing the first {limit} rows of this section: the export "
                        f"stopped at the {limit}-row report limit. ")
            else:
                lead = (f"This section stopped at the {limit}-row report limit before a "
                        "row with displayable values was reached, so no table is printed "
                        "here. ")
            return Paragraph(_pdf_text(
                lead + "The JSON export holds the complete parsed results (the Excel "
                "export has its own row limit)."), note_style)

        # ── activity helpers ──────────────────────────────────────────────

        def _duration(minutes):
            """Every duration in the PDF: ``h:mm`` (hours may pass 24)."""
            minutes = int(minutes or 0)
            return f"{minutes // 60:02d}:{minutes % 60:02d}"

        def _activity_dates(days):
            """Chronological day dates of the valid daily records (UTC days)."""
            dates = []
            for day in days:
                if not isinstance(day, dict):
                    continue
                parsed = _pdf_day_date(day.get("date"))
                if parsed is not None:
                    dates.append(parsed)
            return sorted(set(dates))

        def _month_groups(rows):
            groups, current = [], []
            for row in rows:
                current.append(row)
                if _is_total_row(row):
                    groups.append(current)
                    current = []
            if current:
                groups.append(current)
            return groups

        def _month_label(group):
            """(label, has_subtotal) for one month of the activity table."""
            for row in group:
                if _is_total_row(row):
                    stamp = _pdf_day_date(str(row[0])[: -len(" TOTAL")])
                    if stamp is not None:
                        return f"{stamp.month:02d}/{stamp.year}", True
                    return str(row[0])[: -len(" TOTAL")].strip(), True
            for row in group:
                stamp = _pdf_day_date(row[0] if row else "")
                if stamp is not None:
                    return f"{stamp.month:02d}/{stamp.year}", False
            return "month not identified", False

        def _pdf_activity_header(label):
            """PDF-local ``(h:mm)`` unit on the duration columns."""
            return label.replace(" (h)", " (h:mm)")

        # ── cover data ────────────────────────────────────────────────────

        meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        activities = data.get("activities") or []
        if isinstance(activities, dict):
            activities = [activities]
        if not isinstance(activities, list):
            activities = []
        events = data.get("events") or []
        faults = data.get("faults") or []

        summary = [(field, value) for field, value in summary_rows(data) if field or value]
        summary_lookup = dict(summary)

        def _informative(value):
            """False for a placeholder that says nothing (``N/A``, ``—``)."""
            placeholders = {"N/A", "N/A.", "—", "-", "/", "None"}
            return any(token.strip(",;") not in placeholders
                       for token in str(value).split())

        identity, state, appendix_details = [], [], []
        for field, value in summary:
            if field in _PDF_COVER_IDENTITY_LABELS:
                # "N/A N/A" (an unavailable name beside a real card number) says
                # nothing and is dropped rather than printed as if it were a name.
                if _informative(value):
                    identity.append((field, value))
            elif field in _PDF_COVER_STATE_LABELS:
                state.append((field, value))
            elif field not in _PDF_SUBTITLE_LABELS and field != "Parsed at":
                appendix_details.append((field, value))

        story = []

        # ═══════ COVER ═══════
        source = summary_lookup.get("Source") or (
            "Vehicle Unit" if meta.get("is_vu") else "Driver Card")
        subtitle = "  ·  ".join(
            part for part in (str(meta.get("filename") or ""),
                              str(meta.get("generation") or ""), source) if part)
        story.append(Paragraph("Tachograph Report", title_style))
        story.append(Paragraph(_pdf_text(subtitle), subtitle_style))
        generated = summary_lookup.get("Parsed at") or ""
        story.append(Paragraph(_pdf_text(
            (f"Generated {generated}  ·  " if generated else "")
            + "PDF summary report — the JSON export carries the complete decoded structure"),
            subtitle_style))
        story.append(HRFlowable(width="100%", thickness=1, color=PRIMARY,
                                spaceBefore=3, spaceAfter=5))

        # Activity period (valid day dates only, explicitly UTC and scoped).
        story.append(Paragraph("Activity Period", cover_heading_style))
        dates = _activity_dates(activities)
        if dates:
            first, last = dates[0], dates[-1]
            months = {(stamp.year, stamp.month) for stamp in dates}
            story.append(Paragraph(_pdf_text(
                f"{first.strftime('%d/%m/%Y')} \u2013 {last.strftime('%d/%m/%Y')} (UTC)"
                f"  ·  {len(dates)} dated day{'s' if len(dates) != 1 else ''}"
                f"  ·  {len(months)} month{'s' if len(months) != 1 else ''} represented"),
                cover_line_style))
            story.append(Paragraph(_pdf_text(
                "Day dates are UTC and come only from the daily-activity records in this "
                "file; this is not the file's full retention or download period."),
                cover_note_style))
        else:
            story.append(Paragraph(_pdf_text(
                "No dated activity records in this file, so no activity period can be "
                "stated."), cover_line_style))

        if identity:
            story.append(Paragraph("Identity", cover_heading_style))
            story.append(_pair_table(identity))

        story.append(Paragraph("File State", cover_heading_style))
        if state:
            story.append(_pair_table(state))
        else:
            story.append(Paragraph(_pdf_text("No integrity information was recorded "
                                             "for this file."), cover_line_style))

        # Activity totals: the five buckets, summed by the same slot-aware engine
        # over *every* input day. Known limit: the Daily Activities table is
        # capped at _PDF_MAX_ROWS rows (monthly subtotals included), so the cover
        # can be complete while the table is a subset; per-day arithmetic is the
        # same, and the cover note says so instead of promising equality.
        totals = {"drive": 0, "work": 0, "rest": 0, "available": 0, "unknown": 0}
        active_days = 0
        for day in activities:
            if not isinstance(day, dict):
                continue
            if day.get("changes"):
                active_days += 1
            day_totals = compute_activity_totals(day.get("changes") or [])
            totals["drive"] += day_totals["DRIVE"]
            totals["work"] += day_totals["WORK"]
            totals["rest"] += day_totals["REST"]
            totals["available"] += day_totals["AVAILABLE"]
            totals["unknown"] += day_totals["UNKNOWN"]
        grand_total = sum(totals.values())

        story.append(Paragraph("Activity Totals", cover_heading_style))
        if activities:
            story.append(_stats_table(
                [("Drive", totals["drive"]), ("Work", totals["work"]),
                 ("Rest", totals["rest"]), ("Available", totals["available"]),
                 ("Unknown", totals["unknown"]), ("Total", grand_total)],
                [("Days with activity", active_days), ("Events", len(events)),
                 ("Faults", len(faults))]))
            story.append(Paragraph(_pdf_text(
                "Unknown time is not evidence of a corrupt file: it is time the record "
                "leaves unattributed — minutes before the day's first status entry, an "
                "unrecognised status code, or a card slot with no activity recorded."),
                cover_note_style))
            story.append(Paragraph(_pdf_text(
                "These totals add up every daily record in the input, including days past "
                "the row limit that the Daily Activities table cannot print: once the "
                "limit is reached that table is a subset, while these totals stay "
                "complete. Each day uses the same slot-aware arithmetic as the table, so "
                "per-day figures match."), cover_note_style))
        else:
            story.append(Paragraph(_pdf_text("No daily activity records in this file."),
                                   cover_line_style))

        # ═══════ SECTIONS ═══════
        operational, appendix = [], []
        for label, desc, headers, rows, truncated in section_tables(
                data, max_rows=_PDF_MAX_ROWS):
            if not headers or not rows or (not _has_content(rows) and not truncated):
                # A blank *uncapped* section has nothing to report and is skipped.
                # A blank *capped* section still has to disclose the cap (below).
                _log.warning("PDF: skipping '%s' (no displayable content)", label)
                continue
            entry = (label, desc, headers, rows, truncated)
            (appendix if label in _PDF_APPENDIX_SECTIONS else operational).append(entry)

        def _record_section(label, desc, headers, rows, truncated, *, force_break=False):
            if force_break:
                story.append(CondPageBreak(avail_height - 1))
            story.append(Paragraph(_pdf_text(label), section_style))
            if desc:
                story.append(Paragraph(_pdf_text(desc), note_style))
            if not _has_content(rows):
                # Only reachable for a capped section whose retained rows are all
                # blank: disclose the cut, print no grid, do not imply rows shown.
                story.append(_row_limit_note(showed_rows=False))
                return
            if len(headers) > _PDF_WIDE_COLUMNS:
                story.append(Paragraph(_pdf_text(
                    f"{len(rows)} record(s), {len(headers)} fields each — shown one "
                    "field/value card per record so no field is compressed away."),
                    note_style))
                story.extend(_record_cards(headers, rows))
            else:
                table = _table(headers, rows)
                if table is not None:
                    story.append(table)
            if truncated:
                story.append(_row_limit_note())

        def _activity_section(desc, headers, rows, truncated):
            story.append(Paragraph(_pdf_text("Daily Activities"), section_style))
            if desc:
                story.append(Paragraph(_pdf_text(desc), note_style))
            story.append(Paragraph(_pdf_text(
                "Legend: h:mm durations (00:00 = no time in that bucket); ! marks time the "
                "record leaves unattributed. Drive and Work are summed across the two card "
                "slots, while Rest/Available/Unknown are kept at the maximum across slots, "
                "so a crew day can exceed 24:00 in total."), note_style))
            pdf_headers = [_pdf_activity_header(label) for label in headers]
            for index, group in enumerate(_month_groups(rows)):
                if index:
                    story.append(CondPageBreak(avail_height - 1))
                label, complete = _month_label(group)
                day_count = len(group) - 1 if complete else len(group)
                if complete:
                    title = (f"Daily Activities — {label} "
                             f"({day_count} day{'s' if day_count != 1 else ''})")
                else:
                    title = (f"Daily Activities — {label} (partial month: the "
                             f"{_pdf_number(_PDF_MAX_ROWS)}-row limit stopped the export "
                             "before this month's subtotal)")
                story.append(Paragraph(_pdf_text(title), month_style))
                table = _table(pdf_headers, group, is_activity=True)
                if table is not None:
                    story.append(table)
            if truncated:
                story.append(_row_limit_note())

        first_section = True
        for label, desc, headers, rows, truncated in operational:
            if label == "Daily Activities":
                if first_section:
                    story.append(CondPageBreak(avail_height - 1))
                    first_section = False
                _activity_section(desc, headers, rows, truncated)
            else:
                _record_section(label, desc, headers, rows, truncated,
                                force_break=first_section)
                first_section = False

        # ═══════ TECHNICAL APPENDIX ═══════
        signature_tables = []
        sv = data.get("signature_verification") or {}
        treps = (sv.get("treps") or []) if isinstance(sv, dict) else []
        vu_certs = data.get("vu_certificates") or []
        if appendix or appendix_details or treps or vu_certs:
            story.append(CondPageBreak(min(avail_height - 1, 120 * mm)))
            story.append(Paragraph("Technical Appendix", section_style))
            story.append(Paragraph(_pdf_text(
                "Signature checks, certificates, calibrations, vehicle-unit "
                "configuration and file-level parse details. Operational records are "
                "above; every item here is a verification or configuration fact."),
                note_style))
            if treps:
                signature_tables.append(("Signature Verification", treps))
            if vu_certs:
                signature_tables.append(("VU Certificates (CVC)", vu_certs))
            for label, records in signature_tables:
                headers, rows = records_to_table(records)
                if not headers or not rows or not _has_content(rows):
                    _log.warning("PDF: skipping '%s' (no displayable content)", label)
                    continue
                story.append(Paragraph(_pdf_text(label), cover_heading_style))
                if len(headers) > _PDF_WIDE_COLUMNS:
                    story.extend(_record_cards(headers, rows))
                else:
                    table = _table(headers, rows)
                    if table is not None:
                        story.append(table)
            for label, desc, headers, rows, truncated in appendix:
                _record_section(label, desc, headers, rows, truncated)
            if appendix_details:
                story.append(Paragraph(_pdf_text("File & Parse Details"),
                                       cover_heading_style))
                story.append(_field_table(appendix_details))

        # ═══════ FOOTER ═══════
        def _footer(canvas, document):
            canvas.saveState()
            page_label = f"Page {document.page}"
            name = str(meta.get("filename") or "Tachograph file")
            # Canvas text carries no markup, so a file name the report's own
            # font cannot encode would print as black squares; the whole line
            # is set in the bundled face instead (measured with that font, so
            # the truncation still fits the margin).
            font = _pdf_canvas_font(name)
            canvas.setFont(font, 7)
            canvas.setFillColor(colors.grey)
            budget = avail_width - canvas.stringWidth(page_label, font, 7) - 8
            suffix = f"  ·  TachoReader v{__version__}"
            left = name + suffix
            if canvas.stringWidth(left, font, 7) > budget:
                while name and canvas.stringWidth(
                        name + "\u2026" + suffix, font, 7) > budget:
                    name = name[:-1]
                left = (name + "\u2026" if name else "") + suffix
            canvas.drawString(doc.leftMargin, 8 * mm, left)
            canvas.drawRightString(page_w - doc.rightMargin, 8 * mm, page_label)
            canvas.restoreState()

        doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
