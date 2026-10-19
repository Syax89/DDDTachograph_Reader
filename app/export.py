"""Export of parsed tachograph data to Excel, CSV and PDF.

All exports share the formatting in :mod:`core.report_format` (readable
timestamps, humanised column names, nested structures rendered as text), so
the three formats present the same content consistently.
"""
import logging
import re
from datetime import datetime
from xml.sax.saxutils import escape

from core.utils.report_format import records_to_table, section_tables, summary_rows
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


def _spreadsheet_value(value):
    """Prevent text from being interpreted as a spreadsheet formula."""
    if not isinstance(value, str):
        return value
    formula_candidate = value.lstrip(" \t\r\n")
    if (formula_candidate.startswith(("=", "+", "-", "@"))
            and not _NUMBER_TEXT_RE.fullmatch(formula_candidate)):
        return "'" + value
    return value


class ExportManager:

    # ── Excel ────────────────────────────────────────────────────────────

    @staticmethod
    def export_to_excel(data, filepath):
        """Multi-sheet .xlsx: Summary, signature details (VU), one sheet per
        data section. Styled headers, row stripes, auto-filter, frozen panes;
        sections are truncated at _EXCEL_MAX_ROWS."""
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        HEADER_FONT = Font(bold=True, color="FFFFFF")
        HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
        TITLE_FONT = Font(bold=True, size=14, color="1F4E79")
        STRIPE_FILL = PatternFill("solid", fgColor="EFF4FA")

        wb = Workbook()

        def _autosize(ws, headers, rows):
            for idx, header in enumerate(headers, start=1):
                width = len(str(header))
                for row in rows[:200]:
                    if idx <= len(row):
                        width = max(width, len(str(row[idx - 1])))
                ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 2, 9), 55)

        def _write_table(ws, headers, rows, start_row=1):
            for c, header in enumerate(headers, start=1):
                cell = ws.cell(row=start_row, column=c, value=_spreadsheet_value(header))
                cell.font = HEADER_FONT
                cell.fill = HEADER_FILL
                cell.alignment = Alignment(vertical="center")
            for r, row in enumerate(rows, start=start_row + 1):
                for c, value in enumerate(row, start=1):
                    cell = ws.cell(row=r, column=c, value=_spreadsheet_value(value))
                    if (r - start_row) % 2 == 0:
                        cell.fill = STRIPE_FILL
            ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
            if rows:
                last_col = get_column_letter(len(headers))
                ws.auto_filter.ref = f"A{start_row}:{last_col}{start_row + len(rows)}"
            _autosize(ws, headers, rows)

        # Summary sheet
        ws = wb.active
        ws.title = "Summary"
        ws.cell(row=1, column=1, value="DDD Tachograph Report").font = TITLE_FONT
        row = 3
        for field, value in summary_rows(data):
            if field or value:
                ws.cell(row=row, column=1, value=_spreadsheet_value(field)).font = Font(bold=True)
                ws.cell(row=row, column=2, value=_spreadsheet_value(value))
            row += 1
        ws.column_dimensions["A"].width = 26
        ws.column_dimensions["B"].width = 70

        # Signature details (VU)
        used_names = {"Summary"}
        sv = data.get("signature_verification") or {}
        treps = sv.get("treps") or []
        if treps:
            headers, rows = records_to_table(treps)
            trep_sheet = "TREP Signatures"[:31]
            wsx = wb.create_sheet(trep_sheet)
            used_names.add(trep_sheet)
            _write_table(wsx, headers, rows)
        certs = data.get("vu_certificates") or []
        if certs:
            headers, rows = records_to_table(certs)
            cert_sheet = "VU Certificates"[:31]
            wsx = wb.create_sheet(cert_sheet)
            used_names.add(cert_sheet)
            _write_table(wsx, headers, rows)

        # Data sections
        for label, desc, headers, rows, truncated in section_tables(data, max_rows=_EXCEL_MAX_ROWS):
            if not headers:
                _log.warning("Skipping '%s': no visible export columns", label)
                continue
            if truncated:
                _log.warning("Truncating '%s' to %d rows (Excel limit)", label, _EXCEL_MAX_ROWS)
            safe_label = _SHEET_NAME_RE.sub("_", label)[:31].strip()
            if safe_label in used_names:
                idx = 2
                base = safe_label[:28].rstrip("_")
                while f"{base}_{idx}" in used_names:
                    idx += 1
                safe_label = f"{base}_{idx}"[:31]
            used_names.add(safe_label)
            wsx = wb.create_sheet(safe_label)
            if desc:
                wsx.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
                cell = wsx.cell(row=1, column=1, value=_spreadsheet_value(desc))
                cell.font = Font(italic=True, color="666666", size=9)
                _write_table(wsx, headers, rows, start_row=2)
            else:
                _write_table(wsx, headers, rows)

        wb.save(filepath)

    # ── CSV ──────────────────────────────────────────────────────────────

    @staticmethod
    def export_to_csv(data, filepath):
        """Section-block CSV: every section gets a title row, its own header
        and rows, separated by a blank line — readable in any spreadsheet."""
        import csv

        with open(filepath, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")

            def _write_row(row):
                writer.writerow([_spreadsheet_value(value) for value in row])

            _write_row(["DDD TACHOGRAPH REPORT"])
            for field, value in summary_rows(data):
                if field or value:
                    _write_row([field, value])
            _write_row([])

            wrote_any = False
            for label, desc, headers, rows, truncated in section_tables(data):
                _write_row([f"=== {label.upper()} ==="])
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
            return escape(_pdf_plain(value))

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
            canvas.setFont("Helvetica", 7)
            canvas.setFillColor(colors.grey)
            page_label = f"Page {document.page}"
            budget = (avail_width
                      - canvas.stringWidth(page_label, "Helvetica", 7) - 8)
            name = str(meta.get("filename") or "Tachograph file")
            suffix = f"  ·  TachoReader v{__version__}"
            left = name + suffix
            if canvas.stringWidth(left, "Helvetica", 7) > budget:
                while name and canvas.stringWidth(
                        name + "\u2026" + suffix, "Helvetica", 7) > budget:
                    name = name[:-1]
                left = (name + "\u2026" if name else "") + suffix
            canvas.drawString(doc.leftMargin, 8 * mm, left)
            canvas.drawRightString(page_w - doc.rightMargin, 8 * mm, page_label)
            canvas.restoreState()

        doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
