"""Pre-flight checks. CHECKS fail the run; WARNINGS log only."""
from __future__ import annotations
import os
import shutil
import socket
import sqlite3
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from tools.logging_config import get_logger
from tools.tz import cutoff_utc_iso

load_dotenv()
log = get_logger("health_check")
ROOT = Path(__file__).resolve().parent.parent


def _ollama() -> bool:
    try:
        return httpx.get("http://localhost:11434/api/tags", timeout=5.0).status_code == 200
    except Exception as e:
        log.warning(f"Ollama: {e}")
        return False


def _db() -> bool:
    try:
        c = sqlite3.connect(ROOT / "db" / "threats.sqlite")
        c.execute("SELECT 1").fetchone()
        c.close()
        return True
    except Exception as e:
        log.warning(f"DB: {e}")
        return False


def _internet() -> bool:
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=5)
        return True
    except OSError:
        return False


def _smtp_socket() -> bool:
    """TCP reachability only — login happens at delivery to avoid daily login attempts.
    Skipped (returns True) when SMTP_HOST is not configured."""
    if not os.getenv("SMTP_HOST"):
        log.warning("SMTP_HOST not set — skipping SMTP check (configure .env before live run)")
        return True
    try:
        with socket.create_connection(
            (os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"])), timeout=10
        ):
            return True
    except Exception as e:
        log.warning(f"SMTP socket: {e}")
        return False


def _disk() -> bool:
    return shutil.disk_usage(ROOT).free / (1024 ** 3) > 5.0


def _mitre_data() -> bool:
    ent = ROOT / "data" / "mitre_enterprise_techniques.json"
    ics = ROOT / "data" / "mitre_ics_techniques.json"
    ok = ent.exists() and ics.exists()
    if not ok:
        log.warning("MITRE allowlists missing — run: python -m tools.mitre_data download")
    return ok


def _recent_ingest() -> bool:
    """tz-aware silent-failure detector."""
    try:
        c = sqlite3.connect(ROOT / "db" / "threats.sqlite")
        row = c.execute(
            "SELECT COUNT(*) FROM items WHERE ingested_at > ?",
            (cutoff_utc_iso(24),),
        ).fetchone()
        c.close()
        if row[0] == 0:
            log.warning("No items ingested in 24h — pipeline may be silently broken")
            return False
        return True
    except Exception:
        return False


CHECKS = [
    ("Ollama",          _ollama),
    ("Database",        _db),
    ("Internet",        _internet),
    ("SMTP socket",     _smtp_socket),
    ("Disk (>5GB)",     _disk),
    ("MITRE allowlist", _mitre_data),
]

WARNINGS = [
    ("Recent ingest", _recent_ingest),
]


def run_health_check() -> bool:
    cloud_mode = os.getenv("CLOUD_MODE") == "1"
    all_ok = True
    for name, fn in CHECKS:
        if cloud_mode and name == "Ollama":
            log.info("  SKIP :: Ollama (CLOUD_MODE)")
            continue
        if cloud_mode and name == "Disk (>5GB)":
            log.info("  SKIP :: Disk (CLOUD_MODE)")
            continue
        ok = fn()
        log.info(f"  {'OK  ' if ok else 'FAIL'} :: {name}")
        if not ok:
            all_ok = False
    for name, fn in WARNINGS:
        ok = fn()
        log.info(f"  {'OK  ' if ok else 'WARN'} :: {name}")
    return all_ok


if __name__ == "__main__":
    sys.exit(0 if run_health_check() else 1)
