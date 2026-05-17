"""Ingest feeds with supersession + duplicate tracking + User-Agent + raw_blob."""
from __future__ import annotations
import argparse
import hashlib
import json
import zlib
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import httpx
import yaml

from tools.db import connect
from tools.extract_cves import extract as extract_cves
from tools.logging_config import get_logger

log = get_logger("ingest")
ROOT = Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (Macintosh; cti-briefing) Safari/605"


def _content_hash(title: str, summary: str | None) -> str:
    norm = (title.strip().lower() + "|" + (summary or "").strip().lower()[:500])
    return hashlib.sha256(norm.encode()).hexdigest()


def _update_hash(summary: str | None) -> str:
    """Body-only hash — detects advisory revisions when title stays stable."""
    return hashlib.sha256((summary or "").strip().lower().encode()).hexdigest()


def _compress(entry) -> bytes:
    raw = json.dumps({k: str(v)[:5000] for k, v in entry.items() if k != "summary_detail"})
    return zlib.compress(raw.encode())[:50_000]


def _parse_date(entry):
    for k in ("published", "updated"):
        if entry.get(f"{k}_parsed"):
            try:
                return datetime(*entry[f"{k}_parsed"][:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    return None


def _fetch(url):
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=30.0, follow_redirects=True)
    r.raise_for_status()
    return r


def _parse_rss(cfg):
    parsed = feedparser.parse(_fetch(cfg["url"]).content)
    return [{
        "url": e.get("link"), "source": cfg["name"],
        "title": (e.get("title") or "").strip(),
        "summary": (e.get("summary") or "")[:4000],
        "published_at": _parse_date(e),
        "raw": _compress(e),
    } for e in parsed.entries[:50]]


def _parse_kev(cfg):
    out = []
    for v in _fetch(cfg["url"]).json().get("vulnerabilities", [])[-50:]:
        cve = v["cveID"]
        out.append({
            "url": f"https://nvd.nist.gov/vuln/detail/{cve}",
            "source": "CISA KEV",
            "title": f"{cve}: {v.get('vulnerabilityName', '')}",
            "summary": v.get("shortDescription", ""),
            "published_at": v.get("dateAdded"),
            "raw": zlib.compress(json.dumps(v).encode())[:50_000],
        })
    return out


def _parse_nvd(cfg):
    out = []
    for v in _fetch(cfg["url"]).json().get("vulnerabilities", []):
        cid = v["cve"]["id"]
        desc = next((d["value"] for d in v["cve"]["descriptions"] if d["lang"] == "en"), "")
        out.append({
            "url": f"https://nvd.nist.gov/vuln/detail/{cid}",
            "source": "NVD", "title": cid, "summary": desc[:4000],
            "published_at": v["cve"].get("published"),
            "raw": zlib.compress(json.dumps(v).encode())[:50_000],
        })
    return out


PARSERS = {"rss": _parse_rss, "json_kev": _parse_kev, "nvd_api": _parse_nvd}


def _insert(conn, item, ch: str, uh: str, cves: str, duplicate_of: int | None) -> int:
    cur = conn.execute(
        """INSERT INTO items (url, content_hash, update_hash, source, title, summary,
                              raw_blob, published_at, cve_ids, status,
                              duplicate_of_item_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)""",
        (item["url"], ch, uh, item["source"], item["title"], item.get("summary"),
         item.get("raw"), item.get("published_at"), cves, duplicate_of),
    )
    return cur.lastrowid


def _upsert(conn, item) -> str:
    """Returns one of: 'new', 'dup_url', 'dup_hash', 'superseded'."""
    title = item["title"]
    summary = item.get("summary")
    ch = _content_hash(title, summary)
    uh = _update_hash(summary)
    cves = json.dumps(extract_cves(f"{title} {summary or ''}"))

    # 1. URL match? (same article, possibly revised)
    row = conn.execute(
        """SELECT id, update_hash FROM items
           WHERE url = ? AND superseded_by IS NULL AND duplicate_of_item_id IS NULL""",
        (item["url"],),
    ).fetchone()
    if row:
        if row["update_hash"] == uh:
            return "dup_url"
        # Body changed — advisory revision. Insert new row, supersede old.
        new_id = _insert(conn, item, ch, uh, cves, duplicate_of=None)
        conn.execute(
            "UPDATE items SET superseded_by = ?, status = 'superseded' WHERE id = ?",
            (new_id, row["id"]),
        )
        return "superseded"

    # 2. Content hash match? (same story, different source — keep for diversity)
    row = conn.execute(
        """SELECT id FROM items
           WHERE content_hash = ? AND superseded_by IS NULL
             AND duplicate_of_item_id IS NULL
           LIMIT 1""",
        (ch,),
    ).fetchone()
    if row:
        _insert(conn, item, ch, uh, cves, duplicate_of=row["id"])
        return "dup_hash"

    # 3. Brand new
    _insert(conn, item, ch, uh, cves, duplicate_of=None)
    return "new"


def run(dry_run: bool = False) -> None:
    cfg = yaml.safe_load(open(ROOT / "feeds.yaml"))
    counts = {"new": 0, "dup_url": 0, "dup_hash": 0, "superseded": 0}
    with connect() as conn:
        for feed in cfg["feeds"]:
            parser = PARSERS.get(feed.get("type", "rss"))
            if not parser:
                log.info(f"skip type={feed.get('type')} ({feed['name']})")
                continue
            try:
                items = parser(feed)
            except Exception as e:
                log.warning(f"{feed['name']}: {e}")
                continue
            for it in items:
                if not it.get("url"):
                    continue
                if dry_run:
                    log.info(f"[dry] {feed['name']} | {it['title'][:80]}")
                    continue
                counts[_upsert(conn, it)] += 1
    log.info(f"Ingest: {counts}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(args.dry_run)


if __name__ == "__main__":
    main()
