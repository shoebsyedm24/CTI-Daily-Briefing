"""Commit and push daily briefing via SSH git."""
from __future__ import annotations
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def commit_briefing(md_path: Path) -> str:
    subprocess.run(["git", "remote", "set-url", "origin", os.environ["GIT_REMOTE_SSH"]],
                   cwd=ROOT, check=True)
    subprocess.run(["git", "add", str(md_path)], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", f"briefing: {md_path.stem}"], cwd=ROOT, check=True)
    subprocess.run(["git", "push"], cwd=ROOT, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
