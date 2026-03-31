"""
routes/invoices.py — Invoice management: list, create, view, mark-paid,
                     download PDF, CSV export.
All routes require @login_required.
"""

import logging
import os
from datetime import date, timedelta

from flask import (
    Blueprint, render_template, redirect, url_for,
    request, flash, current_app, jsonify, send_file, abort, session
)
from flask_login import login_required, current_user
from extensions import db
from models import Invoice, InvoiceStatus, Client, BusinessProfile

logger = logging.getLogger(__name__)
invoices_bp = Blueprint("invoices", __name__, url_prefix="/invoices")


# ── List ──────────────────────────────────────────────────────

@invoices_bp.route("/")
@login_required
def list_invoices():
    status_filter = request.args.get("status", "").strip()
    search        = request.args.get("q",      "").strip()
    page          = request.args.get("page", 1, type=int)

    query = Invoice.query.join(Client).filter(  
        Client.admin_id == current_user.id
    ).order_by(Invoice.created_at.desc())

    if status_filter and status_filter in InvoiceStatus.ALL:
        query = query.filter(Invoice.status == status_filter)

    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(Invoice.invoice_number.ilike(like),
                   Client.name.ilike(like))
        )

    pagination = query.paginate(page=page, per_page=15, error_out=False)

    base_query = Invoice.query.join(Client).filter(
        Client.admin_id == current_user.id
    )

    counts = {
        "all": base_query.count(),
        "unpaid": base_query.filter(Invoice.status == InvoiceStatus.UNPAID).count(),
        "paid": base_query.filter(Invoice.status == InvoiceStatus.PAID).count(),
        "overdue": sum(
            1 for inv in base_query.filter(Invoice.status == InvoiceStatus.UNPAID).all()
            if inv.is_overdue
        ),
    }
    
    return render_template(
        "invoices/list.html",
        invoices      = pagination.items,
        pagination    = pagination,
        status_filter = status_filter,
        search        = search,
        counts        = counts,
        app_name      = current_app.config.get("APP_NAME", "InvoiceFlow"),
    )


# ── View (detail page) ────────────────────────────────────────

@invoices_bp.route("/<int:invoice_id>")
@login_required
def view_invoice(invoice_id):
    invoice = Invoice.query.join(Client).filter(
        Invoice.id == invoice_id,
        Client.admin_id == current_user.id
    ).first_or_404()

    # Generate UPI QR as base64 for embedding in HTML
    qr_b64 = ""
    try:
        import base64
        from utils.qr import build_upi_qr_for_invoice
        qr_bytes = build_upi_qr_for_invoice(invoice, current_app._get_current_object())
        if qr_bytes:
            qr_b64 = base64.b64encode(qr_bytes).decode()
    except Exception:
        pass

    user_id = session.get("user_id")
    if not user_id and current_user.is_authenticated:
        user_id = current_user.google_id
        
    business_profile = BusinessProfile.query.filter_by(user_id=user_id).first()
    
    if not business_profile or not business_profile.business_name:
        flash("Please complete your Business Profile before creating an invoice.", "warning")
        return redirect(url_for('main.profile'))
    
    return render_template(
        "invoices/view.html",   # or whatever your template is
        invoice=invoice,
        qr_b64=qr_b64,
        business_profile=business_profile
    )
    # ───────────────────────────────────────────────────────────


# ── Create ────────────────────────────────────────────────────

@invoices_bp.route("/create", methods=["GET", "POST"])
@login_required
def create_invoice():
    # ── NEW: Profile Enforcement ───────────────────────────────
    user_id = session.get("user_id")
    if not user_id and current_user.is_authenticated:
        user_id = current_user.google_id
        
    business_profile = BusinessProfile.query.filter_by(user_id=user_id).first()
    
    if not business_profile or not business_profile.business_name:
        flash("Please complete your Business Profile before creating an invoice.", "warning")
        return redirect(url_for('main.profile'))
    # ───────────────────────────────────────────────────────────
    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()

    if request.method == "POST":
        client_id  = request.form.get("client_id", "").strip()
        amount_raw = request.form.get("amount",    "").strip()
        due_date_s = request.form.get("due_date",  "").strip()
        notes      = request.form.get("notes",     "").strip()
        
        # New GST fields
        gst_rate_raw = request.form.get("gst_rate", "18.0").strip()
        custom_gst_rate_raw = request.form.get("custom_gst_rate", "").strip()

        errors = []
        client = None

        if not client_id:
            errors.append("Please select a client.")
        else:
            client = db.session.get(Client, int(client_id))
            if client is None:
                errors.append("Selected client does not exist.")

        if not amount_raw:
            errors.append("Amount is required.")
        else:
            try:
                amount = float(amount_raw)
                if amount <= 0:
                    errors.append("Amount must be greater than zero.")
            except ValueError:
                errors.append("Amount must be a valid number.")

        if not due_date_s:
            errors.append("Due date is required.")
        else:
            try:
                due_date = date.fromisoformat(due_date_s)
            except ValueError:
                errors.append("Due date format is invalid.")
                
        # Validate GST Rate
        final_gst_rate = 18.0
        if gst_rate_raw.lower() == "custom":
            if not custom_gst_rate_raw:
                errors.append("Custom GST rate is required when 'Custom' is selected.")
            else:
                try:
                    final_gst_rate = float(custom_gst_rate_raw)
                    if final_gst_rate < 0:
                        errors.append("GST rate cannot be negative.")
                except ValueError:
                    errors.append("Custom GST rate must be a valid number.")
        else:
            try:
                final_gst_rate = float(gst_rate_raw)
                if final_gst_rate < 0:
                    errors.append("GST rate cannot be negative.")
            except ValueError:
                errors.append("Selected GST rate is invalid.")

        if errors:
            for err in errors:
                flash(err, "danger")
            return render_template(
                "invoices/create.html",
                clients  = clients,
                form     = request.form,
                today    = date.today(),
                app_name = current_app.config.get("APP_NAME"),
            )

        # ── GST calculation & persist ──────────────────────────
        gst_amount, total = Invoice.calculate_gst(amount, rate=final_gst_rate)

        invoice = Invoice(
            invoice_number = Invoice.next_invoice_number(),
            client_id      = int(client_id),
            amount         = amount,
            gst_rate       = final_gst_rate,
            gst            = gst_amount,
            total          = total,
            due_date       = due_date,
            status         = InvoiceStatus.UNPAID,
            notes          = notes or None,
        )
        db.session.add(invoice)
        db.session.flush()   # get invoice.id

        # ── Generate and save PDF ──────────────────────────────
        app = current_app._get_current_object()
        try:
            from utils.pdf import build_and_save_invoice_pdf
            _, rel_path = build_and_save_invoice_pdf(invoice, app)
            invoice.pdf_path = rel_path
        except Exception as exc:
            logger.error("PDF generation failed for %s: %s",
                         invoice.invoice_number, exc)

        db.session.commit()
        flash(f"Invoice {invoice.invoice_number} created for {invoice.client.name}.",
              "success")

        # ── Send email (non-blocking) ──────────────────────────
        _dispatch_email(invoice, app)

        return redirect(url_for("invoices.view_invoice", invoice_id=invoice.id))

    default_due = (date.today() + timedelta(days=30)).isoformat()
    return render_template(
        "invoices/create.html",
        clients     = clients,
        form        = {},
        default_due = default_due,
        today       = date.today(),
        app_name    = current_app.config.get("APP_NAME", "InvoiceFlow"),
    )


