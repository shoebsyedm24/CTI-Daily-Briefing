"""Centralized SQLite access — short-lived connections, retry-on-locked."""
from __future__ import annotations
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "db" / "threats.sqlite"


@contextmanager
def connect(retry: int = 5):
    """Yield a connection; commit on success, rollback on exception, close always.
    Retries on 'database is locked' with exponential backoff. Keep connections
    SHORT-LIVED — open at the start of a unit of work, close at the end."""
    last_err: Exception | None = None
    for attempt in range(retry):
        try:
            conn = sqlite3.connect(DB, timeout=20.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
                conn.commit()
                return
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            last_err = e
            if "locked" in str(e) and attempt < retry - 1:
                time.sleep(0.5 * (2 ** attempt))
                continue
            raise
    if last_err:
        raise last_err
