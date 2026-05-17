"""Offline fixtures for pipeline testing. Idempotent."""
from __future__ import annotations
import hashlib
import json

from tools.db import connect
from tools.extract_cves import extract as extract_cves

SAMPLE_ITEMS = [
    {
        "url": "https://example.test/article-1",
        "source": "The Hacker News",
        "title": "Critical RCE in Siemens SIMATIC PLC — actively exploited",
        "summary": ("Siemens disclosed CVE-2024-12345 in SIMATIC S7 PLC firmware. "
                    "Exploitation observed in the wild against energy operators. "
                    "Modbus/TCP-facing devices most at risk. CVSS 9.8."),
        "published_at": "2024-12-01T08:00:00+00:00",
    },
    {
        "url": "https://example.test/article-2",
        "source": "BleepingComputer",
        "title": "Ransomware hits regional hospital chain — EHR offline",
        "summary": ("US hospital network reported ransomware incident impacting "
                    "Epic EHR access and PACS imaging. HHS HC3 alert pending. "
                    "Class II/III medical devices on same VLAN under review."),
        "published_at": "2024-12-01T09:30:00+00:00",
    },
    {
        "url": "https://example.test/article-3",
        "source": "CISA KEV",
        "title": "CVE-2024-99999: Fortinet FortiManager authentication bypass",
        "summary": ("Pre-authentication RCE in FortiManager. Internet-facing "
                    "instances should be patched immediately. Added to KEV."),
        "published_at": "2024-12-01T07:00:00+00:00",
    },
]


def _hashes(title: str, summary: str | None):
    ch = hashlib.sha256(
        (title.strip().lower() + "|" + (summary or "").strip().lower()[:500]).encode()
    ).hexdigest()
    uh = hashlib.sha256((summary or "").strip().lower().encode()).hexdigest()
    return ch, uh


def load_sample() -> int:
    n = 0
    with connect() as conn:
        # Pre-populate CVE table so scorer has KEV/CVSS data
        conn.execute(
            """INSERT OR REPLACE INTO cves
               (cve_id, cvss_v3, epss, in_kev, kev_added_date, description)
               VALUES ('CVE-2024-99999', 9.8, 0.9, 1, '2024-12-01',
                       'Fortinet FortiManager auth bypass')"""
        )
        conn.execute(
            """INSERT OR REPLACE INTO cves
               (cve_id, cvss_v3, epss, in_kev, description)
               VALUES ('CVE-2024-12345', 9.8, 0.7, 0, 'Siemens SIMATIC RCE')"""
        )
        for it in SAMPLE_ITEMS:
            ch, uh = _hashes(it["title"], it["summary"])
            cves = json.dumps(extract_cves(f"{it['title']} {it['summary']}"))
            # Skip if already present
            if conn.execute("SELECT 1 FROM items WHERE content_hash = ?", (ch,)).fetchone():
                continue
            conn.execute(
                """INSERT INTO items (url, content_hash, update_hash, source,
                   title, summary, published_at, cve_ids, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new')""",
                (it["url"], ch, uh, it["source"], it["title"],
                 it["summary"], it["published_at"], cves),
            )
            n += 1
    print(f"Inserted {n} sample items")
    return n


if __name__ == "__main__":
    load_sample()
