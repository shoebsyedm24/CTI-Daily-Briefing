"""Rule-based scoring + in-place re-scoring (v4: no status change on rescore)."""
from __future__ import annotations
import json
import re
from pathlib import Path

import yaml

from tools.db import connect
from tools.logging_config import get_logger
from tools.state import transition

log = get_logger("score")
ROOT = Path(__file__).resolve().parent.parent
_CRED_BASE = {"high": 3, "medium": 1, "low": 0}


def _kev_set(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT cve_id FROM cves WHERE in_kev=1")}


def _cve_data(conn, cve_ids):
    if not cve_ids:
        return {}
    qm = ",".join("?" * len(cve_ids))
    rows = conn.execute(
        f"SELECT cve_id, cvss_v3, epss, in_kev FROM cves WHERE cve_id IN ({qm})",
        cve_ids,
    ).fetchall()
    return {r[0]: {"cvss_v3": r[1], "epss": r[2], "in_kev": r[3]} for r in rows}


def _overrides(conn, item) -> tuple[int, str | None]:
    rows = conn.execute("SELECT pattern, action, value FROM overrides").fetchall()
    haystack = f"{item['source']} | {item['title']}".lower()
    for pat, action, value in rows:
        try:
            hit = bool(re.search(pat, haystack, re.IGNORECASE))
        except re.error:
            hit = pat.lower() in haystack
        if hit:
            if action == "suppress":      return -100, "suppress"
            if action == "force_include": return 10, "force_include"
            if action == "boost_score":   return value or 0, "boost"
    return 0, None


def _exploitation_bonus(text: str, kw: dict) -> tuple[int, list[str]]:
    rationale = []
    score = 0
    high = [k for k in kw["exploitation_high"] if k in text]
    mid  = [k for k in kw["exploitation_mid"]  if k in text]
    low  = [k for k in kw["exploitation_low"]  if k in text]
    if high:
        score += 3; rationale.append(f"active exploit ({high[0]}): +3")
    elif mid:
        score += 2; rationale.append(f"exploit signal ({mid[0]}): +2")
    elif low:
        score += 1; rationale.append(f"exploit keyword ({low[0]}): +1")
    return score, rationale


def score_item(item, feeds_cfg, conn) -> dict:
    text = f"{item['title']} {item.get('summary') or ''}".lower()
    score, rationale, sectors = 0, [], set()
    feed_meta = next((f for f in feeds_cfg["feeds"] if f["name"] == item["source"]), {})

    base = _CRED_BASE.get(feed_meta.get("credibility", "medium"), 1)
    score += base; rationale.append(f"credibility: +{base}")

    cves = item.get("cve_ids", [])
    if any(c in _kev_set(conn) for c in cves):
        score += 5; rationale.append("KEV match: +5")

    cd = _cve_data(conn, cves)
    epss_max = max((cd[c]["epss"] or 0 for c in cd), default=0.0)
    if epss_max > 0.5:
        score += 2; rationale.append(f"EPSS {epss_max:.2f}: +2")
    elif epss_max > 0.1:
        score += 1; rationale.append(f"EPSS {epss_max:.2f}: +1")
    cvss_max = max((cd[c]["cvss_v3"] or 0 for c in cd), default=0.0)
    if cvss_max >= 9.0:
        score += 2; rationale.append(f"CVSS {cvss_max}: +2")
    elif cvss_max >= 7.0:
        score += 1; rationale.append(f"CVSS {cvss_max}: +1")

    exp_score, exp_rat = _exploitation_bonus(text, feeds_cfg["keywords"])
    score += exp_score
    rationale.extend(exp_rat)

    ot_hits = [k for k in feeds_cfg["keywords"]["ot"] if k in text]
    if ot_hits:
        score += 2; sectors.add("energy"); rationale.append(f"OT kw {ot_hits[:3]}: +2")

    hc_hits = [k for k in feeds_cfg["keywords"]["healthcare"] if k in text]
    if hc_hits:
        score += 2; sectors.add("healthcare"); rationale.append(f"HC kw {hc_hits[:3]}: +2")

    inv = feeds_cfg["asset_inventory"]
    matched_energy = [v for v in inv["energy_ot_vendors"] if v.lower() in text]
    matched_health = [v for v in inv["healthcare_vendors"] if v.lower() in text]
    matched_it     = [v for v in inv["it_stack"] if v.lower() in text]
    all_matched    = matched_energy + matched_health + matched_it
    if all_matched:
        score += 2; rationale.append(f"vendor {all_matched[:2]}: +2")
        if matched_energy: sectors.add("energy")
        if matched_health: sectors.add("healthcare")
        if matched_it:
            sectors.add("energy"); sectors.add("healthcare")  # IT stack = universal

    boost = feed_meta.get("priority_boost", 0)
    if boost:
        score += boost; rationale.append(f"feed boost: +{boost}")

    wl = [k for k in (feed_meta.get("keyword_whitelist") or []) if k.lower() in text]
    if wl:
        score += 2; rationale.append(f"feed whitelist {wl[:2]}: +2")

    if feed_meta.get("sector") in ("energy", "healthcare"):
        sectors.add(feed_meta["sector"])

    delta, action = _overrides(conn, item)
    if action:
        score += delta; rationale.append(f"override {action}: {delta:+}")

    score = min(10, max(0, score))
    if not sectors:
        sectors.add("general")
    return {"score": score, "sectors": sorted(sectors),
            "score_method": "rule", "rationale": rationale,
            "suppressed": action == "suppress"}


def run() -> None:
    """Score newly ingested items (status='new'). Transitions to triaged."""
    feeds = yaml.safe_load(open(ROOT / "feeds.yaml"))
    n = 0
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, title, summary, source, cve_ids FROM items WHERE status='new'"
        ).fetchall()
        for r in rows:
            item = dict(r)
            item["cve_ids"] = json.loads(item["cve_ids"] or "[]")
            result = score_item(item, feeds, conn)
            conn.execute(
                "UPDATE items SET triage_score=?, sectors=?, score_method=?, rationale=? WHERE id=?",
                (result["score"], json.dumps(result["sectors"]),
                 result["score_method"], json.dumps(result["rationale"]), r["id"]),
            )
            try:
                transition(conn, r["id"], "archived" if result["suppressed"] else "triaged")
                n += 1
            except ValueError as e:
                log.warning(f"item {r['id']}: {e}")
    log.info(f"Scored {n} new items → triaged")


def run_rescore() -> None:
    """Re-score enriched items IN PLACE. Status stays 'enriched' (v4 fix).
    Picks up new KEV/CVSS/EPSS data that wasn't available the first pass."""
    feeds = yaml.safe_load(open(ROOT / "feeds.yaml"))
    n = 0
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, title, summary, source, cve_ids FROM items WHERE status='enriched'"
        ).fetchall()
        for r in rows:
            item = dict(r)
            item["cve_ids"] = json.loads(item["cve_ids"] or "[]")
            result = score_item(item, feeds, conn)
            if result["suppressed"]:
                try:
                    transition(conn, r["id"], "archived")
                except ValueError:
                    pass
                continue
            conn.execute(
                """UPDATE items SET triage_score=?, sectors=?, score_method='rule+enriched',
                   rationale=? WHERE id=?""",
                (result["score"], json.dumps(result["sectors"]),
                 json.dumps(result["rationale"]), r["id"]),
            )
            n += 1
    log.info(f"Re-scored {n} enriched items (status unchanged)")


if __name__ == "__main__":
    run()
