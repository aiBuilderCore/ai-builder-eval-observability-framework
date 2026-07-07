"""qgen-svc — an async worker with a thin health surface.

The worker binds a durable consumer on `qgen.jobs` at startup; there is no public
REST here (submission is accepted at the edge and queued).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from eeof_core.dataplane import get_bus

from .worker import worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_bus().connect()
    await worker.start()
    yield


app = FastAPI(title="qgen-svc", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"service": "qgen-svc", "status": "ok", "consumes": worker.subject}
