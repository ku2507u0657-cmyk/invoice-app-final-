"""
scheduler.py — APScheduler configuration for InvoiceFlow.
Runs two background jobs:
  1. Daily overdue reminder emails
  2. Monthly recurring invoice auto-generation
"""

import logging
import atexit

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy  import SQLAlchemyJobStore
from apscheduler.executors.pool        import ThreadPoolExecutor
from apscheduler.triggers.cron         import CronTrigger

logger = logging.getLogger(__name__)


def init_scheduler(app):
    """Create and start the scheduler. Attach to app.scheduler."""
    if not app.config.get("SCHEDULER_ENABLED", False):
        logger.info("Scheduler disabled (SCHEDULER_ENABLED=False).")
        return

    db_url   = app.config.get("SQLALCHEMY_DATABASE_URI", "sqlite:///invoice_app.db")
    timezone = app.config.get("SCHEDULER_TIMEZONE", "Asia/Kolkata")
    hour     = app.config.get("REMINDER_HOUR",   9)
    minute   = app.config.get("REMINDER_MINUTE", 0)
    rec_day  = app.config.get("RECURRING_DAY",   1)

    scheduler = BackgroundScheduler(
        jobstores    = {"default": SQLAlchemyJobStore(url=db_url,
                                                      tablename="apscheduler_jobs")},
        executors    = {"default": ThreadPoolExecutor(max_workers=2)},
        job_defaults = {"coalesce": True, "max_instances": 1,
                        "misfire_grace_time": 3600},
        timezone     = timezone,
    )

    # ── Job 1: Daily overdue reminder ─────────────────────────
    from utils.reminder import run_overdue_reminder_job
    scheduler.add_job(
        func             = run_overdue_reminder_job,
        trigger          = CronTrigger(hour=hour, minute=minute, timezone=timezone),
        id               = "daily_overdue_reminder",
        name             = "Daily Overdue Reminder",
        args             = [app],
        replace_existing = True,
    )

    # ── Job 2: Monthly recurring invoice generation ───────────
    from utils.reminder import run_recurring_invoice_job
    scheduler.add_job(
        func             = run_recurring_invoice_job,
        trigger          = CronTrigger(day=rec_day, hour=8, minute=0, timezone=timezone),
        id               = "monthly_recurring_invoices",
        name             = "Monthly Recurring Invoice Generator",
        args             = [app],
        replace_existing = True,
    )

    scheduler.start()
    app.scheduler = scheduler

    logger.info(
        "Scheduler started. Reminder: %02d:%02d %s | Recurring: day=%d",
        hour, minute, timezone, rec_day,
    )

    atexit.register(lambda: scheduler.shutdown(wait=False) if scheduler.running else None)
    return scheduler
