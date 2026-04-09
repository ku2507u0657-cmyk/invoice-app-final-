"""
routes/bills.py — Itemized bill management.
Create bills with multiple line items, per-item GST, PDF generation, email.
"""

import logging
import os
from datetime import date, timedelta

from flask import (
    Blueprint, render_template, redirect, url_for,
    request, flash, current_app, jsonify, send_file,
)
from flask_login import login_required
from extensions import db
from models import Bill, BillItem, BillStatus, Client

logger = logging.getLogger(__name__)
bills_bp = Blueprint("bills", __name__, url_prefix="/bills")


# ── List all bills ────────────────────────────────────────────

@bills_bp.route("/")
@login_required
def list_bills():
    status = request.args.get("status", "").strip()
    q      = request.args.get("q",      "").strip()
    page   = request.args.get("page", 1, type=int)

    query = Bill.query.join(Client).order_by(Bill.created_at.desc())

    if status and status in BillStatus.ALL:
        query = query.filter(Bill.status == status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(Bill.bill_number.ilike(like), Client.name.ilike(like))
        )

    pagination = query.paginate(page=page, per_page=15, error_out=False)
    counts = {
        "all":    Bill.query.count(),
        "unpaid": Bill.query.filter_by(status=BillStatus.UNPAID).count(),
        "paid":   Bill.query.filter_by(status=BillStatus.PAID).count(),
    }

    return render_template("bills/list.html",
        bills         = pagination.items,
        pagination    = pagination,
        status_filter = status,
        search        = q,
        counts        = counts,
        app_name      = current_app.config.get("APP_NAME", "InvoiceFlow"),
    )


# ── Bills for a specific client ───────────────────────────────

@bills_bp.route("/client/<int:client_id>")
@login_required
def client_bills(client_id):
    client = db.get_or_404(Client, client_id)
    bills  = (Bill.query
              .filter_by(client_id=client_id)
              .order_by(Bill.created_at.desc())
              .all())
    return render_template("bills/client_bills.html",
        client   = client,
        bills    = bills,
        app_name = current_app.config.get("APP_NAME", "InvoiceFlow"),
    )


# ── Create bill ───────────────────────────────────────────────

@bills_bp.route("/create", methods=["GET", "POST"])
@bills_bp.route("/create/<int:client_id>", methods=["GET", "POST"])
@login_required
def create_bill(client_id=None):
    clients     = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()
    default_due = (date.today() + timedelta(days=30)).isoformat()

    # Pre-select client if coming from client page
    preselected = client_id

    if request.method == "POST":
        cid       = request.form.get("client_id", "").strip()
        notes     = request.form.get("notes",     "").strip()
        due_raw   = request.form.get("due_date",  "").strip()

        # ── Parse line items from form ─────────────────────────
        # Items come as: item_name[], description[], quantity[], rate[], gst_rate[]
        item_names   = request.form.getlist("item_name[]")
        descriptions = request.form.getlist("description[]")
        quantities   = request.form.getlist("quantity[]")
        rates        = request.form.getlist("rate[]")
        gst_rates    = request.form.getlist("item_gst_rate[]")

        # ── Validate ───────────────────────────────────────────
        errors = []

        if not cid:
            errors.append("Please select a client.")
        else:
            client = db.session.get(Client, int(cid))
            if not client:
                errors.append("Client not found.")

        # At least one item required
        valid_items = []
        for i, name in enumerate(item_names):
            name = name.strip()
            if not name:
                continue
            try:
                qty  = float(quantities[i]) if i < len(quantities) else 1
                rate = float(rates[i])      if i < len(rates)      else 0
                gst  = float(gst_rates[i])  if i < len(gst_rates)  else 0
                if qty <= 0:
                    errors.append(f"Row {i+1}: Quantity must be greater than 0.")
                    continue
                if rate < 0:
                    errors.append(f"Row {i+1}: Rate cannot be negative.")
                    continue
                valid_items.append({
                    "name": name,
                    "desc": (descriptions[i].strip() if i < len(descriptions) else ""),
                    "qty":  qty,
                    "rate": rate,
                    "gst":  gst,
                })
            except (ValueError, IndexError):
                errors.append(f"Row {i+1}: Invalid number entered.")

        if not valid_items:
            errors.append("Add at least one item to the bill.")

        due_date = None
        if due_raw:
            try:
                due_date = date.fromisoformat(due_raw)
            except ValueError:
                errors.append("Invalid due date.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("bills/create.html",
                clients      = clients,
                default_due  = default_due,
                preselected  = int(cid) if cid else preselected,
                form         = request.form,
                app_name     = current_app.config.get("APP_NAME"),
            )

        # ── Create Bill and BillItems ──────────────────────────
        bill = Bill(
            bill_number = Bill.next_bill_number(),
            client_id   = int(cid),
            notes       = notes or None,
            status      = BillStatus.UNPAID,
            due_date    = due_date,
        )
        db.session.add(bill)
        db.session.flush()   # get bill.id

        for item_data in valid_items:
            item = BillItem(
                bill_id     = bill.id,
                item_name   = item_data["name"],
                description = item_data["desc"] or None,
                quantity    = item_data["qty"],
                rate        = item_data["rate"],
                gst_rate    = item_data["gst"],
            )
            item.calculate()
            db.session.add(item)

        db.session.flush()

        # Recalculate bill totals from items
        bill.recalculate_totals()

        # Generate PDF
        app = current_app._get_current_object()
        try:
            from utils.bill_pdf import build_and_save_bill_pdf
            _, rel_path = build_and_save_bill_pdf(bill, app)
            bill.pdf_path = rel_path
        except Exception as exc:
            logger.error("Bill PDF failed: %s", exc)

        db.session.commit()
        flash(f"Bill {bill.bill_number} created for {bill.client.name}.", "success")

        # Send email
        _dispatch_bill_email(bill, app)

        return redirect(url_for("bills.view_bill", bill_id=bill.id))

    return render_template("bills/create.html",
        clients     = clients,
        default_due = default_due,
        preselected = preselected,
        form        = {},
        app_name    = current_app.config.get("APP_NAME", "InvoiceFlow"),
    )


