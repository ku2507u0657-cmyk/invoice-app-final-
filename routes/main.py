"""
routes/main.py — Core routes: homepage, dashboard, health check.
"""

import json
from calendar import month_abbr
from datetime import date, datetime, timezone
from dateutil.relativedelta import relativedelta

from flask import Blueprint, render_template, current_app
from flask_login import login_required

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

    today      = date.today()
    month_start = today.replace(day=1)

    # ── KPI 1: Revenue this month (paid invoices) ─────────────
    revenue_this_month = float(
        db.session.query(
            db.func.coalesce(db.func.sum(Invoice.total), 0)
        )
        .filter(
            Invoice.status    == InvoiceStatus.PAID,
            Invoice.paid_at   >= datetime(today.year, today.month, 1,
                                          tzinfo=timezone.utc),
        )
        .scalar()
    )

    # Previous month revenue (for % change badge)
    prev_month_start = month_start - relativedelta(months=1)
    prev_month_end   = month_start
    revenue_prev_month = float(
        db.session.query(
            db.func.coalesce(db.func.sum(Invoice.total), 0)
        )
        .filter(
            Invoice.status  == InvoiceStatus.PAID,
            Invoice.paid_at >= datetime(prev_month_start.year,
                                        prev_month_start.month, 1,
                                        tzinfo=timezone.utc),
            Invoice.paid_at <  datetime(prev_month_end.year,
                                        prev_month_end.month, 1,
                                        tzinfo=timezone.utc),
        )
        .scalar()
    )

    if revenue_prev_month > 0:
        revenue_change_pct = round(
            ((revenue_this_month - revenue_prev_month) / revenue_prev_month) * 100, 1
        )
    else:
        revenue_change_pct = None   # can't compute % from zero

    # ── KPI 2: Unpaid invoices ─────────────────────────────────
    all_unpaid   = Invoice.query.filter_by(status=InvoiceStatus.UNPAID).all()
    unpaid_count = len(all_unpaid)
    unpaid_total = float(sum(inv.total for inv in all_unpaid))
    overdue_count = sum(1 for inv in all_unpaid if inv.is_overdue)

    # Unpaid sorted: overdue first, then by due date ascending
    unpaid_invoices = sorted(
        all_unpaid,
        key=lambda inv: (not inv.is_overdue, inv.due_date),
    )[:8]  # cap at 8 rows in the panel

    # ── KPI 3: Total clients ───────────────────────────────────
    total_clients  = Client.query.count()
    new_clients_30 = Client.query.filter(
        Client.created_at >= datetime.now(timezone.utc) - relativedelta(days=30)
    ).count()

    # ── KPI 4: All-time revenue (paid) ────────────────────────
    total_revenue = float(
        db.session.query(
            db.func.coalesce(db.func.sum(Invoice.total), 0)
        )
        .filter(Invoice.status == InvoiceStatus.PAID)
        .scalar()
    )

    # ── Chart data: last 12 months of revenue ─────────────────
    chart_labels  = []
    chart_revenue = []   # paid totals
    chart_issued  = []   # total invoices issued (billed)

    for i in range(11, -1, -1):
        mo_start = (month_start - relativedelta(months=i))
        mo_end   = mo_start + relativedelta(months=1)

        label = mo_start.strftime("%b '%y")
        chart_labels.append(label)

        paid = float(
            db.session.query(
                db.func.coalesce(db.func.sum(Invoice.total), 0)
            )
            .filter(
                Invoice.status  == InvoiceStatus.PAID,
                Invoice.paid_at >= datetime(mo_start.year, mo_start.month, 1,
                                            tzinfo=timezone.utc),
                Invoice.paid_at <  datetime(mo_end.year,   mo_end.month,   1,
                                            tzinfo=timezone.utc),
            )
            .scalar()
        )

        issued = float(
            db.session.query(
                db.func.coalesce(db.func.sum(Invoice.total), 0)
            )
            .filter(
                Invoice.created_at >= datetime(mo_start.year, mo_start.month, 1,
                                               tzinfo=timezone.utc),
                Invoice.created_at <  datetime(mo_end.year,   mo_end.month,   1,
                                               tzinfo=timezone.utc),
            )
            .scalar()
        )

        chart_revenue.append(round(paid,   2))
        chart_issued.append(round(issued,  2))

    # ── Doughnut: revenue vs outstanding ──────────────────────
    doughnut_data = [
        round(total_revenue, 2),
        round(unpaid_total,  2),
    ]

    # ── Top 5 clients by total billed ─────────────────────────
    top_clients_raw = (
        db.session.query(
            Client,
            db.func.coalesce(db.func.sum(Invoice.total), 0).label("total_billed"),
            db.func.count(Invoice.id).label("invoice_count"),
        )
        .outerjoin(Invoice, Invoice.client_id == Client.id)
        .group_by(Client.id)
        .order_by(db.text("total_billed DESC"))
        .limit(5)
        .all()
    )

    top_clients = [
        {
            "client":        c,
            "total_billed":  float(total),
            "invoice_count": count,
        }
        for c, total, count in top_clients_raw
    ]

    # ── 5 most recent invoices (all statuses) ─────────────────
    recent_invoices = (
        Invoice.query
        .order_by(Invoice.created_at.desc())
        .limit(5)
        .all()
    )

    # ── Collection rate ───────────────────────────────────────
    total_issued = float(
        db.session.query(
            db.func.coalesce(db.func.sum(Invoice.total), 0)
        ).scalar()
    )
    collection_rate = (
        round((total_revenue / total_issued) * 100, 1)
        if total_issued > 0 else 0
    )

    return render_template(
        "dashboard.html",
        # KPI cards
        stats={
            "revenue_this_month":  revenue_this_month,
            "revenue_change_pct":  revenue_change_pct,
            "unpaid_count":        unpaid_count,
            "unpaid_total":        unpaid_total,
            "overdue_count":       overdue_count,
            "total_clients":       total_clients,
            "new_clients_30":      new_clients_30,
            "total_revenue":       total_revenue,
            "collection_rate":     collection_rate,
        },
        # Table panels
        unpaid_invoices = unpaid_invoices,
        recent_invoices = recent_invoices,
        top_clients     = top_clients,
        # Chart.js data (serialised to JSON for the template)
        chart_labels    = json.dumps(chart_labels),
        chart_revenue   = json.dumps(chart_revenue),
        chart_issued    = json.dumps(chart_issued),
        doughnut_data   = json.dumps(doughnut_data),
        today           = today,
        app_name        = current_app.config.get("APP_NAME", "InvoiceFlow"),
    )


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
        "status":   "ok",
        "database": db_status,
        "app":      current_app.config.get("APP_NAME"),
    }
