"""Application tagging — which signal feeds which Company x Application score.

The most precise step in the pipeline. Each signal is tagged with one or more
application_ids from the applications table. That set determines which
Company x Application scores the signal influences.

Strategy (per the blueprint's "over-tag when ambiguous" rule):
  1. Look up keyword hints for the signal_type in SIGNAL_TO_APPLICATION_HINTS.
  2. Match hint keywords against the signal's raw_text_snippet.
  3. If no specific hint matches, tag ALL applications for the industry —
     downstream decay positioning + cascade gating ensure only the right waves
     ever fire, so over-tagging at intake is the safe default.
"""
from __future__ import annotations

from db.connection import fetch_all, get_cursor

# Keyword -> application_name_hint fragments. We resolve hints to live
# application UUIDs at runtime by matching application_name ILIKE the fragment,
# so this config never hardcodes UUIDs.
SIGNAL_TO_APPLICATION_HINTS: dict[str, dict[str, list[str]]] = {
    "CAPEX_FILING": {
        "battery": ["battery", "cell", "giga"],
        "body":    ["body", "chassis", "weld", "press"],
        "powertrain": ["motor", "powertrain", "drivetrain"],
    },
    "PLI_APPROVAL": {
        "battery": ["acc", "battery", "cell"],
        "auto":    ["auto", "component", "vehicle"],
    },
    "JOB_POSTING": {
        "battery": ["battery", "cell", "pack assembly"],
        "automation": ["automation", "plc", "robot"],
        "production": ["production manager", "plant head"],
    },
    "ICEGATE_IMPORT": {
        "battery": ["lithium", "cell", "battery"],
        "automation": ["machine", "robot", "automation"],
    },
    "LAND_ACQUISITION": {},   # always over-tag — location signals are non-specific
    "EC_CLEARANCE": {},
}


def _industry_application_ids(industry_id: str) -> list[str]:
    """All application UUIDs belonging to an industry (via category join)."""
    rows = fetch_all(
        """
        SELECT a.id
        FROM applications a
        JOIN vendor_categories vc ON vc.id = a.category_id
        WHERE vc.industry_id = %s
        """,
        (industry_id,),
    )
    return [str(r["id"]) for r in rows]


def _applications_matching(industry_id: str, fragments: list[str]) -> list[str]:
    """Application UUIDs whose name matches any fragment (case-insensitive)."""
    if not fragments:
        return []
    clauses = " OR ".join(["a.application_name ILIKE %s"] * len(fragments))
    params = [industry_id] + [f"%{f}%" for f in fragments]
    rows = fetch_all(
        f"""
        SELECT DISTINCT a.id
        FROM applications a
        JOIN vendor_categories vc ON vc.id = a.category_id
        WHERE vc.industry_id = %s AND ({clauses})
        """,
        tuple(params),
    )
    return [str(r["id"]) for r in rows]


def compute_tags(signal_type: str, snippet: str, industry_id: str) -> list[str]:
    """Return the list of application UUIDs this signal should tag."""
    hints = SIGNAL_TO_APPLICATION_HINTS.get(signal_type, {})
    low = (snippet or "").lower()

    matched: set[str] = set()
    for _line, keywords in hints.items():
        if any(kw in low for kw in keywords):
            # Use the matched keywords as name fragments to find real app IDs.
            matched.update(_applications_matching(industry_id, keywords))

    if matched:
        return sorted(matched)

    # Ambiguous or no hints — over-tag every application for the industry.
    return _industry_application_ids(industry_id)


def tag_signal(signal_row_id: str) -> list[str]:
    """Compute and persist application_tags for a single raw_signals row."""
    rows = fetch_all(
        "SELECT signal_type, raw_text_snippet, industry_id "
        "FROM raw_signals WHERE id = %s",
        (signal_row_id,),
    )
    if not rows:
        return []
    sig = rows[0]
    tags = compute_tags(sig["signal_type"], sig["raw_text_snippet"],
                        str(sig["industry_id"]))
    with get_cursor() as cur:
        cur.execute(
            "UPDATE raw_signals SET application_tags = %s::uuid[] WHERE id = %s",
            (tags, signal_row_id),
        )
    return tags


def tag_new_signals() -> int:
    """Pipeline entry: tag every signal that has no application_tags yet."""
    rows = fetch_all(
        "SELECT id FROM raw_signals "
        "WHERE application_tags IS NULL OR cardinality(application_tags) = 0"
    )
    for r in rows:
        tag_signal(str(r["id"]))
    print(f"app_tagger: tagged {len(rows)} signals.")
    return len(rows)


if __name__ == "__main__":
    # Offline: verify hint matching logic without a DB by stubbing the lookups.
    import processing.app_tagger as m

    m._applications_matching = lambda ind, frags: [f"app-{frags[0]}"] if frags else []
    m._industry_application_ids = lambda ind: ["app-all-1", "app-all-2"]

    specific = m.compute_tags("CAPEX_FILING", "new giga battery cell plant", "ind1")
    ambiguous = m.compute_tags("CAPEX_FILING", "new manufacturing facility", "ind1")
    print(f"specific (battery snippet): {specific}")
    print(f"ambiguous (no specifics):   {ambiguous}")
    assert specific and specific != ["app-all-1", "app-all-2"]
    assert ambiguous == ["app-all-1", "app-all-2"]
    print("OK: specific snippet narrows tags; ambiguous over-tags all apps.")
