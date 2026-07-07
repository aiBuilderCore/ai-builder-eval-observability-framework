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
    #   echo         -> deterministic, offline, reproducible (default)
    #   anthropic    -> Anthropic Messages API
    #   bedrock      -> AWS Bedrock Converse API (boto3)
    #   azure_openai -> Azure OpenAI Chat Completions (REST)
    model_provider: Literal["echo", "anthropic", "bedrock", "azure_openai"] = "echo"
    model_name: str = "claude-opus-4-8"

    # Anthropic
    anthropic_api_key: str = ""

    # AWS Bedrock (uses the standard AWS credential chain unless keys are set here)
    bedrock_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # Azure OpenAI
    azure_openai_endpoint: str = ""  # https://<resource>.openai.azure.com
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""  # deployment name
    azure_openai_api_version: str = "2024-08-01-preview"

    # Ports — the orchestrator is the only public edge; the rest are in-cluster.
    api_orchestration_port: int = 8080
    persona_svc_port: int = 8091
    judge_registry_port: int = 8092
    qgen_svc_port: int = 8093
    simulation_svc_port: int = 8094
    evaluation_svc_port: int = 8095
    observability_svc_port: int = 8096

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
