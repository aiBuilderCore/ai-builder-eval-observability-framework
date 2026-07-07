"""Conversation engine — one multi-turn replay per seed question.

The user-simulator (model provider, conditioned on the persona) and the
agent-under-test (adapter) alternate turns up to `max_turns`. The full turn list
is the trace.
"""

from __future__ import annotations

from eeof_core.models import Question, Turn

from .adapters import agent_reply

_USER_SYSTEM = (
    "You are simulating a user with tone '{tone}' and tech savviness '{tech}'. "
    "Continue the conversation as that user in ONE short message. Stay in character; "
    "push on anything unclear or unsatisfying. Reply with just the message."
)


async def simulate_conversation(
    question: Question, adapter_snapshot: dict, provider, max_turns: int = 12
) -> list[Turn]:
    turns: list[Turn] = [Turn(role="user", content=question.prompt)]
    tone = question.persona.tone or "casual"
    tech = question.persona.tech_savviness or "intermediate"

    while len(turns) < max_turns:
        agent_text = await agent_reply(adapter_snapshot, turns, provider)
        turns.append(Turn(role="agent", content=agent_text))
        if len(turns) >= max_turns:
            break
        user_text = await provider.chat(
            system=_USER_SYSTEM.format(tone=tone, tech=tech),
            messages=[
                {"role": "user" if t.role == "user" else "assistant", "content": t.content}
                for t in turns
            ],
            max_tokens=120,
            temperature=0.8,
        )
        turns.append(Turn(role="user", content=user_text))
    return turns
