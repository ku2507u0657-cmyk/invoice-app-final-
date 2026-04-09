"""
utils/bill_pdf.py — Itemized Bill PDF generation using ReportLab.
Supports multiple line items, per-item GST rates, UPI QR code.
"""

import io
import os
import logging
from datetime import datetime

from reportlab.lib            import colors
from reportlab.lib.pagesizes  import A4
from reportlab.lib.styles     import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units      import mm
from reportlab.lib.enums      import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.platypus       import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether, Image,
)

logger = logging.getLogger(__name__)

# ── Colours (same palette as invoice PDF) ───────────────────────
INK      = colors.HexColor("#1A1714")
INK_2    = colors.HexColor("#4A4540")
INK_3    = colors.HexColor("#8A8480")
ACCENT   = colors.HexColor("#1D4ED8")
GREEN    = colors.HexColor("#16A34A")
GREEN_BG = colors.HexColor("#DCFCE7")
AMBER    = colors.HexColor("#D97706")
AMBER_BG = colors.HexColor("#FEF3C7")
RED      = colors.HexColor("#DC2626")
BG       = colors.HexColor("#F7F6F2")
BORDER   = colors.HexColor("#E4E0D8")
WHITE    = colors.white


def _s(styles, name="Normal", **kw):
    return ParagraphStyle(
        f"_dyn_{id(kw)}",
        parent    = styles.get(name, styles["Normal"]),
        textColor = kw.pop("color", INK),
        **kw,
    )


def build_and_save_bill_pdf(bill, app):
    """
    Build itemized bill PDF, save to PDF_FOLDER, return (bytes, rel_path).
    """
    pdf_bytes = _render(bill, app)

    pdf_folder = app.config.get("PDF_FOLDER", "invoices")
    os.makedirs(pdf_folder, exist_ok=True)

    filename  = f"{bill.bill_number}.pdf"
    full_path = os.path.join(pdf_folder, filename)
    rel_path  = os.path.join("invoices", filename)

    try:
        with open(full_path, "wb") as fh:
            fh.write(pdf_bytes)
        logger.info("Bill PDF saved: %s", full_path)
    except OSError as exc:
        logger.error("Could not save bill PDF: %s", exc)

    return pdf_bytes, rel_path


def build_bill_pdf_bytes(bill, app):
    return _render(bill, app)


