from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.bus import bus
from app.core.logger import logging_func

logger = logging_func(__name__)

LIVE_LOG = Path("/tmp/browser-agent-live.log")
LIVE_LOG.parent.mkdir(parents=True, exist_ok=True)


async def publish_monitor(event: dict[str, Any]) -> None:
    payload = {"ts": datetime.utcnow().isoformat(), **event}
    try:
        with LIVE_LOG.open("a") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        pass
    try:
        await bus.publish("_monitor", payload)
    except Exception:
        pass
    logger.info(f"monitor {payload.get('state','')} {payload.get('thought','')[:120]}")


async def monitor_stream() -> Any:
    q = bus.subscribe("_monitor")
    try:
        while True:
            ev = await q.get()
            yield ev
    finally:
        bus.unsubscribe("_monitor", q)
