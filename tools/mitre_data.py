"""MITRE ATT&CK STIX bundles + technique validation. Iterates all external_references."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

import httpx

DATA = Path(__file__).resolve().parent.parent / "data"
ENTERPRISE_URL = "https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json"
ICS_URL = "https://raw.githubusercontent.com/mitre/cti/master/ics-attack/ics-attack.json"


def _extract_tids(bundle: dict) -> list[str]:
    """Walk all external_references — mitre-attack ref may not be position 0."""
    out: list[str] = []
    for obj in bundle.get("objects", []):
        if obj.get("type") != "attack-pattern":
            continue
        for ref in obj.get("external_references", []):
            if ref.get("source_name") == "mitre-attack" and ref.get("external_id"):
                out.append(ref["external_id"])
                break   # one TID per pattern; stop after the first mitre-attack ref
    return sorted(set(out))


def download() -> None:
    DATA.mkdir(exist_ok=True)
    for name, url in [("enterprise", ENTERPRISE_URL), ("ics", ICS_URL)]:
        print(f"Fetching {name} ATT&CK ...", file=sys.stderr)
        r = httpx.get(url, timeout=120.0)
        r.raise_for_status()
        ids = _extract_tids(r.json())
        (DATA / f"mitre_{name}_techniques.json").write_text(json.dumps(ids))
        print(f"  → {len(ids)} techniques in {name}", file=sys.stderr)


_cached: set[str] | None = None


def allowlist() -> set[str]:
    global _cached
    if _cached is None:
        ent = json.loads((DATA / "mitre_enterprise_techniques.json").read_text())
        ics = json.loads((DATA / "mitre_ics_techniques.json").read_text())
        _cached = set(ent) | set(ics)
    return _cached


_TID = re.compile(r"\bT\d{4}(?:\.\d{3})?\b")


def validate(ids: list[str]) -> list[str]:
    """Drop IDs not in the allowlist (hallucinations)."""
    allowed = allowlist()
    return [tid for tid in ids if tid in allowed]


def extract_and_validate(text: str) -> list[str]:
    return validate(list(set(_TID.findall(text))))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "download":
        download()
    else:
        print(f"{len(allowlist())} techniques loaded")
