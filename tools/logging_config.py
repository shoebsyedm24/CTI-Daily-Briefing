"""Centralized logging — one rotating file per logger name + stderr."""
from __future__ import annotations
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
_FMT = "%(asctime)s [%(levelname)s] %(name)s :: %(message)s"
_configured: set[str] = set()


def get_logger(name: str) -> logging.Logger:
    log = logging.getLogger(name)
    if name in _configured:
        return log
    log.setLevel(logging.INFO)
    fh = RotatingFileHandler(LOG_DIR / f"{name}.log", maxBytes=10_000_000, backupCount=5)
    fh.setFormatter(logging.Formatter(_FMT))
    log.addHandler(fh)
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter(_FMT))
    log.addHandler(sh)
    _configured.add(name)
    return log
