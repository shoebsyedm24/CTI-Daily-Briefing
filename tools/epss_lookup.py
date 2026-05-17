"""EPSS lookup with UPSERT (works even if NVD failed for that CVE)."""
from __future__ import annotations
import json

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from tools.db import connect
from tools.logging_config import get_logger
from tools.state import bulk_transition

log = get_logger("epss")


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=30))
def _batch(cves):
    if not cves:
        return {}
    r = httpx.get(f"https://api.first.org/data/v1/epss?cve={','.join(cves)}",
                  timeout=20.0, headers={"User-Agent": "cti-briefing/4.0"})
    r.raise_for_status()
    return {d["cve"]: float(d["epss"]) for d in r.json().get("data", [])}


def run() -> None:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT cve_ids FROM items WHERE status='triaged' AND cve_ids != '[]'"
        ).fetchall()
        pool = list({c for (j,) in rows for c in json.loads(j)})
        log.info(f"EPSS hydrating {len(pool)} CVEs")
        for i in range(0, len(pool), 50):
            try:
                for cve, epss in _batch(pool[i:i + 50]).items():
                    conn.execute(
                        """INSERT INTO cves (cve_id, epss, epss_fetched_at)
                           VALUES (?, ?, CURRENT_TIMESTAMP)
                           ON CONFLICT(cve_id) DO UPDATE SET
                             epss = excluded.epss,
                             epss_fetched_at = excluded.epss_fetched_at""",
                        (cve, epss),
                    )
            except Exception as e:
                log.error(f"EPSS batch: {e}")
        # Triaged → enriched means "enrichment stage completed", whether or not CVE
        # work happened. Items without CVEs pass through; that's intentional.
        n = bulk_transition(conn, "triaged", "enriched")
        log.info(f"{n} items triaged → enriched")
