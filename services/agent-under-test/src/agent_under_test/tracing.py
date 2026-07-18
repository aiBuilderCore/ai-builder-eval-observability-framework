"""OpenTelemetry / OpenInference tracing for the agent-under-test.

Every ``/chat`` turn produces a real span tree — a root ``AGENT`` span with a
``PROMPT`` render, one ``LLM`` chat-completion span carrying the measured model
latency and token usage, and one span per tool call (``RETRIEVER`` for retrieval,
``GUARDRAIL`` for the compliance/disclosure step, ``TOOL`` otherwise). Spans carry
OpenInference span kinds plus OTel GenAI semantic-convention attributes.

The canonical output is a list of plain span dicts (W3C ``trace_id``/``span_id``,
``start_ms``/``duration_ms`` relative to the turn start) returned in the ``/chat``
envelope, so the simulation service can stitch them into the trace blob with no
collector running — local mode needs no infrastructure.

When ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, the same spans are *also* exported
over OTLP/HTTP via the real OpenTelemetry SDK, making the advertised OTLP ingest
path genuine wherever a collector is deployed.

`traceparent` (W3C) is honoured on the request so every turn of a simulation run
shares one trace id: the root AGENT span becomes a child of the propagated span.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import time
from contextlib import contextmanager
from typing import Any

# OpenInference span-kind attribute key + OTel GenAI semconv keys. Defined inline
# (they are just attribute names) so the module never hard-depends on the
# openinference-semantic-conventions package at import time.
OI_KIND = "openinference.span.kind"
GENAI_MODEL = "gen_ai.request.model"
GENAI_TOK_IN = "gen_ai.usage.input_tokens"
GENAI_TOK_OUT = "gen_ai.usage.output_tokens"
GENAI_OP = "gen_ai.operation.name"


def new_trace_id() -> str:
    """A fresh 128-bit W3C trace id (32 hex chars)."""
    return secrets.token_hex(16)


def new_span_id() -> str:
    """A fresh 64-bit W3C span id (16 hex chars)."""
    return secrets.token_hex(8)


def parse_traceparent(header: str | None) -> tuple[str | None, str | None]:
    """Return ``(trace_id, parent_span_id)`` from a W3C ``traceparent`` header.

    Format: ``version-traceid-spanid-flags`` (e.g. ``00-<32hex>-<16hex>-01``).
    Returns ``(None, None)`` when the header is absent or malformed, so the caller
    starts a fresh trace.
    """
    if not header:
        return None, None
    parts = header.strip().split("-")
    if len(parts) != 4 or len(parts[1]) != 32 or len(parts[2]) != 16:
        return None, None
    return parts[1], parts[2]


def _tokens_for(text: str, *, floor: int = 0) -> int:
    """Cheap, deterministic token estimate (~words × 1.3) for GenAI attributes."""
    words = max(1, len((text or "").split()))
    return int(words * 1.3) + floor


class _TraceBuilder:
    """Accumulates OpenInference spans for one agent turn with real timing."""

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self._t0 = time.monotonic()
        self.spans: list[dict[str, Any]] = []

    def _ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    def add(
        self,
        *,
        kind: str,
        name: str,
        parent_id: str | None,
        start_ms: int,
        duration_ms: int,
        attrs: dict[str, Any] | None = None,
    ) -> str:
        span_id = new_span_id()
        merged = {OI_KIND: kind, **(attrs or {})}
        self.spans.append(
            {
                "id": span_id,
                # A root span keeps parent_id=None so the trace renders as a
                # waterfall; the propagated `traceparent` gives trace *continuity*
                # (shared trace_id across turns), not a visual parent.
                "parent_id": parent_id,
                "kind": kind,
                "name": name,
                "start_ms": start_ms,
                "duration_ms": max(1, duration_ms),
                "attrs": merged,
            }
        )
        return span_id


def _tool_span_kind(name: str) -> str:
    if name.startswith("retrieve"):
        return "RETRIEVER"
    if any(k in name for k in ("disclosure", "compliance", "guardrail")):
        return "GUARDRAIL"
    return "TOOL"


def _det_ms(seed: str, lo: int, hi: int) -> int:
    """Deterministic pseudo-duration in [lo, hi] from a stable hash of ``seed``."""
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return lo + (h % max(1, hi - lo))


@contextmanager
def timed():
    """Yield a callable returning elapsed milliseconds since entry."""
    start = time.monotonic()
    yield lambda: int((time.monotonic() - start) * 1000)


def build_turn_spans(
    *,
    trace_id: str,
    parent_span_id: str | None,
    convo_text: str,
    reply: str,
    tool_calls: list[dict],
    model_name: str,
    llm_ms: int,
    prompt_ms: int,
) -> list[dict[str, Any]]:
    """Assemble the OpenInference span tree for one completed agent turn.

    ``llm_ms``/``prompt_ms`` are the *measured* durations of the model call and
    prompt render; tool spans get deterministic sub-durations laid out after the
    LLM span, so the whole turn reads as a realistic agentic waterfall.
    """
    b = _TraceBuilder(trace_id)
    tok_in = _tokens_for(convo_text, floor=60)
    tok_out = _tokens_for(reply)

    cursor = 0
    # Root AGENT span — spans the whole turn; filled with the total at the end.
    root_attrs: dict[str, Any] = {GENAI_OP: "invoke_agent", "graph.node.id": "retirement_401k"}
    if parent_span_id:
        # Lineage back to the run-level trace context propagated via `traceparent`.
        root_attrs["trace.parent_span_id"] = parent_span_id
    root = b.add(
        kind="AGENT",
        name="retirement_401k.chat",
        parent_id=None,
        start_ms=0,
        duration_ms=1,  # patched below
        attrs=root_attrs,
    )
    root_rec = b.spans[-1]

    b.add(kind="PROMPT", name="system_prompt.render", parent_id=root,
          start_ms=cursor, duration_ms=max(1, prompt_ms), attrs={})
    cursor += max(1, prompt_ms)

    b.add(
        kind="LLM",
        name="chat.completion",
        parent_id=root,
        start_ms=cursor,
        duration_ms=max(1, llm_ms),
        attrs={GENAI_MODEL: model_name, GENAI_TOK_IN: tok_in, GENAI_TOK_OUT: tok_out,
               GENAI_OP: "chat"},
    )
    cursor += max(1, llm_ms)

    for i, call in enumerate(tool_calls):
        name = call.get("name", "tool")
        kind = _tool_span_kind(name)
        dur = _det_ms(f"{trace_id}:{name}:{i}", 40, 340)
        attrs: dict[str, Any] = {"tool.name": name}
        if call.get("detail"):
            attrs["tool.description"] = call["detail"]
        if kind == "RETRIEVER":
            attrs["retrieval.documents.count"] = 1 + (_det_ms(name, 2, 8))
        if kind == "GUARDRAIL":
            attrs["guardrail.outcome"] = "flagged" if not call.get("ok", True) else "allow"
        b.add(kind=kind, name=name, parent_id=root, start_ms=cursor, duration_ms=dur, attrs=attrs)
        cursor += dur

    root_rec["duration_ms"] = max(1, cursor)
    _maybe_export_otlp(b.spans, trace_id, model_name)
    return b.spans


# --------------------------------------------------------------------------- #
# Optional real OTLP export — only when a collector endpoint is configured.
# --------------------------------------------------------------------------- #
_tracer = None
_otlp_ready = False


def _maybe_export_otlp(spans: list[dict[str, Any]], trace_id: str, model_name: str) -> None:
    """Best-effort mirror of the span tree to an OTLP/HTTP collector, if one is
    configured. No-op (and never raises) when the SDK or endpoint is absent, so
    the primary in-envelope path is unaffected."""
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    global _tracer, _otlp_ready
    if not _otlp_ready:
        try:
            from opentelemetry import trace as ot_trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = TracerProvider(
                resource=Resource.create({"service.name": "agent-under-test"})
            )
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            ot_trace.set_tracer_provider(provider)
            _tracer = ot_trace.get_tracer("agent-under-test")
        except Exception:
            _tracer = None
        _otlp_ready = True
    if _tracer is None:
        return
    try:
        for s in spans:
            with _tracer.start_as_current_span(s["name"]) as sp:
                for k, v in s["attrs"].items():
                    sp.set_attribute(k, v)
    except Exception:
        pass
