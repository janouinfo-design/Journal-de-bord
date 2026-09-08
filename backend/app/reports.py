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

# Mention obligatoire : le carburant des trajets est un calcul LEGACY (8,5 L/100 km),
# JAMAIS une mesure télématique. Toute sortie fiscale doit porter cette étiquette.
FUEL_ESTIMATED_NOTE = (
    "* Carburant : Estimé — calcul historique LOGITRAK (8,5 L/100 km). "
    "Valeur non mesurée : ne provient ni d'une mesure télématique (OBD/CAN) ni du module Énergie."
)


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
        "Carburant estimé (L)", "Vitesse moyenne", "Vitesse max", "Type",
    ])
    for t in trips:
        w.writerow([
            _fmt_dt(t["start_time"]), _fmt_dt(t["end_time"]),
            t.get("driver_name", ""), t.get("vehicle_plate", ""),
            t.get("start_address", ""), t.get("end_address", ""),
            t.get("distance_km", 0), t.get("duration_min", 0),
            t.get("fuel_l"), t.get("avg_speed", 0), t.get("max_speed", 0),
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
        "Carburant estimé (L)", "Vit. moyenne", "Vit. max", "Type",
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
            t.get("fuel_l"), t.get("avg_speed", 0), t.get("max_speed", 0),
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


# ---------------------------------------------------------------------------
# Export Excel du rapprochement achats ↔ consommation — jamais 0 pour une
# absence de donnée (cellule vide), estimations toujours étiquetées.
# ---------------------------------------------------------------------------
RECON_MEASUREMENT_LABEL = {"MEASURED": "Mesuré", "ESTIMATED": "Estimé",
                           "REFERENCE": "Référence", "NONE": "Aucun"}
RECON_STATUS_LABEL = {"OK": "OK", "A_CONTROLER": "À contrôler",
                      "INDICATIF": "Indicatif", "IMPOSSIBLE": "Impossible"}
RECON_RELIABILITY_LABEL = {"EXPLOITABLE": "Exploitable", "INDICATIF": "Indicatif",
                           "IMPOSSIBLE": "Impossible"}
RECON_POWERTRAIN_LABEL = {"ICE": "Thermique", "HEV": "Hybride",
                          "PHEV": "Hybride rechargeable", "BEV": "Électrique",
                          "UNKNOWN": "Inconnue"}


def _metric_cell(m):
    if not m or m.get("value") is None:
        return ""
    return round(float(m["value"]), 2)


def _stale_suffix(metric) -> str:
    """STALE reste STALE : une mesure périmée n'est jamais présentée comme fraîche."""
    return " (périmé)" if (metric or {}).get("availability") == "STALE" else ""


def reconciliation_to_xlsx(rows, meta: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Rapprochement"

    headers = [
        "Véhicule", "Plaque", "Période", "Motorisation", "Tracker ID",
        "Achats carburant (L)", "Achats recharge (kWh)", "Transactions", "Montant (CHF)",
        "Consommation (L)", "Type de mesure", "Source consommation",
        "Consommation électrique (kWh)", "Type mesure électrique", "Source électrique",
        "Écart (L)", "Écart (%)", "Fiabilité", "Statut", "Raison du statut",
    ]
    ws.append([f"Rapprochement achats ↔ consommation — {meta.get('tenant', '')}"])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    ws.cell(row=1, column=1).font = Font(size=14, bold=True, color="1F2937")
    ws.append([f"Période : {meta.get('period_from')} → {meta.get('period_to')}"])
    ws.append([f"Généré le : {meta.get('generated_at')}"])
    filters = meta.get("filters") or []
    ws.append([f"Filtres appliqués : {' ; '.join(filters) if filters else 'aucun'}"])
    th = meta.get("thresholds") or {}
    ws.append([("Seuil configuré : "
                + " · ".join(([f"{th.get('percent')} %"] if th.get("percent") is not None else [])
                             + ([f"{th.get('liters')} L"] if th.get("liters") is not None else [])))
               if th.get("configured")
               else "Aucun seuil configuré — rapprochement en mode diagnostic"])
    ws.append(["Alertes automatiques : désactivées"])
    if meta.get("mode") == "fixture":
        ws.append(["Données de démonstration contractuelles (FIXTURE) — PAS le module Énergie réel"])
    elif not meta.get("connected"):
        ws.append(["Module Énergie non connecté — consommations indisponibles"])
    ws.append([])

    ws.append(headers)
    header_row = ws.max_row
    for col_idx in range(1, len(headers) + 1):
        c = ws.cell(row=header_row, column=col_idx)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2196F3")
        c.alignment = Alignment(horizontal="left", vertical="center")

    period_str = f"{meta.get('period_from')} → {meta.get('period_to')}"
    for r in rows:
        buy = r.get("purchased") or {}
        has_buy = (buy.get("tx_count") or 0) > 0
        cf = r.get("consumed_fuel")
        ce = r.get("consumed_electric")
        ce_present = bool(ce and ce.get("value") is not None)
        ws.append([
            r.get("model") or "",
            r.get("plate") or "",
            period_str,
            RECON_POWERTRAIN_LABEL.get(r.get("powertrain"), r.get("powertrain") or ""),
            r.get("navixy_tracker_id") or "",
            round(buy.get("liters", 0), 2) if has_buy else "",
            round(buy.get("kwh", 0), 2) if has_buy else "",
            buy.get("tx_count") if has_buy else "",
            round(buy.get("amount_chf", 0), 2) if has_buy else "",
            _metric_cell(cf),
            RECON_MEASUREMENT_LABEL.get(r.get("consumption_measurement_type"), "Aucun") + _stale_suffix(cf),
            (cf or {}).get("source") or "",
            _metric_cell(ce),
            (RECON_MEASUREMENT_LABEL.get((ce or {}).get("measurement_type"), "") + _stale_suffix(ce)) if ce_present else "",
            ((ce or {}).get("source") or "") if ce_present else "",
            r.get("gap_l") if r.get("gap_l") is not None else "",
            r.get("gap_pct") if r.get("gap_pct") is not None else "",
            RECON_RELIABILITY_LABEL.get(r.get("reliability"), r.get("reliability") or ""),
            RECON_STATUS_LABEL.get(r.get("status"), r.get("status") or ""),
            r.get("status_reason") or "",
        ])

    from openpyxl.utils import get_column_letter
    widths = [20, 16, 24, 18, 12, 16, 16, 12, 14, 16, 14, 16, 18, 16, 16, 12, 12, 12, 12, 60]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Export PDF du rapprochement — même source de données que l'écran et l'Excel
# (_build_reconciliation). null → « — », JAMAIS 0. L et kWh toujours séparés.
# Polices standard PDF (cp1252) : pas de caractères ↔ ou → dans ce document.
# ---------------------------------------------------------------------------
def _pdf_num(v, decimals=2):
    if v is None or v == "":
        return "—"
    return f"{float(v):.{decimals}f}"


def reconciliation_to_pdf(rows, meta: dict) -> bytes:
    buf = io.BytesIO()
    page_size = landscape(A4)
    doc = SimpleDocTemplate(
        buf, pagesize=page_size,
        leftMargin=1.0 * cm, rightMargin=1.0 * cm,
        topMargin=1.0 * cm, bottomMargin=1.5 * cm,
        title="Rapprochement achats-consommation")
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("rt", parent=styles["Title"], fontSize=15, alignment=0,
                                 textColor=colors.HexColor("#0F172A"), spaceAfter=2)
    sub = ParagraphStyle("rs", parent=styles["Normal"], fontSize=8.5,
                         textColor=colors.HexColor("#64748B"), leading=11)
    warn = ParagraphStyle("rw", parent=sub, textColor=colors.HexColor("#B45309"))
    cell = ParagraphStyle("rc", parent=styles["Normal"], fontSize=7.6,
                          textColor=colors.HexColor("#0F172A"), leading=9.4)
    small = ParagraphStyle("rsm", parent=cell, fontSize=7.0,
                           textColor=colors.HexColor("#475569"), leading=8.8)
    head = ParagraphStyle("rh", parent=styles["Normal"], fontSize=7.6,
                          textColor=colors.white, fontName="Helvetica-Bold", leading=9.2)

    def P(text, style=cell):
        return Paragraph("" if text is None else str(text).replace("&", "&amp;"), style)

    flow = [Paragraph(f"Rapprochement achats / consommation — {meta.get('tenant', '')}", title_style)]
    flow.append(Paragraph(
        f"Période : {meta.get('period_from')} au {meta.get('period_to')} · "
        f"Généré le : {meta.get('generated_at')}", sub))
    filters = meta.get("filters") or []
    flow.append(Paragraph(f"Filtres appliqués : {' ; '.join(filters) if filters else 'aucun'}", sub))
    th = meta.get("thresholds") or {}
    if th.get("configured"):
        parts = (([f"{th.get('percent')} %"] if th.get("percent") is not None else [])
                 + ([f"{th.get('liters')} L"] if th.get("liters") is not None else []))
        flow.append(Paragraph(f"Seuil configuré : {' · '.join(parts)}", sub))
    else:
        flow.append(Paragraph("Aucun seuil configuré — rapprochement en mode diagnostic", sub))
    flow.append(Paragraph("Alertes automatiques : désactivées — aucun message envoyé", sub))
    if meta.get("mode") == "fixture":
        flow.append(Paragraph(
            "Données de démonstration contractuelles (FIXTURE) — PAS le module Énergie réel", warn))
    elif not meta.get("connected"):
        flow.append(Paragraph("Module Énergie non connecté — consommations indisponibles", warn))
    flow.append(Spacer(1, 0.3 * cm))

    if not rows:
        flow.append(Paragraph("Aucun véhicule ne correspond aux filtres.", sub))
    else:
        data = [[P(h, head) for h in (
            "Véhicule", "Motorisation", "Achats (L)", "Recharges (kWh)", "Tx",
            "Montant (CHF)", "Conso (L)", "Type de mesure", "Conso élec (kWh)",
            "Écart (L)", "Écart (%)", "Fiabilité", "Statut", "Raison du statut")]]
        check_rows = []
        for i, r in enumerate(rows, start=1):
            buy = r.get("purchased") or {}
            has_buy = (buy.get("tx_count") or 0) > 0
            cf = r.get("consumed_fuel") or {}
            ce = r.get("consumed_electric") or {}
            veh = r.get("plate") or r.get("model") or "—"
            veh_extra = r.get("model") if r.get("plate") else ""
            if not r.get("mapped"):
                veh_extra = (f"{veh_extra} · " if veh_extra else "") + "Non mappé"
            if r.get("status") == "A_CONTROLER":
                check_rows.append(i)
            data.append([
                P(f"<b>{veh}</b>" + (f"<br/>{veh_extra}" if veh_extra else "")),
                P(RECON_POWERTRAIN_LABEL.get(r.get("powertrain"), r.get("powertrain") or "—")),
                P(_pdf_num(buy.get("liters")) if has_buy else "—"),
                P(_pdf_num(buy.get("kwh")) if has_buy else "—"),
                P(buy.get("tx_count") if has_buy else "—"),
                P(_pdf_num(buy.get("amount_chf")) if has_buy else "—"),
                P(_pdf_num(cf.get("value"))),
                P(RECON_MEASUREMENT_LABEL.get(r.get("consumption_measurement_type"), "Aucun") + _stale_suffix(cf)),
                P(_pdf_num(ce.get("value"))),
                P(_pdf_num(r.get("gap_l"))),
                P(_pdf_num(r.get("gap_pct"), 1)),
                P(RECON_RELIABILITY_LABEL.get(r.get("reliability"), r.get("reliability") or "—")),
                P(RECON_STATUS_LABEL.get(r.get("status"), r.get("status") or "—")),
                P(r.get("status_reason") or "", small),
            ])
        col_widths = [3.3, 2.0, 1.7, 1.8, 0.9, 1.8, 1.6, 1.8, 1.8, 1.5, 1.5, 1.7, 1.7, 4.6]
        table = Table(data, colWidths=[w * cm for w in col_widths], repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2196F3")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ALIGN", (2, 1), (10, -1), "RIGHT"),
        ]
        for i in check_rows:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FEF3C7")))
        table.setStyle(TableStyle(style))
        flow.append(table)

    flow.append(Spacer(1, 0.25 * cm))
    flow.append(Paragraph(
        "« — » = donnée non disponible (jamais assimilée à zéro). Les consommations proviennent "
        "exclusivement du module Énergie ; les achats proviennent des transactions cartes. "
        "Litres et kWh ne sont jamais fusionnés (PHEV/HEV : énergies séparées).",
        ParagraphStyle("rlegend", parent=sub, fontSize=7.5)))

    def _footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#94A3B8"))
        canvas.drawString(1.0 * cm, 0.65 * cm,
                          "Logitrak — Livre de bord · Rapprochement achats / consommation · "
                          "Alertes automatiques : désactivées")
        canvas.drawRightString(page_size[0] - 1.0 * cm, 0.65 * cm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(flow, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def trips_to_pdf(trips, classification_label: str, title: str, subtitle: str = "") -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=1.0 * cm, rightMargin=1.0 * cm,
        topMargin=1.0 * cm, bottomMargin=1.2 * cm,
        title=title,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("t", parent=styles["Title"], fontSize=16,
                                 alignment=0,  # left
                                 textColor=colors.HexColor("#0F172A"),
                                 spaceAfter=2)
    sub_style = ParagraphStyle("s", parent=styles["Normal"], fontSize=9,
                               textColor=colors.HexColor("#64748B"))
    cell_style = ParagraphStyle("c", parent=styles["Normal"], fontSize=8.2,
                                textColor=colors.HexColor("#0F172A"),
                                leading=10)
    addr_style = ParagraphStyle("a", parent=cell_style, fontSize=7.6,
                                textColor=colors.HexColor("#334155"),
                                leading=9.2)
    head_style = ParagraphStyle("h", parent=styles["Normal"], fontSize=8.5,
                                textColor=colors.white,
                                fontName="Helvetica-Bold")

    def P(text, style=cell_style):
        if text is None:
            text = ""
        return Paragraph(str(text).replace("&", "&amp;"), style)

    # Compute totals
    total_km = sum((t.get("distance_km") or 0) for t in trips)
    total_fuel = sum((t.get("fuel_l") or 0) for t in trips)
    total_min = sum((t.get("duration_min") or 0) for t in trips)
    hours = total_min // 60
    mins = total_min % 60

    # ----- Header block -----
    flow = []
    flow.append(Paragraph(title, title_style))
    meta_parts = []
    if subtitle:
        meta_parts.append(subtitle)
    meta_parts.append(f"{len(trips)} trajet{'s' if len(trips) > 1 else ''}")
    meta_parts.append(f"{total_km:,.1f} km".replace(",", "'"))
    meta_parts.append(f"{hours}h {mins:02d}min")
    meta_parts.append(f"{total_fuel:,.2f} L (est.)".replace(",", "'"))
    flow.append(Paragraph(" · ".join(meta_parts), sub_style))
    flow.append(Spacer(1, 0.35 * cm))

    # ----- Table -----
    header_row = [
        P("Date", head_style),
        P("Conducteur", head_style),
        P("Véhicule", head_style),
        P("Départ", head_style),
        P("Arrivée", head_style),
        P("Km", head_style),
        P("Durée", head_style),
        P("Carb. est. L", head_style),
        P("Type", head_style),
    ]

    data = [header_row]
    for t in trips:
        data.append([
            P(_fmt_dt(t.get("start_time", ""))),
            P(t.get("driver_name", "")),
            P(t.get("vehicle_plate", "")),
            P(t.get("start_address", ""), addr_style),
            P(t.get("end_address", ""), addr_style),
            P(f"{t.get('distance_km', 0):.1f}"),
            P(f"{t.get('duration_min', 0)} min"),
            P(f"{t['fuel_l']:.2f}" if t.get("fuel_l") is not None else "—"),
            P(classification_label),
        ])

    # Total row at the end
    bold_style = ParagraphStyle("b", parent=cell_style, fontName="Helvetica-Bold")
    data.append([
        P("", bold_style), P("", bold_style), P("", bold_style),
        P("", bold_style),
        P("TOTAL", bold_style),
        P(f"{total_km:.1f}", bold_style),
        P(f"{total_min} min", bold_style),
        P(f"{total_fuel:.2f}", bold_style),
        P("", bold_style),
    ])

    # Page width in landscape A4 minus margins ~ 27.7cm
    col_widths = [
        2.5 * cm,   # Date
        2.6 * cm,   # Conducteur
        2.0 * cm,   # Véhicule
        7.2 * cm,   # Départ
        7.2 * cm,   # Arrivée
        1.5 * cm,   # Km
        1.6 * cm,   # Durée
        1.5 * cm,   # Carb. L
        1.6 * cm,   # Type
    ]

    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2196F3")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#1565C0")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F8FAFC")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E3F2FD")),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#1976D2")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        # Right-align numeric columns
        ("ALIGN", (5, 1), (7, -1), "RIGHT"),
        # Center the Type column
        ("ALIGN", (8, 1), (8, -1), "CENTER"),
    ]))
    flow.append(table)

    flow.append(Spacer(1, 0.3 * cm))
    flow.append(Paragraph(
        f"Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')} · "
        f"Logitrak — Livre de Bord · Données GPS officielles LOGITRAK",
        ParagraphStyle("foot", parent=sub_style, fontSize=7.5,
                       textColor=colors.HexColor("#94A3B8")),
    ))

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
        ["Carburant professionnel (L) — Estimé*", f"{stats['pro_fuel']:.2f}"],
        ["Carburant personnel (L) — Estimé*", f"{stats['perso_fuel']:.2f}"],
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
    flow.append(Spacer(1, 0.4 * cm))
    flow.append(Paragraph(
        FUEL_ESTIMATED_NOTE,
        ParagraphStyle("fuelnote", parent=body, fontSize=9, textColor=colors.HexColor("#B45309")),
    ))
    flow.append(Spacer(1, 0.8 * cm))
    flow.append(Paragraph(
        "Ce document est généré automatiquement par Logitrak — Livre de Bord, "
        "à partir des données GPS officielles LOGITRAK. Les kilomètres correspondent exactement "
        "aux distances enregistrées par le système. Conformité avec les exigences fiscales suisses (déduction privé/pro).",
        body,
    ))
    flow.append(Spacer(1, 0.3 * cm))
    flow.append(Paragraph(
        f"Document émis le {datetime.now().strftime('%d/%m/%Y à %H:%M')} — Logitrak SA, Genève.",
        ParagraphStyle("foot", parent=body, fontSize=9, textColor=colors.HexColor("#94A3B8")),
    ))

    doc.build(flow)
    return buf.getvalue()