def _render(bill, app) -> bytes:
    from utils.qr import build_upi_qr_for_invoice

    buf    = io.BytesIO()
    styles = getSampleStyleSheet()

    company_name    = app.config.get("COMPANY_NAME",    "InvoiceFlow")
    company_address = app.config.get("COMPANY_ADDRESS", "")
    company_phone   = app.config.get("COMPANY_PHONE",   "")
    company_email   = app.config.get("COMPANY_EMAIL",   "")
    company_gstin   = app.config.get("COMPANY_GSTIN",   "")
    company_logo    = app.config.get("COMPANY_LOGO",    "")
    upi_id          = app.config.get("UPI_ID",          "")

    W = A4[0] - 40 * mm

    doc = SimpleDocTemplate(
        buf,
        pagesize     = A4,
        leftMargin   = 20 * mm,
        rightMargin  = 20 * mm,
        topMargin    = 16 * mm,
        bottomMargin = 16 * mm,
        title        = f"Bill {bill.bill_number}",
        author       = company_name,
    )

    S = lambda **kw: _s(styles, **kw)
    story = []

    # ── Header ────────────────────────────────────────────────
    logo_cell = Spacer(1, 1)
    if company_logo and os.path.exists(company_logo):
        try:
            logo_cell = Image(company_logo, width=36*mm, height=14*mm, kind="proportional")
        except Exception:
            pass

    co_lines = [Paragraph(company_name,
                S(fontSize=14, fontName="Helvetica-Bold", color=INK))]
    if company_address:
        co_lines.append(Paragraph(company_address, S(fontSize=8, color=INK_2, leading=11)))
    if company_phone or company_email:
        co_lines.append(Paragraph("  |  ".join(filter(None, [company_phone, company_email])),
                        S(fontSize=8, color=INK_2, leading=11)))
    if company_gstin:
        co_lines.append(Paragraph(f"GSTIN: {company_gstin}", S(fontSize=8, color=INK_3, leading=11)))

    hdr = Table([[
        KeepTogether([logo_cell, Spacer(1, 4)] + co_lines),
        Paragraph("BILL", S(fontSize=30, fontName="Helvetica-Bold",
                             color=ACCENT, alignment=TA_RIGHT)),
    ]], colWidths=[W * 0.55, W * 0.45])
    hdr.setStyle(TableStyle([("VALIGN", (0,0),(-1,-1), "BOTTOM"),
                              ("BOTTOMPADDING", (0,0),(-1,-1), 0)]))
    story.append(hdr)
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=8))

    # ── Bill meta + Bill-to ────────────────────────────────────
    eff = bill.effective_status
    tc  = {"paid": GREEN, "unpaid": AMBER, "overdue": RED, "draft": INK_3}.get(eff, INK_2)
    bgc = {"paid": GREEN_BG, "unpaid": AMBER_BG, "overdue": colors.HexColor("#FEE2E2"),
           "draft": BG}.get(eff, BG)

    badge = Table([[Paragraph(eff.upper(),
                   S(fontSize=7.5, fontName="Helvetica-Bold",
                     color=tc, alignment=TA_CENTER))]],
                  colWidths=[28*mm])
    badge.setStyle(TableStyle([
        ("BACKGROUND", (0,0),(-1,-1), bgc),
        ("TOPPADDING",    (0,0),(-1,-1), 3), ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 6), ("RIGHTPADDING",  (0,0),(-1,-1), 6),
    ]))

    meta_rows = [
        [Paragraph("Bill No.", S(fontSize=8, color=INK_3)),
         Paragraph(bill.bill_number, S(fontSize=10, fontName="Helvetica-Bold", alignment=TA_RIGHT))],
        [Paragraph("Issue Date", S(fontSize=8, color=INK_3)),
         Paragraph(bill.created_at.strftime("%d %B %Y"), S(fontSize=9, alignment=TA_RIGHT))],
    ]
    if bill.due_date:
        meta_rows.append([
            Paragraph("Due Date", S(fontSize=8, color=INK_3)),
            Paragraph(bill.due_date.strftime("%d %B %Y"), S(fontSize=9, alignment=TA_RIGHT)),
        ])
    meta_rows.append([Paragraph("Status", S(fontSize=8, color=INK_3)), badge])

    meta_tbl = Table(meta_rows, colWidths=[30*mm, 38*mm])
    meta_tbl.setStyle(TableStyle([
        ("ALIGN", (1,0),(1,-1), "RIGHT"), ("VALIGN", (0,0),(-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0),(-1,-1), 3), ("BOTTOMPADDING", (0,0),(-1,-1), 3),
    ]))

    c = bill.client
    bill_lines = [
        Paragraph("BILL TO", S(fontSize=7.5, fontName="Helvetica-Bold", color=INK_3, leading=12)),
        Paragraph(c.name, S(fontSize=11, fontName="Helvetica-Bold", color=INK, leading=15)),
    ]
    if c.email:
        bill_lines.append(Paragraph(c.email, S(fontSize=9, color=INK_2, leading=13)))
    if c.phone:
        bill_lines.append(Paragraph(c.phone, S(fontSize=9, color=INK_2, leading=13)))
    if c.address:
        bill_lines.append(Paragraph(c.address, S(fontSize=8.5, color=INK_2, leading=12)))
    if c.gst_number:
        bill_lines.append(Paragraph(f"GSTIN: {c.gst_number}",
                          S(fontSize=8.5, color=INK_3, leading=12)))

    info_tbl = Table([[KeepTogether(bill_lines), meta_tbl]],
                     colWidths=[W * 0.52, W * 0.48])
    info_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0),(-1,-1), "TOP"),
        ("TOPPADDING", (0,0),(-1,-1), 8), ("BOTTOMPADDING", (0,0),(-1,-1), 8),
    ]))
    story.append(info_tbl)
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=12))

    # ── Line-items table ──────────────────────────────────────
    # Columns: #  |  Item  |  Desc  |  Qty  |  Rate  |  GST%  |  GST Amt  |  Total
    cw = [W*0.04, W*0.22, W*0.18, W*0.07, W*0.12, W*0.07, W*0.12, W*0.13]

    def th(text, align=TA_LEFT):
        return Paragraph(text, S(fontSize=7.5, fontName="Helvetica-Bold",
                                  color=WHITE, alignment=align))
    def td(text, align=TA_LEFT, bold=False, color=INK_2):
        return Paragraph(text, S(fontSize=8.5, color=color,
                                  fontName="Helvetica-Bold" if bold else "Helvetica",
                                  alignment=align, leading=12))

    header = [th("#"), th("Item"), th("Description"),
              th("Qty", TA_RIGHT), th("Rate", TA_RIGHT),
              th("GST%", TA_CENTER), th("GST Amt", TA_RIGHT), th("Total", TA_RIGHT)]

    rows = [header]
    for i, item in enumerate(bill.items, 1):
        rows.append([
            td(str(i), TA_CENTER),
            td(item.item_name, bold=True, color=INK),
            td(item.description or "", color=INK_3),
            td(f"{float(item.quantity):g}", TA_RIGHT),
            td(f"\u20b9{float(item.rate):,.2f}", TA_RIGHT),
            td(item.gst_rate_display, TA_CENTER),
            td(f"\u20b9{float(item.gst_amount):,.2f}", TA_RIGHT, color=ACCENT),
            td(f"\u20b9{float(item.item_total):,.2f}", TA_RIGHT, bold=True, color=INK),
        ])

    items_tbl = Table(rows, colWidths=cw, repeatRows=1)
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND",     (0,0), (-1,0), INK),
        ("TOPPADDING",     (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 6),
        ("LEFTPADDING",    (0,0), (-1,-1), 5),
        ("RIGHTPADDING",   (0,0), (-1,-1), 5),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, BG]),
        ("LINEBELOW",      (0,1), (-1,-1), 0.5, BORDER),
        ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(items_tbl)
    story.append(Spacer(1, 4*mm))

    # ── Totals ─────────────────────────────────────────────────
    label_w  = 44 * mm
    value_w  = 30 * mm
    spacer_w = W - label_w - value_w

    def tot(label, val, bold=False, inv=False):
        fn = "Helvetica-Bold" if bold else "Helvetica"
        tc = WHITE if inv else INK
        return [Spacer(1,1),
                Paragraph(label, S(fontSize=9, fontName=fn, color=tc, alignment=TA_RIGHT)),
                Paragraph(val,   S(fontSize=9, fontName=fn, color=tc, alignment=TA_RIGHT))]

    tots_data = [
        tot("Subtotal (excl. GST)", bill.subtotal_display),
        tot("Total GST",            bill.total_gst_display),
        tot("Grand Total",          bill.grand_total_display, bold=True, inv=True),
    ]
    if bill.notes:
        story.append(Paragraph(f"<b>Notes:</b> {bill.notes}",
                     S(fontSize=8.5, color=INK_2)))
        story.append(Spacer(1, 3*mm))

    tots_tbl = Table(tots_data, colWidths=[spacer_w, label_w, value_w])
    tots_tbl.setStyle(TableStyle([
        ("TOPPADDING",    (0,0),(-1,-1), 5), ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (1,0),(-1,-1), 10), ("RIGHTPADDING", (1,0),(-1,-1), 10),
        ("LEFTPADDING",   (0,0),(0,-1), 0),   ("RIGHTPADDING", (0,0),(0,-1), 0),
        ("TOPPADDING",    (0,0),(0,-1), 0),   ("BOTTOMPADDING",(0,0),(0,-1), 0),
        ("LINEABOVE",     (1,0),(-1,0), 0.75, BORDER),
        ("LINEABOVE",     (1,2),(-1,2), 0.75, INK),
        ("BACKGROUND",    (1,2),(-1,2), INK),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))

    # UPI QR
    qr_bytes = b""
    try:
        from utils.qr import build_upi_qr_bytes
        if upi_id:
            from utils.qr import build_upi_qr_bytes
            upi_payee = app.config.get("UPI_PAYEE_NAME", company_name)
            qr_bytes  = build_upi_qr_bytes(upi_id, upi_payee,
                                            float(bill.grand_total), bill.bill_number)
    except Exception:
        pass

    if qr_bytes and upi_id:
        qr_img   = Image(io.BytesIO(qr_bytes), width=28*mm, height=28*mm)
        qr_block = Table([[qr_img],
                           [Paragraph("Scan to Pay (UPI)",
                             S(fontSize=7.5, fontName="Helvetica-Bold",
                               color=INK_2, alignment=TA_CENTER))],
                           [Paragraph(upi_id,
                             S(fontSize=7, color=INK_3, alignment=TA_CENTER))]],
                          colWidths=[32*mm])
        qr_block.setStyle(TableStyle([
            ("ALIGN", (0,0),(-1,-1), "CENTER"),
            ("TOPPADDING", (0,0),(-1,-1), 2), ("BOTTOMPADDING", (0,0),(-1,-1), 2),
        ]))
        combined = Table([[tots_tbl, qr_block]],
                          colWidths=[W - 34*mm, 34*mm])
        combined.setStyle(TableStyle([
            ("VALIGN",       (0,0),(-1,-1), "TOP"),
            ("LEFTPADDING",  (1,0),(1,-1), 8),
            ("RIGHTPADDING", (1,0),(1,-1), 0),
        ]))
        story.append(combined)
    else:
        story.append(tots_tbl)

    story.append(Spacer(1, 8*mm))

    # ── Footer ────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.75, color=BORDER, spaceAfter=5))
    story.append(Paragraph(
        f"{company_name}  &bull;  "
        f"Generated {datetime.utcnow().strftime('%d %b %Y')}  &bull;  "
        f"{bill.bill_number}",
        S(fontSize=7.5, color=INK_3, alignment=TA_CENTER),
    ))

    doc.build(story)
    return buf.getvalue()
