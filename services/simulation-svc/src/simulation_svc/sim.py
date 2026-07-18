"""Conversation engine — one multi-turn replay per seed question.

A **turn** is one back-and-forth exchange: a user message followed by the agent's
reply. `max_turns` therefore bounds the number of *exchanges*, so a 3-turn run is
user→agent, user→agent, user→agent (six messages), not three lone messages.

The user-simulator (model provider, conditioned on the persona) opens each turn
and the agent-under-test (adapter) answers it. The flat message list is the trace.

Multi-turn is history-grounded: each turn's user message is generated from the
whole conversation so far plus the persona's goal and edge-case, so every
follow-up is a genuine reaction to what the agent just said — pushing on anything
unresolved rather than restating the opener. The first user message is always the
verbatim seed prompt; `max_turns == 1` is a single exchange (seed + one reply).

`mode` selects how long a conversation runs:
  - ``single_turn`` — exactly one exchange, whatever ``max_turns`` says.
  - ``multi_turn``  — up to ``max_turns`` exchanges.
  - ``auto``        — decided per question: adversarial/hard questions run
    multi-turn (up to ``max_turns``), simple answer-style questions run single.

The adapter's declared interaction type overrides all of the above: a target
onboarded as ``single_turn`` (a stateless task app) is always replayed as one
exchange, since it holds no session for a conversation to build on.
"""

from __future__ import annotations

import secrets

from eeof_core.models import Question, Turn

from .adapters import agent_reply


def _auto_prefers_multi_turn(question: Question) -> bool:
    """Auto mode: infer per-question whether follow-up pressure is worthwhile.

    Adversarial shapes and hard scenarios reward pushing the agent across
    several turns; a simple answer-style question resolves in one exchange. This
    reads only frozen question fields, so it stays deterministic for a run.
    """
    if getattr(question, "shape", "") == "adversify":
        return True
    if str(getattr(question, "scenario", "")).endswith(".hard"):
        return True
    return getattr(question, "rubric", "") == "safety"


def adapter_interaction_mode(adapter_snapshot: dict | None) -> str:
    """The target application's declared interaction type.

    Set at onboarding on ``capabilities.interaction_mode``. A ``single_turn``
    target is a stateless task app (one prompt → one answer, no session), so it
    can only ever be replayed single-turn no matter what the run asked for.
    Anything unset or unrecognised defaults to ``multi_turn`` (conversational).
    """
    caps = (adapter_snapshot or {}).get("capabilities", {}) or {}
    im = caps.get("interaction_mode")
    return im if im in ("single_turn", "multi_turn") else "multi_turn"


def resolve_mode(mode: str, question: Question, adapter_snapshot: dict | None = None) -> str:
    """Resolve ``auto`` to the concrete per-question mode; pass others through.

    The adapter's declared interaction type takes precedence: a ``single_turn``
    target clamps every run to a single exchange regardless of the requested
    mode, because there is no session to carry a conversation.

    Callers use this both to size the conversation and to stamp the *effective*
    mode onto the trace, so ``auto`` runs are recorded as what they actually did.
    """
    if adapter_interaction_mode(adapter_snapshot) == "single_turn":
        return "single_turn"
    if mode == "auto":
        return "multi_turn" if _auto_prefers_multi_turn(question) else "single_turn"
    return mode


def _effective_exchanges(mode: str, max_turns: int) -> int:
    """Number of user→agent exchanges for a resolved (non-auto) mode."""
    if mode == "single_turn":
        return 1
    return max(1, int(max_turns))

# The simulator sees the full running transcript as chat history; this system
# prompt tells it to react to that history in character.
_USER_SYSTEM = (
    "You are role-playing a single user in an ongoing conversation with an AI "
    "agent. Stay in character:\n"
    "  persona: {name} — {role}\n"
    "  tone: {tone}; tech savviness: {tech}\n"
    "  your goal: {goal}\n"
    "  edge-case to keep surfacing: {edge}\n"
    "You are given the conversation so far. Read the agent's most recent reply "
    "and respond with ONE short, natural follow-up message that reacts to it — "
    "push on anything unclear, unsatisfying, or unfinished, and keep pursuing "
    "your goal. Do not restate your first message. Reply with just the message, "
    "no preamble."
)


def _persona_field(persona, *names: str, default: str = "") -> str:
    for n in names:
        val = getattr(persona, n, None)
        if isinstance(val, list) and val:
            return str(val[0])
        if val:
            return str(val)
    return default


async def simulate_conversation(
    question: Question,
    adapter_snapshot: dict,
    provider,
    max_turns: int = 12,
    mode: str = "multi_turn",
    trace_id: str | None = None,
) -> list[Turn]:
    persona = question.persona
    tone = persona.tone or "casual"
    tech = persona.tech_savviness or "intermediate"
    sim_system = _USER_SYSTEM.format(
        name=_persona_field(persona, "name", default="the user"),
        role=_persona_field(persona, "role", default="a customer"),
        tone=tone,
        tech=tech,
        goal=_persona_field(persona, "goals", "goal", default="get a useful answer"),
        edge=_persona_field(persona, "edge_cases", default="asks for specifics"),
    )

    turns: list[Turn] = []
    exchanges = _effective_exchanges(resolve_mode(mode, question, adapter_snapshot), max_turns)
    for i in range(exchanges):
        # Open the exchange with a user message: the verbatim seed prompt on the
        # first turn, a history-grounded follow-up thereafter.
        if i == 0:
            user_text = question.prompt
        else:
            user_text = await provider.chat(
                system=sim_system,
                messages=[
                    {"role": "user" if t.role == "user" else "assistant", "content": t.content}
                    for t in turns
                ],
                max_tokens=120,
                temperature=0.8,
            )
            # The provider can occasionally return an empty/whitespace completion
            # (rate-limit blip, over-eager stop). A blank user turn renders as an
            # empty bubble and breaks the "N real turns" contract, so fall back to
            # a persona-flavoured probe that keeps the conversation moving.
            if not (user_text or "").strip():
                edge = _persona_field(persona, "edge_cases", default="")
                user_text = (
                    f"Can you be more specific about {edge}?" if edge
                    else "Can you walk me through that with a concrete example?"
                )
        turns.append(Turn(role="user", content=user_text.strip()))
        # Close the exchange with the agent's reply, its real tool-call sequence,
        # and the OpenInference span tree it emitted. A fresh per-turn parent span
        # id under the shared run trace id gives W3C trace-context continuity.
        parent_span_id = secrets.token_hex(8)
        agent_text, tool_calls, spans = await agent_reply(
            adapter_snapshot, turns, provider, trace_id, parent_span_id
        )
        turns.append(
            Turn(role="agent", content=agent_text, tool_calls=tool_calls, spans=spans)
        )
    return turns
