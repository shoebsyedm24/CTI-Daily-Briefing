"""Map enriched items to MITRE ATT&CK. Validates against STIX allowlist."""
from __future__ import annotations
import json

from tools.db import connect
from tools.logging_config import get_logger
from tools.mitre_data import validate
from tools.ollama_client import chat_json
from tools.safe_prompt import build as build_prompt
from tools.state import transition

log = get_logger("mitre_map")

SYSTEM = (
    "You map cybersecurity articles to MITRE ATT&CK technique IDs.\n"
    "Use BOTH matrices: Enterprise (T1xxx) and ICS (T0xxx) when relevant.\n"
    'Output strict JSON: {"techniques": ["T1190", "T0866"], "rationale": "one line each"}.\n'
    "Cap at 5 techniques. Prefer specificity over coverage."
)


def run() -> None:
    with connect() as conn:
        # Advance low-scoring items past LLM stages without processing them
        skipped = conn.execute(
            "UPDATE items SET status='mapped', mitre_techniques='[]' WHERE status='enriched' AND triage_score < 6"
        ).rowcount
        if skipped:
            log.info(f"Skipped ATT&CK mapping for {skipped} items with score < 6")

        rows = conn.execute(
            "SELECT id, title, summary, sectors FROM items WHERE status='enriched' AND triage_score >= 6"
        ).fetchall()
        log.info(f"Mapping {len(rows)} items to ATT&CK")
        for r in rows:
            system, user = build_prompt(
                SYSTEM,
                untrusted={"title": r["title"], "summary": (r["summary"] or "")[:1500]},
                trusted={"sectors": r["sectors"]},
            )
            try:
                out = chat_json("default", user, system)
                raw_ids = out.get("techniques", [])
                valid_ids = validate(raw_ids)
                if len(valid_ids) < len(raw_ids):
                    dropped = set(raw_ids) - set(valid_ids)
                    log.warning(f"item {r['id']}: dropped hallucinated TIDs {dropped}")
                conn.execute(
                    "UPDATE items SET mitre_techniques = ? WHERE id = ?",
                    (json.dumps(valid_ids), r["id"]),
                )
                transition(conn, r["id"], "mapped")
            except Exception as e:
                log.error(f"item {r['id']}: {e}")
                try:
                    transition(conn, r["id"], "failed", error=str(e)[:300])
                except ValueError:
                    pass