# ── View bill ─────────────────────────────────────────────────

@bills_bp.route("/<int:bill_id>")
@login_required
def view_bill(bill_id):
    bill = db.get_or_404(Bill, bill_id)

    qr_b64 = ""
    try:
        import base64
        from utils.qr import build_upi_qr_bytes
        upi_id    = current_app.config.get("UPI_ID", "")
        upi_payee = current_app.config.get("UPI_PAYEE_NAME", "")
        if upi_id:
            qr_bytes = build_upi_qr_bytes(upi_id, upi_payee,
                                           float(bill.grand_total), bill.bill_number)
            if qr_bytes:
                qr_b64 = base64.b64encode(qr_bytes).decode()
    except Exception:
        pass

    return render_template("bills/view.html",
        bill         = bill,
        qr_b64       = qr_b64,
        upi_id       = current_app.config.get("UPI_ID", ""),
        company_name = current_app.config.get("COMPANY_NAME", ""),
        app_name     = current_app.config.get("APP_NAME", "InvoiceFlow"),
    )


# ── Mark paid ─────────────────────────────────────────────────

@bills_bp.route("/<int:bill_id>/mark-paid", methods=["POST"])
@login_required
def mark_paid(bill_id):
    bill = db.get_or_404(Bill, bill_id)
    if bill.status == BillStatus.PAID:
        flash(f"{bill.bill_number} is already paid.", "warning")
    else:
        bill.mark_paid()
        db.session.commit()
        flash(f"{bill.bill_number} marked as paid.", "success")
    next_page = request.args.get("next") or url_for("bills.list_bills")
    return redirect(next_page)


# ── Download PDF ──────────────────────────────────────────────

@bills_bp.route("/<int:bill_id>/download")
@login_required
def download_pdf(bill_id):
    bill = db.get_or_404(Bill, bill_id)
    app  = current_app._get_current_object()

    if not bill.pdf_path or not os.path.exists(bill.pdf_path):
        try:
            from utils.bill_pdf import build_and_save_bill_pdf
            _, rel_path = build_and_save_bill_pdf(bill, app)
            bill.pdf_path = rel_path
            db.session.commit()
        except Exception as exc:
            flash(f"Could not generate PDF: {exc}", "danger")
            return redirect(url_for("bills.view_bill", bill_id=bill_id))

    return send_file(
        bill.pdf_path,
        mimetype      = "application/pdf",
        as_attachment = True,
        download_name = f"{bill.bill_number}.pdf",
    )


# ── Resend email ──────────────────────────────────────────────

@bills_bp.route("/<int:bill_id>/resend-email", methods=["POST"])
@login_required
def resend_email(bill_id):
    bill = db.get_or_404(Bill, bill_id)
    _dispatch_bill_email(bill, current_app._get_current_object(), force=True)
    return redirect(url_for("bills.view_bill", bill_id=bill_id))


# ── AJAX: calculate row total ─────────────────────────────────

@bills_bp.route("/calc-row")
@login_required
def calc_row():
    """Return {total, gst_amount, item_total} for a single line item."""
    try:
        qty  = float(request.args.get("qty",  1))
        rate = float(request.args.get("rate", 0))
        gst  = float(request.args.get("gst",  0))
    except ValueError:
        return jsonify({"error": "invalid"}), 400

    from decimal import Decimal, ROUND_HALF_UP
    q   = Decimal(str(qty))
    r   = Decimal(str(rate))
    g   = Decimal(str(gst)) / 100
    tot = (q * r).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    gst_amt = (tot * g).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return jsonify({
        "total":      f"{float(tot):.2f}",
        "gst_amount": f"{float(gst_amt):.2f}",
        "item_total": f"{float(tot + gst_amt):.2f}",
    })


# ── Internal helpers ──────────────────────────────────────────

def _dispatch_bill_email(bill, app, force=False):
    try:
        from utils.email import send_bill_email, EmailError
        send_bill_email(bill, app)
        if app.config.get("MAIL_ENABLED", False):
            recipient = bill.client.email or app.config.get("MAIL_FALLBACK_RECIPIENT", "")
            if recipient:
                flash(f"Bill emailed to {recipient}.", "info")
    except Exception as exc:
        logger.exception("Bill email failed for %s: %s", bill.bill_number, exc)
        flash(f"Bill saved but email failed: {exc}", "warning")
