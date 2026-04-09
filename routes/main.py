"""
routes/main.py — Core routes: homepage, dashboard, health check.
"""

import json
from datetime import date, datetime, timezone
from dateutil.relativedelta import relativedelta

from flask import Blueprint, render_template, current_app
from flask_login import login_required, current_user

main_bp = Blueprint("main", __name__)


# ── Homepage ──────────────────────────────────────────────────

@main_bp.route("/")
def index():
    return render_template(
        "index.html",
        app_name=current_app.config.get("APP_NAME", "InvoiceFlow"),
    )


# ── Dashboard ─────────────────────────────────────────────────

@main_bp.route("/dashboard")
@login_required
def dashboard():
    from extensions import db
    from models import Client, Invoice, InvoiceStatus

    # 🔥 BASE FILTERS (MOST IMPORTANT)
    invoice_query = Invoice.query.join(Client).filter(
        Client.admin_id == current_user.id
    )

    client_query = Client.query.filter(
        Client.admin_id == current_user.id
    )

    today       = date.today()
    month_start = today.replace(day=1)

    # ── Revenue this month ────────────────────────────────────
    revenue_this_month = float(
        invoice_query.filter(
            Invoice.status == InvoiceStatus.PAID,
            Invoice.paid_at >= datetime(today.year, today.month, 1, tzinfo=timezone.utc)
        )
        .with_entities(db.func.coalesce(db.func.sum(Invoice.total), 0))
        .scalar()
    )

    # ── Previous month revenue ────────────────────────────────
    prev_month_start = month_start - relativedelta(months=1)
    prev_month_end   = month_start

    revenue_prev_month = float(
        invoice_query.filter(
            Invoice.status == InvoiceStatus.PAID,
            Invoice.paid_at >= datetime(prev_month_start.year, prev_month_start.month, 1, tzinfo=timezone.utc),
            Invoice.paid_at <  datetime(prev_month_end.year, prev_month_end.month, 1, tzinfo=timezone.utc),
        )
        .with_entities(db.func.coalesce(db.func.sum(Invoice.total), 0))
        .scalar()
    )

    revenue_change_pct = (
        round(((revenue_this_month - revenue_prev_month) / revenue_prev_month) * 100, 1)
        if revenue_prev_month > 0 else None
    )

    # ── Unpaid invoices ───────────────────────────────────────
    all_unpaid = invoice_query.filter(
        Invoice.status == InvoiceStatus.UNPAID
    ).all()

    unpaid_count  = len(all_unpaid)
    unpaid_total  = float(sum(inv.total for inv in all_unpaid))
    overdue_count = sum(1 for inv in all_unpaid if inv.is_overdue)

    unpaid_invoices = sorted(
        all_unpaid,
        key=lambda inv: (not inv.is_overdue, inv.due_date),
    )[:8]

    # ── Clients ───────────────────────────────────────────────
    # Sirf logged-in user ke clients ka count
    total_clients = client_query.filter(Client.admin_id == current_user.id).count()

    # Pichle 30 days mein add huye clients (filtered by admin_id)
    new_clients_30 = client_query.filter(
        Client.admin_id == current_user.id,
        Client.created_at >= datetime.now(timezone.utc) - relativedelta(days=30)
    ).count()

    
    # ── All-time revenue ─────────────────────────────────────
    total_revenue = float(
        invoice_query.filter(
            Invoice.status == InvoiceStatus.PAID
        )
        .with_entities(db.func.coalesce(db.func.sum(Invoice.total), 0))
        .scalar()
    )

    # ── Chart (last 12 months) ───────────────────────────────
    chart_labels  = []
    chart_revenue = []
    chart_issued  = []

    for i in range(11, -1, -1):
        mo_start = month_start - relativedelta(months=i)
        mo_end   = mo_start + relativedelta(months=1)

        chart_labels.append(mo_start.strftime("%b '%y"))

        paid = float(
            invoice_query.filter(
                Invoice.status == InvoiceStatus.PAID,
                Invoice.paid_at >= datetime(mo_start.year, mo_start.month, 1, tzinfo=timezone.utc),
                Invoice.paid_at <  datetime(mo_end.year, mo_end.month, 1, tzinfo=timezone.utc),
            )
            .with_entities(db.func.coalesce(db.func.sum(Invoice.total), 0))
            .scalar()
        )

        issued = float(
            invoice_query.filter(
                Invoice.created_at >= datetime(mo_start.year, mo_start.month, 1, tzinfo=timezone.utc),
                Invoice.created_at <  datetime(mo_end.year, mo_end.month, 1, tzinfo=timezone.utc),
            )
            .with_entities(db.func.coalesce(db.func.sum(Invoice.total), 0))
            .scalar()
        )

        chart_revenue.append(round(paid, 2))
        chart_issued.append(round(issued, 2))

    # ── Doughnut ─────────────────────────────────────────────
    paid_total = total_revenue

    unpaid_total_chart = float(
        invoice_query.filter(
            Invoice.status == InvoiceStatus.UNPAID
        )
        .with_entities(db.func.coalesce(db.func.sum(Invoice.total), 0))
        .scalar()
    )

    doughnut_data = [
        round(paid_total, 2),
        round(unpaid_total_chart, 2),
    ]

    # ── Top clients ──────────────────────────────────────────
    top_clients_raw = (
        db.session.query(
            Client,
            db.func.coalesce(db.func.sum(Invoice.total), 0),
            db.func.count(Invoice.id)
        )
        .join(Invoice)
        .filter(Client.admin_id == current_user.id)
        .group_by(Client.id)
        .order_by(db.desc(db.func.sum(Invoice.total)))
        .limit(5)
        .all()
    )

    top_clients = [
        {
            "client": c,
            "total_billed": float(total),
            "invoice_count": count,
        }
        for c, total, count in top_clients_raw
    ]

    # ── Recent invoices ──────────────────────────────────────
    recent_invoices = (
        invoice_query
        .order_by(Invoice.created_at.desc())
        .limit(5)
        .all()
    )

    # ── Collection rate ──────────────────────────────────────
    total_issued = float(
        invoice_query.with_entities(
            db.func.coalesce(db.func.sum(Invoice.total), 0)
        ).scalar()
    )

    collection_rate = (
        round((total_revenue / total_issued) * 100, 1)
        if total_issued > 0 else 0
    )

    # Progress bar helper
    amounts = [item["total_billed"] for item in top_clients]
    max_billed_val = max(amounts) if amounts and max(amounts) > 0 else 1

    return render_template(
        "dashboard.html",
        stats={
            "revenue_this_month": revenue_this_month,
            "revenue_change_pct": revenue_change_pct,
            "unpaid_count": unpaid_count,
            "unpaid_total": unpaid_total,
            "overdue_count": overdue_count,
            "max_billed": max_billed_val,
            "total_clients": total_clients,
            "new_clients_30": new_clients_30,
            "total_revenue": total_revenue,
            "collection_rate": collection_rate,
        },
        unpaid_invoices=unpaid_invoices,
        recent_invoices=recent_invoices,
        top_clients=top_clients,
        chart_labels=json.dumps(chart_labels),
        chart_revenue=json.dumps(chart_revenue),
        chart_issued=json.dumps(chart_issued),
        doughnut_data=json.dumps(doughnut_data),
        today=today,
        app_name=current_app.config.get("APP_NAME", "InvoiceFlow"),
    )

