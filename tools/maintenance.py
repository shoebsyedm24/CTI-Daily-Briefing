"""Weekly hygiene: archive old items, drop raw_blob, WAL checkpoint, VACUUM."""
from __future__ import annotations
from datetime import date

from tools.db import connect
from tools.logging_config import get_logger

log = get_logger("maintenance")


def run():
    if date.today().weekday() != 4:
        return  # Fridays only
    with connect() as conn:
        conn.execute("""UPDATE items SET status='archived', raw_blob=NULL
                        WHERE status IN ('briefed','composed','superseded')
                          AND briefing_date < date('now','-30 days')""")
        conn.execute("UPDATE items SET raw_blob=NULL WHERE ingested_at < datetime('now','-7 days')")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    log.info("Maintenance complete")
