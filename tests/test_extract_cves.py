from tools.extract_cves import extract


def test_extracts_basic():
    assert extract("CVE-2024-1234 and cve-2024-99999") == ["CVE-2024-1234", "CVE-2024-99999"]


def test_dedup():
    assert extract("CVE-2024-1234 CVE-2024-1234") == ["CVE-2024-1234"]


def test_no_partial():
    assert extract("CVE-202-1234") == []
    assert extract("CVE-2024-1") == []


def test_empty():
    assert extract("") == []
    assert extract("no CVEs here") == []


def test_seven_digit():
    assert extract("CVE-2024-1234567") == ["CVE-2024-1234567"]


def test_preserves_order():
    result = extract("CVE-2024-9999 and CVE-2024-1111")
    assert result == ["CVE-2024-9999", "CVE-2024-1111"]
