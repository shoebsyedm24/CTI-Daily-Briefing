"""Refresh CISA KEV cache. Tenacity-backed."""
from __future__ import annotations
from datetime import datetime, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from tools.db import connect
from tools.logging_config import get_logger

log = get_logger("kev")
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"


@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=2, max=30))
def _fetch():
    r = httpx.get(KEV_URL, headers={"User-Agent": "cti-briefing/4.0"}, timeout=30.0)
    r.raise_for_status()
    return r.json()


def refresh() -> int:
    data = _fetch()
    n = 0
    with connect() as conn:
        for v in data.get("vulnerabilities", []):
            conn.execute(
                """INSERT INTO cves (cve_id, in_kev, kev_added_date, description, fetched_at)
                   VALUES (?, 1, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(cve_id) DO UPDATE SET
                     in_kev = 1,
                     kev_added_date = excluded.kev_added_date,
                     description = COALESCE(cves.description, excluded.description)""",
                (v["cveID"], v.get("dateAdded"), v.get("shortDescription", "")),
            )
            n += 1
    log.info(f"KEV refreshed: {n} entries at {datetime.now(timezone.utc)}")
    return n


run = refresh
