"""Write daily briefing as an Obsidian note with frontmatter."""
from __future__ import annotations
import os
from pathlib import Path
from datetime import date

from dotenv import load_dotenv

from tools.tz import today_ct

load_dotenv()
VAULT = Path(os.getenv("OBSIDIAN_VAULT_PATH", ""))
SUBFOLDER = os.getenv("OBSIDIAN_CTI_FOLDER", "CTI/Daily")


def write_note(markdown: str, on: date | None = None) -> Path:
    on = on or today_ct()
    dest = VAULT / SUBFOLDER
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{on.isoformat()}.md"
    fm = f"---\ndate: {on.isoformat()}\ntags: [cti, daily-briefing, energy, healthcare]\ntype: briefing\n---\n\n"
    path.write_text(fm + markdown)
    return path
