from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(log_dir: Path, run_id: str, verbose: bool = False, extra_handlers=None) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("smartpost")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s [%(name)s] %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    fh = logging.FileHandler(log_dir / f"smartpost_{run_id}.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Keep console output only in source/dev mode when requested by callers.
    sh = logging.StreamHandler()
    sh.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    for handler in extra_handlers or []:
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    return logger
