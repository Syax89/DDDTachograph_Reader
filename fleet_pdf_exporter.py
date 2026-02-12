"""
Fleet PDF Exporter - Aurora DDD Analytics
Genera un report PDF multi-pagina per l'analisi aggregata della flotta.
"""
import os
from datetime import datetime
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.graphics.shapes import Rect, String, Drawing
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

# ── Palette colori Aurora ──────────────────────────────────────────────────────
C_DARK    = colors.HexColor("#1a1a2e")
C_BLUE    = colors.HexColor("#1F538D")
C_BLUE_LT = colors.HexColor("#3B8ED0")
C_GREEN   = colors.HexColor("#1E8449")
C_GREEN_LT= colors.HexColor("#2ECC71")
C_ORANGE  = colors.HexColor("#E67E22")
C_RED     = colors.HexColor("#C0392B")
C_LIGHT   = colors.HexColor("#F8F9FA")
C_GREY    = colors.HexColor("#95A5A6")
C_WHITE   = colors.white


def _styles():
    base = getSampleStyleSheet()
    custom = {
        "title": ParagraphStyle("title", fontSize=26, fontName="Helvetica-Bold",
                                 textColor=C_WHITE, alignment=TA_CENTER, spaceAfter=4),
        "subtitle": ParagraphStyle("subtitle", fontSize=12, fontName="Helvetica",
                                    textColor=colors.HexColor("#BDC3C7"), alignment=TA_CENTER),
        "h2": ParagraphStyle("h2", fontSize=14, fontName="Helvetica-Bold",
                              textColor=C_BLUE, spaceBefore=14, spaceAfter=6),
        "h3": ParagraphStyle("h3", fontSize=11, fontName="Helvetica-Bold",
                              textColor=C_DARK, spaceBefore=8, spaceAfter=4),
        "body": ParagraphStyle("body", fontSize=9, fontName="Helvetica",
                                textColor=C_DARK, spaceAfter=3),
        "small": ParagraphStyle("small", fontSize=7, fontName="Helvetica",
                                  textColor=C_GREY),
        "small_red": ParagraphStyle("small_red", fontSize=8, fontName="Helvetica-Bold",
                                     textColor=C_RED),
        "small_green": ParagraphStyle("small_green", fontSize=8, fontName="Helvetica-Bold",
                                       textColor=C_GREEN),
        "cell": ParagraphStyle("cell", fontSize=8, fontName="Helvetica", textColor=C_DARK),
        "cell_bold": ParagraphStyle("cell_bold", fontSize=8, fontName="Helvetica-Bold", textColor=C_DARK),
    }
    return custom


