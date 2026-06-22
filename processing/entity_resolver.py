"""Entity resolution — structured matching + Claude API fallback + queue.

Two-stage resolution of a signal's raw_company_name to a row in `companies`:

  Stage 1 (free, instant): structured_match()
     CIN -> legal_name -> alias -> fuzzy (difflib >= 0.85)

  Stage 2 (paid, ambiguous only): llm_match()
     Claude API, invoked ONLY when structured matching scores < 70%.
     The prompt forces evidence-based reasoning (investment amount, sector,
     location, timeframe) and forbids training-knowledge guessing about
     abbreviations — the documented failure mode.

Confidence routes the signal to a resolution tier:
     >= 95  Tier A  (auto-link, create company if new)
     >= 70  Tier B  (auto-link)
     >= 40  Tier C  (queue with best guess)
     <  40  Tier D  (queue, no guess)

The entity_resolution_queue runs a 14-day lifecycle: re-attempt as new signals
arrive, flag for human review when confidence is rising but unresolved, archive
(never delete) after 14 days.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from difflib import SequenceMatcher

from db.connection import fetch_all, fetch_one, get_cursor

FUZZY_THRESHOLD = 0.85
CIN_RE = re.compile(r"\b([LUu]\d{5}[A-Za-z]{2}\d{4}[A-Za-z]{3}\d{6})\b")
CLAUDE_MODEL = "claude-sonnet-4-6"


# ===========================================================================
# Stage 1 — structured matching
# ===========================================================================
def _normalise(name: str) -> str:
    """Lowercase, strip common suffixes/punctuation for comparison."""
    n = (name or "").lower()
    n = re.sub(r"[.,&]", " ", n)
    for suffix in (" private limited", " pvt ltd", " pvt. ltd.", " limited",
                   " ltd", " llp", " inc", " corporation", " corp"):
        n = n.replace(suffix, " ")
    return re.sub(r"\s+", " ", n).strip()


def structured_match(raw_name: str, snippet: str = "") -> tuple[str | None, int]:
    """Return (company_id, confidence_pct) or (None, 0)."""
    # Stage 1: exact CIN match if a CIN appears in the snippet.
    cin_hit = CIN_RE.search(snippet or "")
    if cin_hit:
        row = fetch_one("SELECT id FROM companies WHERE cin = %s",
                        (cin_hit.group(1).upper(),))
        if row:
            return str(row["id"]), 100

    norm_raw = _normalise(raw_name)
    if not norm_raw:
        return None, 0

    # Stage 2: exact legal_name match (case-insensitive, suffix-normalised).
    candidates = fetch_all(
        "SELECT id, legal_name, known_aliases FROM companies")
    for c in candidates:
        if _normalise(c["legal_name"]) == norm_raw:
            return str(c["id"]), 98

    # Stage 3: alias match against known_aliases array.
    for c in candidates:
        for alias in (c["known_aliases"] or []):
            if _normalise(alias) == norm_raw:
                return str(c["id"]), 92

    # Stage 4: fuzzy match (difflib SequenceMatcher >= 0.85).
    best_id, best_ratio = None, 0.0
    for c in candidates:
        ratio = SequenceMatcher(None, norm_raw, _normalise(c["legal_name"])).ratio()
        if ratio > best_ratio:
            best_id, best_ratio = str(c["id"]), ratio
    if best_ratio >= FUZZY_THRESHOLD:
        return best_id, int(best_ratio * 100)

    return None, 0


# ===========================================================================
# Stage 2 — Claude API fallback (ambiguous cases only)
# ===========================================================================
def _get_candidates(limit: int = 25) -> list[dict]:
    return fetch_all(
        "SELECT id, legal_name, known_aliases, plant_location, industry_id "
        "FROM companies LIMIT %s", (limit,))


def llm_match(raw_name: str, snippet: str,
              candidates: list[dict]) -> tuple[str | None, int]:
    """Call Claude for ambiguous cases. Returns (company_id, confidence_pct)."""
    if not os.environ.get("ANTHROPIC_API_KEY") or not candidates:
        return None, 0

    try:
        import anthropic
    except ImportError:
        return None, 0

    candidate_lines = [
        {"company_id": str(c["id"]), "legal_name": c["legal_name"],
         "aliases": c["known_aliases"] or [], "location": c["plant_location"]}
        for c in candidates
    ]
    prompt = f"""Company reference found in a signal: "{raw_name}"
Context from the signal: "{snippet}"
Candidate companies in our database (JSON): {json.dumps(candidate_lines)}

Are any of these candidates the same legal entity as the reference?

You MUST justify your answer using ONLY the evidence in the context above
(investment amount, sector, location, timeframe). DO NOT use your training
knowledge of company names or what abbreviations might mean. If the context
does not contain enough evidence to be confident, return company_id null with
low confidence.

