# InvoiceFlow — Invoice Automation for Indian Small Businesses

A production-ready invoice automation web app built with Flask, designed for
coaching classes, gyms, and other service-based small businesses in India.

## Features

- **Admin Authentication** — Secure login with hashed passwords
- **Client Management** — Add, edit, remove clients with monthly fee tracking
- **Invoice System** — Auto-numbered invoices with 18% GST calculation
- **UPI QR Code** — Embedded in PDF and invoice view for instant payment
- **PDF Generation** — Professional A4 invoices saved to `/invoices/` folder
- **Email Automation** — Invoice emailed on creation, reminders for overdue
- **Payment Tracking** — Mark paid, record payment date, see collection rate
- **Business Dashboard** — Revenue charts, KPI cards, unpaid list, top clients
- **CSV Export** — Export all/filtered invoices as CSV
- **Recurring Invoices** — Auto-generate monthly invoices for active clients
- **Reminder Scheduler** — Daily background job for overdue reminders
- **PostgreSQL Ready** — SQLite for dev, PostgreSQL for production
- **One-click Deploy** — Render.com `render.yaml` included

---

## Quick Start (Local Development)

### 1. Clone & setup

```bash
git clone <your-repo-url> invoiceflow
cd invoiceflow
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your values (at minimum set SECRET_KEY)
```

### 3. Run

```bash
python app.py
```

Open http://localhost:5000 — login with `admin` / `changeme123`

---

## Project Structure

```
invoiceflow/
├── app.py                  # App factory, entry point
├── config.py               # All environment-based config
├── extensions.py           # SQLAlchemy, Migrate, LoginManager
├── models.py               # Admin, Client, Invoice ORM models
├── scheduler.py            # APScheduler — reminders + recurring
├── requirements.txt
├── Procfile                # Gunicorn for Render/Railway
├── render.yaml             # One-click Render deploy config
├── runtime.txt             # Python 3.11
├── .env.example            # Template for all environment variables
├── README.md
│
├── routes/
│   ├── auth.py             # Login / logout
│   ├── clients.py          # Client CRUD
│   ├── invoices.py         # Invoice list, create, view, download, CSV
│   └── main.py             # Dashboard with live chart data
│
├── utils/
│   ├── pdf.py              # ReportLab PDF generator (with UPI QR)
│   ├── qr.py               # UPI QR code builder
│   ├── email.py            # smtplib invoice + reminder mailer
│   ├── reminder.py         # Overdue reminder + recurring invoice jobs
│   ├── csv_export.py       # CSV export helper
│   └── helpers.py          # Shared utilities
│
├── templates/
│   ├── base.html           # Master layout (sidebar, topbar)
│   ├── index.html          # Public landing page
│   ├── dashboard.html      # Business dashboard with Chart.js
│   ├── auth/login.html
│   ├── clients/
│   │   ├── list.html
│   │   └── form.html       # Add / Edit (shared)
│   ├── invoices/
│   │   ├── list.html       # Filterable invoice list + CSV export button
│   │   ├── create.html     # New invoice form with live GST preview
│   │   └── view.html       # Invoice detail with UPI QR + PDF download
│   └── emails/
│       ├── invoice_email.html
│       └── reminder_email.html
│
├── static/
│   ├── css/main.css        # Full design system
│   ├── css/home.css        # Landing page styles
│   └── js/main.js
│
└── invoices/               # Auto-created — saved PDF files (gitignored)
```

---

## Deployment on Render (Free Tier)

### Option A — render.yaml (one-click)

1. Push your code to GitHub
2. Go to [render.com](https://render.com) → **New** → **Blueprint**
3. Connect your repo — Render reads `render.yaml` automatically
4. Add your secret env vars in the Render dashboard:
   - `ADMIN_PASSWORD`
   - `MAIL_USERNAME`, `MAIL_PASSWORD` (if using email)
   - `UPI_ID`, `COMPANY_NAME`, etc.
5. Deploy — Render provisions a free PostgreSQL database automatically

### Option B — Manual

1. Create a **Web Service** on Render with Python runtime
2. Build command: `pip install -r requirements.txt`
3. Start command: `gunicorn app:app --workers 1 --bind 0.0.0.0:$PORT --timeout 120`
4. Add a **PostgreSQL** database and copy its `DATABASE_URL`
5. Set all required env vars from `.env.example`

---

## Gmail Setup (Email Sending)

1. Enable 2-Step Verification on your Google account
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Create an App Password → copy the 16-character password
4. In `.env`:
   ```
   MAIL_ENABLED=True
   MAIL_USERNAME=you@gmail.com
   MAIL_PASSWORD=xxxx xxxx xxxx xxxx
   ```

---

## UPI QR Code Setup

```
UPI_ID=yourname@okicici        # or @ybl, @upi, etc.
UPI_PAYEE_NAME=Your Coaching Class
```

The QR code is auto-embedded in every generated PDF and shown on the invoice
view page. Students can scan with GPay, PhonePe, BHIM, or any UPI app.

---

## Scheduler Jobs

| Job | Schedule | Description |
|-----|----------|-------------|
| `daily_overdue_reminder` | Daily at 09:00 IST | Emails all unpaid overdue invoices |
| `monthly_recurring_invoices` | 1st of month, 08:00 IST | Auto-generates invoices for active clients with monthly fees |

Enable with `SCHEDULER_ENABLED=True` in `.env`.

---

## Default Credentials

| Field | Value |
|-------|-------|
| Username | `admin` |
| Password | `changeme123` |

**Change immediately** via `ADMIN_USERNAME` / `ADMIN_PASSWORD` in `.env`.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, Flask 3.0 |
| ORM | SQLAlchemy 2.0 + Flask-Migrate |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Auth | Flask-Login + Werkzeug hashing |
| PDF | ReportLab 4.2 |
| QR Code | qrcode + Pillow |
| Email | smtplib (stdlib) |
| Scheduler | APScheduler 3.10 |
| Frontend | Bootstrap 5, Jinja2, Chart.js 4 |
| Server | Gunicorn |
