# ai-builder-eval-observability-framework

Evaluation and observability framework for the aiBuilderCore agentic / GenAI applications. Generates synthetic users, drives them through the target system, grades the outcomes with LLM-as-judge, and emits the resulting traces and metrics for monitoring.

> **Status:** placeholder. The repo currently contains the package skeleton (empty `__init__.py` files), this README, and `CLAUDE.md`. Implementation in progress.

## Stack

- **Language** — Python `>=3.13`
- **Package manager** — [uv](https://docs.astral.sh/uv/)
- **Schemas / I/O contracts** — pydantic
- **Lint / format** — ruff
- **Tests** — pytest (`uv run pytest`)
- **Tracing** — OpenTelemetry-compatible exporters (OTLP) — concrete backends pluggable

## What this framework does (target shape)

The framework implements an end-to-end evaluation loop for any agentic or GenAI application:

1. **Persona Lab** — generates and curates a library of synthetic users (demographics, goals, tone, edge-case behaviors). Personas are versioned and reusable across eval runs so results stay comparable.
2. **Question generation** — given a persona and a task domain, synthesizes prompts / questions / interaction scripts the persona would realistically produce. Supports rubric-driven generation (e.g. ambiguity, jailbreak, multi-turn).
3. **Agentic simulation** — drives the generated input through the target agent / GenAI system under test, captures every turn, tool call, and intermediate state.
4. **LLM-as-judge evaluation** — scores each run against rubrics (faithfulness, helpfulness, safety, task completion, tone). Judges are themselves versioned LLM prompts; multiple judges can vote.
5. **Observability** — exports traces, judge scores, and run metadata so dashboards and regression alerts can pick them up. Designed to consume runtime traces emitted by [ai-builder-agent-factory](https://github.com/aiBuilderCore/ai-builder-agent-factory).

## Anticipated project layout

```
ai-builder-eval-observability-framework/
├── pyproject.toml
├── uv.lock
├── README.md
├── CLAUDE.md
├── eval_obs/
│   ├── __init__.py
│   ├── persona_lab/             # synthetic user generation + library
│   │   ├── generator.py         # build personas from a spec
│   │   ├── library.py           # load / save / version curated personas
│   │   └── schemas.py           # Persona, PersonaSpec
│   ├── question_generation/     # synthesize eval inputs from a persona
│   │   ├── strategies.py        # ambiguity, multi-turn, adversarial, etc.
│   │   └── schemas.py           # Question, GenerationRequest
│   ├── simulation/              # drive target system, capture run trace
│   │   ├── runner.py            # async runner; pluggable target adapter
│   │   ├── adapters/            # adapters per target (agent-factory HTTP, local, etc.)
│   │   └── schemas.py           # RunInput, RunOutput, RunTrace
│   ├── judges/                  # LLM-as-judge evaluators
│   │   ├── llm_judge.py         # generic judge runner
│   │   ├── rubrics/             # versioned rubric prompts (.md + schema)
│   │   └── schemas.py           # Rubric, JudgeVerdict, Score
│   ├── observability/           # tracing + metric export
│   │   ├── tracer.py            # OTel span helpers around eval phases
│   │   ├── exporters.py         # OTLP / file / dashboard sinks
│   │   └── schemas.py           # EvalEvent, MetricRecord
│   ├── pipelines/               # orchestrate full eval runs
│   │   └── orchestrator.py      # persona → question → simulate → judge → export
│   ├── core/                    # config, logging, common types
│   │   ├── config.py            # pydantic BaseSettings
│   │   └── logging.py
│   └── cli.py                   # `uv run eval-obs ...` entrypoint
└── tests/
    └── (mirrors eval_obs/ layout)
```

## Quick start (once code lands)

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format .

# end-to-end eval run (target shape)
uv run eval-obs run --target agent-factory --persona-set onboarding-v1 --judge default
```

## How it fits with the rest of aiBuilderCore

| Repo | Relationship |
|---|---|
| [ai-builder-meta](https://github.com/aiBuilderCore/ai-builder-meta) | Workspace index + shared Claude config |
| [ai-builder-agent-factory](https://github.com/aiBuilderCore/ai-builder-agent-factory) | Primary system under test — its agents emit the runtime traces this framework consumes and grades |
| [ai-builder-artifacts](https://github.com/aiBuilderCore/ai-builder-artifacts) | Receives eval reports, dashboards, and result decks generated here |
| [ai-builder-first-gcc](https://github.com/aiBuilderCore/ai-builder-first-gcc) | Strategic context driving which evaluation rubrics matter |

## Design principles

- **Reproducibility first.** Every run is keyed by `(persona_set_version, question_strategy_version, target_version, rubric_version)`. Re-running the same key on the same target should produce the same scores within judge variance.
- **Judges are code, not configuration.** Rubric prompts live in `judges/rubrics/` under version control; changing a rubric is a code change with a PR.
- **Don't grade what you can't trace.** Every score must be traceable back to the exact persona, question, and run it came from. Observability is upstream of evaluation, not bolted on.
- **Pluggable targets.** The simulation runner talks to the system under test through a thin adapter; evaluating a new system means writing one adapter, not forking the framework.
