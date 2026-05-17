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
    """ISO timestamp in UTC, N hours before now-CT. Use as SQL parameter."""
    return (now_ct() - timedelta(hours=hours_back)).astimezone(UTC).isoformat()


def is_weekend() -> bool:
    return today_ct().weekday() >= 5
