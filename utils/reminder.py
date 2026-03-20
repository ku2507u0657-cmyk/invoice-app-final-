"""
utils/reminder.py — Daily overdue-invoice reminder job + monthly recurring generator.
Both functions run inside APScheduler background threads with their own app context.
"""

import logging
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  Overdue reminder job (runs daily)
# ─────────────────────────────────────────────────────────────

def run_overdue_reminder_job(app):
    """APScheduler entry point for daily overdue reminders."""
    with app.app_context():
        _send_overdue_reminders(app)


def _send_overdue_reminders(app):
    from extensions import db
    from models import Invoice, InvoiceStatus
    from utils.email import send_reminder_email, EmailError

    today      = date.today()
    grace_days = app.config.get("REMINDER_GRACE_DAYS", 0)

    logger.info("[Reminder] Starting overdue check at %s (grace=%d days)",
                datetime.now(timezone.utc).isoformat(), grace_days)

    overdue = (Invoice.query
               .filter(Invoice.status   == InvoiceStatus.UNPAID,
                       Invoice.due_date <  today)
               .order_by(Invoice.due_date.asc())
               .all())

    if not overdue:
        logger.info("[Reminder] No overdue invoices. Done.")
        return

    sent = skipped = failed = 0

    for inv in overdue:
        days_overdue = (today - inv.due_date).days

        if days_overdue < grace_days:
            skipped += 1
            continue

        recipient = (inv.client.email
                     or app.config.get("MAIL_FALLBACK_RECIPIENT"))
        if not recipient:
            logger.warning("[Reminder] Skip %s — no email for client '%s'",
                           inv.invoice_number, inv.client.name)
            skipped += 1
            continue

        try:
            send_reminder_email(inv, app, days_overdue=days_overdue)
            logger.info("[Reminder] Sent for %s -> %s (%d days overdue)",
                        inv.invoice_number, recipient, days_overdue)
            sent += 1
        except Exception as exc:
            logger.error("[Reminder] Failed for %s: %s", inv.invoice_number, exc)
            failed += 1

    logger.info("[Reminder] Done. sent=%d  skipped=%d  failed=%d",
                sent, skipped, failed)


# ─────────────────────────────────────────────────────────────
#  Recurring invoice generator (runs on 1st of each month)
# ─────────────────────────────────────────────────────────────

def run_recurring_invoice_job(app):
    """APScheduler entry point for monthly auto-invoice generation."""
    with app.app_context():
        _generate_recurring_invoices(app)


def _generate_recurring_invoices(app):
    """
    For every active client with a monthly_fee set, auto-generate
    an unpaid invoice for the current month if one hasn't been created yet.
    """
    from extensions import db
    from models import Client, Invoice, InvoiceStatus
    from utils.pdf import build_and_save_invoice_pdf
    from utils.email import send_invoice_email, EmailError
    from datetime import timedelta

    today = date.today()
    # Due date = last day of current month
    if today.month == 12:
        due_date = date(today.year + 1, 1, 1) - timedelta(days=1)
    else:
        due_date = date(today.year, today.month + 1, 1) - timedelta(days=1)

    logger.info("[Recurring] Generating invoices for %s-%02d",
                today.year, today.month)

    clients = Client.query.filter_by(is_active=True).all()
    created = skipped = 0

    for client in clients:
        if not client.monthly_fee or float(client.monthly_fee) <= 0:
            continue

        # Check if invoice already exists for this client this month
        existing = (Invoice.query
                    .filter(Invoice.client_id   == client.id,
                            Invoice.is_recurring == True,
                            db.extract("year",  Invoice.created_at) == today.year,
                            db.extract("month", Invoice.created_at) == today.month)
                    .first())

        if existing:
            logger.debug("[Recurring] Skip %s — already invoiced this month",
                         client.name)
            skipped += 1
            continue

        gst_amt, total = Invoice.calculate_gst(float(client.monthly_fee))

        inv = Invoice(
            invoice_number = Invoice.next_invoice_number(),
            client_id      = client.id,
            amount         = client.monthly_fee,
            gst            = gst_amt,
            total          = total,
            due_date       = due_date,
            status         = InvoiceStatus.UNPAID,
            is_recurring   = True,
            notes          = f"Monthly fee — {today.strftime('%B %Y')}",
        )
        db.session.add(inv)
        db.session.flush()   # get inv.id before PDF

        # Generate and save PDF
        try:
            _, rel_path = build_and_save_invoice_pdf(inv, app)
            inv.pdf_path = rel_path
        except Exception as exc:
            logger.error("[Recurring] PDF failed for %s: %s",
                         inv.invoice_number, exc)

        db.session.commit()

        # Send email
        try:
            send_invoice_email(inv, app)
        except Exception as exc:
            logger.warning("[Recurring] Email failed for %s: %s",
                           inv.invoice_number, exc)

        logger.info("[Recurring] Created %s for %s",
                    inv.invoice_number, client.name)
        created += 1

    logger.info("[Recurring] Done. created=%d  skipped=%d", created, skipped)
