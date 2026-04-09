"""
utils/email.py — Email delivery via smtplib for InvoiceFlow.

Public API
----------
    send_invoice_email(invoice, app)               -> None
    send_reminder_email(invoice, app, days_overdue) -> None
"""

import logging
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart   import MIMEMultipart
from email.mime.text        import MIMEText

logger = logging.getLogger(__name__)


class EmailError(Exception):
    """Raised when email delivery fails."""


# ─────────────────────────────────────────────────────────────
#  Public: send original invoice
# ─────────────────────────────────────────────────────────────

def send_invoice_email(invoice, app) -> None:
    cfg          = app.config
    company_name = cfg.get("COMPANY_NAME", cfg.get("APP_NAME", "InvoiceFlow"))

    _guard_enabled(cfg)
    recipient = _resolve_recipient(invoice, cfg)

    # Build PDF bytes
    from utils.pdf import build_invoice_pdf_bytes
    pdf_bytes = _safe_pdf(invoice, app)

    subject    = f"Invoice {invoice.invoice_number} from {company_name}"
    html_body  = _render_template(app, "emails/invoice_email.html",
                                  invoice=invoice, company_name=company_name)
    plain_body = _plain_invoice(invoice, company_name)

    msg = _assemble(
        subject      = subject,
        from_name    = cfg.get("MAIL_FROM_NAME",    company_name),
        from_address = cfg.get("MAIL_FROM_ADDRESS", cfg.get("MAIL_USERNAME", "")),
        recipient    = recipient,
        plain_body   = plain_body,
        html_body    = html_body,
        pdf_bytes    = pdf_bytes,
        pdf_filename = f"{invoice.invoice_number}.pdf",
    )
    _smtp_send(msg, recipient, cfg)
    logger.info("Invoice email sent: %s -> %s", invoice.invoice_number, recipient)


# ─────────────────────────────────────────────────────────────
#  Public: send reminder
# ─────────────────────────────────────────────────────────────

def send_reminder_email(invoice, app, days_overdue: int = 0) -> None:
    cfg          = app.config
    company_name = cfg.get("COMPANY_NAME", cfg.get("APP_NAME", "InvoiceFlow"))

    _guard_enabled(cfg)
    recipient = _resolve_recipient(invoice, cfg)
    pdf_bytes = _safe_pdf(invoice, app)

    day_str = f"{days_overdue} day{'s' if days_overdue != 1 else ''}"
    subject = f"Payment Reminder: {invoice.invoice_number} is {day_str} overdue"

    html_body  = _render_template(app, "emails/reminder_email.html",
                                  invoice=invoice, company_name=company_name,
                                  days_overdue=days_overdue)
    plain_body = _plain_reminder(invoice, company_name, days_overdue)

    msg = _assemble(
        subject      = subject,
        from_name    = cfg.get("MAIL_FROM_NAME",    company_name),
        from_address = cfg.get("MAIL_FROM_ADDRESS", cfg.get("MAIL_USERNAME", "")),
        recipient    = recipient,
        plain_body   = plain_body,
        html_body    = html_body,
        pdf_bytes    = pdf_bytes,
        pdf_filename = f"{invoice.invoice_number}.pdf",
    )
    _smtp_send(msg, recipient, cfg)
    logger.info("Reminder sent: %s -> %s (%d days overdue)",
                invoice.invoice_number, recipient, days_overdue)


# ─────────────────────────────────────────────────────────────
#  Private helpers
# ─────────────────────────────────────────────────────────────

def _guard_enabled(cfg):
    if not cfg.get("MAIL_ENABLED", False):
        raise EmailError("Email sending is disabled (MAIL_ENABLED=False).")


def _resolve_recipient(invoice, cfg):
    r = invoice.client.email or cfg.get("MAIL_FALLBACK_RECIPIENT")
    if not r:
        raise EmailError(
            f"No recipient for {invoice.invoice_number}: "
            "client has no email and MAIL_FALLBACK_RECIPIENT is not set."
        )
    return r


def _safe_pdf(invoice, app):
    """Try to build PDF; return empty bytes on failure (don't block email)."""
    try:
        from utils.pdf import build_invoice_pdf_bytes
        return build_invoice_pdf_bytes(invoice, app)
    except Exception as exc:
        logger.error("PDF build failed for email attachment: %s", exc)
        return b""


def _render_template(app, path, **ctx):
    with app.app_context():
        return app.jinja_env.get_template(path).render(**ctx)


def _assemble(subject, from_name, from_address, recipient,
              plain_body, html_body, pdf_bytes, pdf_filename):
    root = MIMEMultipart("mixed")
    root["Subject"] = subject
    root["From"]    = f"{from_name} <{from_address}>"
    root["To"]      = recipient

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body,  "html",  "utf-8"))
    root.attach(alt)

    if pdf_bytes:
        part = MIMEApplication(pdf_bytes, _subtype="pdf")
        part.add_header("Content-Disposition", "attachment", filename=pdf_filename)
        root.attach(part)

    return root


