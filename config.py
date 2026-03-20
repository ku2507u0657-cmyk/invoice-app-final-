"""
config.py — Environment-based configuration for InvoiceFlow
Supports SQLite (development) and PostgreSQL (production).
"""

import os
from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    # ── Flask ──────────────────────────────────────────────────
    SECRET_KEY   = os.environ.get("SECRET_KEY", "dev-fallback-secret-key-change-in-production")
    APP_NAME     = os.environ.get("APP_NAME",     "InvoiceFlow")
    COMPANY_NAME = os.environ.get("COMPANY_NAME", "Your Company")
    COMPANY_ADDRESS = os.environ.get("COMPANY_ADDRESS", "")
    COMPANY_PHONE   = os.environ.get("COMPANY_PHONE",   "")
    COMPANY_EMAIL   = os.environ.get("COMPANY_EMAIL",   "")
    COMPANY_GSTIN   = os.environ.get("COMPANY_GSTIN",   "")
    COMPANY_LOGO    = os.environ.get("COMPANY_LOGO",    "")   # path to logo file

    # ── Database ───────────────────────────────────────────────
    # Set DATABASE_URL to postgresql://... in .env for production.
    # Render / Railway automatically set DATABASE_URL on deploy.
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    _db_url = os.environ.get("DATABASE_URL", "sqlite:///invoice_app.db")
    # Render gives postgres:// but SQLAlchemy needs postgresql://
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url

    # ── PDF Storage ────────────────────────────────────────────
    # Where generated invoice PDFs are saved on disk.
    PDF_FOLDER = os.environ.get("PDF_FOLDER", os.path.join(os.path.dirname(__file__), "invoices"))

    # ── UPI Payment ────────────────────────────────────────────
    UPI_ID          = os.environ.get("UPI_ID",          "")   # e.g. yourname@upi
    UPI_PAYEE_NAME  = os.environ.get("UPI_PAYEE_NAME",  os.environ.get("COMPANY_NAME", "InvoiceFlow"))

    # ── SMTP / Email ───────────────────────────────────────────
    MAIL_ENABLED          = os.environ.get("MAIL_ENABLED", "True").lower() == "true"
    MAIL_SERVER           = os.environ.get("MAIL_SERVER",   "smtp.gmail.com")
    MAIL_PORT             = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USE_TLS          = os.environ.get("MAIL_USE_TLS",  "True").lower() == "true"
    MAIL_USERNAME         = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD         = os.environ.get("MAIL_PASSWORD")
    MAIL_FROM_NAME        = os.environ.get("MAIL_FROM_NAME",    APP_NAME)
    MAIL_FROM_ADDRESS     = os.environ.get("MAIL_FROM_ADDRESS",
                                           MAIL_USERNAME or "noreply@invoiceflow.app")
    MAIL_FALLBACK_RECIPIENT = os.environ.get("MAIL_FALLBACK_RECIPIENT")

    # ── Google OAuth2 ──────────────────────────────────────────
    # Obtain from https://console.cloud.google.com/
    #   APIs & Services → Credentials → OAuth 2.0 Client IDs
    # Authorised redirect URI must include:
    #   http://localhost:5000/auth/google/callback  (dev)
    #   https://yourdomain.com/auth/google/callback (prod)
    GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID",     "")
    GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    # Comma-separated list of allowed Google email addresses.
    # Leave empty to allow ANY Google account (not recommended for production).
    GOOGLE_ALLOWED_EMAILS = os.environ.get("GOOGLE_ALLOWED_EMAILS", "")

    # ── APScheduler ────────────────────────────────────────────
    SCHEDULER_ENABLED   = os.environ.get("SCHEDULER_ENABLED", "True").lower() == "true"
    REMINDER_HOUR       = int(os.environ.get("REMINDER_HOUR",   9))
    REMINDER_MINUTE     = int(os.environ.get("REMINDER_MINUTE", 0))
    SCHEDULER_TIMEZONE  = os.environ.get("SCHEDULER_TIMEZONE",  "Asia/Kolkata")
    REMINDER_GRACE_DAYS = int(os.environ.get("REMINDER_GRACE_DAYS", 0))

    # ── Recurring Invoices ─────────────────────────────────────
    # Day of month (1-28) on which recurring invoices are auto-generated.
    RECURRING_DAY = int(os.environ.get("RECURRING_DAY", 1))


class DevelopmentConfig(BaseConfig):
    DEBUG             = True
    TESTING           = False
    MAIL_ENABLED      = os.environ.get("MAIL_ENABLED",      "False").lower() == "true"
    SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "False").lower() == "true"


class TestingConfig(BaseConfig):
    DEBUG             = True
    TESTING           = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED  = False
    MAIL_ENABLED      = False
    SCHEDULER_ENABLED = False


class ProductionConfig(BaseConfig):
    DEBUG   = False
    TESTING = False


config_map = {
    "development": DevelopmentConfig,
    "testing":     TestingConfig,
    "production":  ProductionConfig,
}


def get_config():
    env = os.environ.get("FLASK_ENV", "development").lower()
    return config_map.get(env, DevelopmentConfig)