def _kpi_block(title: str, value: str, color=C_BLUE_LT) -> Table:
    """Un blocco KPI 4x1."""
    data = [
        [Paragraph(f'<font color="#{color.hexval()[1:]}"><b>{value}</b></font>',
                   ParagraphStyle("kv", fontSize=22, fontName="Helvetica-Bold",
                                  alignment=TA_CENTER))],
        [Paragraph(title, ParagraphStyle("kt", fontSize=8, fontName="Helvetica",
                                          textColor=C_GREY, alignment=TA_CENTER))],
    ]
    t = Table(data, colWidths=[50 * mm])
    t.setStyle(TableStyle([
        ("BOX",        (0, 0), (-1, -1), 1, colors.HexColor("#2D3436")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1E1E2E")),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    return t


def generate_fleet_pdf(results: list, output_path: str, folder_name: str = ""):
    """
    Genera il PDF di report flotta.

    :param results: lista di dict restituita da FleetAnalytics.run()
    :param output_path: path del file PDF di output
    :param folder_name: nome della cartella sorgente (solo cosmetic)
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=landscape(A4),
        rightMargin=15 * mm, leftMargin=15 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
    )
    S = _styles()
    elements = []

    ok_results  = [r for r in results if r.get("status") == "OK"]
    err_results = [r for r in results if r.get("status") != "OK"]

    total_km    = sum(r.get("total_km", 0) for r in ok_results)
    total_hours = sum(r.get("total_drive_time_hours", 0) for r in ok_results)
    total_inf   = sum(r.get("infractions", 0) for r in ok_results)
    n_drivers   = len(ok_results)

    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    # ── COPERTINA ─────────────────────────────────────────────────────────────
    cover_bg = Table(
        [[Paragraph("REPORT ANALISI FLOTTA", S["title"]),
          Paragraph("Aurora DDD Analytics ✨", S["subtitle"])]],
        colWidths=[267 * mm],
    )
    cover_bg.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), C_DARK),
        ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ("SPAN",       (0, 0), (-1, -1)),
    ]))
    # Workaround: due righe separate nel cover_bg
    cover_data = [
        [Paragraph("REPORT ANALISI FLOTTA", S["title"])],
        [Paragraph("Aurora DDD Analytics ✨", S["subtitle"])],
        [Paragraph(
            f'Cartella: <b>{folder_name or "N/A"}</b>  —  Generato il {now_str}',
            ParagraphStyle("cov_sub2", fontSize=9, fontName="Helvetica",
                           textColor=C_GREY, alignment=TA_CENTER)
        )],
    ]
    cover = Table(cover_data, colWidths=[267 * mm])
    cover.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_DARK),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    elements.append(cover)
    elements.append(Spacer(1, 10 * mm))

    # ── KPI BAR ───────────────────────────────────────────────────────────────
    inf_color = C_RED if total_inf > 0 else C_GREEN_LT
    kpi_data = [[
        _kpi_block("CONDUCENTI ANALIZZATI", str(n_drivers), C_BLUE_LT),
        _kpi_block("KM TOTALI FLOTTA", f"{total_km:,}", C_BLUE_LT),
        _kpi_block("ORE GUIDA TOTALI", f"{total_hours:.1f} h", C_BLUE_LT),
        _kpi_block("INFRAZIONI TOTALI", str(total_inf), inf_color),
        _kpi_block("FILE IN ERRORE", str(len(err_results)),
                   C_RED if err_results else C_GREEN_LT),
    ]]
    kpi_table = Table(kpi_data, colWidths=[50 * mm] * 5,
                      hAlign="CENTER", spaceBefore=0, spaceAfter=10)
    kpi_table.setStyle(TableStyle([
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
    ]))
    elements.append(kpi_table)
    elements.append(HRFlowable(width="100%", thickness=1, color=C_BLUE))
    elements.append(Spacer(1, 6 * mm))

    # ── TABELLA CONDUCENTI ────────────────────────────────────────────────────
    elements.append(Paragraph("Riepilogo Conducenti", S["h2"]))

    header = ["#", "Conducente", "N° Carta", "KM Totali", "Ore Guida",
              "Ultima Attività", "Infrazioni", "Integrità", "File"]
    col_w  = [8, 45, 38, 22, 22, 28, 22, 30, 50]  # mm
    col_w  = [w * mm for w in col_w]

    table_data = [
        [Paragraph(f"<b>{h}</b>", ParagraphStyle("th", fontSize=8,
                   fontName="Helvetica-Bold", textColor=C_WHITE, alignment=TA_CENTER))
         for h in header]
    ]

    for i, r in enumerate(ok_results, start=1):
        inf_count = r.get("infractions", 0)
        integrity = r.get("integrity", "N/A")

        # Colore riga
        row_bg = colors.white if i % 2 == 0 else C_LIGHT

        # Integrità
        is_ok_int = str(integrity).upper() in ["OK", "VERIFIED (G1)", "TRUE", "VERIFIED"]
        int_para = Paragraph(
            f'<font color="{"#1E8449" if is_ok_int else "#C0392B"}">{"✓ " if is_ok_int else "⚠ "}{integrity}</font>',
            ParagraphStyle("int", fontSize=7, fontName="Helvetica-Bold", alignment=TA_CENTER)
        )

        # Infrazioni
        if inf_count == 0:
            inf_para = Paragraph('<font color="#1E8449"><b>✓ 0</b></font>',
                                  ParagraphStyle("inf", fontSize=8, alignment=TA_CENTER))
        else:
            inf_para = Paragraph(f'<font color="#C0392B"><b>⚠ {inf_count}</b></font>',
                                  ParagraphStyle("inf", fontSize=8, alignment=TA_CENTER))

        row = [
            Paragraph(str(i), ParagraphStyle("n", fontSize=8, alignment=TA_CENTER)),
            Paragraph(r.get("driver_name", "N/A") or "N/A", S["cell_bold"]),
            Paragraph(r.get("card_number", "N/A") or "N/A",
                      ParagraphStyle("card", fontSize=7, fontName="Helvetica")),
            Paragraph(f'{r.get("total_km", 0):,} km',
                      ParagraphStyle("km", fontSize=8, alignment=TA_CENTER)),
            Paragraph(f'{r.get("total_drive_time_hours", 0):.1f} h',
                      ParagraphStyle("h", fontSize=8, alignment=TA_CENTER)),
            Paragraph(r.get("last_activity", "N/A") or "N/A",
                      ParagraphStyle("la", fontSize=8, alignment=TA_CENTER)),
            inf_para,
            int_para,
            Paragraph(r.get("filename", "N/A") or "N/A",
                      ParagraphStyle("fn", fontSize=6, fontName="Helvetica", textColor=C_GREY)),
        ]
        table_data.append(row)

    # Righe errore
    for r in err_results:
        row = [
            Paragraph("—", ParagraphStyle("n", fontSize=8, alignment=TA_CENTER)),
            Paragraph('<font color="#C0392B"><b>⚠ ERRORE PARSING</b></font>',
                       ParagraphStyle("err", fontSize=8)),
            Paragraph("—", S["cell"]),
            Paragraph("—", S["cell"]),
            Paragraph("—", S["cell"]),
            Paragraph("—", S["cell"]),
            Paragraph("—", S["cell"]),
            Paragraph("—", S["cell"]),
            Paragraph(r.get("filename", "N/A") or "N/A",
                      ParagraphStyle("fn", fontSize=6, textColor=C_GREY)),
        ]
        table_data.append(row)

    driver_table = Table(table_data, colWidths=col_w, repeatRows=1)
    row_styles = [
        ("BACKGROUND",    (0, 0), (-1, 0),  C_DARK),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  C_WHITE),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#DDD")),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_LIGHT, colors.white]),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    driver_table.setStyle(TableStyle(row_styles))
    elements.append(driver_table)
    elements.append(Spacer(1, 8 * mm))

    # ── SEZIONE INFRAZIONI (solo conducenti con infrazioni) ───────────────────
    infractions_drivers = [r for r in ok_results if r.get("infractions", 0) > 0]
    if infractions_drivers:
        elements.append(PageBreak())
        elements.append(Paragraph("⚠ Conducenti con Infrazioni Rilevate", S["h2"]))
        elements.append(Spacer(1, 4 * mm))

        inf_header = ["Conducente", "N° Carta", "N° Infrazioni", "File"]
        inf_col_w  = [60 * mm, 50 * mm, 40 * mm, 100 * mm]
        inf_data   = [
            [Paragraph(f"<b>{h}</b>", ParagraphStyle("th", fontSize=9,
                       fontName="Helvetica-Bold", textColor=C_WHITE, alignment=TA_CENTER))
             for h in inf_header]
        ]
        for r in infractions_drivers:
            inf_data.append([
                Paragraph(r.get("driver_name", "N/A") or "N/A", S["cell_bold"]),
                Paragraph(r.get("card_number", "N/A") or "N/A", S["cell"]),
                Paragraph(f'<font color="#C0392B"><b>{r.get("infractions", 0)}</b></font>',
                           ParagraphStyle("iv", fontSize=10, fontName="Helvetica-Bold",
                                          alignment=TA_CENTER)),
                Paragraph(r.get("filename", "N/A") or "N/A",
                           ParagraphStyle("fn", fontSize=7, textColor=C_GREY)),
            ])

        inf_table = Table(inf_data, colWidths=inf_col_w, repeatRows=1)
        inf_table.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#922B21")),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  C_WHITE),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.HexColor("#FDEDEC"), colors.white]),
            ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#DDD")),
            ("ALIGN",         (0, 0), (-1, -1), "LEFT"),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elements.append(inf_table)
        elements.append(Spacer(1, 8 * mm))

    # ── NOTE LEGALI ───────────────────────────────────────────────────────────
    elements.append(HRFlowable(width="100%", thickness=0.5, color=C_GREY))
    elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph(
        "<i>Report generato da Aurora DDD Analytics. Le sanzioni indicate sono stime basate sull'Art. 174 del "
        "Codice della Strada e possono variare in base alle circostanze specifiche. "
        "Questo documento non ha valore legale autonomo.</i>",
        S["small"]
    ))

    doc.build(elements)
    return output_path


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 3:
        print("Uso: python3 fleet_pdf_exporter.py fleet_results.json output.pdf")
    else:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            data = json.load(f)
        generate_fleet_pdf(data, sys.argv[2])
        print(f"PDF flotta generato: {sys.argv[2]}")
