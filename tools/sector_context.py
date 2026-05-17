"""Add sector-specific operational context to mapped items."""
from __future__ import annotations
import json

from tools.db import connect
from tools.logging_config import get_logger
from tools.ollama_client import chat_json
from tools.safe_prompt import build as build_prompt
from tools.state import transition

log = get_logger("sector_context")

SYSTEM = (
    "You are a CTI analyst specializing in energy OT and healthcare IT/OT security. "
    "Given a threat article and its sector(s), write 2-4 sentences of operational context "
    "explaining the specific risk to that sector. Focus on operational impact, not generic advice. "
    'Output strict JSON: {"context": "operational context text here"}.'
)


def run() -> None:
    with connect() as conn:
        skipped = conn.execute(
            "UPDATE items SET status='contextualized' WHERE status='mapped' AND triage_score < 6"
        ).rowcount
        if skipped:
            log.info(f"Skipped sector context for {skipped} items with score < 6")

        rows = conn.execute(
            "SELECT id, title, summary, sectors, mitre_techniques FROM items WHERE status='mapped' AND triage_score >= 6"
        ).fetchall()
        log.info(f"Adding sector context to {len(rows)} items")
        for r in rows:
            sectors = json.loads(r["sectors"] or "[]")
            techniques = json.loads(r["mitre_techniques"] or "[]")
            system, user = build_prompt(
                SYSTEM,
                untrusted={
                    "title": r["title"],
                    "summary": (r["summary"] or "")[:1500],
                },
                trusted={
                    "sectors": ", ".join(sectors),
                    "techniques": ", ".join(techniques),
                },
            )
            try:
                out = chat_json("security", user, system)
                context = out.get("context", "")
                conn.execute(
                    "UPDATE items SET sector_context = ? WHERE id = ?",
                    (context, r["id"]),
                )
                transition(conn, r["id"], "contextualized")
            except Exception as e:
                log.error(f"item {r['id']}: {e}")
                try:
                    transition(conn, r["id"], "failed", error=str(e)[:300])
                except ValueError:
                    pass
