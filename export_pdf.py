import json
import sys
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Rect, String, Group, Line, Drawing
from fines_calculator import FinesCalculator

def draw_timeline(drawing, events, infractions_dates, current_date):
    """Draws a 24h timeline with colored blocks."""
    width = 160 * mm
    height = 10 * mm
    x_offset = 0
    y_offset = 0
    
    # Background
    drawing.add(Rect(x_offset, y_offset, width, height, fillColor=colors.whitesmoke, strokeColor=colors.black))
    
    # Time markers (every 3 hours)
    for i in range(0, 25, 3):
        x = x_offset + (i / 24.0) * width
        drawing.add(Line(x, y_offset, x, y_offset - 2, strokeColor=colors.grey))
        drawing.add(String(x - 2, y_offset - 8, f"{i:02d}", fontSize=6, fontName="Helvetica"))

    color_map = {
        "GUIDA": colors.HexColor("#3498db"),     # Blue
        "LAVORO": colors.HexColor("#95a5a6"),    # Grey
        "RIPOSO": colors.HexColor("#2ecc71"),    # Green
        "DISPONIBILITÀ": colors.HexColor("#f1c40f") # Yellow
    }

    for ev in events:
        try:
            h, m = map(int, ev.get("ora", "00:00").split(":"))
            start_ratio = (h * 60 + m) / (24 * 60)
            
            # Duration - in a real app we'd have this, but let's estimate 
            # from next event or end of day if missing
            # For the visual, we use a default or actual duration if available
            durata = ev.get("durata", 30) # Default 30 min for viz if missing
            dur_ratio = durata / (24 * 60)
            
            block_width = dur_ratio * width
            # Cap width to not overflow 24h
            if start_ratio + dur_ratio > 1.0:
                block_width = (1.0 - start_ratio) * width
                
            rect_x = x_offset + start_ratio * width
            drawing.add(Rect(rect_x, y_offset, block_width, height, 
                            fillColor=color_map.get(ev["tipo"], colors.white), 
                            strokeWidth=0))
            
            # Infraction marker
            if current_date in infractions_dates:
                # Simple logic: if there's an infraction on this day, we could mark specific events
                # For now, let's mark events of type "GUIDA" if it's an excess day, 
                # or just a general marker.
                # Improvements: pass specific infraction times.
                pass
        except Exception:
            continue

def generate_pdf(json_data, output_path):
    doc = SimpleDocTemplate(output_path, pagesize=A4, rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    styles = getSampleStyleSheet()
    elements = []

    # Title
    elements.append(Paragraph("Report Analisi Tachigrafo Digitale (v1.2.0)", styles['Title']))
    elements.append(Spacer(1, 12))

    # Summary and Fines
    infractions = json_data.get("infractions", [])
    total_min, total_max = FinesCalculator.get_total_estimate(infractions)
    
    summary_data = [
        [Paragraph("<b>Riepilogo Violazioni</b>", styles['Normal']), Paragraph(f"<b>{len(infractions)}</b>", styles['Normal'])],
        [Paragraph("<b>Sanzioni Stimate (Art. 174 CdS)</b>", styles['Normal']), Paragraph(f"<b>€ {total_min} - € {total_max}</b>", styles['Normal'])]
    ]
    st = Table(summary_data, colWidths=[350, 100])
    st.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.lavender),
        ('GRID', (0, 0), (-1, -1), 1, colors.white),
        ('PADDING', (0, 0), (-1, -1), 8)
    ]))
    elements.append(st)
    elements.append(Spacer(1, 18))

    # Metadata
    meta = json_data.get("metadata", {})
    driver = json_data.get("driver", {})
    vehicle = json_data.get("vehicle", {})
    
    info_data = [
        ["File:", meta.get('filename'), "Conducente:", driver.get('card_number')],
        ["Data Analisi:", meta.get('parsed_at'), "Veicolo:", vehicle.get('plate')],
        ["Integrità:", meta.get('integrity_check'), "VIN:", vehicle.get('vin')]
    ]
    it = Table(info_data, colWidths=[80, 150, 80, 150])
    it.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.darkslategrey),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
    ]))
    elements.append(it)
    elements.append(Spacer(1, 18))

    # Timeline Section
    elements.append(Paragraph("Visualizzazione Grafica Attività (Last 7 Days)", styles['Heading2']))
    activities = json_data.get("activities", [])
    infractions_dates = [inf.get("data") for inf in infractions]

    for day in activities[:7]:
        elements.append(Paragraph(f"Data: {day.get('data')} - Km: {day.get('km', 'N/A')}", styles['Heading3']))
        
        # Create Timeline Drawing
        d = Drawing(160 * mm, 15 * mm)
        
        # Calculate event durations for visualization
        events = day.get("eventi", [])
        viz_events = []
        for i in range(len(events)):
            ev = events[i].copy()
            h, m = map(int, ev["ora"].split(":"))
            t_start = h * 60 + m
            if i < len(events) - 1:
                nh, nm = map(int, events[i+1]["ora"].split(":"))
                t_end = nh * 60 + nm
            else:
                t_end = 24 * 60
            ev["durata"] = t_end - t_start
            viz_events.append(ev)

        draw_timeline(d, viz_events, infractions_dates, day.get('data'))
        elements.append(d)
        elements.append(Spacer(1, 10))
        
        # Infraction Markers (Simplified: Red dots for days with issues)
        if day.get('data') in infractions_dates:
            elements.append(Paragraph("<font color='red'>• Rilevate infrazioni in questa giornata</font>", styles['Italic']))
        
        elements.append(Spacer(1, 10))

    # Infractions Detail
    elements.append(Paragraph("Dettaglio Infrazioni Rilevate", styles['Heading2']))
    if not infractions:
        elements.append(Paragraph("Nessuna infrazione rilevata.", styles['Normal']))
    else:
        data = [["Data", "Gravità", "Tipo", "Sanzione Est.", "Descrizione"]]
        for inf in infractions:
            severity = inf.get("severita") or inf.get("severity") or "SI"
            inf_type = inf.get("tipo")
            f_min, f_max = FinesCalculator.estimate_fine(inf_type, severity)
            
            sev_p = Paragraph(f"<b>{severity}</b>", ParagraphStyle('sev', fontSize=8, textColor=colors.red if severity=="MSI" else colors.orange if severity=="SI" else colors.black))
            data.append([
                inf.get("data"), 
                sev_p, 
                inf_type.replace("_", " "), 
                f"€{f_min}-{f_max}",
                Paragraph(inf.get("descrizione", ""), ParagraphStyle('desc', fontSize=7))
            ])
        
        t = Table(data, colWidths=[55, 40, 100, 70, 200])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
        ]))
        elements.append(t)
    
    elements.append(Spacer(1, 18))
    elements.append(Paragraph("<i>Nota: Le sanzioni sono stime basate sull'Art. 174 del CdS e possono variare in base alle circostanze specifiche.</i>", styles['Italic']))

    doc.build(elements)

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python3 export_pdf.py input.json output.pdf")
    else:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            data = json.load(f)
        generate_pdf(data, sys.argv[2])
        print(f"PDF generato: {sys.argv[2]}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python3 export_pdf.py input.json output.pdf")
    else:
        with open(sys.argv[1], 'r', encoding='utf-8') as f:
            data = json.load(f)
        generate_pdf(data, sys.argv[2])
        print(f"PDF generato: {sys.argv[2]}")
