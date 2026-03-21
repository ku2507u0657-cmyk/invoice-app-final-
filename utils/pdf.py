"""
utils/pdf.py — Modern "Split Header" invoice PDF — ReportLab / Indian GST.

Design
------
- Large "Invoice" title top-left  |  Company name + address top-right
- Meta row: Billed To (left)  |  Date Issued / Invoice No. / Amount Due (right)
- Thick ACCENT (#3F3DBC) divider before items table
- Items table: Description | Rate | Qty | Amount  (ACCENT header row)
- GST summary: Subtotal → GST @ 18% → Total
- Notes + Terms footer sections
- UPI QR code block (right of totals) when UPI_ID is configured
- Rupee symbol via \\u20B9 — no custom font required

Technical
---------
- Zero KeepTogether inside Table cells (avoids tallest-row-16777218 crash)
- All env strings guarded with (.strip() / fallback)
- Images (logo, QR) only constructed when source is valid / non-empty
- A4, 20 mm margins on all four sides
- Public signatures unchanged — routes.py needs no edits
"""

import io
import os
import logging
from datetime import datetime

from reportlab.lib           import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles    import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units     import mm
from reportlab.lib.enums     import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.platypus      import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image,
)

logger = logging.getLogger(__name__)

# ── Colour palette ────────────────────────────────────────────────────────────
ACCENT  = colors.HexColor("#3F3DBC")   # headers, labels, thick divider, totals bg
DARK    = colors.HexColor("#1A1A1A")   # primary text
GREY    = colors.HexColor("#666666")   # secondary / meta text
LGREY   = colors.HexColor("#999999")   # faint labels, footer
BG_ROW  = colors.HexColor("#F4F4FB")   # alternating item-row tint
BORDER  = colors.HexColor("#DDDDF0")   # light grid lines
WHITE   = colors.white

# Status badge colours
GREEN    = colors.HexColor("#16A34A")
GREEN_BG = colors.HexColor("#DCFCE7")
AMBER    = colors.HexColor("#D97706")
AMBER_BG = colors.HexColor("#FEF3C7")
RED      = colors.HexColor("#DC2626")
RED_BG   = colors.HexColor("#FEE2E2")

# Rupee symbol — Unicode escape, works with Helvetica, no font file needed
RS = "\u20B9"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _status_colors(status):
    return {
        "paid":    (GREEN, GREEN_BG),
        "unpaid":  (AMBER, AMBER_BG),
        "overdue": (RED,   RED_BG),
    }.get(status, (GREY, BG_ROW))


def _style(styles, **kw):
    """Return a fresh ParagraphStyle without touching the shared stylesheet."""
    return ParagraphStyle(
        f"_d_{id(kw)}",
        parent    = styles["Normal"],
        textColor = kw.pop("color", DARK),
        **kw,
    )


def _rupee(display_str: str) -> str:
    """Prepend Rupee symbol if the display string does not already have one."""
    s = (display_str or "0").strip()
    return s if s.startswith(RS) else f"{RS}{s}"


# ─────────────────────────────────────────────────────────────────────────────
# Public API  — signatures are UNCHANGED so routes.py needs no edits
# ─────────────────────────────────────────────────────────────────────────────

def build_invoice_pdf_bytes(invoice, app) -> bytes:
    """Build PDF and return raw bytes (does NOT save to disk)."""
    return _render(invoice, app)


