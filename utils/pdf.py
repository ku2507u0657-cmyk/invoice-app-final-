"""
utils/pdf.py — Professional invoice PDF generation using ReportLab.

Features
--------
- Company header with optional logo
- Bill-to client details
- Line-items table with GST breakdown
- UPI QR code for instant payment
- Saves file to PDF_FOLDER/INV-NNNN.pdf
- Returns raw bytes AND saved file path

Usage
-----
    from utils.pdf import build_and_save_invoice_pdf
    pdf_bytes, rel_path = build_and_save_invoice_pdf(invoice, app)

Fix (v2)
--------
- Removed all KeepTogether wrappers from inside Table cells.
  ReportLab cannot compute the height of a KeepTogether nested inside a
  Table row, which causes the "tallest row 16777218 too large" crash.
  Flowable lists are passed directly into cells instead.
- Added .strip() / fallback guards on every env-driven string.
- Image objects (logo & QR) are only added when the source is valid.
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
    HRFlowable, Image,
)

logger = logging.getLogger(__name__)

# ── Colour palette (mirrors app CSS design tokens exactly) ────────────────
INK      = colors.HexColor("#1A1714")
INK_2    = colors.HexColor("#4A4540")
INK_3    = colors.HexColor("#8A8480")
ACCENT   = colors.HexColor("#1D4ED8")
GREEN    = colors.HexColor("#16A34A")
GREEN_BG = colors.HexColor("#DCFCE7")
AMBER    = colors.HexColor("#D97706")
AMBER_BG = colors.HexColor("#FEF3C7")
RED      = colors.HexColor("#DC2626")
RED_BG   = colors.HexColor("#FEE2E2")
BG       = colors.HexColor("#F7F6F2")
BORDER   = colors.HexColor("#E4E0D8")
WHITE    = colors.white


def _status_colors(status):
    return {
        "paid":    (GREEN, GREEN_BG),
        "unpaid":  (AMBER, AMBER_BG),
        "overdue": (RED,   RED_BG),
    }.get(status, (INK_2, BG))


def _s(styles, name="Normal", **kw):
    """Create a one-off ParagraphStyle from a base."""
    return ParagraphStyle(
        f"_dyn_{id(kw)}",
        parent    = styles.get(name, styles["Normal"]),
        textColor = kw.pop("color", INK),
        **kw,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API  (signatures are unchanged — routes.py needs no edits)
# ─────────────────────────────────────────────────────────────────────────────

def build_invoice_pdf_bytes(invoice, app) -> bytes:
    """Build PDF and return raw bytes (does NOT save to disk)."""
    return _render(invoice, app)


def build_and_save_invoice_pdf(invoice, app):
    """
    Build PDF, save it to PDF_FOLDER, and return (bytes, relative_path).

    Returns
    -------
    tuple[bytes, str]  (pdf_bytes, relative_path_from_project_root)
    """
    pdf_bytes = _render(invoice, app)

    pdf_folder = app.config.get("PDF_FOLDER", "invoices")
    os.makedirs(pdf_folder, exist_ok=True)

    filename  = f"{invoice.invoice_number}.pdf"
    full_path = os.path.join(pdf_folder, filename)
    rel_path  = os.path.join("invoices", filename)

    try:
        with open(full_path, "wb") as fh:
            fh.write(pdf_bytes)
        logger.info("PDF saved: %s", full_path)
    except OSError as exc:
        logger.error("Could not save PDF to %s: %s", full_path, exc)

    return pdf_bytes, rel_path


# ─────────────────────────────────────────────────────────────────────────────
# Core renderer
# ─────────────────────────────────────────────────────────────────────────────

def _render(invoice, app) -> bytes:
    """Build the PDF document and return its bytes."""
    from utils.qr import build_upi_qr_for_invoice

    buf    = io.BytesIO()
    styles = getSampleStyleSheet()
    story  = []

    # ── Config (with .strip() guards so empty strings never crash Paragraph) ─
    company_name    = (app.config.get("COMPANY_NAME",    "") or "InvoiceFlow").strip()
    company_address = (app.config.get("COMPANY_ADDRESS", "") or "").strip()
    company_phone   = (app.config.get("COMPANY_PHONE",   "") or "").strip()
    company_email   = (app.config.get("COMPANY_EMAIL",   "") or "").strip()
    company_gstin   = (app.config.get("COMPANY_GSTIN",   "") or "").strip()
    company_logo    = (app.config.get("COMPANY_LOGO",    "") or "").strip()
    upi_id          = (app.config.get("UPI_ID",          "") or "").strip()

    W = A4[0] - 40 * mm

    doc = SimpleDocTemplate(
        buf,
        pagesize     = A4,
        leftMargin   = 20 * mm,
        rightMargin  = 20 * mm,
        topMargin    = 16 * mm,
        bottomMargin = 16 * mm,
        title        = f"Invoice {invoice.invoice_number}",
        author       = company_name,
    )

    # Shorthand style builder
    def S(**kw):
        return _s(styles, **kw)

    # ── Header: logo + company info (left) | "INVOICE" label (right) ─────────
    #
    # FIX: KeepTogether removed.  The logo Image and the company Paragraphs
    # are placed directly in a nested Table so ReportLab can measure each
    # row individually.  A two-row inner table (logo row + text row) sits in
    # the left cell; the INVOICE heading sits in the right cell.
    # ─────────────────────────────────────────────────────────────────────────

    # Build left-cell contents as a nested table (no KeepTogether wrapper)
    left_rows = []

    # Logo row — only add when the file actually exists
    if company_logo and os.path.exists(company_logo):
        try:
            logo_img = Image(company_logo, width=36 * mm, height=14 * mm,
                             kind="proportional")
            left_rows.append([logo_img])
            left_rows.append([Spacer(1, 4)])
        except Exception:
            pass  # silently skip a broken logo

    # Company name
    left_rows.append([
        Paragraph(company_name,
                  S(fontSize=14, fontName="Helvetica-Bold", color=INK, leading=18))
    ])
    if company_address:
        left_rows.append([
            Paragraph(company_address, S(fontSize=8, color=INK_2, leading=11))
        ])
    contact = "  |  ".join(filter(None, [company_phone, company_email]))
    if contact:
        left_rows.append([
            Paragraph(contact, S(fontSize=8, color=INK_2, leading=11))
        ])
    if company_gstin:
        left_rows.append([
            Paragraph(f"GSTIN: {company_gstin}", S(fontSize=8, color=INK_3, leading=11))
        ])

    left_inner = Table(left_rows, colWidths=[W * 0.55])
    left_inner.setStyle(TableStyle([
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))

    hdr_data = [[
        left_inner,
        Paragraph("INVOICE",
                  S(fontSize=30, fontName="Helvetica-Bold",
                    color=ACCENT, alignment=TA_RIGHT)),
    ]]
    hdr = Table(hdr_data, colWidths=[W * 0.55, W * 0.45])
    hdr.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "BOTTOM"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
    ]))
    story.append(hdr)
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=8))

    # ── Status badge ──────────────────────────────────────────────────────────
    eff     = invoice.effective_status
    tc, bgc = _status_colors(eff)
    badge   = Table(
        [[Paragraph(eff.upper(),
                    S(fontSize=7.5, fontName="Helvetica-Bold",
                      color=tc, alignment=TA_CENTER))]],
        colWidths=[28 * mm],
    )
    badge.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), bgc),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
    ]))

    meta_rows = [
        [Paragraph("Invoice No.", S(fontSize=8, color=INK_3)),
         Paragraph(invoice.invoice_number,
                   S(fontSize=10, fontName="Helvetica-Bold", alignment=TA_RIGHT))],
        [Paragraph("Issue Date",  S(fontSize=8, color=INK_3)),
         Paragraph(invoice.created_at.strftime("%d %B %Y"),
                   S(fontSize=9, alignment=TA_RIGHT))],
        [Paragraph("Due Date",    S(fontSize=8, color=INK_3)),
         Paragraph(invoice.due_date.strftime("%d %B %Y"),
                   S(fontSize=9, alignment=TA_RIGHT))],
        [Paragraph("Status",      S(fontSize=8, color=INK_3)), badge],
    ]
    meta_tbl = Table(meta_rows, colWidths=[30 * mm, 38 * mm])
    meta_tbl.setStyle(TableStyle([
        ("ALIGN",         (1, 0), (1, -1), "RIGHT"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    # ── Bill-to block ─────────────────────────────────────────────────────────
    #
    # FIX: The original used KeepTogether([list of Paragraphs]) as a table
    # cell value.  Now the Paragraphs live in a nested single-column Table
    # so ReportLab can measure each row's height without confusion.
    # ─────────────────────────────────────────────────────────────────────────

    c = invoice.client
    client_name    = (getattr(c, "name",       "") or "Client").strip()
    client_email   = (getattr(c, "email",      "") or "").strip()
    client_phone   = (getattr(c, "phone",      "") or "").strip()
    client_address = (getattr(c, "address",    "") or "").strip()
    client_gstin   = (getattr(c, "gst_number", "") or "").strip()

    bill_rows = [
        [Paragraph("BILL TO",
                   S(fontSize=7.5, fontName="Helvetica-Bold",
                     color=INK_3, leading=12))],
        [Paragraph(client_name,
                   S(fontSize=11, fontName="Helvetica-Bold",
                     color=INK, leading=15))],
    ]
    if client_email:
        bill_rows.append([Paragraph(client_email, S(fontSize=9, color=INK_2, leading=13))])
    if client_phone:
        bill_rows.append([Paragraph(client_phone, S(fontSize=9, color=INK_2, leading=13))])
    if client_address:
        bill_rows.append([Paragraph(client_address, S(fontSize=8.5, color=INK_2, leading=12))])
    if client_gstin:
        bill_rows.append([Paragraph(f"GSTIN: {client_gstin}",
                                    S(fontSize=8.5, color=INK_3, leading=12))])

    bill_inner = Table(bill_rows, colWidths=[W * 0.52])
    bill_inner.setStyle(TableStyle([
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))

    info_tbl = Table(
        [[bill_inner, meta_tbl]],
        colWidths=[W * 0.52, W * 0.48],
    )
    info_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ]))
    story.append(info_tbl)
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=12))

    # ── Line-items table ──────────────────────────────────────────────────────
    cw = [W * 0.52, W * 0.10, W * 0.19, W * 0.19]

    def th(text, align=TA_LEFT):
        return Paragraph(text,
               S(fontSize=8.5, fontName="Helvetica-Bold",
                 color=WHITE, alignment=align))

    def td(text, align=TA_LEFT, bold=False):
        return Paragraph(text,
               S(fontSize=9, color=INK_2,
                 fontName="Helvetica-Bold" if bold else "Helvetica",
                 alignment=align, leading=13))

    desc = (invoice.notes or "").strip() or "Professional Services"

    items = [
        [th("Description"), th("Qty", TA_CENTER),
         th("Rate", TA_RIGHT), th("Amount", TA_RIGHT)],
        [td(f"{desc} — {client_name}"),
         td("1", TA_CENTER),
         td(invoice.amount_display, TA_RIGHT),
         td(invoice.amount_display, TA_RIGHT)],
    ]
    items_tbl = Table(
    items,
    colWidths=cw,
    repeatRows=1,
    splitByRow=True   
    )
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  INK),
        ("TOPPADDING",     (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 8),
        ("LEFTPADDING",    (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 10),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, BG]),
        ("LINEBELOW",      (0, 1), (-1, -1), 0.5, BORDER),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(items_tbl)
    story.append(Spacer(1, 4 * mm))

    # ── Totals + QR block ─────────────────────────────────────────────────────
    label_w  = 44 * mm
    value_w  = 30 * mm
    spacer_w = W - label_w - value_w

    def tot(label, val, bold=False, inv_colors=False):
        fn = "Helvetica-Bold" if bold else "Helvetica"
        tc = WHITE if inv_colors else INK
        return [
            Spacer(1, 1),
            Paragraph(label, S(fontSize=9, fontName=fn, color=tc, alignment=TA_RIGHT)),
            Paragraph(val,   S(fontSize=9, fontName=fn, color=tc, alignment=TA_RIGHT)),
        ]

    tots = [
        tot("Subtotal (excl. GST)", invoice.amount_display),
        tot("GST @ 18%",            invoice.gst_display),
        tot("Total Payable",         invoice.total_display, bold=True, inv_colors=True),
    ]
    tots_tbl = Table(tots, colWidths=[spacer_w, label_w, value_w])
    tots_tbl.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (1, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (1, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (0, -1),  0),
        ("RIGHTPADDING",  (0, 0), (0, -1),  0),
        ("TOPPADDING",    (0, 0), (0, -1),  0),
        ("BOTTOMPADDING", (0, 0), (0, -1),  0),
        ("LINEABOVE",     (1, 0), (-1, 0),  0.75, BORDER),
        ("LINEABOVE",     (1, 2), (-1, 2),  0.75, INK),
        ("BACKGROUND",    (1, 2), (-1, 2),  INK),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))

    # ── UPI QR code ───────────────────────────────────────────────────────────
    #
    # FIX: The QR label block previously used KeepTogether([Paragraph, Paragraph])
    # as a table cell.  Now the two Paragraphs live in a nested Table directly.
    # Image is only constructed when qr_bytes is truthy (non-empty bytes).
    # ─────────────────────────────────────────────────────────────────────────

    qr_bytes = build_upi_qr_for_invoice(invoice, app)
    if qr_bytes and upi_id:
        qr_img = Image(io.BytesIO(qr_bytes), width=28 * mm, height=28 * mm)

        label_rows = [
            [Paragraph("Scan to Pay (UPI)",
                        S(fontSize=7.5, fontName="Helvetica-Bold",
                          color=INK_2, alignment=TA_CENTER))],
            [Paragraph(upi_id,
                        S(fontSize=7, color=INK_3, alignment=TA_CENTER))],
        ]
        label_inner = Table(label_rows, colWidths=[32 * mm])
        label_inner.setStyle(TableStyle([
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ("TOPPADDING",    (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))

        qr_block = Table(
            [[qr_img], [label_inner]],
            colWidths=[32 * mm],
        )
        qr_block.setStyle(TableStyle([
            ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
            ("TOPPADDING",    (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ]))

        combined = Table(
            [[tots_tbl, qr_block]],
            colWidths=[W - 34 * mm, 34 * mm],
        )
        combined.setStyle(TableStyle([
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",  (1, 0), (1, -1),  8),
            ("RIGHTPADDING", (1, 0), (1, -1),  0),
            ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
        ]))
        story.append(combined)
    else:
        story.append(tots_tbl)

    story.append(Spacer(1, 8 * mm))

    # ── Payment notes ─────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.75, color=BORDER,
                            spaceBefore=2, spaceAfter=6))
    story.append(Paragraph("Payment Notes",
                            S(fontSize=9, fontName="Helvetica-Bold", color=INK_2)))
    story.append(Spacer(1, 3))
    pay_note = (
        f"Please reference <b>{invoice.invoice_number}</b> when making payment. "
        f"Payment is due by <b>{invoice.due_date.strftime('%d %B %Y')}</b>."
    )
    if upi_id:
        pay_note += (
            " You may also scan the UPI QR code to pay instantly "
            "via GPay, PhonePe, or BHIM."
        )
    story.append(Paragraph(pay_note, S(fontSize=8.5, color=INK_2, leading=13)))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=0.75, color=BORDER, spaceAfter=5))
    story.append(Paragraph(
        f"{company_name}  &bull;  "
        f"Generated {datetime.utcnow().strftime('%d %b %Y')}  &bull;  "
        f"{invoice.invoice_number}",
        S(fontSize=7.5, color=INK_3, alignment=TA_CENTER),
    ))

    doc.build(story)
    return buf.getvalue()
