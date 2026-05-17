"""Tests for supersession and duplicate tracking in rss_ingest."""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((ROOT / "db" / "schema.sql").read_text())
    return conn


from tools.rss_ingest import _upsert, _content_hash, _update_hash


def _item(url, title, summary):
    return {"url": url, "source": "Test Feed", "title": title, "summary": summary,
            "published_at": "2024-12-01T00:00:00+00:00", "raw": b""}


def test_new_item_inserted():
    conn = _make_conn()
    result = _upsert(conn, _item("https://a.test/1", "Title A", "Summary A"))
    assert result == "new"
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1


def test_dup_url_same_body_skipped():
    conn = _make_conn()
    it = _item("https://a.test/1", "Title A", "Summary A")
    _upsert(conn, it)
    result = _upsert(conn, it)
    assert result == "dup_url"
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1


def test_supersession_same_url_different_body():
    conn = _make_conn()
    _upsert(conn, _item("https://a.test/1", "Title A", "Summary A"))
    result = _upsert(conn, _item("https://a.test/1", "Title A", "Summary A REVISED"))
    assert result == "superseded"
    rows = conn.execute("SELECT id, status, superseded_by FROM items").fetchall()
    assert len(rows) == 2
    old = next(r for r in rows if r["status"] == "superseded")
    new = next(r for r in rows if r["status"] == "new")
    assert old["superseded_by"] == new["id"]


def test_dup_hash_different_url():
    conn = _make_conn()
    _upsert(conn, _item("https://a.test/1", "Title A", "Summary A"))
    result = _upsert(conn, _item("https://b.test/2", "Title A", "Summary A"))
    assert result == "dup_hash"
    rows = conn.execute("SELECT id, duplicate_of_item_id FROM items").fetchall()
    assert len(rows) == 2
    dup = next(r for r in rows if r["duplicate_of_item_id"] is not None)
    assert dup["duplicate_of_item_id"] is not None


def test_two_distinct_items():
    conn = _make_conn()
    _upsert(conn, _item("https://a.test/1", "Title A", "Summary A"))
    _upsert(conn, _item("https://b.test/2", "Title B", "Summary B"))
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2
