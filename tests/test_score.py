"""Tests for rule-based scoring. Uses an in-memory SQLite DB."""
import json
import sqlite3
import pytest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    schema = (ROOT / "db" / "schema.sql").read_text()
    conn.executescript(schema)
    return conn


def _feeds():
    import yaml
    return yaml.safe_load(open(ROOT / "feeds.yaml"))


def _item(title="", summary="", source="BleepingComputer", cve_ids=None):
    return {"id": 1, "title": title, "summary": summary,
            "source": source, "cve_ids": cve_ids or []}


from tools.score import score_item


def test_credibility_high():
    conn = _make_conn()
    feeds = _feeds()
    result = score_item(_item(source="Krebs on Security"), feeds, conn)
    assert result["score"] >= 3  # high credibility = +3 base


def test_credibility_medium():
    conn = _make_conn()
    feeds = _feeds()
    result = score_item(_item(source="BleepingComputer"), feeds, conn)
    assert result["score"] >= 1  # medium = +1 base


def test_kev_boost():
    conn = _make_conn()
    conn.execute("INSERT INTO cves (cve_id, in_kev) VALUES ('CVE-2024-9999', 1)")
    conn.commit()
    feeds = _feeds()
    result = score_item(_item(title="CVE-2024-9999 vuln", cve_ids=["CVE-2024-9999"]), feeds, conn)
    assert result["score"] >= 6  # medium(1) + KEV(5)


def test_active_exploitation():
    conn = _make_conn()
    feeds = _feeds()
    result = score_item(
        _item(title="actively exploited bug", summary="exploited in the wild"),
        feeds, conn
    )
    assert result["score"] >= 4


def test_ot_keyword_adds_energy_sector():
    conn = _make_conn()
    feeds = _feeds()
    result = score_item(_item(summary="scada plc modbus affected"), feeds, conn)
    assert "energy" in result["sectors"]


def test_healthcare_keyword():
    conn = _make_conn()
    feeds = _feeds()
    result = score_item(_item(summary="epic ehr hipaa fhir vulnerability"), feeds, conn)
    assert "healthcare" in result["sectors"]


def test_it_stack_universal_sectors():
    conn = _make_conn()
    feeds = _feeds()
    result = score_item(_item(summary="microsoft active directory critical bug"), feeds, conn)
    assert "energy" in result["sectors"]
    assert "healthcare" in result["sectors"]


def test_suppressed_item():
    conn = _make_conn()
    conn.execute("INSERT INTO overrides (pattern, action) VALUES ('(?i)test corp', 'suppress')")
    conn.commit()
    feeds = _feeds()
    result = score_item(_item(title="test corp breach"), feeds, conn)
    assert result["suppressed"] is True


def test_score_capped_at_10():
    conn = _make_conn()
    conn.execute("INSERT INTO cves (cve_id, in_kev, cvss_v3, epss) VALUES ('CVE-2024-1', 1, 10.0, 0.99)")
    conn.commit()
    feeds = _feeds()
    result = score_item(
        _item(title="actively exploited scada epic ransomware CVE-2024-1",
              summary="exploited in the wild modbus hipaa",
              source="CISA ICS Advisories",
              cve_ids=["CVE-2024-1"]),
        feeds, conn
    )
    assert result["score"] <= 10


def test_score_not_negative():
    conn = _make_conn()
    feeds = _feeds()
    result = score_item(_item(source="Cyber Security News"), feeds, conn)
    assert result["score"] >= 0
