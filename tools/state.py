"""State machine — single source of truth for items.status transitions."""
from __future__ import annotations

ALLOWED: dict[str, set[str]] = {
    "new":            {"triaged", "archived", "failed", "superseded"},
    "triaged":        {"enriched", "archived", "failed"},
    "enriched":       {"mapped", "archived", "failed"},   # v4: NO back to triaged
    "mapped":         {"contextualized", "failed"},
    "contextualized": {"mitigated", "failed"},
    "mitigated":      {"composed", "failed"},
    "composed":       {"briefed", "failed"},
    "briefed":        {"archived"},
    "archived":       set(),
    "superseded":     set(),                              # v4: terminal
    "failed":         {"new", "triaged", "enriched", "mapped",
                       "contextualized", "mitigated", "composed"},
}


def can_transition(from_state: str, to_state: str) -> bool:
    return to_state in ALLOWED.get(from_state, set())


def transition(conn, item_id: int, to_state: str, error: str | None = None) -> None:
    row = conn.execute("SELECT status FROM items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise ValueError(f"Item {item_id} not found")
    if not can_transition(row[0], to_state):
        raise ValueError(f"Invalid transition: {row[0]} → {to_state} (item {item_id})")
    conn.execute(
        "UPDATE items SET status = ?, error = ?, processed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (to_state, error, item_id),
    )


def bulk_transition(conn, from_state: str, to_state: str) -> int:
    """Advance every item currently in from_state. Returns row count."""
    if not can_transition(from_state, to_state):
        raise ValueError(f"Invalid transition: {from_state} → {to_state}")
    cur = conn.execute(
        "UPDATE items SET status = ?, processed_at = CURRENT_TIMESTAMP WHERE status = ?",
        (to_state, from_state),
    )
    return cur.rowcount


def bulk_transition_by_ids(conn, item_ids: list[int], to_state: str) -> int:
    """Transition a specific set of items, validating each. Silently skips invalid."""
    if not item_ids:
        return 0
    placeholders = ",".join("?" * len(item_ids))
    rows = conn.execute(
        f"SELECT id, status FROM items WHERE id IN ({placeholders})",
        item_ids,
    ).fetchall()
    valid = [r["id"] for r in rows if can_transition(r["status"], to_state)]
    if valid:
        ph = ",".join("?" * len(valid))
        conn.execute(
            f"UPDATE items SET status = ?, processed_at = CURRENT_TIMESTAMP WHERE id IN ({ph})",
            (to_state, *valid),
        )
    return len(valid)