Return ONLY JSON: {{"company_id": "<id or null>", "confidence": <0-100>,
"reasoning": "<evidence-based justification>"}}"""

    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        data = json.loads(text)
    except Exception as exc:
        print(f"entity_resolver.llm_match: Claude call failed: {exc}")
        return None, 0

    cid = data.get("company_id")
    conf = int(data.get("confidence", 0) or 0)
    if not cid or str(cid).lower() == "null":
        return None, conf
    return str(cid), conf


# ===========================================================================
# Routing + persistence
# ===========================================================================
def _update_signal(signal_id: str, company_id: str | None,
                   conf: int, tier: str) -> None:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE raw_signals SET resolved_company_id = %s, "
            "entity_confidence_pct = %s, resolution_tier = %s WHERE id = %s",
            (company_id, conf, tier, signal_id),
        )


def _enqueue(signal_id: str, raw_name: str,
             best_guess: str | None, conf: int) -> None:
    with get_cursor() as cur:
        cur.execute(
            "INSERT INTO entity_resolution_queue "
            "(signal_id, raw_company_name, best_guess_company_id, confidence_pct) "
            "VALUES (%s, %s, %s, %s)",
            (signal_id, raw_name, best_guess, conf),
        )


def _route_and_persist(signal_id: str, raw_name: str,
                       company_id: str | None, conf: int) -> str:
    """Apply tier routing and persist. Returns the resolution tier letter."""
    if company_id and conf >= 95:
        _update_signal(signal_id, company_id, conf, "A")
        _trigger_score_recalc(company_id)
        return "A"
    if company_id and conf >= 70:
        _update_signal(signal_id, company_id, conf, "B")
        _trigger_score_recalc(company_id)
        return "B"
    if company_id and conf >= 40:
        _update_signal(signal_id, None, conf, "C")
        _enqueue(signal_id, raw_name, company_id, conf)
        return "C"
    _update_signal(signal_id, None, conf, "D")
    _enqueue(signal_id, raw_name, None, conf)
    return "D"


def _trigger_score_recalc(company_id: str) -> None:
    """Recalculate scores once a signal resolves to a company (Tier A/B)."""
    try:
        from engine.scoring_engine import recalculate_company
        recalculate_company(company_id)
    except Exception:
        pass  # daily scoring pass is the safety net


def resolve(signal_id: str, raw_name: str, snippet: str) -> str:
    """Full two-stage resolution for one signal. Returns the tier letter."""
    comp_id, conf = structured_match(raw_name, snippet)
    if conf >= 70:
        return _route_and_persist(signal_id, raw_name, comp_id, conf)

    # Structured matching was weak — escalate to Claude.
    comp_id, conf = llm_match(raw_name, snippet, _get_candidates())
    return _route_and_persist(signal_id, raw_name, comp_id, conf)


def resolve_signal(signal_row_id: str) -> str:
    """Entry point called by BaseScraper after a signal is written."""
    row = fetch_one(
        "SELECT raw_company_name, raw_text_snippet FROM raw_signals WHERE id = %s",
        (signal_row_id,))
    if not row:
        return "D"
    return resolve(signal_row_id, row["raw_company_name"] or "",
                   row["raw_text_snippet"] or "")


def resolve_new_signals() -> int:
    """Pipeline entry: resolve every signal still missing a tier."""
    rows = fetch_all(
        "SELECT id FROM raw_signals WHERE resolution_tier IS NULL")
    for r in rows:
        resolve_signal(str(r["id"]))
    print(f"entity_resolver: resolved {len(rows)} new signals.")
    return len(rows)


# ===========================================================================
# Queue lifecycle — 14-day
# ===========================================================================
def process_queue_daily() -> None:
    """Run once per day after all scrapers complete."""
    items = fetch_all(
        "SELECT * FROM entity_resolution_queue WHERE status = 'Active'")
    for item in items:
        days = (item["days_in_queue"] or 0) + 1
        item_id = str(item["id"])

        # Re-attempt with any new evidence for this probable entity.
        new_conf = _reattempt(item)
        if new_conf >= 70 and item["best_guess_company_id"]:
            _promote(item, new_conf)
            continue

        notes = None
        # Human-review flag: confidence rising but still unresolved after 7 days.
        if days >= 7 and new_conf > (item["confidence_pct"] or 0):
            notes = "FLAG_HUMAN_REVIEW: confidence rising, not yet resolved"

        if days >= 14:
            _archive(item_id)
            continue

        with get_cursor() as cur:
            cur.execute(
                "UPDATE entity_resolution_queue SET days_in_queue = %s, "
                "confidence_pct = %s, last_reattempt_at = %s, "
                "resolution_notes = COALESCE(%s, resolution_notes) WHERE id = %s",
                (days, max(new_conf, item["confidence_pct"] or 0),
                 datetime.now(), notes, item_id),
            )


def _reattempt(item: dict) -> int:
    """Re-run structured matching, now possibly with more companies in the DB."""
    _cid, conf = structured_match(item["raw_company_name"] or "")
    return conf


def _promote(item: dict, conf: int) -> None:
    """Promote a queued item to Tier B and link its signal."""
    _update_signal(str(item["signal_id"]),
                   str(item["best_guess_company_id"]), conf, "B")
    _trigger_score_recalc(str(item["best_guess_company_id"]))
    with get_cursor() as cur:
        cur.execute(
            "UPDATE entity_resolution_queue SET status = 'Resolved', "
            "confidence_pct = %s, resolution_notes = 'Promoted to Tier B' "
            "WHERE id = %s", (conf, str(item["id"])))


def _archive(item_id: str) -> None:
    """Archive (never delete) after 14 days."""
    with get_cursor() as cur:
        cur.execute(
            "UPDATE entity_resolution_queue SET status = 'Archived', "
            "resolution_notes = 'Archived after 14 days unresolved' WHERE id = %s",
            (item_id,))


if __name__ == "__main__":
    # Offline: verify normalisation, CIN extraction, and fuzzy ratio without DB.
    assert _normalise("Tata Motors Limited") == "tata motors"
    assert _normalise("Tata Motors Ltd.") == "tata motors"
    cin = CIN_RE.search("incorporated as U34100HR2013PLC123456 in Haryana")
    assert cin and cin.group(1) == "U34100HR2013PLC123456"
    ratio = SequenceMatcher(None, _normalise("Ola Electric"),
                            _normalise("Ola Electric Mobility Ltd")).ratio()
    print(f"normalise OK; CIN extracted {cin.group(1)}; "
          f"Ola fuzzy ratio={ratio:.2f}")
    print("OK: entity resolver primitives work.")
