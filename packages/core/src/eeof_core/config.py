"""Runtime configuration, read from the environment (see .env.example).

One `settings` singleton is shared by every service. The only switch that
changes wiring is `app_env`: `local` selects the in-memory data plane and needs
no external process; `infra` points the same interfaces at ScyllaDB/NATS/MinIO.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "infra"] = "local"

    # Demo seeding switch. When true (default) a fresh boot seeds the demo
    # lineage (runs/verdicts/batches), the built-in agent-under-test adapter, and
    # the self-heal incident backlog so the dashboards have rows to aggregate.
    # Set SEED_DEMO=0 to boot a clean slate: only the core persona + judge
    # libraries load lazily on first access; adapters, runs, verdicts, and
    # self-heal incidents all start empty so an operator can drive the whole
    # pipeline by hand and watch real data appear only after each stage runs.
    seed_demo: bool = True

    # Data plane (infra mode)
    scylla_endpoint: str = "http://localhost:8000"
    scylla_region: str = "us-east-1"
    scylla_table: str = "platform"
    nats_url: str = "nats://localhost:4222"
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "eeof-blobs"

    # Model provider — every real backend is invoked over its HTTP/API surface.
    #   azure_openai -> Azure OpenAI Chat Completions (REST) — the default (GPT-4)
    #   groq         -> Groq OpenAI-compatible Chat Completions (REST)
    #   anthropic    -> Anthropic Messages API
    #   bedrock      -> AWS Bedrock Converse API (boto3)
    #   echo         -> deterministic, offline, reproducible fallback
    # The factory builds a *fallback chain*: primary (`model_provider`) → the
    # `model_fallback` backend → `echo`. Any backend whose credentials are absent
    # is skipped, so a from-scratch checkout still boots (see providers/__init__.py).
    # Default wiring: Azure OpenAI GPT-4 primary, Groq fallback. With Azure creds
    # blank, calls resolve straight to Groq; with neither set, to offline `echo`.
    model_provider: Literal["echo", "anthropic", "bedrock", "azure_openai", "groq"] = "azure_openai"
    model_name: str = "gpt-4"
    # Secondary backend tried when the primary is unavailable or errors.
    # Empty string disables fallback (primary → echo only).
    model_fallback: Literal["", "echo", "anthropic", "bedrock", "azure_openai", "groq"] = "groq"

    # Anthropic
    anthropic_api_key: str = ""

    # Groq — OpenAI-compatible endpoint; fastest hosted open-weight inference.
    # Used as the default fallback for Azure OpenAI. Get a key at
    # https://console.groq.com/keys
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_endpoint: str = "https://api.groq.com/openai/v1"

    # AWS Bedrock (uses the standard AWS credential chain unless keys are set here)
    bedrock_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # Azure OpenAI — the default backend. Point these at your GPT-4 deployment.
    azure_openai_endpoint: str = ""  # https://<resource>.openai.azure.com
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4"  # deployment name
    azure_openai_api_version: str = "2024-08-01-preview"

    @property
    def azure_openai_ready(self) -> bool:
        return bool(
            self.azure_openai_endpoint
            and self.azure_openai_api_key
            and self.azure_openai_deployment
        )

    @property
    def groq_ready(self) -> bool:
        return bool(self.groq_api_key and self.groq_model)

    # Ports — the orchestrator is the only public edge; the rest are in-cluster.
    api_orchestration_port: int = 8080
    persona_svc_port: int = 8091
    judge_registry_port: int = 8092
    qgen_svc_port: int = 8093
    simulation_svc_port: int = 8094
    evaluation_svc_port: int = 8095
    observability_svc_port: int = 8096
    # The demo agent-under-test (401k retirement planner) served over REST.
    agent_under_test_port: int = 8097
    # Self-Heal — closed-loop remediation (gate → RCA → simulate → remediate).
    self_heal_svc_port: int = 8098

    @property
    def agent_under_test_url(self) -> str:
        return f"http://127.0.0.1:{self.agent_under_test_port}/chat"

    # Dev auth: any bearer token resolves to this tenant/workspace in local mode.
    dev_tenant: str = "acme"
    dev_workspace: str = "trust-and-safety"

    @property
    def is_local(self) -> bool:
        return self.app_env == "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
