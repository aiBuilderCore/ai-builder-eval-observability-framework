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
"""

from __future__ import annotations

from eeof_core.models import Question, Turn

from .adapters import agent_reply

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
    question: Question, adapter_snapshot: dict, provider, max_turns: int = 12
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
    exchanges = max(1, int(max_turns))
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
        # Close the exchange with the agent's reply to the full history so far.
        agent_text = await agent_reply(adapter_snapshot, turns, provider)
        turns.append(Turn(role="agent", content=agent_text))
    return turns
