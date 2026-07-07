"""Conversation engine — one multi-turn replay per seed question.

The user-simulator (model provider, conditioned on the persona) and the
agent-under-test (adapter) alternate turns up to `max_turns`. The full turn list
is the trace.

Multi-turn is history-grounded: turn *n*'s follow-up is generated from the whole
conversation so far (turns 1..n-1) plus the persona's goal and edge-case, so each
new user message is a genuine reaction to what the agent just said — pushing on
anything unresolved rather than restating the opener. When `max_turns` is 1 the
loop stops after the agent's first reply and no follow-up is generated.
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
    turns: list[Turn] = [Turn(role="user", content=question.prompt)]
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

    while len(turns) < max_turns:
        agent_text = await agent_reply(adapter_snapshot, turns, provider)
        turns.append(Turn(role="agent", content=agent_text))
        if len(turns) >= max_turns:
            break
        # Follow-up for turn n is generated from turns 1..n-1 (the full history
        # so far), so it is a real reaction to the agent's latest reply.
        user_text = await provider.chat(
            system=sim_system,
            messages=[
                {"role": "user" if t.role == "user" else "assistant", "content": t.content}
                for t in turns
            ],
            max_tokens=120,
            temperature=0.8,
        )
        turns.append(Turn(role="user", content=user_text))
    return turns
