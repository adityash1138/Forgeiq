"""AI Copilot — Claude tool-calling over the ForgeIQ data model.

Design (the part the audit said was never specified):

  • Data access: a fixed set of read-only tools that query scores, signals,
    companies, and the vendor's own delivered leads — never raw SQL from the
    model, so it can only see what these tools expose.
  • Scoping: lead tools are filtered to the authenticated vendor. Company /
    signal intelligence is shared (that's the product), but contact PII is not
    returned by Copilot tools.
  • System prompt: pins the assistant to ForgeIQ's domain, tells it to answer
    only from tool results, and to say so when it lacks data — no hallucinated
    company facts (the same discipline as the entity resolver).
  • Fallback: if ANTHROPIC_API_KEY is unset, a deterministic intent handler
    answers the common questions from the same tools, so the feature works in
    every environment and degrades gracefully.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_current_vendor
from db.connection import fetch_all, fetch_one

router = APIRouter()

COPILOT_MODEL = "claude-sonnet-4-6"
MAX_TOOL_TURNS = 6


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


# ── tools (read-only, the only data the model can reach) ────────────────────
def tool_list_my_leads(vendor: dict, status: Optional[str] = None) -> list[dict]:
    clauses = ["ld.vendor_id = %s"]
    params: list = [vendor["id"]]
    if status:
        clauses.append("s.status = %s"); params.append(status.upper())
    return fetch_all(
        f"""
        SELECT c.legal_name AS company, a.application_name AS application,
               s.current_score AS score, s.status, c.plant_location AS location
        FROM lead_delivery ld JOIN scores s ON s.id = ld.score_id
        JOIN companies c ON c.id = s.company_id
        LEFT JOIN applications a ON a.id = s.application_id
        WHERE {' AND '.join(clauses)}
        ORDER BY s.current_score DESC LIMIT 50
        """, tuple(params))


def tool_find_company(vendor: dict, name: str) -> dict:
    co = fetch_one(
        "SELECT id, legal_name, cin, plant_location, negative_flag "
        "FROM companies WHERE legal_name ILIKE %s LIMIT 1", (f"%{name}%",))
    if not co:
        return {"found": False, "message": f"No company matching '{name}'."}
    scores = fetch_all(
        "SELECT a.application_name AS application, s.current_score AS score, "
        "s.status FROM scores s LEFT JOIN applications a ON a.id = s.application_id "
        "WHERE s.company_id = %s ORDER BY s.current_score DESC", (co["id"],))
    signals = fetch_all(
        "SELECT signal_type, date_detected, source FROM raw_signals "
        "WHERE resolved_company_id = %s ORDER BY date_detected DESC LIMIT 10",
        (co["id"],))
    return {"found": True, "company": co["legal_name"], "cin": co["cin"],
            "location": co["plant_location"],
            "negative_flag": co["negative_flag"] if co["negative_flag"] != "None" else None,
            "scores": scores, "recent_signals": signals}


def tool_sector_overview(vendor: dict) -> dict:
    stats = fetch_one(
        "SELECT COUNT(*) AS companies, "
        "COUNT(*) FILTER (WHERE status='HOT') AS hot, "
        "ROUND(AVG(current_score),1) AS avg_score FROM scores") or {}
    hot = fetch_all(
        "SELECT c.legal_name AS company, a.application_name AS application, "
        "s.current_score AS score FROM scores s JOIN companies c ON c.id=s.company_id "
        "LEFT JOIN applications a ON a.id=s.application_id WHERE s.status='HOT' "
        "ORDER BY s.current_score DESC LIMIT 10")
    return {"companies_tracked": stats.get("companies"),
            "hot_companies": stats.get("hot"),
            "avg_score": float(stats.get("avg_score") or 0),
            "top_hot": hot}


TOOL_DEFS = [
    {"name": "list_my_leads",
     "description": "List leads delivered to the current vendor, optionally "
                    "filtered by status (HOT/WARM/COLD). Use for 'my leads'.",
     "input_schema": {"type": "object", "properties": {
         "status": {"type": "string", "enum": ["HOT", "WARM", "COLD"]}}}},
    {"name": "find_company",
     "description": "Look up a company by name: its scores per application, "
                    "recent buying signals, and any negative flag.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"}}, "required": ["name"]}},
    {"name": "sector_overview",
     "description": "High-level sector stats: companies tracked, how many are "
                    "HOT, average score, and the top hot companies.",
     "input_schema": {"type": "object", "properties": {}}},
]

TOOL_FNS = {"list_my_leads": tool_list_my_leads, "find_company": tool_find_company,
            "sector_overview": tool_sector_overview}

SYSTEM_PROMPT = (
    "You are the ForgeIQ Copilot, an assistant for B2B equipment vendors using "
    "ForgeIQ, a purchase-intent lead-intelligence platform for the Indian EV / "
    "manufacturing sector. ForgeIQ scores companies 0-100 on expansion intent "
    "(HOT>=70, WARM>=40, COLD<40) from buying signals like CAPEX filings, PLI "
    "approvals, land acquisitions and imports. "
    "Answer ONLY from the data returned by your tools. If the tools do not "
    "contain the answer, say so plainly — never invent company facts, scores, "
    "or signals. Be concise and specific, cite scores and signal types. Do not "
    "reveal contact personal data. When the user asks about 'my leads', use the "
    "list_my_leads tool (already scoped to them).")


def _exec_tool(name: str, args: dict, vendor: dict):
    fn = TOOL_FNS.get(name)
    if not fn:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(vendor, **args)
    except Exception as exc:  # never crash the chat on a tool error
        return {"error": str(exc)}


# ── deterministic fallback (no API key) ─────────────────────────────────────
def _fallback(message: str, vendor: dict) -> str:
    m = message.lower()
    if any(w in m for w in ("my lead", "my hot", "delivered", "leads do i")):
        status = "HOT" if "hot" in m else "WARM" if "warm" in m else None
        leads = tool_list_my_leads(vendor, status)
        if not leads:
            return "You have no leads matching that yet."
        lines = [f"• {l['company']} — {l['application']} — {round(l['score'])} ({l['status']})"
                 for l in leads[:10]]
        return f"You have {len(leads)} lead(s):\n" + "\n".join(lines)
    if "sector" in m or "overview" in m or "how many" in m:
        o = tool_sector_overview(vendor)
        top = ", ".join(f"{h['company']} ({round(h['score'])})" for h in o["top_hot"][:5])
        return (f"Sector: {o['companies_tracked']} companies tracked, "
                f"{o['hot_companies']} HOT, avg score {o['avg_score']}. "
                f"Top hot: {top}.")
    # try treating the message as a company name (strip filler words first)
    filler = {"tell", "me", "about", "what", "is", "the", "score", "for", "show",
              "who", "how", "of", "a", "on", "give", "details", "company", "info"}
    query = " ".join(w for w in message.split() if w.lower().strip("?.,") not in filler)
    if query.strip():
        res = tool_find_company(vendor, query.strip())
        if res.get("found"):
            sc = ", ".join(f"{s['application']}: {round(s['score'])} ({s['status']})"
                           for s in res["scores"])
            flag = f" ⚠ {res['negative_flag']}" if res.get("negative_flag") else ""
            return (f"{res['company']} ({res.get('location') or '—'}){flag}. "
                    f"Scores — {sc or 'none yet'}. "
                    f"{len(res['recent_signals'])} recent signal(s).")
    return ("Copilot is in limited mode (no ANTHROPIC_API_KEY set). I can still "
            "answer: 'show my hot leads', 'sector overview', or a company name "
            "like 'Ather Energy'. Set the API key to enable full conversational AI.")


# ── endpoint ────────────────────────────────────────────────────────────────
@router.post("/chat")
def chat(body: ChatRequest, vendor: dict = Depends(get_current_vendor)):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"reply": _fallback(body.message, vendor), "mode": "fallback"}
    try:
        import anthropic
    except ImportError:
        return {"reply": _fallback(body.message, vendor), "mode": "fallback"}

    client = anthropic.Anthropic()
    messages = [{"role": m.role, "content": m.content} for m in body.history]
    messages.append({"role": "user", "content": body.message})

    used_tools: list[str] = []
    for _ in range(MAX_TOOL_TURNS):
        resp = client.messages.create(
            model=COPILOT_MODEL, max_tokens=1024, system=SYSTEM_PROMPT,
            tools=TOOL_DEFS, messages=messages)
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text")
            return {"reply": text, "mode": "ai", "tools_used": used_tools}
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                used_tools.append(block.name)
                out = _exec_tool(block.name, block.input or {}, vendor)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(out, default=str)})
        messages.append({"role": "user", "content": results})

    return {"reply": "I couldn't complete that — too many steps. Try rephrasing.",
            "mode": "ai", "tools_used": used_tools}
