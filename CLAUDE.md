# ai-builder-eval-observability-framework

Evaluation + observability framework for aiBuilderCore agentic / GenAI applications. See `README.md` for the architectural overview.

## Stack

- Python `>=3.13`, managed with `uv`
- pydantic for all I/O and schema contracts
- OpenTelemetry for tracing/metric export (OTLP)
- pytest for tests, ruff for lint/format

## Common commands

- Install/sync deps: `uv sync`
- Add a dep: `uv add <pkg>` (use `uv add --dev <pkg>` for dev tools)
- Run tests: `uv run pytest`
- Lint: `uv run ruff check .`
- Format: `uv run ruff format .`
- Run an eval pipeline (target shape): `uv run eval-obs run --target <name> --persona-set <id> --judge <id>`

## Conventions

- **Always use `uv run`** for Python invocations — never bare `python` or `pip`.
- **`pyproject.toml` is the source of truth** for deps; never hand-edit `uv.lock`.
- **Type hints required** on all public functions, pydantic models, and judge outputs. Treat missing hints as a lint failure.
- **Pydantic for every cross-boundary shape** — personas, questions, run traces, judge verdicts, metric records. No untyped dicts at module boundaries.
- **Async-first I/O.** Anything that calls an LLM, target system, or exporter is `async def`. Wrap sync libs with `asyncio.to_thread`.
- **Determinism is a feature.** Seeds are explicit inputs to persona generation, question generation, and any sampling judge. Don't read entropy from `random` / `time` without threading through a seed.
- **No print statements.** Use the configured logger from `eval_obs/core/logging.py` (once it exists). Logs go through the structured logger so observability exporters can pick them up.
- **Judges are code.** Rubric prompts live under `eval_obs/judges/rubrics/` and are versioned. Editing a rubric is a code change — bump the rubric version in the same PR.
- **One concern per module.** A persona generator does not call a judge. A judge does not export traces. The orchestrator in `eval_obs/pipelines/` is the only place phases are stitched together.

## Hard rules

- **Never commit secrets.** LLM API keys (Anthropic, OpenAI, etc.), OTLP endpoints with embedded creds, dataset URIs with tokens — all go in `.env` (gitignored) and are read via pydantic `BaseSettings` in `eval_obs/core/config.py`.
- **Never commit recorded eval runs, persona libraries, or model outputs as fixtures unless they're explicitly anonymized and redacted.** Real interaction data leaks PII.
- **Don't introduce competing eval frameworks.** This repo owns the eval loop; don't pull in ragas, deepeval, promptfoo, etc. without explicit user agreement. If a piece of one is genuinely useful, vendor the specific helper, don't take the whole framework.
- **Don't bypass the trace.** Every judge verdict must be reachable from the run trace it scored. No "side-channel" scoring that isn't tied back to a `RunTrace` id.
- **Don't grade in the simulator or simulate in the judge.** Crossing those boundaries breaks reproducibility — keep `simulation/` and `judges/` independent.
- **Don't mix sync and async carelessly.** Same rule as `ai-builder-agent-factory`: wrap sync I/O with `asyncio.to_thread`, don't make the whole pipeline sync.

## Where to put what

| Concern | Location |
|---|---|
| New synthetic-user generator or persona schema | `eval_obs/persona_lab/` |
| New question / prompt generation strategy | `eval_obs/question_generation/strategies.py` |
| New target-system adapter (system under test) | `eval_obs/simulation/adapters/<target>.py` |
| New judge or rubric | `eval_obs/judges/` (rubric prompt under `judges/rubrics/<name>/`) |
| New trace / metric exporter | `eval_obs/observability/exporters.py` |
| End-to-end eval orchestration | `eval_obs/pipelines/orchestrator.py` |
| Config / env vars | `eval_obs/core/config.py` |
| Tests | `tests/` mirroring `eval_obs/` layout |

## Versioning eval artifacts

Every reproducible eval run is keyed by a tuple of versions. When you change one of these, bump its version in the same PR:

- `persona_set_version` — `eval_obs/persona_lab/library.py`
- `question_strategy_version` — `eval_obs/question_generation/strategies.py`
- `rubric_version` — per-rubric, in the rubric's metadata
- `target_version` — supplied by the system under test (e.g. agent-factory git SHA)

Result records that don't carry all four are invalid and will be rejected by the orchestrator.

## Notes

- This is the **placeholder phase** — the package directories exist but modules are empty. When scaffolding, follow the layout in `README.md` and the conventions here.
- Telemetry contracts will be defined jointly with [ai-builder-agent-factory](https://github.com/aiBuilderCore/ai-builder-agent-factory) — coordinate before changing trace schemas.
