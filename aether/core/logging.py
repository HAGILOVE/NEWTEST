"""Structured, level-controlled console logging with solver progress helpers."""
from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager

_FMT = "%(asctime)s.%(msecs)03d | %(levelname)-7s | %(name)-22s | %(message)s"
_DATEFMT = "%H:%M:%S"

_configured = False


def configure(level: int | str = logging.INFO, stream=sys.stdout) -> None:
    """Install Aether's root handler exactly once."""
    global _configured
    root = logging.getLogger("aether")
    if _configured:
        root.setLevel(_as_level(level))
        return
    h = logging.StreamHandler(stream)
    h.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root.addHandler(h)
    root.setLevel(_as_level(level))
    root.propagate = False
    _configured = True


def _as_level(level) -> int:
    if isinstance(level, str):
        return getattr(logging, level.upper(), logging.INFO)
    return int(level)


def get_logger(name: str) -> logging.Logger:
    configure()
    return logging.getLogger(f"aether.{name}")


@contextmanager
def timed(logger: logging.Logger, label: str, level: int = logging.INFO):
    """Context manager logging wall-clock duration of a solver stage."""
    t0 = time.perf_counter()
    logger.log(level, "%s ...", label)
    try:
        yield
    finally:
        dt = time.perf_counter() - t0
        logger.log(level, "%s done in %.3f s", label, dt)


__all__ = ["configure", "get_logger", "timed"]
