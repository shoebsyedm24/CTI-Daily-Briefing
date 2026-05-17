from tools.ollama_client import _extract_json
import pytest


def test_plain():
    assert _extract_json('{"score": 7}') == {"score": 7}


def test_fenced():
    assert _extract_json('```json\n{"score": 7}\n```') == {"score": 7}


def test_fenced_no_lang():
    assert _extract_json('```\n{"score": 7}\n```') == {"score": 7}


def test_with_preface():
    assert _extract_json('Sure, here it is: {"score": 7, "notes": "ok"}') == {"score": 7, "notes": "ok"}


def test_nested():
    assert _extract_json('{"a": {"b": 1}}') == {"a": {"b": 1}}


def test_empty_raises():
    with pytest.raises(ValueError):
        _extract_json("")


def test_unparseable_raises():
    with pytest.raises(ValueError):
        _extract_json("this is not json at all")
