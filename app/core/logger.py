from __future__ import annotations

import logging
import os
from pathlib import Path


RUNTIME_LOG = Path(os.getenv("BROWSER_AGENT_RUNTIME_LOG", "/tmp/browser-agent.log"))


def _file_handler() -> logging.FileHandler | None:
    try:
        handler = logging.FileHandler(RUNTIME_LOG)
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        return handler
    except Exception:
        return None


def logging_func(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        sh = logging.StreamHandler()
        sh.setFormatter(formatter)
        logger.addHandler(sh)
        try:
            fh = _file_handler()
            if fh:
                logger.addHandler(fh)
        except Exception:
            pass
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def configure_server_logging() -> None:
    """Mirror Uvicorn/reload output into the runtime log without hiding stdout."""
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "watchfiles.main"):
        logger = logging.getLogger(name)
        if any(getattr(handler, "baseFilename", None) == str(RUNTIME_LOG) for handler in logger.handlers):
            continue
        handler = _file_handler()
        if handler:
            logger.addHandler(handler)
