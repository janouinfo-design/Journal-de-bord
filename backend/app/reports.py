"""Report generation: PDF (reportlab), Excel (openpyxl), CSV."""
import io
import csv
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment


def _fmt_dt(s: str) -> str:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return s


def trips_to_csv(trips, classification_label: str) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([
        "Date départ", "Date arrivée", "Conducteur", "Véhicule",
        "Départ", "Arrivée", "Distance (km)", "Durée (min)",
        "Carburant (L)", "Vitesse moyenne", "Vitesse max", "Type",
    ])
    for t in trips:
        w.writerow([
            _fmt_dt(t["start_time"]), _fmt_dt(t["end_time"]),
            t.get("driver_name", ""), t.get("vehicle_plate", ""),
            t.get("start_address", ""), t.get("end_address", ""),
            t.get("distance_km", 0), t.get("duration_min", 0),
            t.get("fuel_l", 0), t.get("avg_speed", 0), t.get("max_speed", 0),
            classification_label,
        ])
    return buf.getvalue().encode("utf-8-sig")


def trips_to_xlsx(trips, classification_label: str, title: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Trajets"

    headers = [
        "Date départ", "Date arrivée", "Conducteur", "Véhicule",
        "Départ", "Arrivée", "Distance (km)", "Durée (min)",
        "Carburant (L)", "Vit. moyenne", "Vit. max", "Type",
    ]
    ws.append([title])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    ws.cell(row=1, column=1).font = Font(size=14, bold=True, color="1F2937")
    ws.append([])

    ws.append(headers)
    header_row = ws.max_row
    for col_idx in range(1, len(headers) + 1):
        c = ws.cell(row=header_row, column=col_idx)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2196F3")
        c.alignment = Alignment(horizontal="left", vertical="center")

    total_km = 0
    total_fuel = 0
    for t in trips:
        ws.append([
            _fmt_dt(t["start_time"]), _fmt_dt(t["end_time"]),
            t.get("driver_name", ""), t.get("vehicle_plate", ""),
            t.get("start_address", ""), t.get("end_address", ""),
            t.get("distance_km", 0), t.get("duration_min", 0),
            t.get("fuel_l", 0), t.get("avg_speed", 0), t.get("max_speed", 0),
            classification_label,
        ])
        total_km += t.get("distance_km", 0) or 0
        total_fuel += t.get("fuel_l", 0) or 0

    ws.append([])
    ws.append(["TOTAL", "", "", "", "", "", round(total_km, 1), "", round(total_fuel, 2), "", "", ""])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)

    from openpyxl.utils import get_column_letter
    widths = [18, 18, 22, 14, 40, 40, 12, 10, 12, 12, 12, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def trips_to_pdf(trips, classification_label: str, title: str, subtitle: str = "") -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=1.2 * cm, rightMargin=1.2 * cm,
        topMargin=1.0 * cm, bottomMargin=1.0 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("t", parent=styles["Title"], fontSize=18, textColor=colors.HexColor("#0F172A"))
    sub_style = ParagraphStyle("s", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#475569"))

    flow = [Paragraph(title, title_style)]
    if subtitle:
        flow.append(Paragraph(subtitle, sub_style))
    flow.append(Spacer(1, 0.4 * cm))

    data = [["Date", "Conducteur", "Véhicule", "Départ", "Arrivée", "Km", "Durée", "Carb. L", "Type"]]
    total_km = 0
    total_fuel = 0
    for t in trips:
        data.append([
            _fmt_dt(t["start_time"]),
            t.get("driver_name", ""),
            t.get("vehicle_plate", ""),
            (t.get("start_address", "") or "")[:40],
            (t.get("end_address", "") or "")[:40],
            f"{t.get('distance_km', 0):.1f}",
            f"{t.get('duration_min', 0)} min",
            f"{t.get('fuel_l', 0):.2f}",
            classification_label,
        ])
        total_km += t.get("distance_km", 0) or 0
        total_fuel += t.get("fuel_l", 0) or 0
    data.append(["", "", "", "", "TOTAL", f"{round(total_km, 1)}", "", f"{round(total_fuel, 2)}", ""])

    table = Table(data, repeatRows=1, colWidths=[2.6 * cm, 3.0 * cm, 2.4 * cm, 5.2 * cm, 5.2 * cm, 1.5 * cm, 1.8 * cm, 1.8 * cm, 2.2 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2196F3")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F8FAFC")]),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#1976D2")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E3F2FD")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    flow.append(table)

    doc.build(flow)
    return buf.getvalue()


def swiss_tax_report_pdf(stats: dict, year: int, owner: str = "") -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    title_s = ParagraphStyle("t", parent=styles["Title"], fontSize=20, textColor=colors.HexColor("#0F172A"))
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, textColor=colors.HexColor("#1976D2"))
    body = ParagraphStyle("b", parent=styles["BodyText"], fontSize=11, leading=16, textColor=colors.HexColor("#334155"))

    flow = []
    flow.append(Paragraph("Rapport Fiscal Annuel — Suisse", title_s))
    flow.append(Paragraph(f"Année fiscale : <b>{year}</b>", body))
    if owner:
        flow.append(Paragraph(f"Conducteur / Véhicule : <b>{owner}</b>", body))
    flow.append(Spacer(1, 0.5 * cm))
    flow.append(Paragraph("Synthèse kilométrique", h2))

    data = [
        ["Catégorie", "Valeur"],
        ["Kilomètres professionnels", f"{stats['pro_km']:,.1f} km".replace(",", "'")],
        ["Kilomètres personnels", f"{stats['perso_km']:,.1f} km".replace(",", "'")],
        ["Kilomètres totaux", f"{stats['total_km']:,.1f} km".replace(",", "'")],
        ["Pourcentage professionnel", f"{stats['pct_pro']:.1f} %"],
        ["Pourcentage personnel", f"{stats['pct_perso']:.1f} %"],
        ["Carburant professionnel (L)", f"{stats['pro_fuel']:.2f}"],
        ["Carburant personnel (L)", f"{stats['perso_fuel']:.2f}"],
    ]
    t = Table(data, colWidths=[9 * cm, 7 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2196F3")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    flow.append(t)
    flow.append(Spacer(1, 0.8 * cm))
    flow.append(Paragraph(
        "Ce document est généré automatiquement par Logitrak — Livre de Bord, "
        "à partir des données GPS officielles Navixy. Les kilomètres correspondent exactement "
        "aux distances Navixy. Conformité avec les exigences fiscales suisses (déduction privé/pro).",
        body,
    ))
    flow.append(Spacer(1, 0.3 * cm))
    flow.append(Paragraph(
        f"Document émis le {datetime.now().strftime('%d/%m/%Y à %H:%M')} — Logitrak SA, Genève.",
        ParagraphStyle("foot", parent=body, fontSize=9, textColor=colors.HexColor("#94A3B8")),
    ))

    doc.build(flow)
    return buf.getvalue()
