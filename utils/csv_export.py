"""
utils/csv_export.py — CSV export for invoices.

Usage
-----
    from utils.csv_export import invoices_to_csv_response
    return invoices_to_csv_response(invoices)   # returns a Flask Response
"""

import csv
import io
from flask import Response


def invoices_to_csv_response(invoices, filename="invoices_export.csv"):
    """
    Convert a list of Invoice ORM objects to a downloadable CSV response.

    Parameters
    ----------
    invoices : list[Invoice]
    filename : str

    Returns
    -------
    Flask Response with CSV attachment
    """
    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header row
    writer.writerow([
        "Invoice Number", "Client Name", "Client Email", "Client Phone",
        "Amount (excl GST)", "GST (18%)", "Total",
        "Due Date", "Status", "Recurring", "Created At", "Paid At",
    ])

    # Data rows
    for inv in invoices:
        writer.writerow([
            inv.invoice_number,
            inv.client.name if inv.client else "",
            inv.client.email if inv.client else "",
            inv.client.phone if inv.client else "",
            f"{float(inv.amount):.2f}",
            f"{float(inv.gst):.2f}",
            f"{float(inv.total):.2f}",
            inv.due_date.strftime("%d-%m-%Y"),
            inv.effective_status,
            "Yes" if inv.is_recurring else "No",
            inv.created_at.strftime("%d-%m-%Y %H:%M"),
            inv.paid_at.strftime("%d-%m-%Y %H:%M") if inv.paid_at else "",
        ])

    output = buf.getvalue()
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
