"""
utils/helpers.py — Shared helper functions for InvoiceFlow.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def format_currency(amount: float, symbol: str = "$") -> str:
    """Format a float as a currency string, e.g. 1234.5 → '$1,234.50'."""
    return f"{symbol}{amount:,.2f}"


def slugify(text: str) -> str:
    """Convert a string to a URL-safe slug."""
    import re
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text


def paginate_query(query, page: int, per_page: int = 20):
    """Return a Flask-SQLAlchemy pagination object."""
    return query.paginate(page=page, per_page=per_page, error_out=False)