def _smtp_send(msg, recipient, cfg):
    username = cfg.get("MAIL_USERNAME")
    password = cfg.get("MAIL_PASSWORD")
    if not username or not password:
        raise EmailError("MAIL_USERNAME and MAIL_PASSWORD must both be set.")

    server  = cfg.get("MAIL_SERVER",  "smtp.gmail.com")
    port    = cfg.get("MAIL_PORT",    587)
    use_tls = cfg.get("MAIL_USE_TLS", True)

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(server, port, timeout=15) as smtp:
            smtp.ehlo()
            if use_tls:
                smtp.starttls(context=ctx)
                smtp.ehlo()
            smtp.login(username, password)
            smtp.sendmail(
                from_addr = cfg.get("MAIL_FROM_ADDRESS", username),
                to_addrs  = [recipient],
                msg       = msg.as_string(),
            )
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailError("SMTP authentication failed. Check credentials.") from exc
    except smtplib.SMTPException as exc:
        raise EmailError(f"SMTP error: {exc}") from exc
    except OSError as exc:
        raise EmailError(f"Cannot connect to {server}:{port} — {exc}") from exc


# ─────────────────────────────────────────────────────────────
#  Plain-text bodies
# ─────────────────────────────────────────────────────────────

def _plain_invoice(invoice, company_name):
    return (
        f"Dear {invoice.client.name},\n\n"
        f"Please find attached invoice {invoice.invoice_number} from {company_name}.\n\n"
        f"  Amount (excl. GST):  {invoice.amount_display}\n"
        f"  GST (18%):           {invoice.gst_display}\n"
        f"  Total Payable:       {invoice.total_display}\n"
        f"  Due Date:            {invoice.due_date.strftime('%d %B %Y')}\n\n"
        f"Please reference {invoice.invoice_number} when making payment.\n\n"
        f"Thank you,\n{company_name}"
    )


def _plain_reminder(invoice, company_name, days_overdue):
    ds = f"{days_overdue} day{'s' if days_overdue != 1 else ''}"
    return (
        f"Dear {invoice.client.name},\n\n"
        f"Invoice {invoice.invoice_number} from {company_name} is {ds} overdue.\n\n"
        f"  Invoice:    {invoice.invoice_number}\n"
        f"  Due Date:   {invoice.due_date.strftime('%d %B %Y')}\n"
        f"  Total Due:  {invoice.total_display}\n\n"
        f"Please arrange payment immediately. Quote {invoice.invoice_number} as reference.\n\n"
        f"Regards,\n{company_name}"
    )


# ─────────────────────────────────────────────────────────────
#  Public: send itemized bill email
# ─────────────────────────────────────────────────────────────

def send_bill_email(bill, app) -> None:
    """Send itemized bill PDF via email to the client."""
    cfg          = app.config
    company_name = cfg.get("COMPANY_NAME", cfg.get("APP_NAME", "InvoiceFlow"))

    _guard_enabled(cfg)
    recipient = bill.client.email or cfg.get("MAIL_FALLBACK_RECIPIENT")
    if not recipient:
        raise EmailError(
            f"No recipient for {bill.bill_number}: "
            "client has no email and MAIL_FALLBACK_RECIPIENT is not set."
        )

    # Build PDF bytes
    try:
        from utils.bill_pdf import build_bill_pdf_bytes
        pdf_bytes = build_bill_pdf_bytes(bill, app)
    except Exception as exc:
        logger.error("Bill PDF build failed: %s", exc)
        pdf_bytes = b""

    subject = f"Bill {bill.bill_number} from {company_name}"

    # Render bill email template
    try:
        html_body = _render_template(app, "emails/bill_email.html",
                                     bill=bill, company_name=company_name)
    except Exception:
        html_body = _plain_bill_body(bill, company_name)

    plain_body = _plain_bill_body(bill, company_name)

    msg = _assemble(
        subject      = subject,
        from_name    = cfg.get("MAIL_FROM_NAME",    company_name),
        from_address = cfg.get("MAIL_FROM_ADDRESS", cfg.get("MAIL_USERNAME", "")),
        recipient    = recipient,
        plain_body   = plain_body,
        html_body    = html_body,
        pdf_bytes    = pdf_bytes,
        pdf_filename = f"{bill.bill_number}.pdf",
    )
    _smtp_send(msg, recipient, cfg)
    logger.info("Bill email sent: %s -> %s", bill.bill_number, recipient)


def _plain_bill_body(bill, company_name):
    items_text = "\n".join(
        f"  {i}. {item.item_name} x{float(item.quantity):g} @ "
        f"\u20b9{float(item.rate):,.2f} = \u20b9{float(item.item_total):,.2f}"
        for i, item in enumerate(bill.items, 1)
    )
    return (
        f"Dear {bill.client.name},\n\n"
        f"Please find your bill {bill.bill_number} from {company_name}.\n\n"
        f"Items:\n{items_text}\n\n"
        f"  Subtotal:    {bill.subtotal_display}\n"
        f"  Total GST:   {bill.total_gst_display}\n"
        f"  Grand Total: {bill.grand_total_display}\n\n"
        f"Please reference {bill.bill_number} when making payment.\n\n"
        f"Thank you,\n{company_name}"
    )
