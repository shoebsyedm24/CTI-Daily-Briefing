"""LLM triage for fuzzy items (rule score 3-5, no CVEs). Injection-defended."""
from __future__ import annotations
import json

from tools.db import connect
from tools.logging_config import get_logger
from tools.ollama_client import chat_json
from tools.safe_prompt import build as build_prompt

log = get_logger("llm_triage")

SYSTEM = (
    "You are a CTI triage analyst for an energy + healthcare organization. "
    "Output strict JSON: "
    '{"score":0-10,"sectors":["energy"|"healthcare"|"general"],"rationale":"one sentence"}. '
    "Bias toward 0-3 unless the article shows direct operational relevance."
)


def run() -> None:
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, title, summary, source, triage_score, rationale
               FROM items WHERE status='triaged' AND triage_score BETWEEN 3 AND 5
                 AND (cve_ids IS NULL OR cve_ids = '[]')"""
        ).fetchall()
        log.info(f"LLM refining {len(rows)} fuzzy items")
        for r in rows:
            system, user = build_prompt(
                SYSTEM,
                untrusted={
                    "title": r["title"],
                    "summary": (r["summary"] or "")[:1500],
                },
                trusted={
                    "source": r["source"],
                    "rule_score": str(r["triage_score"]),
                },
            )
            try:
                out = chat_json("default", user, system)
                new_score = max(0, min(10, int(out.get("score", r["triage_score"]))))
                conn.execute(
                    """UPDATE items SET triage_score=?, sectors=?, score_method='rule+llm',
                       rationale = json_insert(coalesce(rationale,'[]'), '$[#]', ?)
                       WHERE id=?""",
                    (new_score, json.dumps(out.get("sectors", ["general"])),
                     f"LLM: {out.get('rationale','')}", r["id"]),
                )
            except Exception as e:
                log.error(f"item {r['id']}: {e}")
