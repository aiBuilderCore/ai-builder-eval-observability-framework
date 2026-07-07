"""Single-table key builders (PK/SK/GSIPK/GSISK) per the framework data model.

Every entity's keys live here so the orchestrator and each service agree on the
exact string layout. Tenant is always the top-level partition prefix, so
isolation is physical, not a filter.
"""

from __future__ import annotations


def _t(tenant: str, family: str) -> str:
    return f"TENANT#{tenant}#{family}"


# --- Persona (persona-lab) ---
def persona_pk(tenant: str) -> str:
    return _t(tenant, "PERSONA")


def persona_sk(persona_id: str, version: str) -> str:
    return f"PERSONA#{persona_id}#{version}"


def persona_gsi(tenant: str, created_at: str) -> tuple[str, str]:
    return _t(tenant, "PERSONA_BY_TIME"), created_at


# --- Seed set / Question (question-generation) ---
def seedset_pk(tenant: str) -> str:
    return _t(tenant, "SEEDSET")


def seedset_sk(seed_set_id: str) -> str:
    return f"SEEDSET#{seed_set_id}"


def seedset_gsi(tenant: str, created_at: str) -> tuple[str, str]:
    return _t(tenant, "SEEDSET_BY_TIME"), created_at


def question_pk(seed_set_id: str) -> str:
    return f"SEEDSET#{seed_set_id}"


def question_sk(question_id: str) -> str:
    return f"QUESTION#{question_id}"


# --- Run / Trace / Adapter (simulation) ---
def run_pk(tenant: str) -> str:
    return _t(tenant, "RUN")


def run_sk(run_id: str) -> str:
    return f"RUN#{run_id}"


def run_gsi(tenant: str, state: str, ts: str) -> tuple[str, str]:
    return _t(tenant, "RUN_BY_STATE"), f"{state}#{ts}"


def trace_pk(run_id: str) -> str:
    return f"RUN#{run_id}"


def trace_sk(trace_id: str) -> str:
    return f"TRACE#{trace_id}"


def adapter_pk(tenant: str) -> str:
    return _t(tenant, "ADAPTER")


def adapter_sk(adapter_id: str, version: int) -> str:
    return f"ADAPTER#{adapter_id}#v{version}"


def adapter_gsi(tenant: str, created_at: str) -> tuple[str, str]:
    return _t(tenant, "ADAPTER_BY_TIME"), created_at


# --- Verdict set / Verdict / Judge / Jury (evaluation) ---
def verdictset_pk(tenant: str) -> str:
    return _t(tenant, "VERDICTSET")


def verdictset_sk(vs_id: str) -> str:
    return f"VERDICTSET#{vs_id}"


def verdictset_gsi(tenant: str, created_at: str) -> tuple[str, str]:
    return _t(tenant, "VERDICTSET_BY_TIME"), created_at


def verdict_pk(vs_id: str) -> str:
    return f"VERDICTSET#{vs_id}"


def verdict_sk(verdict_id: str) -> str:
    return f"VERDICT#{verdict_id}"


def verdict_gsi(run_id: str, verdict_id: str) -> tuple[str, str]:
    return f"RUN#{run_id}", f"VERDICT#{verdict_id}"


def judge_pk(tenant: str) -> str:
    return _t(tenant, "JUDGE")


def judge_sk(name: str, version: int) -> str:
    return f"JUDGE#{name}#v{version}"


def judge_gsi(tenant: str, created_at: str) -> tuple[str, str]:
    return _t(tenant, "JUDGE_BY_TIME"), created_at


def jury_pk(tenant: str) -> str:
    return _t(tenant, "JURY")


def jury_sk(panel_id: str) -> str:
    return f"JURY#{panel_id}"


# --- Job (shared, this index) ---
def job_pk(tenant: str) -> str:
    return _t(tenant, "JOB")


def job_sk(job_id: str) -> str:
    return f"JOB#{job_id}"


def job_gsi(tenant: str, state: str, ts: str) -> tuple[str, str]:
    return _t(tenant, "JOB_BY_STATE"), f"{state}#{ts}"


# --- Observability (monitor / incident / evidence / calibration) ---
def monitor_pk(tenant: str) -> str:
    return _t(tenant, "MONITOR")


def monitor_sk(monitor_id: str, version: int) -> str:
    return f"MONITOR#{monitor_id}#v{version}"


def monitor_gsi(tenant: str, env: str, version: int) -> tuple[str, str]:
    return _t(tenant, "MONITOR_BY_ENV"), f"{env}#{version}"


def incident_pk(tenant: str) -> str:
    return _t(tenant, "INCIDENT")


def incident_sk(incident_id: str) -> str:
    return f"INCIDENT#{incident_id}"


def incident_gsi(tenant: str, state: str, ts: str) -> tuple[str, str]:
    return _t(tenant, "INCIDENT_BY_STATE"), f"{state}#{ts}"


def evidence_pk(tenant: str) -> str:
    return _t(tenant, "EVIDENCE")


def evidence_sk(pack_id: str) -> str:
    return f"EVIDENCE#{pack_id}"


def evidence_gsi(tenant: str, issued_at: str) -> tuple[str, str]:
    return _t(tenant, "EVIDENCE_BY_TIME"), issued_at
