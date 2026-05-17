"""Generate RAG-grounded mitigation blocks. Confidence-scored."""
from __future__ import annotations
import json
import os

from tools.db import connect
from tools.logging_config import get_logger
from tools.ollama_client import chat_json
from tools.rag import index_notes, query as rag_query
from tools.safe_prompt import build as build_prompt
from tools.state import transition

log = get_logger("mitigation_author")

SYSTEM = (
    "You are a cybersecurity remediation engineer for an energy + healthcare organization. "
    "Using the provided environment context chunks, write actionable mitigation steps. "
    "Output strict JSON:\n"
    "{\n"
    '  "detection": "...",\n'
    '  "containment": "...",\n'
    '  "patch": "...",\n'
    '  "servicenow": "...",\n'
    '  "verification": "...",\n'
    '  "confidence": 0.0-1.0,\n'
    '  "grounded_chunks": ["path/to/chunk.md#section"]\n'
    "}\n"
    "confidence = 1.0 if every section cites a chunk; 0.5 partial; 0.2 generic. "
    "For healthcare CVEs on Class II/III devices, include: "
    "'Verify vendor-validated patch status before deployment to maintain FDA compliance.' "
    "For energy CVEs on BES Cyber Assets, include: "
    "'Route through CIP-010 change management; do not field-patch without TFE outside maintenance window.'"
)

_DEVICE_KEYWORDS = ["class ii", "class iii", "medical device", "fda cleared", "fda approved"]
_BES_KEYWORDS = ["bes cyber asset", "nerc cip", "substation", "ied", "rtu"]


def _is_medical_device(item) -> bool:
    text = f"{item['title']} {item.get('summary') or ''} {item.get('sector_context') or ''}".lower()
    return any(k in text for k in _DEVICE_KEYWORDS)


def _is_bes_asset(item) -> bool:
    text = f"{item['title']} {item.get('summary') or ''} {item.get('sector_context') or ''}".lower()
    return any(k in text for k in _BES_KEYWORDS)


def run() -> None:
    # Re-index env_notes on every run (skips unchanged files)
    try:
        index_notes()
    except Exception as e:
        log.warning(f"RAG index failed: {e}")

    with connect() as conn:
        skipped = conn.execute(
            "UPDATE items SET status='mitigated' WHERE status='contextualized' AND triage_score < 6"
        ).rowcount
        if skipped:
            log.info(f"Skipped mitigation authoring for {skipped} items with score < 6")

        rows = conn.execute(
            """SELECT id, title, summary, sectors, mitre_techniques, sector_context, cve_ids
               FROM items WHERE status='contextualized' AND triage_score >= 6"""
        ).fetchall()
        log.info(f"Authoring mitigations for {len(rows)} items")
        for r in rows:
            item = dict(r)
            # Build RAG query from title + sector context
            rag_text = f"{r['title']} {r['sector_context'] or ''}"
            try:
                chunks = rag_query(rag_text, n_results=4)
            except Exception as e:
                log.warning(f"RAG query failed for item {r['id']}: {e}")
                chunks = []

            chunk_text = "\n\n".join(
                f"[{c['path']}]\n{c['text'][:800]}" for c in chunks
            ) if chunks else "No environment context available."

            system, user = build_prompt(
                SYSTEM,
                untrusted={
                    "title": r["title"],
                    "summary": (r["summary"] or "")[:1000],
                    "sector_context": r["sector_context"] or "",
                },
                trusted={
                    "sectors": r["sectors"] or "[]",
                    "techniques": r["mitre_techniques"] or "[]",
                    "environment_context": chunk_text,
                },
            )
            try:
                out = chat_json("composer", user, system)
                confidence = float(out.get("confidence", 0.2))

                # Build mitigation block text
                sections = []
                for key, label in [
                    ("detection", "Detection"),
                    ("containment", "Containment"),
                    ("patch", "Patch"),
                    ("servicenow", "ServiceNow VR"),
                    ("verification", "Verification"),
                ]:
                    val = out.get(key, "")
                    if val:
                        sections.append(f"**{label}:** {val}")

                mitigation_block = "\n".join(sections)

                conn.execute(
                    """UPDATE items SET mitigation_block=?, mitigation_confidence=?
                       WHERE id=?""",
                    (mitigation_block, confidence, r["id"]),
                )
                transition(conn, r["id"], "mitigated")
            except Exception as e:
                log.error(f"item {r['id']}: {e}")
                try:
                    transition(conn, r["id"], "failed", error=str(e)[:300])
                except ValueError:
                    pass
