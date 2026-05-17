"""Analyst override CLI. Validates regex before persisting."""
from __future__ import annotations
import argparse
import re
import sys

from tools.db import connect

VALID_ACTIONS = {"suppress", "force_include", "boost_score"}


def add(pattern: str, action: str, value: int = 0, note: str = "") -> None:
    if action not in VALID_ACTIONS:
        raise ValueError(f"action must be one of {VALID_ACTIONS}")
    try:
        re.compile(pattern)
    except re.error as e:
        raise ValueError(f"invalid regex: {e}")
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO overrides (pattern, action, value, note) VALUES (?,?,?,?)",
            (pattern, action, value, note),
        )
    print(f"Added: {action} '{pattern}'", file=sys.stderr)


def list_all() -> None:
    with connect() as conn:
        for row in conn.execute("SELECT pattern, action, value, note FROM overrides"):
            print(f"  {row['action']:15} {row['pattern']:30}  {row['note'] or ''}")


def remove(pattern: str) -> None:
    with connect() as conn:
        cur = conn.execute("DELETE FROM overrides WHERE pattern = ?", (pattern,))
        print(f"Removed {cur.rowcount} row(s)", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    p_add = sp.add_parser("add")
    p_add.add_argument("--pattern", required=True)
    p_add.add_argument("--action", required=True, choices=list(VALID_ACTIONS))
    p_add.add_argument("--value", type=int, default=0)
    p_add.add_argument("--note", default="")
    sp.add_parser("list")
    p_rm = sp.add_parser("remove")
    p_rm.add_argument("--pattern", required=True)
    args = ap.parse_args()
    if args.cmd == "add":
        add(args.pattern, args.action, args.value, args.note)
    elif args.cmd == "list":
        list_all()
    elif args.cmd == "remove":
        remove(args.pattern)


if __name__ == "__main__":
    main()
