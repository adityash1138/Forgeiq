"""Job scheduler and orchestration — APScheduler, IST.

Runs the whole pipeline on a schedule inside the Python app (no separate
service). Every job is wrapped in run_with_logging() which records a row in
job_runs and alerts the founder on failure. An hourly heartbeat row + an
external uptime monitor on /health is the primary reliability mechanism.

Local run:  python -m scheduler.scheduler
On Railway: this is the `worker` process in the Procfile.
"""
from __future__ import annotations

import os
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from apscheduler.schedulers.blocking import BlockingScheduler

from db.connection import get_cursor

scheduler = BlockingScheduler(timezone="Asia/Kolkata")


# --------------------------------------------------------------------- logging
def log_job_run(job_name: str, status: str, started_at: datetime,
                error: str | None = None) -> None:
    try:
        with get_cursor() as cur:
            cur.execute(
                "INSERT INTO job_runs (job_name, status, started_at, error) "
                "VALUES (%s, %s, %s, %s)", (job_name, status, started_at, error))
    except Exception as exc:
        print(f"log_job_run failed for {job_name}: {exc}")


def send_failure_alert(job_name: str, error: str) -> None:
    """Email/WhatsApp the founder on a failed job (wire messaging integration)."""
    print(f"[ALERT] job '{job_name}' failed: {error}")


def run_with_logging(job_name: str, job_fn) -> None:
    start = datetime.now()
    try:
        job_fn()
        log_job_run(job_name, "success", start)
    except Exception as exc:  # noqa: BLE001 — jobs must never crash the scheduler
        log_job_run(job_name, "failed", start, error=str(exc))
        send_failure_alert(job_name, str(exc))


# --------------------------------------------------------------------- jobs
@scheduler.scheduled_job("cron", hour=5, minute=30)
def run_tier1_scrapers():
    def _job():
        from scrapers.gem_scraper import GemScraper
        from scrapers.bse_scraper import BseScraper
        from scrapers.pli_scraper import PliScraper
        from scrapers.icegate_scraper import IcegateScraper
        GemScraper().run()
        BseScraper().run()
        PliScraper().run()
        IcegateScraper().run()
    run_with_logging("tier1_scrapers", _job)


@scheduler.scheduled_job("cron", hour=6, minute=0)
def run_tier2_scrapers():
    def _job():
        from scrapers.jobs_scraper import JobsScraper
        from scrapers.land_scraper import LandScraper
        from scrapers.ec_scraper import EcScraper
        from scrapers.oem_news_scraper import OemNewsScraper
        from scrapers.vc_scraper import VcScraper
        from scrapers.mca_scraper import McaScraper
        JobsScraper().run()
        LandScraper().run()
        EcScraper().run()
        OemNewsScraper().run()
        VcScraper().run()
        McaScraper().run()
    run_with_logging("tier2_scrapers", _job)


@scheduler.scheduled_job("cron", hour="*/4")
def run_tier3_scrapers():
    def _job():
        from scrapers.gst_scraper import GstScraper
        from scrapers.news_scraper import NewsScraper
        GstScraper().run()
        NewsScraper().run()
    run_with_logging("tier3_scrapers", _job)


@scheduler.scheduled_job("cron", hour=7, minute=0)
def run_pipeline():
    def _job():
        from processing import deduplicator, app_tagger, entity_resolver
        from engine import scoring_engine, cascade_engine
        from contact import contact_sourcer
        from delivery import lead_router
        deduplicator.process_new_signals()
        app_tagger.tag_new_signals()
        entity_resolver.resolve_new_signals()
        entity_resolver.process_queue_daily()
        scoring_engine.recalculate_all_due()
        cascade_engine.process_cascade_states_daily()
        contact_sourcer.source_for_new_warm_leads()
        lead_router.route_hot_scores()
    run_with_logging("pipeline", _job)


@scheduler.scheduled_job("cron", hour=9, minute=0)
def send_feedback_pings():
    def _job():
        from feedback.outcome_processor import send_14day_pings
        send_14day_pings()
    run_with_logging("feedback_pings", _job)


@scheduler.scheduled_job("cron", minute=0)  # hourly heartbeat
def heartbeat():
    log_job_run("heartbeat", "heartbeat", datetime.now())


if __name__ == "__main__":
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL not set — scheduler needs the database.")
    print("ForgeIQ scheduler starting (Asia/Kolkata). Jobs:")
    for job in scheduler.get_jobs():
        print(f"  {job.id}: {job.trigger}")
    scheduler.start()
