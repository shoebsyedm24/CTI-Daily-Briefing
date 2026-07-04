"""Compose the daily briefing — clustering + in_kev join + tz-aware + bounded lookback.

Guaranteed-daily behavior: the primary query keeps the score>=6 relevance bar. If
nothing clears it (a quiet threat day), a fallback surfaces the day's top items by
score so a briefing — and therefore an email — still goes out every run.
"""
from __future__ import annotations
import json
from pathlib import Path

from jinja2 import Template

from tools.cluster import cluster as cluster_items
from tools.db import connect
from tools.logging_config import get_logger
from tools.state import bulk_transition_by_ids
from tools.tz import today_ct, cutoff_utc_iso

log = get_logger("composer")
ROOT = Path(__file__).resolve().parent.parent

_SELECT_COLS = """
SELECT i.id, i.url, i.source, i.title, i.summary, i.triage_score, i.sectors,
       i.cve_ids, i.mitre_techniques, i.sector_context, i.mitigation_block,
       i.mitigation_confidence, i.rationale, i.published_at, i.ingested_at,
       EXISTS(
           SELECT 1 FROM json_each(i.cve_ids) je
           JOIN cves c ON c.cve_id = je.value
           WHERE c.in_kev = 1
       ) AS in_kev
FROM items i
WHERE i.briefing_date IS NULL
  AND i.status = 'mitigated'
  AND i.duplicate_of_item_id IS NULL
  AND i.superseded_by IS NULL
"""

SELECT_SQL = _SELECT_COLS + """
  AND i.triage_score >= 6
  AND (
        (i.triage_score >= 8 AND i.ingested_at >= ?)
        OR i.ingested_at >= ?
      )
ORDER BY i.triage_score DESC, i.ingested_at DESC
LIMIT 24
"""

FALLBACK_SQL = _SELECT_COLS + """
  AND i.ingested_at >= ?
ORDER BY i.triage_score DESC, i.ingested_at DESC
LIMIT 24
"""

TEMPLATE = Template("""# CTI Daily Briefing — {{ d }}

**Items kept (post-clustering):** {{ items|length }}
{% if low_signal %}**Note:** quiet threat day — nothing cleared the score-6 relevance bar, so this shows the day's top items by score.
{% endif %}**Sectors today:** {{ sectors|join(", ") }}

---

{% for it in items %}
## {{ loop.index }}. {{ it.title }}
**Source:** {{ it.source }} - **Score:** {{ it.score }}/10 - **Sectors:** {{ it.sectors|join(", ") }}
**CVEs:** {{ it.cves|join(", ") or "-" }}{% if it.in_kev %} - **CISA KEV**{% endif %}
**ATT&CK:** {{ it.attack|join(", ") or "-" }}
**Mitigation confidence:** {{ "%.0f"|format((it.confidence or 0)*100) }}%{% if (it.confidence or 0) < 0.5 %} generic{% endif %}
**Published:** {{ it.when }}

{{ it.summary }}

### Sector context
{{ it.sector_context }}

### Mitigation
{{ it.mitigation_block }}

[Source]({{ it.url }})
{% if it.related %}
**Related coverage:**
{% for r in it.related %}- [{{ r.source }}]({{ r.url }}) - {{ r.title }}
{% endfor %}{% endif %}

---
{% endfor %}

_Generated locally. Reply with `FP <#>` or `TP <#>` to tune tomorrow's triage._
""")

FALLBACK_HOURS = 30


def run():
    with connect() as conn:
        rows = conn.execute(
            SELECT_SQL,
            (cutoff_utc_iso(72), cutoff_utc_iso(24)),
        ).fetchall()

        low_signal = False
        if not rows:
            rows = conn.execute(FALLBACK_SQL, (cutoff_utc_iso(FALLBACK_HOURS),)).fetchall()
            low_signal = True
            if rows:
                log.info(
                    f"No items cleared score>=6 - fallback surfacing top "
                    f"{min(len(rows), 8)} of the last {FALLBACK_HOURS}h"
                )

        if not rows:
            log.info("No fresh items at all - skipping briefing")
            return None

        raw = []
        for r in rows:
            raw.append({
                "id": r["id"], "url": r["url"], "source": r["source"],
                "title": r["title"], "summary": r["summary"],
                "score": r["triage_score"],
                "sectors": json.loads(r["sectors"] or "[]"),
                "cves": json.loads(r["cve_ids"] or "[]"),
                "in_kev": bool(r["in_kev"]),
                "attack": json.loads(r["mitre_techniques"] or "[]"),
                "sector_context": r["sector_context"] or "",
                "mitigation_block": r["mitigation_block"] or "",
                "confidence": r["mitigation_confidence"],
                "when": (r["published_at"] or r["ingested_at"])[:10],
            })

        clustered = cluster_items(raw, threshold=0.85)
        items = clustered[:8]
        log.info(f"Composer: {len(raw)} candidates -> {len(clustered)} clusters -> top {len(items)}")

        sectors = set()
        for it in items:
            sectors.update(it["sectors"])

        today = today_ct()
        md = TEMPLATE.render(
            d=today.isoformat(), items=items, sectors=sorted(sectors),
            low_signal=low_signal,
        )
        out_path = ROOT / "briefings" / f"{today.isoformat()}.md"
        out_path.parent.mkdir(exist_ok=True)
        out_path.write_text(md)

        primary_ids = [int(it["id"]) for it in items]
        cluster_member_ids = []
        for it in items:
            for r in it.get("related", []):
                row = conn.execute("SELECT id FROM items WHERE url = ? LIMIT 1", (r["url"],)).fetchone()
                if row:
                    cluster_member_ids.append(row["id"])

        all_ids = primary_ids + cluster_member_ids
        if all_ids:
            placeholders = ",".join("?" * len(all_ids))
            conn.execute(
                f"UPDATE items SET briefing_date = ? WHERE id IN ({placeholders})",
                (today.isoformat(), *all_ids),
            )

        bulk_transition_by_ids(conn, primary_ids, "composed")

        conn.execute(
            "INSERT OR REPLACE INTO briefings (date, item_count, markdown_path) VALUES (?, ?, ?)",
            (today.isoformat(), len(items), str(out_path)),
        )
        log.info(f"Briefing written: {out_path}")
        return out_path
