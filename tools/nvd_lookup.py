"""NVD CVE lookup — token bucket + tenacity + caching (v4: real pacing, not just backoff)."""
from __future__ import annotations
import json
import os

import httpx
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from tools.db import connect
from tools.logging_config import get_logger
from tools.rate_limit import TokenBucket

load_dotenv()
log = get_logger("nvd")
BASE = "https://services.nvd.nist.gov/rest/json/cves/2.0"

# NVD: 5 req/30s without key, 50 req/30s with key.
_BUCKET = TokenBucket(
    rate=50 if os.getenv("NVD_API_KEY") else 5,
    period=30.0,
)


class RateLimited(Exception):
    pass


@retry(
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=2, min=6, max=120),
    retry=retry_if_exception_type((RateLimited, httpx.HTTPError, httpx.TimeoutException)),
)
def _fetch(cve_id):
    _BUCKET.acquire()
    headers = {"User-Agent": "cti-briefing/4.0"}
    if os.getenv("NVD_API_KEY"):
        headers["apiKey"] = os.environ["NVD_API_KEY"]
    r = httpx.get(BASE, params={"cveId": cve_id}, headers=headers, timeout=30.0)
    if r.status_code in (429, 503):
        log.warning(f"NVD {r.status_code} for {cve_id}")
        raise RateLimited()
    r.raise_for_status()
    vulns = r.json().get("vulnerabilities", [])
    return vulns[0]["cve"] if vulns else None


def lookup(cve_id, conn):
    cached = conn.execute(
        "SELECT cvss_v3, description, refs_json FROM cves WHERE cve_id=? AND cvss_v3 IS NOT NULL",
        (cve_id,),
    ).fetchone()
    if cached:
        return {"cvss_v3": cached[0], "description": cached[1], "refs": json.loads(cached[2] or "[]")}

    cve = _fetch(cve_id)
    if not cve:
        return None
    cvss = None
    for k in ("cvssMetricV31", "cvssMetricV30"):
        m = cve.get("metrics", {}).get(k) or []
        if m:
            cvss = m[0]["cvssData"]["baseScore"]
            break
    desc = next((d["value"] for d in cve.get("descriptions", []) if d["lang"] == "en"), "")
    refs = [r["url"] for r in cve.get("references", [])]
    conn.execute(
        """INSERT INTO cves (cve_id, cvss_v3, description, refs_json)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(cve_id) DO UPDATE SET
             cvss_v3 = excluded.cvss_v3,
             description = COALESCE(excluded.description, cves.description),
             refs_json = excluded.refs_json""",
        (cve_id, cvss, desc, json.dumps(refs)),
    )
    return {"cvss_v3": cvss, "description": desc, "refs": refs}


def run() -> None:
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT cve_ids FROM items WHERE status='triaged' AND cve_ids != '[]'"
        ).fetchall()
        all_cves = set()
        for (j,) in rows:
            all_cves.update(json.loads(j))
        log.info(f"NVD hydrating {len(all_cves)} CVEs")
        for c in all_cves:
            try:
                lookup(c, conn)
            except Exception as e:
                log.error(f"NVD {c}: {e}")
