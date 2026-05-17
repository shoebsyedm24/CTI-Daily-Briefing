"""Push score≥9 items immediately. Gated on alerted_at to prevent re-fires.
Filters dupes/superseded so a noisy event doesn't spam."""
from __future__ import annotations
import os

import httpx

from tools.db import connect
from tools.logging_config import get_logger

log = get_logger("alert")


def run() -> None:
    if not (os.getenv("ALERT_WEBHOOK_URL") or os.getenv("ALERT_EMAIL")):
        return
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, title, source, url, triage_score
               FROM items
               WHERE status IN ('mitigated', 'composed')
                 AND briefing_date IS NULL
                 AND triage_score >= 9
                 AND alerted_at IS NULL
                 AND duplicate_of_item_id IS NULL
                 AND superseded_by IS NULL"""
        ).fetchall()
        for r in rows:
            msg = f"🚨 [CTI {r['triage_score']}/10] {r['title']}\n{r['source']}\n{r['url']}"
            sent = False
            if os.getenv("ALERT_WEBHOOK_URL"):
                try:
                    httpx.post(os.environ["ALERT_WEBHOOK_URL"],
                               json={"text": msg}, timeout=10).raise_for_status()
                    sent = True
                except Exception as e:
                    log.error(f"webhook for item {r['id']}: {e}")
            if sent:
                conn.execute(
                    "UPDATE items SET alerted_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (r["id"],),
                )
