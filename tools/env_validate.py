"""Fail-fast .env validator. Run as `python -m tools.env_validate` or import."""
from __future__ import annotations
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REQUIRED = ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO",
            "OBSIDIAN_VAULT_PATH", "GIT_REMOTE_SSH"]

# Not required when CLOUD_MODE=1 (Obsidian write goes to /tmp; git handled by Actions)
_CLOUD_OPTIONAL = {"OBSIDIAN_VAULT_PATH", "GIT_REMOTE_SSH"}


def validate(strict: bool = True) -> list[str]:
    load_dotenv()
    errs: list[str] = []
    cloud_mode = os.getenv("CLOUD_MODE") == "1"

    required = [v for v in REQUIRED if not (cloud_mode and v in _CLOUD_OPTIONAL)]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        errs.append(f"required env vars missing: {missing}")

    vault = os.getenv("OBSIDIAN_VAULT_PATH")
    if vault and not cloud_mode and not Path(vault).exists():
        errs.append(f"OBSIDIAN_VAULT_PATH does not exist: {vault}")

    ssh = os.getenv("GIT_REMOTE_SSH", "")
    if ssh and not cloud_mode and not (ssh.startswith("git@") and ":" in ssh):
        errs.append(f"GIT_REMOTE_SSH should be SSH format (git@host:user/repo.git), got: {ssh}")

    port = os.getenv("SMTP_PORT", "")
    if port and not port.isdigit():
        errs.append(f"SMTP_PORT must be numeric, got: {port}")

    if errs and strict:
        for e in errs:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    return errs


if __name__ == "__main__":
    validate(strict=True)
    print("env OK")
