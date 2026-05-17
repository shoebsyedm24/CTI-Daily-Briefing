"""RAG over obsidian_vault/env_notes/ using ChromaDB. Re-embeds on mtime change."""
from __future__ import annotations
import os
from pathlib import Path

import chromadb
from dotenv import load_dotenv

from tools.logging_config import get_logger
from tools.ollama_client import embed

load_dotenv()
log = get_logger("rag")

VAULT = Path(os.getenv("OBSIDIAN_VAULT_PATH", "obsidian_vault"))
ENV_NOTES = VAULT / "env_notes"
CHROMA_DIR = Path(__file__).resolve().parent.parent / "chroma_db"
COLLECTION = "env_notes"

_client: chromadb.Client | None = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection
    _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    _collection = _client.get_or_create_collection(
        COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def index_notes() -> int:
    """Index or re-index env_notes/ files. Skips files unchanged since last embed."""
    if not ENV_NOTES.exists():
        log.warning(f"env_notes dir not found: {ENV_NOTES}")
        return 0

    col = _get_collection()
    indexed = 0
    for md_path in sorted(ENV_NOTES.glob("**/*.md")):
        doc_id = str(md_path.relative_to(VAULT))
        mtime = str(md_path.stat().st_mtime)
        existing = col.get(ids=[doc_id], include=["metadatas"])
        if existing["ids"] and existing["metadatas"][0].get("mtime") == mtime:
            continue  # unchanged
        text = md_path.read_text(encoding="utf-8", errors="replace")
        vec = embed([text])[0]
        col.upsert(
            ids=[doc_id],
            embeddings=[vec],
            documents=[text],
            metadatas=[{"path": doc_id, "mtime": mtime}],
        )
        indexed += 1
        log.info(f"indexed {doc_id}")
    log.info(f"RAG index: {indexed} files updated")
    return indexed


def query(text: str, n_results: int = 4) -> list[dict]:
    """Return top-n chunks with source path."""
    col = _get_collection()
    vec = embed([text])[0]
    results = col.query(
        query_embeddings=[vec],
        n_results=min(n_results, col.count() or 1),
        include=["documents", "metadatas", "distances"],
    )
    out = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        out.append({"text": doc, "path": meta.get("path", ""), "distance": dist})
    return out
