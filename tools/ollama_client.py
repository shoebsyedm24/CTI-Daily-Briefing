"""Ollama wrapper — robust JSON extraction, fallback chain, explicit unload, embeddings."""
from __future__ import annotations
import json
import os
import re
from typing import Literal

import httpx
import ollama

from tools.logging_config import get_logger

log = get_logger("ollama_client")

# Tags verified against `ollama list` on 2026-05-17.
MODELS = {
    "default":    "qwen3:14b",
    "security":   "qwen3:14b",        # hermes3 not installed; qwen3 fallback
    "composer":   "qwen3:14b",
    "embeddings": "nomic-embed-text",  # must be pulled: ollama pull nomic-embed-text
}
FALLBACK_LOCAL = ["qwen3:14b"]


def chat(role: Literal["default", "security", "composer"],
         prompt: str, system: str = "", json_mode: bool = False) -> str:
    # CLOUD_MODE: skip local Ollama, try Groq then Together.ai
    if os.getenv("CLOUD_MODE") == "1":
        last_err = None
        if os.getenv("GROQ_API_KEY"):
            try:
                return _groq(prompt, system, json_mode)
            except Exception as e:
                last_err = e
                log.warning(f"Groq failed, trying Together.ai: {e}")
        if os.getenv("TOGETHER_API_KEY"):
            try:
                return _together(prompt, system, json_mode)
            except Exception as e:
                last_err = e
                log.error(f"Together.ai failed: {e}")
        raise RuntimeError(f"All cloud LLMs failed: {last_err}")

    primary = MODELS.get(role, MODELS["default"])
    chain = [primary] + [m for m in FALLBACK_LOCAL if m != primary]
    last_err = None
    for model in chain:
        try:
            msgs = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
            resp = ollama.chat(
                model=model, messages=msgs,
                format="json" if json_mode else "",
                options={"num_ctx": 8192, "temperature": 0.2, "think": False},
                keep_alive="5m",
            )
            return resp["message"]["content"]
        except Exception as e:
            log.warning(f"{model} failed: {e}")
            last_err = e

    if os.getenv("GROQ_API_KEY"):
        try:
            return _groq(prompt, system, json_mode)
        except Exception as e:
            last_err = e
            log.error(f"Groq: {e}")

    raise RuntimeError(f"All models failed for role={role}: {last_err}")


def _extract_json(text: str) -> dict:
    """Robust JSON extraction. Handles fences, prefaces, partial outputs."""
    if not text or not text.strip():
        raise ValueError("empty LLM response")

    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Strip ```json ... ``` fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 3. Extract the first balanced {...} block
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = -1
                    continue

    raise ValueError(f"unparseable JSON; first 200 chars: {text[:200]!r}")


def chat_json(role, prompt, system="") -> dict:
    txt = chat(role, prompt, system=system, json_mode=True)
    return _extract_json(txt)


def embed(texts: list[str]) -> list[list[float]]:
    """Get embeddings via Ollama. Returns one vector per input."""
    if os.getenv("CLOUD_MODE") == "1":
        raise ConnectionError("Embeddings not available in CLOUD_MODE — clustering will be skipped")
    out = []
    for t in texts:
        r = ollama.embeddings(model=MODELS["embeddings"], prompt=t)
        out.append(r["embedding"])
    return out


def unload(model: str | None = None) -> None:
    """Force Ollama to evict model(s) from VRAM (keep_alive=0)."""
    targets = [model] if model else list(set(MODELS.values()))
    for m in targets:
        try:
            httpx.post("http://localhost:11434/api/generate",
                       json={"model": m, "keep_alive": 0}, timeout=10)
            log.info(f"unloaded {m}")
        except Exception as e:
            log.warning(f"unload {m}: {e}")


def _groq(prompt, system, json_mode):
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    kwargs = {"model": "llama-3.3-70b-versatile", "messages": msgs, "temperature": 0.2}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    return client.chat.completions.create(**kwargs).choices[0].message.content


def _together(prompt, system, json_mode):
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    payload = {
        "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
        "messages": msgs,
        "temperature": 0.2,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    r = httpx.post(
        "https://api.together.xyz/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['TOGETHER_API_KEY']}",
                 "Content-Type": "application/json"},
        json=payload,
        timeout=60.0,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]
