"""
routes/auth.py — Authentication: username/password + Google OAuth2.

Google OAuth flow
-----------------
1.  GET  /auth/google/login        — redirect user to Google consent screen
2.  GET  /auth/google/callback     — Google redirects here with ?code=
3.                                   Exchange code for token, fetch profile
4.                                   Find or create Admin, login_user(), redirect

Password flow (kept as fallback)
---------------------------------
POST /auth/login  →  validate credentials  →  login_user()
"""

import logging
import secrets

from flask import (
    Blueprint, render_template, redirect, url_for,
    request, flash, current_app, session,
)
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db
from models import Admin

logger  = logging.getLogger(__name__)
auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

def _get_google_client():
    """
    Return a configured Authlib OAuth registry client for Google.
    Returns None if GOOGLE_CLIENT_ID is not set.
    """
    client_id     = current_app.config.get("GOOGLE_CLIENT_ID",     "")
    client_secret = current_app.config.get("GOOGLE_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        return None

    from authlib.integrations.requests_client import OAuth2Session

    client = OAuth2Session(
        client_id     = client_id,
        client_secret = client_secret,
        scope         = "openid email profile",
        redirect_uri  = url_for("auth.google_callback", _external=True),
    )
    return client


def _is_email_allowed(email: str) -> bool:
    """
    If GOOGLE_ALLOWED_EMAILS is set, only listed addresses may log in.
    An empty list means all Google accounts are accepted.
    """
    allowed_raw = current_app.config.get("GOOGLE_ALLOWED_EMAILS", "")
    if not allowed_raw.strip():
        return True   # open — any Google account

    allowed = [e.strip().lower() for e in allowed_raw.split(",") if e.strip()]
    return email.lower() in allowed


def _find_or_create_admin(google_id: str, email: str,
                           display_name: str, avatar_url: str) -> Admin:
    """
    Look up an existing admin by google_id or email; create one if new.
    Existing password-only admins are upgraded with their Google data.
    """
    # 1. Match by google_id (most specific)
    admin = Admin.query.filter_by(google_id=google_id).first()
    if admin:
        # Refresh profile data on every login
        admin.display_name = display_name
        admin.avatar_url   = avatar_url
        db.session.commit()
        return admin

    # 2. Match by email — upgrade an existing password-only account
    admin = Admin.query.filter_by(email=email).first()
    if not admin:
        # Also try matching by username == email (common pattern)
        admin = Admin.query.filter_by(username=email).first()

    if admin:
        admin.google_id    = google_id
        admin.email        = email
        admin.display_name = display_name
        admin.avatar_url   = avatar_url
        db.session.commit()
        logger.info("Linked Google account to existing admin '%s'", admin.username)
        return admin

    # 3. Brand-new admin — create from Google profile
    username = email.split("@")[0]
    # Ensure username is unique
    base, n = username, 1
    while Admin.query.filter_by(username=username).first():
        username = f"{base}{n}"
        n += 1

    admin = Admin(
        username     = username,
        google_id    = google_id,
        email        = email,
        display_name = display_name,
        avatar_url   = avatar_url,
    )
    db.session.add(admin)
    db.session.commit()
    logger.info("Created new admin '%s' via Google OAuth", username)
    return admin


# ═══════════════════════════════════════════════════════════════
#  Password login (unchanged, kept as fallback)
# ═══════════════════════════════════════════════════════════════

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Username + password login form."""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    google_enabled = bool(current_app.config.get("GOOGLE_CLIENT_ID"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        if not username or not password:
            flash("Username and password are required.", "danger")
            return render_template("auth/login.html",
                                   app_name=current_app.config.get("APP_NAME"),
                                   google_enabled=google_enabled)

        admin = Admin.query.filter_by(username=username).first()

        if admin is None or not admin.check_password(password):
            flash("Invalid username or password.", "danger")
            return render_template("auth/login.html",
                                   app_name=current_app.config.get("APP_NAME"),
                                   google_enabled=google_enabled)

        login_user(admin, remember=remember)
        flash(f"Welcome back, {admin.display_name or admin.username}!", "success")

        next_page = request.args.get("next")
        if next_page and next_page.startswith("/"):
            return redirect(next_page)
        return redirect(url_for("main.dashboard"))

    return render_template(
        "auth/login.html",
        app_name       = current_app.config.get("APP_NAME", "InvoiceFlow"),
        google_enabled = google_enabled,
    )


# ═══════════════════════════════════════════════════════════════
#  Google OAuth — Step 1: redirect to Google
# ═══════════════════════════════════════════════════════════════

@auth_bp.route("/google/login")
def google_login():
    """Redirect the browser to Google's OAuth consent screen."""
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    client = _get_google_client()
    if not client:
        flash("Google login is not configured on this server.", "warning")
        return redirect(url_for("auth.login"))

    # Generate a CSRF-protection state token
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state

    authorization_url, _ = client.create_authorization_url(
        "https://accounts.google.com/o/oauth2/v2/auth",
        state             = state,
        access_type       = "online",
        prompt            = "select_account",   # always show account picker
    )
    return redirect(authorization_url)


# ═══════════════════════════════════════════════════════════════
#  Google OAuth — Step 2: handle callback from Google
# ═══════════════════════════════════════════════════════════════

@auth_bp.route("/google/callback")
def google_callback():
    """
    Google redirects here after the user grants (or denies) access.
    Exchange the authorisation code for an access token, fetch the
    user's profile, then find-or-create an Admin record.
    """
    # ── Error from Google ──────────────────────────────────────
    error = request.args.get("error")
    if error:
        flash(f"Google login cancelled or denied: {error}", "warning")
        return redirect(url_for("auth.login"))

    # ── CSRF state check ───────────────────────────────────────
    returned_state = request.args.get("state", "")
    stored_state   = session.pop("oauth_state", None)
    if not stored_state or returned_state != stored_state:
        flash("Security check failed. Please try logging in again.", "danger")
        return redirect(url_for("auth.login"))

    client = _get_google_client()
    if not client:
        flash("Google login is not configured.", "warning")
        return redirect(url_for("auth.login"))

    # ── Exchange code for token ────────────────────────────────
    try:
        token = client.fetch_token(
            "https://oauth2.googleapis.com/token",
            authorization_response = request.url,
            code                   = request.args.get("code"),
        )
    except Exception as exc:
        logger.exception("Token exchange failed: %s", exc)
        flash("Google login failed — could not exchange token. Please try again.", "danger")
        return redirect(url_for("auth.login"))

    # ── Fetch Google user profile ──────────────────────────────
    try:
        resp    = client.get("https://www.googleapis.com/oauth2/v3/userinfo")
        profile = resp.json()
    except Exception as exc:
        logger.exception("Could not fetch Google profile: %s", exc)
        flash("Google login failed — could not fetch profile.", "danger")
        return redirect(url_for("auth.login"))

    google_id    = profile.get("sub")          # unique, stable Google user ID
    email        = profile.get("email", "")
    display_name = profile.get("name",  "")
    avatar_url   = profile.get("picture", "")

    if not google_id or not email:
        flash("Google did not return a valid account. Please try again.", "danger")
        return redirect(url_for("auth.login"))

    # ── Email allowlist check ──────────────────────────────────
    if not _is_email_allowed(email):
        logger.warning("Blocked Google login for non-allowed email: %s", email)
        flash(
            f"{email} is not authorised to access this application. "
            "Contact the administrator.",
            "danger",
        )
        return redirect(url_for("auth.login"))

    # ── Find or create Admin ───────────────────────────────────
    try:
        admin = _find_or_create_admin(google_id, email, display_name, avatar_url)
    except Exception as exc:
        logger.exception("find_or_create_admin failed: %s", exc)
        flash("Login failed — database error. Please try again.", "danger")
        return redirect(url_for("auth.login"))

    # ── Log in ─────────────────────────────────────────────────
    login_user(admin, remember=True)
    flash(f"Welcome, {admin.display_name or admin.username}! Signed in with Google.", "success")

    next_page = request.args.get("next") or session.pop("next_url", None)
    if next_page and next_page.startswith("/"):
        return redirect(next_page)
    return redirect(url_for("main.dashboard"))


# ═══════════════════════════════════════════════════════════════
#  Logout
# ═══════════════════════════════════════════════════════════════

@auth_bp.route("/logout")
@login_required
def logout():
    """Clear session and redirect to login."""
    logout_user()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
