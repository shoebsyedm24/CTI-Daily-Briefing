"""Timezone helpers — briefing day is America/Chicago. Use these everywhere."""
from __future__ import annotations
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
UTC = ZoneInfo("UTC")


def now_ct() -> datetime:
    return datetime.now(CT)


def today_ct() -> date:
    return now_ct().date()


def cutoff_utc_iso(hours_back: int) -> str:
    """UTC timestamp N hours before now-CT, in SQLite's CURRENT_TIMESTAMP format.
    Must use space separator (not T) to compare correctly with stored ingested_at values."""
    dt = (now_ct() - timedelta(hours=hours_back)).astimezone(UTC)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def is_weekend() -> bool:
    return today_ct().weekday() >= 5
