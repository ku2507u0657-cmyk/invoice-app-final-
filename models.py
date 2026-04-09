"""
models.py — SQLAlchemy models for InvoiceFlow
Supports SQLite (dev) and PostgreSQL (production).
"""

from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


DEFAULT_GST_RATE = Decimal("18.0")   # Default 18% GST


class TimestampMixin:
    """Adds created_at / updated_at to any model."""
    created_at = db.Column(db.DateTime, nullable=False,
                           default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, nullable=False,
                           default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))


# ─────────────────────────────────────────────────────────────
#  Admin
# ─────────────────────────────────────────────────────────────

class Admin(UserMixin, TimestampMixin, db.Model):
    """
    Admin login account.
    Supports two login methods — they can coexist on the same account:
      1. Username + password  (traditional)
      2. Google OAuth         (google_id + email)
    """
    clients = db.relationship("Client", backref="admin", lazy=True)

    __tablename__ = "admins"

    id            = db.Column(db.Integer,     primary_key=True)
    username      = db.Column(db.String(80),  unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=True)   # nullable — Google-only admins have no password

    # ── Google OAuth fields ────────────────────────────────────
    google_id     = db.Column(db.String(128), unique=True, nullable=True, index=True)
    email         = db.Column(db.String(255), unique=True, nullable=True, index=True)
    display_name  = db.Column(db.String(200), nullable=True)   # full name from Google
    avatar_url    = db.Column(db.String(500), nullable=True)   # Google profile picture URL

    def set_password(self, plaintext):
        self.password_hash = generate_password_hash(plaintext)

    def check_password(self, plaintext):
        if not self.password_hash:
            return False   # Google-only account has no password
        return check_password_hash(self.password_hash, plaintext)

    @property
    def has_password(self):
        return bool(self.password_hash)

    @property
    def login_method(self):
        """Return human-readable login method label."""
        if self.google_id and self.password_hash:
            return "Google + Password"
        if self.google_id:
            return "Google"
        return "Password"

    def __repr__(self):
        return f"<Admin id={self.id} username={self.username!r}>"


# ─────────────────────────────────────────────────────────────
#  Client
# ─────────────────────────────────────────────────────────────

class Client(db.Model):
    """A billing client (coaching student / gym member, etc.)."""
    __tablename__ = "clients"

    id          = db.Column(db.Integer,        primary_key=True)
    name        = db.Column(db.String(200),    nullable=False, index=True)
    phone       = db.Column(db.String(50),     nullable=True)
    email       = db.Column(db.String(255),    nullable=True, index=True)
    monthly_fee = db.Column(db.Numeric(10, 2), nullable=True, default=0.00)
    gst_number  = db.Column(db.String(30),     nullable=True)
    address     = db.Column(db.Text,           nullable=True)
    notes       = db.Column(db.Text,           nullable=True)
    is_active   = db.Column(db.Boolean,        default=True, nullable=False)
    created_at  = db.Column(db.DateTime,       nullable=False,
                            default=lambda: datetime.now(timezone.utc))
    admin_id = db.Column(db.Integer, db.ForeignKey("admins.id"), nullable=False)

    invoices = db.relationship("Invoice", back_populates="client",
                               lazy="dynamic", cascade="all, delete-orphan")

    @property
    def monthly_fee_display(self):
        if self.monthly_fee is None:
            return "—"
        return f"\u20b9{float(self.monthly_fee):,.2f}"   # Indian Rupee symbol

    @property
    def initials(self):
        parts = self.name.strip().split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return self.name[:2].upper()

    def __repr__(self):
        return f"<Client id={self.id} name={self.name!r}>"

    def to_dict(self):
        return {
            "id":          self.id,
            "name":        self.name,
            "phone":       self.phone,
            "email":       self.email,
            "monthly_fee": float(self.monthly_fee) if self.monthly_fee else 0.0,
            "gst_number":  self.gst_number,
            "address":     self.address,
            "is_active":   self.is_active,
            "created_at":  self.created_at.isoformat(),
        }


# ─────────────────────────────────────────────────────────────
#  Invoice
# ─────────────────────────────────────────────────────────────

class InvoiceStatus:
    UNPAID  = "unpaid"
    PAID    = "paid"
    OVERDUE = "overdue"
    ALL     = [UNPAID, PAID, OVERDUE]


