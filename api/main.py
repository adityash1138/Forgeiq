"""ForgeIQ FastAPI application — REST layer over the intelligence pipeline."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routers import admin, auth, leads, outcomes, vendors
from db.connection import fetch_all, fetch_one

app = FastAPI(title="ForgeIQ API", version="1.0")


@app.on_event("startup")
def _startup_init_db():
    """Self-initialize schema + config on a fresh database (idempotent).

    Disabled by setting FORGEIQ_AUTO_INIT=0. See db/init_db.py.
    """
    from db.init_db import maybe_init_on_startup
    maybe_init_on_startup()

_static = Path(__file__).parent.parent / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(str(_static / "index.html"))

    @app.get("/onboarding", include_in_schema=False)
    def onboarding():
        return FileResponse(str(_static / "onboarding.html"))

    @app.get("/admin", include_in_schema=False)
    def admin_console():
        return FileResponse(str(_static / "admin.html"))

    @app.get("/buyer", include_in_schema=False)
    def buyer_portal():
        return FileResponse(str(_static / "buyer.html"))

app.include_router(leads.router, prefix="/api/v1/leads", tags=["leads"])
app.include_router(vendors.router, prefix="/api/v1/vendors", tags=["vendors"])
app.include_router(outcomes.router, prefix="/api/v1/outcomes", tags=["outcomes"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])

# Webhooks (public, secured by their own secret in production).
webhooks = APIRouter()


@webhooks.post("/whatsapp")
def whatsapp_outcome(delivery_id: str, response_code: int):
    """Map a WhatsApp quick-reply code to an outcome and record it."""
    status_map = {1: "Contacted", 2: "No response",
                  3: "Lost-Competitor", 4: "Not-Relevant"}
    status = status_map.get(response_code, "No response")
    from feedback.outcome_processor import record_outcome
    record_outcome(delivery_id, status, captured_via="whatsapp")
    return {"ok": True, "recorded": status}


app.include_router(webhooks, prefix="/webhook", tags=["webhooks"])


@app.get("/api/v1/applications", tags=["meta"])
def list_applications():
    """Public: applications available for vendor onboarding (id + name)."""
    return fetch_all(
        """
        SELECT a.id, a.application_name, a.production_line_type,
               vc.category_name
        FROM applications a
        LEFT JOIN vendor_categories vc ON vc.id = a.category_id
        ORDER BY a.application_name
        """)


@app.get("/health")
def health():
    """System health + last scraper run timestamps."""
    db_ok = True
    last_runs: list[dict] = []
    try:
        fetch_one("SELECT 1 AS ok")
        last_runs = fetch_all(
            "SELECT job_name, status, MAX(finished_at) AS last_run "
            "FROM job_runs GROUP BY job_name, status "
            "ORDER BY last_run DESC LIMIT 10")
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded",
            "database": "up" if db_ok else "down",
            "recent_jobs": [
                {"job": r["job_name"], "status": r["status"],
                 "last_run": r["last_run"]} for r in last_runs]}