def build_and_save_invoice_pdf(invoice, app):
    """
    Build PDF, save to PDF_FOLDER, and return (bytes, relative_path).

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
    from utils.qr import build_upi_qr_for_invoice

    buf    = io.BytesIO()
    styles = getSampleStyleSheet()
    story  = []

    # ── App config (all guarded with .strip() / fallback) ────────────────────
    company_name    = (app.config.get("COMPANY_NAME",    "") or "InvoiceFlow").strip()
    company_address = (app.config.get("COMPANY_ADDRESS", "") or "").strip()
    company_phone   = (app.config.get("COMPANY_PHONE",   "") or "").strip()
    company_email   = (app.config.get("COMPANY_EMAIL",   "") or "").strip()
    company_gstin   = (app.config.get("COMPANY_GSTIN",   "") or "").strip()
    company_logo    = (app.config.get("COMPANY_LOGO",    "") or "").strip()
    upi_id          = (app.config.get("UPI_ID",          "") or "").strip()
    terms_text      = (app.config.get("INVOICE_TERMS",   "") or
                       "Please pay within 30 days of the invoice date.").strip()

    W = A4[0] - 40 * mm          # usable width with 20 mm margins each side

    doc = SimpleDocTemplate(
        buf,
        pagesize     = A4,
        leftMargin   = 20 * mm,
        rightMargin  = 20 * mm,
        topMargin    = 20 * mm,
        bottomMargin = 20 * mm,
        title        = f"Invoice {invoice.invoice_number}",
        author       = company_name,
    )

    def S(**kw):                 # shorthand style builder
        return _style(styles, **kw)

    # ── Client fields ─────────────────────────────────────────────────────────
    c = invoice.client
    client_name    = (getattr(c, "name",       "") or "Client").strip()
    client_email   = (getattr(c, "email",      "") or "").strip()
    client_phone   = (getattr(c, "phone",      "") or "").strip()
    client_address = (getattr(c, "address",    "") or "").strip()
    client_gstin   = (getattr(c, "gst_number", "") or "").strip()

    amount_display = _rupee(invoice.amount_display)
    gst_display    = _rupee(invoice.gst_display)
    total_display  = _rupee(invoice.total_display)

    # ══════════════════════════════════════════════════════════════════════════
    # 1. SPLIT HEADER
    #    Left  — large "Invoice" title (+ optional logo above)
    #    Right — company name + address, right-aligned
    # ══════════════════════════════════════════════════════════════════════════

    # Left column — nested single-col Table (NO KeepTogether)
    left_rows = []
    if company_logo and os.path.exists(company_logo):
        try:
            left_rows.append(
                [Image(company_logo, width=36*mm, height=14*mm, kind="proportional")]
            )
            left_rows.append([Spacer(1, 4)])
        except Exception:
            pass   # broken logo → skip silently

    left_rows.append([
        Paragraph("Invoice",
                  S(fontSize=34, fontName="Helvetica-Bold", color=DARK, leading=42))
    ])

    left_inner = Table(left_rows, colWidths=[W * 0.50])
    left_inner.setStyle(TableStyle([
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 2),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
    ]))

    # Right column — nested single-col Table (NO KeepTogether)
    right_rows = [[
        Paragraph(company_name,
                  S(fontSize=11, fontName="Helvetica-Bold",
                    color=DARK, alignment=TA_RIGHT, leading=15))
    ]]
    if company_address:
        for seg in company_address.split(","):
            seg = seg.strip()
            if seg:
                right_rows.append([
                    Paragraph(seg, S(fontSize=8.5, color=GREY,
                                     alignment=TA_RIGHT, leading=12))
                ])
    for part in filter(None, [company_phone, company_email]):
        right_rows.append([
            Paragraph(part, S(fontSize=8.5, color=GREY, alignment=TA_RIGHT, leading=12))
        ])
    if company_gstin:
        right_rows.append([
            Paragraph(f"GSTIN: {company_gstin}",
                      S(fontSize=8, color=LGREY, alignment=TA_RIGHT, leading=11))
        ])

    right_inner = Table(right_rows, colWidths=[W * 0.50])
    right_inner.setStyle(TableStyle([
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 2),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
    ]))

    hdr = Table([[left_inner, right_inner]], colWidths=[W*0.50, W*0.50])
    hdr.setStyle(TableStyle([
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 0),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 10*mm))

    # ══════════════════════════════════════════════════════════════════════════
    # 2. META ROW
    #    Left  — "Billed To" block
    #    Right — 3-col sub-table: Date Issued | Invoice Number | Amount Due
    #                             Due Date    | Status
    # ══════════════════════════════════════════════════════════════════════════

    # Billed To — nested single-col Table
    bt_rows = [
        [Paragraph("Billed To",
                   S(fontSize=8, fontName="Helvetica-Bold",
                     color=ACCENT, leading=11))],
        [Paragraph(client_name,
                   S(fontSize=10, fontName="Helvetica-Bold",
                     color=DARK, leading=14))],
    ]
    if client_address:
        bt_rows.append([
            Paragraph(client_address, S(fontSize=8.5, color=GREY, leading=12))
        ])
    if client_email:
        bt_rows.append([
            Paragraph(client_email, S(fontSize=8.5, color=GREY, leading=12))
        ])
    if client_phone:
        bt_rows.append([
            Paragraph(client_phone, S(fontSize=8.5, color=GREY, leading=12))
        ])
    if client_gstin:
        bt_rows.append([
            Paragraph(f"GSTIN: {client_gstin}",
                      S(fontSize=8, color=LGREY, leading=11))
        ])

    bt_inner = Table(bt_rows, colWidths=[W * 0.46])
    bt_inner.setStyle(TableStyle([
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 2),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
    ]))

    # Status badge
    eff     = invoice.effective_status
    tc, bgc = _status_colors(eff)
    badge   = Table(
        [[Paragraph(eff.upper(),
                    S(fontSize=7, fontName="Helvetica-Bold",
                      color=tc, alignment=TA_CENTER))]],
        colWidths=[22*mm],
    )
    badge.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), bgc),
        ("TOPPADDING",    (0,0),(-1,-1), 2),
        ("BOTTOMPADDING", (0,0),(-1,-1), 2),
        ("LEFTPADDING",   (0,0),(-1,-1), 5),
        ("RIGHTPADDING",  (0,0),(-1,-1), 5),
    ]))

    col_w3 = W * 0.54 / 3

    def _ml(text):   # meta label
        return Paragraph(text,
               S(fontSize=7.5, fontName="Helvetica-Bold",
                 color=ACCENT, leading=10))

    def _mv(text, bold=False):   # meta value
        return Paragraph(text,
               S(fontSize=9,
                 fontName="Helvetica-Bold" if bold else "Helvetica",
                 color=DARK, leading=13))

    meta3 = Table(
        [
            [_ml("Date Issued"),  _ml("Invoice Number"),  _ml("Amount Due")],
            [_mv(invoice.created_at.strftime("%d/%m/%Y")),
             _mv(invoice.invoice_number),
             _mv(total_display, bold=True)],
            [_ml("Due Date"),     _ml("Status"),           Spacer(1,1)],
            [_mv(invoice.due_date.strftime("%d/%m/%Y")),
             badge,
             Spacer(1,1)],
        ],
        colWidths=[col_w3, col_w3, col_w3],
    )
    meta3.setStyle(TableStyle([
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
        ("TOPPADDING",    (0,0),(-1,-1), 3),
        ("BOTTOMPADDING", (0,0),(-1,-1), 3),
        ("LEFTPADDING",   (0,0),(-1,-1), 6),
        ("RIGHTPADDING",  (0,0),(-1,-1), 6),
        ("LEFTPADDING",   (0,0),(0,-1),  0),
        ("LINEBELOW",     (0,1),(-1,1),  0.5, BORDER),
    ]))

    meta_row = Table([[bt_inner, meta3]], colWidths=[W*0.46, W*0.54])
    meta_row.setStyle(TableStyle([
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 0),
    ]))
    story.append(meta_row)
    story.append(Spacer(1, 8*mm))

    # ══════════════════════════════════════════════════════════════════════════
    # 3. THICK ACCENT DIVIDER
    # ══════════════════════════════════════════════════════════════════════════
    story.append(HRFlowable(width="100%", thickness=3, color=ACCENT,
                            spaceBefore=0, spaceAfter=6))

    # ══════════════════════════════════════════════════════════════════════════
    # 4. ITEMS TABLE  — Description | Rate | Qty | Amount
    # ══════════════════════════════════════════════════════════════════════════
    cw = [W*0.46, W*0.18, W*0.12, W*0.24]

    def th(text, align=TA_LEFT):
        return Paragraph(text,
               S(fontSize=8.5, fontName="Helvetica-Bold",
                 color=WHITE, alignment=align))

    def td(text, align=TA_LEFT, bold=False):
        return Paragraph(text,
               S(fontSize=9, color=DARK,
                 fontName="Helvetica-Bold" if bold else "Helvetica",
                 alignment=align, leading=13))

    item_desc = (invoice.notes or "").strip() or "Professional Services"

    item_rows = [
        [th("Description"), th("Rate", TA_RIGHT),
         th("Qty", TA_CENTER), th("Amount", TA_RIGHT)],
        [td(f"{item_desc}"),
         td(amount_display, TA_RIGHT),
         td("1", TA_CENTER),
         td(amount_display, TA_RIGHT, bold=True)],
    ]

    items_tbl = Table(item_rows, colWidths=cw, repeatRows=1, splitByRow=True)
    items_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,0),  ACCENT),
        ("TOPPADDING",    (0,0),(-1,0),  9),
        ("BOTTOMPADDING", (0,0),(-1,0),  9),
        ("LEFTPADDING",   (0,0),(-1,0),  10),
        ("RIGHTPADDING",  (0,0),(-1,0),  10),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, BG_ROW]),
        ("TOPPADDING",    (0,1),(-1,-1), 8),
        ("BOTTOMPADDING", (0,1),(-1,-1), 8),
        ("LEFTPADDING",   (0,1),(-1,-1), 10),
        ("RIGHTPADDING",  (0,1),(-1,-1), 10),
        ("LINEBELOW",     (0,1),(-1,-1), 0.5, BORDER),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    story.append(items_tbl)
    story.append(Spacer(1, 6*mm))

    # ══════════════════════════════════════════════════════════════════════════
    # 5. TOTALS  +  optional UPI QR (right of totals)
    # ══════════════════════════════════════════════════════════════════════════
    label_w  = 48 * mm
    value_w  = 34 * mm
    spacer_w = W - label_w - value_w

    def _tr(label, val, bold=False, highlight=False):
        fn  = "Helvetica-Bold" if bold else "Helvetica"
        col = WHITE if highlight else DARK
        return [
            Spacer(1, 1),
            Paragraph(label, S(fontSize=9, fontName=fn,
                                color=col, alignment=TA_RIGHT)),
            Paragraph(val,   S(fontSize=9, fontName=fn,
                                color=col, alignment=TA_RIGHT)),
        ]

    tots_data = [
        _tr("Subtotal",  amount_display),
        _tr("GST @ 18%", gst_display),
        _tr("Total",     total_display, bold=True, highlight=True),
    ]
    tots_tbl = Table(tots_data, colWidths=[spacer_w, label_w, value_w])
    tots_tbl.setStyle(TableStyle([
        # spacer column — zero padding
        ("LEFTPADDING",   (0,0),(0,-1),  0),
        ("RIGHTPADDING",  (0,0),(0,-1),  0),
        ("TOPPADDING",    (0,0),(0,-1),  0),
        ("BOTTOMPADDING", (0,0),(0,-1),  0),
        # label + value columns
        ("TOPPADDING",    (1,0),(-1,-1), 5),
        ("BOTTOMPADDING", (1,0),(-1,-1), 5),
        ("LEFTPADDING",   (1,0),(-1,-1), 10),
        ("RIGHTPADDING",  (1,0),(-1,-1), 10),
        ("LINEABOVE",     (1,0),(-1,0),  0.75, BORDER),
        ("LINEABOVE",     (1,2),(-1,2),  1.5,  ACCENT),
        ("BACKGROUND",    (1,2),(-1,2),  ACCENT),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))

    # UPI QR — only if qr_bytes is non-empty AND upi_id is set
    qr_bytes = build_upi_qr_for_invoice(invoice, app)
    if qr_bytes and upi_id:
        qr_img = Image(io.BytesIO(qr_bytes), width=28*mm, height=28*mm)

        qr_label_rows = [
            [Paragraph("Scan to Pay (UPI)",
                        S(fontSize=7.5, fontName="Helvetica-Bold",
                          color=GREY, alignment=TA_CENTER))],
            [Paragraph(upi_id,
                        S(fontSize=7, color=LGREY, alignment=TA_CENTER))],
        ]
        qr_label_inner = Table(qr_label_rows, colWidths=[32*mm])
        qr_label_inner.setStyle(TableStyle([
            ("ALIGN",         (0,0),(-1,-1), "CENTER"),
            ("LEFTPADDING",   (0,0),(-1,-1), 0),
            ("RIGHTPADDING",  (0,0),(-1,-1), 0),
            ("TOPPADDING",    (0,0),(-1,-1), 1),
            ("BOTTOMPADDING", (0,0),(-1,-1), 1),
        ]))
        qr_block = Table([[qr_img], [qr_label_inner]], colWidths=[32*mm])
        qr_block.setStyle(TableStyle([
            ("ALIGN",         (0,0),(-1,-1), "CENTER"),
            ("TOPPADDING",    (0,0),(-1,-1), 2),
            ("BOTTOMPADDING", (0,0),(-1,-1), 2),
            ("LEFTPADDING",   (0,0),(-1,-1), 0),
            ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ]))
        combined = Table([[tots_tbl, qr_block]],
                         colWidths=[W - 34*mm, 34*mm])
        combined.setStyle(TableStyle([
            ("VALIGN",        (0,0),(-1,-1), "TOP"),
            ("LEFTPADDING",   (1,0),(1,-1),  8),
            ("RIGHTPADDING",  (1,0),(1,-1),  0),
            ("TOPPADDING",    (0,0),(-1,-1), 0),
            ("BOTTOMPADDING", (0,0),(-1,-1), 0),
        ]))
        story.append(combined)
    else:
        story.append(tots_tbl)

    story.append(Spacer(1, 10*mm))

    # ══════════════════════════════════════════════════════════════════════════
    # 6. FOOTER — Notes  +  Terms
    # ══════════════════════════════════════════════════════════════════════════
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER,
                            spaceBefore=0, spaceAfter=6))

    # Notes (invoice.notes used as line-item description above; reuse as notes)
    notes_body = (invoice.notes or "").strip()
    story.append(
        Paragraph("Notes", S(fontSize=9, fontName="Helvetica-Bold", color=ACCENT))
    )
    story.append(Spacer(1, 2))
    pay_note = (
        f"Please reference <b>{invoice.invoice_number}</b> when making payment. "
        f"Payment is due by <b>{invoice.due_date.strftime('%d %B %Y')}</b>."
    )
    if upi_id:
        pay_note += (
            " You may also scan the UPI QR code to pay instantly "
            "via GPay, PhonePe, or BHIM."
        )
    if notes_body:
        pay_note = notes_body + "  " + pay_note
    story.append(Paragraph(pay_note, S(fontSize=8.5, color=GREY, leading=13)))

    story.append(Spacer(1, 6))
    story.append(
        Paragraph("Terms", S(fontSize=9, fontName="Helvetica-Bold", color=ACCENT))
    )
    story.append(Spacer(1, 2))
    story.append(Paragraph(terms_text, S(fontSize=8.5, color=GREY, leading=13)))

    # Footer bar
    story.append(Spacer(1, 8*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=4))
    story.append(Paragraph(
        f"{company_name}  &bull;  "
        f"Generated {datetime.utcnow().strftime('%d %b %Y')}  &bull;  "
        f"{invoice.invoice_number}",
        S(fontSize=7.5, color=LGREY, alignment=TA_CENTER),
    ))

    doc.build(story)
    return buf.getvalue()
