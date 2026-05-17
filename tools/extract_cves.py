"""Extract CVE IDs via regex. No LLM."""
from __future__ import annotations
import re

_CVE = re.compile(r"\bCVE-(\d{4})-(\d{4,7})\b", re.IGNORECASE)


def extract(text: str) -> list[str]:
    if not text:
        return []
    seen: list[str] = []
    for m in _CVE.finditer(text):
        cve = f"CVE-{m.group(1)}-{m.group(2)}"
        if cve not in seen:
            seen.append(cve)
    return seen
