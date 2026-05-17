"""Embedding-based clustering — collapse near-duplicate stories before composing."""
from __future__ import annotations
import numpy as np

from tools.logging_config import get_logger
from tools.ollama_client import embed

log = get_logger("cluster")


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def cluster(
    items: list[dict],
    threshold: float = 0.85,
    text_key=lambda it: f"{it['title']} {(it.get('summary') or '')[:500]}",
) -> list[dict]:
    """Group near-duplicate items. Returns one entry per cluster, primary = highest-
    scored. Each result item gets a `related` list of {source, url, title} for the
    rest of its cluster."""
    if len(items) <= 1:
        return items

    try:
        vectors = [np.array(v) for v in embed([text_key(it) for it in items])]
    except Exception as e:
        log.warning(f"Embeddings unavailable ({e}); skipping clustering, returning items as-is")
        return items
    n = len(items)
    assigned = [False] * n
    clusters: list[list[int]] = []

    for i in range(n):
        if assigned[i]:
            continue
        members = [i]
        assigned[i] = True
        for j in range(i + 1, n):
            if assigned[j]:
                continue
            if _cosine(vectors[i], vectors[j]) >= threshold:
                members.append(j)
                assigned[j] = True
        clusters.append(members)

    output = []
    for members in clusters:
        primary_idx = max(members, key=lambda k: items[k].get("score", 0))
        primary = dict(items[primary_idx])
        related = [
            {"source": items[k]["source"], "url": items[k]["url"],
             "title": items[k]["title"]}
            for k in members if k != primary_idx
        ]
        if related:
            primary["related"] = related
        output.append(primary)
    return output
