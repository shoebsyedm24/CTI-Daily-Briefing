"""Tests for dedup logic — content_hash and update_hash computation."""
from tools.rss_ingest import _content_hash, _update_hash


def test_same_title_same_summary_same_hash():
    h1 = _content_hash("Title A", "Summary A")
    h2 = _content_hash("Title A", "Summary A")
    assert h1 == h2


def test_different_summary_different_content_hash():
    h1 = _content_hash("Title A", "Summary A")
    h2 = _content_hash("Title A", "Summary B")
    assert h1 != h2


def test_case_insensitive_content_hash():
    h1 = _content_hash("TITLE A", "SUMMARY A")
    h2 = _content_hash("title a", "summary a")
    assert h1 == h2


def test_update_hash_changes_on_body():
    u1 = _update_hash("Original body text")
    u2 = _update_hash("Revised body text")
    assert u1 != u2


def test_update_hash_stable():
    u1 = _update_hash("Stable body")
    u2 = _update_hash("Stable body")
    assert u1 == u2


def test_none_summary():
    h1 = _content_hash("Title", None)
    h2 = _content_hash("Title", "")
    assert h1 == h2
