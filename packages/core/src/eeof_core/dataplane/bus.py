"""Message bus interface + in-memory and NATS JetStream implementations.

Three concerns, matching the framework Messaging spec:
  * fan-out pub/sub  — STATUS (`status.<stage>.<job_id>`) and TRACES
    (`trace.events.<run_id>`): every subscriber gets a copy.
  * work-queue       — JOBS (`qgen.jobs`/`sim.jobs`/`eval.jobs`): each message is
    delivered to exactly one worker (durable consumer).
  * KV bucket        — `job_progress`: last-known snapshot for WS ressubscribe.
"""

from __future__ import annotations

import asyncio
import contextlib
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from ..config import settings

Payload = dict[str, Any]
Handler = Callable[[Payload], Awaitable[None]]


def subject_matches(pattern: str, subject: str) -> bool:
    """NATS-style token match: `*` = one token, `>` = tail."""
    p, s = pattern.split("."), subject.split(".")
    for i, tok in enumerate(p):
        if tok == ">":
            return True
        if i >= len(s):
            return False
        if tok != "*" and tok != s[i]:
            return False
    return len(p) == len(s)


class Bus(ABC):
    @abstractmethod
    async def connect(self) -> None: ...
    @abstractmethod
    async def close(self) -> None: ...
    @abstractmethod
    async def publish(self, subject: str, data: Payload) -> None: ...
    @abstractmethod
    async def subscribe(self, pattern: str, handler: Handler) -> Callable[[], None]: ...
    @abstractmethod
    async def publish_job(self, subject: str, data: Payload) -> None: ...
    @abstractmethod
    async def bind_worker(self, subject: str, durable: str, handler: Handler) -> None: ...
    @abstractmethod
    async def kv_put(self, bucket: str, key: str, value: Payload) -> None: ...
    @abstractmethod
    async def kv_get(self, bucket: str, key: str) -> Payload | None: ...


class InMemoryBus(Bus):
    def __init__(self) -> None:
        self._fanout: list[tuple[str, Handler]] = []
        self._queues: dict[str, asyncio.Queue[Payload]] = {}
        self._tasks: list[asyncio.Task] = []
        self._kv: dict[tuple[str, str], Payload] = {}

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t

    async def publish(self, subject: str, data: Payload) -> None:
        for pattern, handler in list(self._fanout):
            if subject_matches(pattern, subject):
                self._tasks.append(asyncio.create_task(self._safe(handler, data)))

    async def subscribe(self, pattern: str, handler: Handler) -> Callable[[], None]:
        entry = (pattern, handler)
        self._fanout.append(entry)
        return lambda: self._fanout.remove(entry) if entry in self._fanout else None

    async def publish_job(self, subject: str, data: Payload) -> None:
        self._queues.setdefault(subject, asyncio.Queue()).put_nowait(data)

    async def bind_worker(self, subject: str, durable: str, handler: Handler) -> None:
        q = self._queues.setdefault(subject, asyncio.Queue())

        async def _loop() -> None:
            while True:
                data = await q.get()
                await self._safe(handler, data)

        self._tasks.append(asyncio.create_task(_loop()))

    async def kv_put(self, bucket: str, key: str, value: Payload) -> None:
        self._kv[(bucket, key)] = value

    async def kv_get(self, bucket: str, key: str) -> Payload | None:
        return self._kv.get((bucket, key))

    @staticmethod
    async def _safe(handler: Handler, data: Payload) -> None:
        try:
            await handler(data)
        except Exception as e:  # a bad handler must not kill the loop
            print(f"[bus] handler error: {e}")


class NatsJetStreamBus(Bus):
    """Real NATS JetStream. Requires extra: infra (`nats-py`)."""

    def __init__(self) -> None:
        self._nc = None
        self._js = None
        self._kv_stores: dict[str, Any] = {}

    async def connect(self) -> None:
        if self._nc is not None:  # idempotent — run_all/lifespan may call repeatedly
            return
        import nats

        from ..messaging import STREAMS

        self._nc = await nats.connect(settings.nats_url)
        self._js = self._nc.jetstream()
        for stream, subjects in STREAMS.items():
            with contextlib.suppress(Exception):
                await self._js.add_stream(name=stream, subjects=subjects)

    async def close(self) -> None:
        if self._nc:
            await self._nc.drain()

    async def publish(self, subject: str, data: Payload) -> None:
        import json

        await self._js.publish(subject, json.dumps(data).encode())

    async def subscribe(self, pattern: str, handler: Handler) -> Callable[[], None]:
        import json

        async def _cb(msg):
            await handler(json.loads(msg.data))
            await msg.ack()

        sub = await self._js.subscribe(pattern, cb=_cb)
        return lambda: asyncio.create_task(sub.unsubscribe())

    async def publish_job(self, subject: str, data: Payload) -> None:
        await self.publish(subject, data)

    async def bind_worker(self, subject: str, durable: str, handler: Handler) -> None:
        import json

        async def _cb(msg):
            await handler(json.loads(msg.data))
            await msg.ack()

        await self._js.subscribe(subject, durable=durable, cb=_cb, manual_ack=True)

    async def _kv(self, bucket: str):
        if bucket not in self._kv_stores:
            with contextlib.suppress(Exception):
                self._kv_stores[bucket] = await self._js.create_key_value(bucket=bucket)
            if bucket not in self._kv_stores:
                self._kv_stores[bucket] = await self._js.key_value(bucket)
        return self._kv_stores[bucket]

    async def kv_put(self, bucket: str, key: str, value: Payload) -> None:
        import json

        kv = await self._kv(bucket)
        await kv.put(key, json.dumps(value).encode())

    async def kv_get(self, bucket: str, key: str) -> Payload | None:
        import json

        kv = await self._kv(bucket)
        try:
            entry = await kv.get(key)
            return json.loads(entry.value)
        except Exception:
            return None


_bus: Bus | None = None


def get_bus() -> Bus:
    global _bus
    if _bus is None:
        _bus = InMemoryBus() if settings.is_local else NatsJetStreamBus()
    return _bus