# ── Mark as paid ──────────────────────────────────────────────

@invoices_bp.route("/<int:invoice_id>/mark-paid", methods=["POST"])
@login_required
def mark_paid(invoice_id):
    invoice = Invoice.query.join(Client).filter(
        Invoice.id == invoice_id,
        Client.admin_id == current_user.id
    ).first_or_404()

    if invoice.status == InvoiceStatus.PAID:
        flash(f"{invoice.invoice_number} is already paid.", "warning")
    else:
        invoice.mark_paid()
        db.session.commit()
        flash(f"{invoice.invoice_number} marked as paid.", "success")

    next_page = request.args.get("next") or url_for("invoices.list_invoices")
    return redirect(next_page)


# ── Download PDF ──────────────────────────────────────────────

@invoices_bp.route("/<int:invoice_id>/download")
@login_required
def download_pdf(invoice_id):
    invoice = Invoice.query.join(Client).filter(
        Invoice.id == invoice_id,
        Client.admin_id == current_user.id
    ).first_or_404()

    # Regenerate if file missing
    if not invoice.pdf_path or not os.path.exists(invoice.pdf_path):
        try:
            from utils.pdf import build_and_save_invoice_pdf
            app = current_app._get_current_object()
            _, rel_path = build_and_save_invoice_pdf(invoice, app)
            invoice.pdf_path = rel_path
            db.session.commit()
        except Exception as exc:
            flash(f"Could not generate PDF: {exc}", "danger")
            return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))

    return send_file(
        invoice.pdf_path,
        mimetype      = "application/pdf",
        as_attachment = True,
        download_name = f"{invoice.invoice_number}.pdf",
    )


# ── CSV Export ────────────────────────────────────────────────

@invoices_bp.route("/export/csv")
@login_required
def export_csv():
    """Export all invoices (or filtered by status) as CSV."""
    from utils.csv_export import invoices_to_csv_response

    status = request.args.get("status", "").strip()
    query  = Invoice.query.join(Client).order_by(Invoice.created_at.desc())

    if status and status in InvoiceStatus.ALL:
        query = query.filter(Invoice.status == status)

    invoices  = query.all()
    filename  = f"invoices{'_' + status if status else ''}.csv"
    return invoices_to_csv_response(invoices, filename=filename)


# ── GST preview (AJAX) ────────────────────────────────────────

@invoices_bp.route("/gst-preview")
@login_required
def gst_preview():
    try:
        amount = float(request.args.get("amount", 0))
        rate = float(request.args.get("rate", 18.0))
        if amount < 0 or rate < 0:
            raise ValueError
    except ValueError:
        return jsonify({"error": "invalid amount or rate"}), 400

    gst, total = Invoice.calculate_gst(amount, rate=rate)
    return jsonify({
        "gst":   f"{float(gst):,.2f}",
        "total": f"{float(total):,.2f}",
    })


# ── Resend email ──────────────────────────────────────────────

@invoices_bp.route("/<int:invoice_id>/resend-email", methods=["POST"])
@login_required
def resend_email(invoice_id):
    invoice = Invoice.query.join(Client).filter(
        Invoice.id == invoice_id,
        Client.admin_id == current_user.id
    ).first_or_404()
    _dispatch_email(invoice, current_app._get_current_object(), force=True)
    return redirect(url_for("invoices.view_invoice", invoice_id=invoice_id))


# ── Internal helpers ──────────────────────────────────────────

def _dispatch_email(invoice, app, force=False):
    """Send invoice email; catch all errors so invoice is never lost."""
    try:
        from utils.email import send_invoice_email, EmailError
        send_invoice_email(invoice, app)

        if app.config.get("MAIL_ENABLED", False):
            recipient = (invoice.client.email
                         or app.config.get("MAIL_FALLBACK_RECIPIENT", ""))
            flash(f"Invoice email sent to {recipient}.", "info")

    except Exception as exc:
        logger.exception("Email failed for %s: %s", invoice.invoice_number, exc)
        flash(f"Invoice saved but email failed: {exc}", "warning")