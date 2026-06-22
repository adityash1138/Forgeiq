"""Admin / founder console API — the developer interface to operate ForgeIQ.

Covers the 10 developer-panel items from the gap audit: scraper health, entity
resolution queue, scoring runs, signal/cascade config editing, outcome review,
vendor management, lead-delivery audit, company browser, and job logs.

All endpoints require the x-admin-key header (see api/deps.require_admin).
These are read-mostly operational views over data that already lives in the DB;
two PATCH endpoints let the founder tune signal/cascade config without a deploy.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.deps import require_admin
from db.connection import fetch_all, fetch_one, get_cursor

router = APIRouter(dependencies=[Depends(require_admin)])


# ── system overview ────────────────────────────────────────────────────────
@router.get("/stats")
def system_stats():
    """Headline counts for the admin home screen."""
    def n(q: str) -> int:
        return (fetch_one(q) or {}).get("n", 0)
    return {
        "companies": n("SELECT COUNT(*) n FROM companies"),
        "raw_signals": n("SELECT COUNT(*) n FROM raw_signals"),
        "signals_unresolved": n(
            "SELECT COUNT(*) n FROM raw_signals WHERE resolved_company_id IS NULL"),
        "scores": n("SELECT COUNT(*) n FROM scores"),
        "hot_scores": n("SELECT COUNT(*) n FROM scores WHERE status='HOT'"),
        "warm_scores": n("SELECT COUNT(*) n FROM scores WHERE status='WARM'"),
        "vendors": n("SELECT COUNT(*) n FROM vendors"),
        "leads_delivered": n("SELECT COUNT(*) n FROM lead_delivery"),
        "entity_queue_active": n(
            "SELECT COUNT(*) n FROM entity_resolution_queue WHERE status='Active'"),
        "outcomes": n("SELECT COUNT(*) n FROM outcomes"),
    }


# ── 1. scraper health ──────────────────────────────────────────────────────
@router.get("/scrapers")
def scraper_health():
    """Last run per job: status + timestamp + error, from job_runs."""
    return fetch_all(
        """
        SELECT DISTINCT ON (job_name)
               job_name, status, started_at, finished_at, error
        FROM job_runs
        ORDER BY job_name, finished_at DESC
        """)


# ── 2. entity resolution queue ─────────────────────────────────────────────
@router.get("/entity-queue")
def entity_queue(status: Optional[str] = Query(None)):
    clauses, params = [], []
    if status:
        clauses.append("eq.status = %s")
        params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    items = fetch_all(
        f"""
        SELECT eq.id, eq.raw_company_name, eq.confidence_pct, eq.days_in_queue,
               eq.status, eq.resolution_notes, eq.created_at,
               c.legal_name AS best_guess_name
        FROM entity_resolution_queue eq
        LEFT JOIN companies c ON c.id = eq.best_guess_company_id
        {where}
        ORDER BY eq.created_at DESC LIMIT 200
        """, tuple(params))
    # Tier breakdown (A/B auto-resolved live on raw_signals; C/D queue here).
    tiers = fetch_all(
        "SELECT resolution_tier AS tier, COUNT(*) n FROM raw_signals "
        "WHERE resolution_tier IS NOT NULL GROUP BY resolution_tier")
    return {"queue": items, "tier_breakdown": {t["tier"]: t["n"] for t in tiers}}


# ── 3. scoring engine runs ─────────────────────────────────────────────────
@router.get("/scores")
def recent_scores():
    return fetch_all(
        """
        SELECT s.current_score, s.status, s.negative_multiplier,
               s.last_calculated_at, c.legal_name AS company_name,
               a.application_name
        FROM scores s
        JOIN companies c ON c.id = s.company_id
        LEFT JOIN applications a ON a.id = s.application_id
        ORDER BY s.last_calculated_at DESC NULLS LAST LIMIT 200
        """)


# ── 4. signal type config editor ───────────────────────────────────────────
@router.get("/signal-config")
def signal_config():
    return fetch_all("SELECT * FROM signal_type_config ORDER BY tier, signal_type")


class SignalConfigUpdate(BaseModel):
    tier_weight: Optional[float] = None
    base_strength: Optional[int] = None
    decay_curve: Optional[str] = None
    peak_start_days: Optional[int] = None
    peak_end_days: Optional[int] = None
    total_decay_days: Optional[int] = None
    is_cascade_trigger: Optional[str] = None


@router.patch("/signal-config/{signal_type}")
def update_signal_config(signal_type: str, body: SignalConfigUpdate):
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")
    sets = ", ".join(f"{k} = %s" for k in fields)
    params = list(fields.values()) + [signal_type]
    with get_cursor() as cur:
        cur.execute(
            f"UPDATE signal_type_config SET {sets} WHERE signal_type = %s",
            tuple(params))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="signal_type not found")
    return fetch_one("SELECT * FROM signal_type_config WHERE signal_type = %s",
                     (signal_type,))


# ── 5. cascade wave config editor ──────────────────────────────────────────
@router.get("/cascade-config")
def cascade_config():
    return fetch_all(
        """
        SELECT cw.*, a.application_name
        FROM cascade_wave_config cw
        LEFT JOIN applications a ON a.id = cw.application_id
        ORDER BY cw.trigger_signal_type, cw.wave_order
        """)


# ── 6. outcome review (calibration) ────────────────────────────────────────
@router.get("/outcomes")
def outcomes():
    rows = fetch_all(
        """
        SELECT o.outcome_status, o.reason_detail, o.captured_via, o.captured_at,
               v.vendor_name, c.legal_name AS company_name
        FROM outcomes o
        JOIN lead_delivery ld ON ld.id = o.delivery_id
        JOIN vendors v ON v.id = ld.vendor_id
        JOIN scores s ON s.id = ld.score_id
        JOIN companies c ON c.id = s.company_id
        ORDER BY o.captured_at DESC LIMIT 200
        """)
    breakdown = fetch_all(
        "SELECT outcome_status, COUNT(*) n FROM outcomes GROUP BY outcome_status")
    return {"outcomes": rows,
            "breakdown": {b["outcome_status"]: b["n"] for b in breakdown}}


# ── 7. vendor management ───────────────────────────────────────────────────
@router.get("/vendors")
def vendors():
    return fetch_all(
        """
        SELECT v.id, v.vendor_name, v.price_tier, v.geography, v.application_id,
               v.onboarding_complete, v.api_key, v.created_at,
               a.application_name,
               (SELECT COUNT(*) FROM lead_delivery ld WHERE ld.vendor_id = v.id)
                 AS leads_delivered
        FROM vendors v
        LEFT JOIN applications a ON a.id = v.application_id
        ORDER BY v.created_at DESC
        """)


# ── 8. lead delivery audit ─────────────────────────────────────────────────
@router.get("/deliveries")
def deliveries():
    return fetch_all(
        """
        SELECT ld.id, ld.delivered_at, ld.confidence_tier_shown,
               ld.human_spotcheck_done, ld.exclusivity_window_end,
               v.vendor_name, c.legal_name AS company_name, s.current_score,
               s.status,
               (SELECT o.outcome_status FROM outcomes o
                WHERE o.delivery_id = ld.id
                ORDER BY o.captured_at DESC LIMIT 1) AS latest_outcome
        FROM lead_delivery ld
        JOIN vendors v ON v.id = ld.vendor_id
        JOIN scores s ON s.id = ld.score_id
        JOIN companies c ON c.id = s.company_id
        ORDER BY ld.delivered_at DESC LIMIT 200
        """)


# ── 9. company / entity browser ────────────────────────────────────────────
@router.get("/companies")
def companies(q: Optional[str] = Query(None)):
    clauses, params = [], []
    if q:
        clauses.append("(legal_name ILIKE %s OR cin ILIKE %s)")
        params += [f"%{q}%", f"%{q}%"]
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return fetch_all(
        f"""
        SELECT c.id, c.legal_name, c.cin, c.plant_location, c.negative_flag,
               c.negative_flag_date,
               (SELECT COUNT(*) FROM raw_signals rs
                  WHERE rs.resolved_company_id = c.id) AS signal_count,
               (SELECT COUNT(*) FROM scores s WHERE s.company_id = c.id) AS score_count
        FROM companies c {where}
        ORDER BY c.legal_name LIMIT 200
        """, tuple(params))


# ── 10. job scheduler log viewer ───────────────────────────────────────────
@router.get("/jobs")
def job_log(limit: int = Query(100, le=500)):
    return fetch_all(
        "SELECT job_name, status, started_at, finished_at, error "
        "FROM job_runs ORDER BY finished_at DESC LIMIT %s", (limit,))


# ── 11. manual scraper trigger ─────────────────────────────────────────────
@router.post("/run-scrapers")
def run_scrapers(tier: Optional[str] = Query(None, description="1, 2, 3, or all")):
    """Manually trigger scrapers. Protected by x-admin-key.
    tier=1 → BSE/GEM/PLI/ICEGATE  tier=2 → jobs/land/news  tier=3 → RSS/news
    Omit tier (or tier=all) to run everything.
    Also runs the full pipeline (entity resolve + score + deliver) after scraping.
    """
    from datetime import datetime
    results = {}
    start = datetime.now()

    def _run(name: str, fn):
        try:
            count = fn()
            results[name] = {"status": "ok", "signals": count}
        except Exception as exc:
            results[name] = {"status": "error", "error": str(exc)}

    t = (tier or "all").strip()

    if t in ("1", "all"):
        from scrapers.bse_scraper import BseScraper
        from scrapers.gem_scraper import GemScraper
        from scrapers.pli_scraper import PliScraper
        _run("bse", lambda: BseScraper().run())
        _run("gem", lambda: GemScraper().run())
        _run("pli", lambda: PliScraper().run())

    if t in ("2", "all"):
        from scrapers.news_scraper import NewsScraper
        from scrapers.oem_news_scraper import OemNewsScraper
        from scrapers.vc_scraper import VcScraper
        _run("news", lambda: NewsScraper().run())
        _run("oem_news", lambda: OemNewsScraper().run())
        _run("vc", lambda: VcScraper().run())

    if t in ("3", "all"):
        from scrapers.jobs_scraper import JobsScraper
        from scrapers.land_scraper import LandScraper
        _run("jobs", lambda: JobsScraper().run())
        _run("land", lambda: LandScraper().run())

    # run pipeline after scraping
    try:
        from processing import deduplicator, entity_resolver, app_tagger
        from engine import scoring_engine, cascade_engine
        from delivery import lead_router
        deduplicator.process_new_signals()
        app_tagger.tag_new_signals()
        entity_resolver.resolve_new_signals()
        entity_resolver.process_queue_daily()
        scoring_engine.recalculate_all_due()
        cascade_engine.process_cascade_states_daily()
        lead_router.route_hot_scores()
        results["pipeline"] = {"status": "ok"}
    except Exception as exc:
        results["pipeline"] = {"status": "error", "error": str(exc)}

    elapsed = round((datetime.now() - start).total_seconds(), 1)
    return {"ok": True, "elapsed_seconds": elapsed, "results": results}
