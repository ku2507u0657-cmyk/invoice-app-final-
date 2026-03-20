"""
scheduler.py — APScheduler configuration for InvoiceFlow.
Runs two background jobs:
  1. Daily overdue reminder emails
  2. Monthly recurring invoice auto-generation
"""

import logging
import atexit
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)


def init_scheduler(app):
    """Create and start the scheduler. Attach to app.scheduler."""

    if not app.config.get("SCHEDULER_ENABLED", True):
        logger.info("Scheduler disabled.")
        return

    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    # ✅ Wrapper 1
    def overdue_wrapper():
        from app import app
        from utils.reminder import run_overdue_reminder_job

        with app.app_context():
            run_overdue_reminder_job()

    # ✅ Wrapper 2
    def recurring_wrapper():
        from app import app
        from utils.reminder import run_recurring_invoice_job

        with app.app_context():
            run_recurring_invoice_job()

    # ✅ Job 1 (test every 1 min)
    scheduler.add_job(
        func=overdue_wrapper,
        trigger="interval",
        minutes=1,
        id="daily_overdue_reminder",
        replace_existing=True,
    )

    # ✅ Job 2 (test every 1 min)
    scheduler.add_job(
        func=recurring_wrapper,
        trigger="interval",
        minutes=1,
        id="monthly_recurring_invoices",
        replace_existing=True,
    )

    scheduler.start()
    app.scheduler = scheduler

    logger.info("Scheduler started successfully")

    atexit.register(lambda: scheduler.shutdown(wait=False) if scheduler.running else None)

    return scheduler
