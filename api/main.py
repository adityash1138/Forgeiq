"""ForgeIQ FastAPI application — REST layer over the intelligence pipeline."""
from __future__ import annotations

from fastapi import APIRouter, FastAPI

from api.routers import auth, leads, outcomes, vendors
from db.connection import fetch_all, fetch_one

app = FastAPI(title="ForgeIQ API", version="1.0")

app.include_router(leads.router, prefix="/api/v1/leads", tags=["leads"])
app.include_router(vendors.router, prefix="/api/v1/vendors", tags=["vendors"])
app.include_router(outcomes.router, prefix="/api/v1/outcomes", tags=["outcomes"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])

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
