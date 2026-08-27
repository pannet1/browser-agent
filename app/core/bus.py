from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, AsyncGenerator, Callable


class EventBus:

    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        for q in list(self._subs[topic]):
            await q.put(payload)
        for q in list(self._subs["*"]):
            await q.put({"topic": topic, **payload})

    def subscribe(self, topic: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subs[topic].append(q)
        return q

    def unsubscribe(self, topic: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if queue in self._subs[topic]:
            self._subs[topic].remove(queue)

    async def stream(self, topic: str) -> AsyncGenerator[dict[str, Any], None]:
        q = self.subscribe(topic)
        try:
            while True:
                yield await q.get()
        finally:
            self.unsubscribe(topic, q)


bus = EventBus()
