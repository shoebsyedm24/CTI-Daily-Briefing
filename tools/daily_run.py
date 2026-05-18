"""Orchestrator (v4): no outer DB connection, stage criticality, per-channel delivery."""
from __future__ import annotations
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from tools.db import connect
from tools.env_validate import validate as env_validate
from tools.health_check import run_health_check
from tools.logging_config import get_logger
from tools.state import bulk_transition_by_ids
from tools.tz import today_ct, is_weekend
from tools import (rss_ingest, kev_check, score, nvd_lookup, epss_lookup,
                   llm_triage, mitre_map, sector_context, mitigation_author,
                   alert_immediate, composer, obsidian_write, github_commit,
                   send_email, maintenance, ollama_client)

log = get_logger("daily_run")
ROOT = Path(__file__).resolve().parent.parent

STAGES = [
    ("kev_refresh",     kev_check.refresh,             False),
    ("ingest",          rss_ingest.run,                True),
    ("score_rules",     score.run,                     True),
    ("nvd_enrich",      nvd_lookup.run,                False),
    ("epss_enrich",     epss_lookup.run,               False),
    ("score_rules_2",   score.run_rescore,             False),
    ("llm_triage",      llm_triage.run,                False),
    ("mitre_map",       mitre_map.run,                 False),
    ("sector_context",  sector_context.run,            False),
    ("mitigate",        mitigation_author.run,         False),
    ("alert_immediate", alert_immediate.run,           False),
    ("compose",         composer.run,                  True),
    ("deliver",         lambda args: _deliver(args),   True),
    ("unload_models",   ollama_client.unload,          False),
    ("maintenance",     maintenance.run,               False),
]


def _deliver(args):
    """Per-channel idempotent delivery. Email/Obsidian/git each tracked separately."""
    today = today_ct().isoformat()
    with connect() as conn:
        row = conn.execute(
            """SELECT markdown_path, email_sent_at, obsidian_written_at, git_committed_at
               FROM briefings WHERE date = ?""", (today,)
        ).fetchone()
        if not row:
            log.info("No briefing for today — skipping delivery")
            return
        md_path = Path(row["markdown_path"])
        if not md_path.exists():
            # Stored path may have a different root (e.g., seeded from another machine)
            md_path = ROOT / "briefings" / md_path.name
        md = md_path.read_text()

        if not row["email_sent_at"] and not args.no_email:
            send_email.send(md)
            conn.execute("UPDATE briefings SET email_sent_at=CURRENT_TIMESTAMP WHERE date=?", (today,))
            log.info("email: sent")
        else:
            log.info(f"email: skipped (sent_at={row['email_sent_at']}, --no-email={args.no_email})")

        if not row["obsidian_written_at"]:
            obsidian_write.write_note(md)
            conn.execute("UPDATE briefings SET obsidian_written_at=CURRENT_TIMESTAMP WHERE date=?", (today,))
            log.info("obsidian: written")

        if not row["git_committed_at"] and not args.no_git:
            sha = github_commit.commit_briefing(md_path)
            conn.execute(
                "UPDATE briefings SET git_committed_at=CURRENT_TIMESTAMP, git_sha=? WHERE date=?",
                (sha, today),
            )
            log.info(f"git: committed {sha[:8]}")

        # Mark composed items as briefed once all required channels completed.
        row2 = conn.execute(
            "SELECT email_sent_at, obsidian_written_at, git_committed_at FROM briefings WHERE date=?",
            (today,),
        ).fetchone()
        email_done = row2["email_sent_at"] or args.no_email
        git_done = row2["git_committed_at"] or args.no_git
        obs_done = row2["obsidian_written_at"]
        if email_done and obs_done and git_done:
            composed_ids = [r["id"] for r in conn.execute(
                "SELECT id FROM items WHERE briefing_date=? AND status='composed'",
                (today,),
            ).fetchall()]
            bulk_transition_by_ids(conn, composed_ids, "briefed")
            log.info(f"{len(composed_ids)} items → briefed")


def _log_stage(stage, t0, ok, err=None):
    """Short-lived connection per log write — no outer transaction held across stages."""
    with connect() as conn:
        conn.execute(
            """INSERT INTO run_log (run_date, stage, started_at, finished_at, status, error)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?)""",
            (today_ct().isoformat(), stage,
             datetime.fromtimestamp(t0).isoformat(),
             "ok" if ok else "fail", err),
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--from", dest="from_stage")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-weekend", action="store_true")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--no-git",   action="store_true")
    ap.add_argument("--no-llm",   action="store_true")
    args = ap.parse_args()

    if args.skip_weekend and is_weekend():
        log.info("Weekend — skipping")
        return 0

    log.info(f"=== Daily run @ {datetime.now().isoformat()} ===")
    if env_validate(strict=False):
        log.error("env_validate failed — aborting")
        return 1
    if not run_health_check():
        log.error("Health check failed — aborting")
        return 1

    llm_stages = {"llm_triage", "mitre_map", "sector_context", "mitigate"}
    stages = STAGES
    if args.only:
        stages = [s for s in STAGES if s[0] == args.only]
    elif args.from_stage:
        idx = next((i for i, (n, _, _) in enumerate(STAGES) if n == args.from_stage), 0)
        stages = STAGES[idx:]

    for name, fn, critical in stages:
        if args.no_llm and name in llm_stages:
            log.info(f"--- stage: {name} [SKIPPED --no-llm]")
            continue
        t0 = time.time()
        log.info(f"--- stage: {name}{' (critical)' if critical else ''}")
        if args.dry_run:
            log.info("    [DRY]")
            continue
        try:
            if name == "deliver":
                fn(args)
            else:
                fn()
            _log_stage(name, t0, ok=True)
        except Exception as e:
            log.exception(f"stage {name} failed")
            _log_stage(name, t0, ok=False, err=str(e)[:500])
            if critical:
                log.error(f"CRITICAL stage {name} failed — aborting run")
                return 2

    log.info("=== done ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