from flask import render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from extensions import db
from models import BusinessProfile

# ── Business Profile ──────────────────────────────────────────

@main_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    # Grab the google_id from the session as per your setup
    user_id = session.get("user_id")
    
    # Quick fallback just in case it's stored directly on current_user
    if not user_id and current_user.is_authenticated:
        user_id = current_user.google_id

    if not user_id:
        flash("Please log in to access your business profile.", "danger")
        return redirect(url_for('auth.login'))

    # Fetch existing profile
    profile_data = BusinessProfile.query.filter_by(user_id=user_id).first()

    if request.method == 'POST':
        business_name = request.form.get('business_name', '').strip()
        gst_number    = request.form.get('gst_number', '').strip()
        upi_id        = request.form.get('upi_id', '').strip()
        phone         = request.form.get('phone', '').strip()
        address       = request.form.get('address', '').strip()

        if not business_name:
            flash("Business Name is required.", "danger")
            return redirect(url_for('main.profile'))

        # UPSERT Logic
        if profile_data:
            # Update existing record
            profile_data.business_name = business_name
            profile_data.gst_number    = gst_number
            profile_data.upi_id        = upi_id
            profile_data.phone         = phone
            profile_data.address       = address
        else:
            # Create new record
            profile_data = BusinessProfile(
                user_id=user_id,
                business_name=business_name,
                gst_number=gst_number,
                upi_id=upi_id,
                phone=phone,
                address=address
            )
            db.session.add(profile_data)

        db.session.commit()
        flash("Business profile saved successfully.", "success")
        return redirect(url_for('main.profile'))

    return render_template('profile.html', 
                           profile=profile_data, 
                           app_name="InvoiceFlow")


# ── Health ────────────────────────────────────────────────────

@main_bp.route("/health")
def health():
    from extensions import db
    try:
        db.session.execute(db.text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:
        db_status = f"error: {exc}"

    return {
        "status": "ok",
        "database": db_status,
        "app": current_app.config.get("APP_NAME"),
    }