class Invoice(db.Model):
    """
    A billable invoice.

    Fields
    ------
    id              – primary key
    invoice_number  – e.g. INV-0042
    client_id       – FK → clients.id
    amount          – base amount before GST
    gst_rate        – GST percentage applied (e.g. 18.0)
    gst             – Calculated GST amount based on gst_rate
    total           – amount + gst
    due_date        – payment due date
    status          – unpaid | paid | overdue
    pdf_path        – relative path to saved PDF file
    notes           – optional notes on the invoice
    is_recurring    – True if auto-generated monthly
    paid_at         – UTC timestamp when marked paid
    created_at      – UTC insert timestamp
    """

    __tablename__ = "invoices"

    id             = db.Column(db.Integer,        primary_key=True)
    invoice_number = db.Column(db.String(20),     unique=True, nullable=False, index=True)
    client_id      = db.Column(db.Integer,        db.ForeignKey("clients.id"),
                                nullable=False, index=True)
    amount         = db.Column(db.Numeric(10, 2), nullable=False)
    gst_rate       = db.Column(db.Numeric(5, 2),  nullable=False, default=18.00)
    gst            = db.Column(db.Numeric(10, 2), nullable=False)
    total          = db.Column(db.Numeric(10, 2), nullable=False)
    due_date       = db.Column(db.Date,           nullable=False)
    status         = db.Column(db.String(10),     nullable=False,
                                default=InvoiceStatus.UNPAID, index=True)
    pdf_path       = db.Column(db.String(300),    nullable=True)    # relative path
    notes          = db.Column(db.Text,           nullable=True)
    is_recurring   = db.Column(db.Boolean,        default=False, nullable=False)
    paid_at        = db.Column(db.DateTime,       nullable=True)
    created_at     = db.Column(db.DateTime,       nullable=False,
                                default=lambda: datetime.now(timezone.utc))

    client = db.relationship("Client", back_populates="invoices")

    # ── Class methods ─────────────────────────────────────────

    @classmethod
    def next_invoice_number(cls):
        """Return the next sequential invoice number as INV-NNNN."""
        last = (cls.query
                .order_by(cls.id.desc())
                .with_entities(cls.invoice_number)
                .first())
        if last is None:
            return "INV-0001"
        try:
            seq = int(last[0].split("-")[1]) + 1
        except (IndexError, ValueError):
            seq = cls.query.count() + 1
        return f"INV-{seq:04d}"

    @classmethod
    def calculate_gst(cls, amount, rate=18.0):
        """Return (gst_amount, total) as Decimals rounded to 2 d.p."""
        base  = Decimal(str(amount))
        rate_decimal = Decimal(str(rate)) / Decimal("100")
        gst   = (base * rate_decimal).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total = base + gst
        return gst, total

    # ── Instance helpers ──────────────────────────────────────

    @property
    def is_overdue(self):
        return (self.status == InvoiceStatus.UNPAID
                and self.due_date < date.today())

    @property
    def effective_status(self):
        if self.is_overdue:
            return InvoiceStatus.OVERDUE
        return self.status

    @property
    def status_label(self):
        return {
            InvoiceStatus.PAID:    ("Paid",    "status-paid"),
            InvoiceStatus.UNPAID:  ("Unpaid",  "status-unpaid"),
            InvoiceStatus.OVERDUE: ("Overdue", "status-overdue"),
        }.get(self.effective_status, ("Unknown", ""))

    @property
    def amount_display(self):
        return f"\u20b9{float(self.amount):,.2f}"
    
    @property
    def gst_rate_display(self):
        """Helper to cleanly display the percentage (e.g. 18% or 12.5%)."""
        rate_float = float(self.gst_rate)
        return f"{rate_float:g}%"

    @property
    def gst_display(self):
        return f"\u20b9{float(self.gst):,.2f}"

    @property
    def total_display(self):
        return f"\u20b9{float(self.total):,.2f}"

    def mark_paid(self):
        self.status  = InvoiceStatus.PAID
        self.paid_at = datetime.now(timezone.utc)

    def __repr__(self):
        return f"<Invoice {self.invoice_number} status={self.status!r}>"

    def to_dict(self):
        return {
            "id":             self.id,
            "invoice_number": self.invoice_number,
            "client_id":      self.client_id,
            "client_name":    self.client.name if self.client else None,
            "amount":         float(self.amount),
            "gst_rate":       float(self.gst_rate),
            "gst":            float(self.gst),
            "total":          float(self.total),
            "due_date":       self.due_date.isoformat(),
            "status":         self.effective_status,
            "is_recurring":   self.is_recurring,
            "pdf_path":       self.pdf_path,
            "created_at":     self.created_at.isoformat(),
        }
class BusinessProfile(db.Model):
    """User's business details used for generating PDF invoices."""
    __tablename__ = "business_profiles"

    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.String(255), unique=True, nullable=False, index=True)
    business_name = db.Column(db.String(200), nullable=False)
    gst_number    = db.Column(db.String(50),  nullable=True)
    address       = db.Column(db.Text,        nullable=True)
    upi_id        = db.Column(db.String(100), nullable=True)
    phone         = db.Column(db.String(50),  nullable=True)

    def __repr__(self):
        return f"<BusinessProfile user_id={self.user_id} name={self.business_name!r}>"