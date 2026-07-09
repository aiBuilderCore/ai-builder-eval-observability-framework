"""Breach → Self-Heal incident detection.

Closes the observability→self-heal seam described in `models/selfheal.py`: *"An
Observability gate/drift breach opens a `SelfHealIncident`."* When an evaluation
job finishes, this module inspects the real verdicts and opens an incident for
every judge dimension whose failure rate crosses that judge's own guardrail.

Everything on the incident is **derived from real verdict rows** — the failing
agent, the breached judge, the actual failure rate, the real flagged trace refs,
and a real judge rationale. It is deliberately *detect-only*: the candidate
`fix`, `confidence`, and the simulate/remediate stages are left empty because
those require an RCA/simulate agent that the pipeline does not automate. The UI
renders those as honest "pending" states rather than fabricating evidence.

Runs from the evaluation worker over the shared data plane (the same cross-domain
table write the worker already does for judge-calibration records), so it never
introduces a service→service import.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from eeof_core.dataplane import get_table, keys
from eeof_core.models import Verdict, VerdictSet
from eeof_core.models.judge_catalog import CORE_JUDGES, JUDGE_PILLARS
from eeof_core.models.selfheal import IncidentTrace, SelfHealIncident, TimelineStep

# judge/dimension name → thresholds, keyed by both the judge `name` and its
# scored `dimension` so either identifier on a verdict resolves.
_JUDGE_THRESHOLD: dict[str, float] = {}
for _j in CORE_JUDGES:
    _JUDGE_THRESHOLD[_j["name"]] = _j.get("threshold", 0.7)
    _JUDGE_THRESHOLD[_j.get("dimension", _j["name"])] = _j.get("threshold", 0.7)

# Small pillar/dimension → UI glyph map (icons the Self-Heal queue understands).
_GLYPH = {
    "Safety": "finance",
    "Privacy": "parser",
    "Reliability": "retriever",
    "Explainability": "prompt",
    "Transparency": "prompt",
    "Fairness": "chat",
}
_DIM_GLYPH = {
    "no_financial_advice": "finance",
    "hallucination": "chat",
    "faithfulness": "retriever",
    "tool_call_correctness": "tool",
    "pii_leakage": "parser",
}

# Breached dimension → the candidate remediation action(s) the RCA agent would
# most plausibly draw from the fixed registry vocabulary (see
# `models/selfheal.py::RemediationAction`). This is NOT a fabricated fix — it is
# a deterministic proposal grounded in the failure class, surfaced in the UI as a
# *proposed* action pending RCA. Names mirror the seeded registry labels so the
# modal chips read identically to the "Remediation registry" card.
_PROPOSED_ACTION = {
    "numeric_accuracy": "Guardrail tweak · KB update",
    "regulatory_disclosure": "Prompt rewrite · Guardrail tweak",
    "no_financial_advice": "Guardrail tweak · Prompt rewrite",
    "hallucination": "KB update · Re-rank tune",
    "faithfulness": "Re-rank tune · KB update",
    "tool_call_correctness": "Fall-back · Circuit break",
    "pii_leakage": "Guardrail tweak · Circuit break",
}


def _proposed_action(dim: str) -> str:
    return _PROPOSED_ACTION.get(dim.split("@")[0], "Guardrail tweak")


def _threshold(dim: str) -> float:
    return _JUDGE_THRESHOLD.get(dim.split("@")[0], 0.7)


def _incident_id(vset_id: str, dim: str) -> str:
    """Deterministic id per (verdict set, dimension) → idempotent re-detection."""
    h = hashlib.sha256(f"{vset_id}:{dim}".encode()).hexdigest()[:12]
    return f"inc_{h}"


async def _match_policy(tenant: str, dim: str) -> tuple[str | None, float | None]:
    """Best-effort: match the breached dimension to a governing policy by scanning
    real `heal_policy` rows' triggers. Returns (policy_name, band) or (None, None)
    when self-heal policies have not been seeded yet."""
    try:
        rows = await get_table().query(keys.heal_policy_pk(tenant), "HEAL_POLICY#")
    except Exception:
        return None, None
    for r in rows:
        data = r.get("data", {})
        if dim in (data.get("trigger") or ""):
            return data.get("name"), data.get("band")
    return None, None


async def detect_incidents(
    tenant: str,
    vset: VerdictSet,
    verdicts: list[Verdict],
    agent_name: str,
) -> list[str]:
    """Open a Self-Heal incident for every judge dimension that breached its
    guardrail in this verdict set. Idempotent. Returns the opened incident ids."""
    by_dim: dict[str, list[Verdict]] = defaultdict(list)
    for v in verdicts:
        by_dim[v.dimension].append(v)

    opened: list[str] = []
    table = get_table()
    for dim, group in by_dim.items():
        fails = [v for v in group if not v.passed]
        if not fails:
            continue
        fail_rate = len(fails) / len(group)
        threshold = _threshold(dim)
        # A stricter judge (higher pass threshold) tolerates fewer failures. The
        # guardrail budget is derived directly from that threshold, so the breach
        # test is grounded in the judge's own bar rather than a magic constant.
        budget = round(1 - threshold, 4)
        if fail_rate <= budget:
            continue

        inc_id = _incident_id(vset.id, dim)
        pk, sk = keys.heal_incident_pk(tenant), keys.heal_incident_sk(inc_id)
        if await table.get(pk, sk):
            continue  # already opened for this verdict set + dimension

        pillar = JUDGE_PILLARS.get(dim.split("@")[0], "Reliability")
        glyph = _DIM_GLYPH.get(dim.split("@")[0], _GLYPH.get(pillar, "chat"))
        policy, band = await _match_policy(tenant, dim)

        # Real flagged traces — the sessions that actually failed this judge.
        traces = [
            IncidentTrace(
                id=v.trace_id,
                agent=agent_name,
                intent=(v.persona_name or "unknown persona"),
                meta=f"score {v.score:.2f} · {dim} fail",
            )
            for v in fails[:6]
        ]
        rationale = next((v.rationale for v in fails if v.rationale), "")

        inc = SelfHealIncident(
            id=inc_id,
            glyph=glyph,
            agent=agent_name,
            failure=f"{dim} guardrail breach",
            pillars=[pillar],
            stage="rca",
            age="just now",
            status="open",
            dispo="Diagnosing · RCA",
            dispo_class="idle",
            policy=policy,
            band=band,
            confidence=None,
            action=_proposed_action(dim),
            incident_from=vset.id,
            timeline=[
                TimelineStep(
                    stage="gate", status="done", when="just now",
                    note=(
                        f"{dim} judge fired: {len(fails)}/{len(group)} verdicts "
                        f"({fail_rate:.0%}) failed, above the {budget:.0%} "
                        f"guardrail budget (judge threshold {threshold:.2f})."
                    ),
                ),
                TimelineStep(
                    stage="rca", status="active", when="just now",
                    note=(
                        "Diagnosing from the real judge rationale: "
                        f"“{rationale}”" if rationale else
                        "Diagnosing the breached transcripts — no rationale on record."
                    ),
                ),
                TimelineStep(
                    stage="simulate", status="queued", when="queued",
                    note="Pending RCA — candidate rehearsal is not automated in this build.",
                ),
                TimelineStep(
                    stage="remediate", status="queued", when="queued",
                    note="Not started.",
                ),
            ],
            fix=None,
            traces=traces,
        )
        gsipk, gsisk = keys.heal_incident_gsi(tenant, inc.status, inc.opened_at)
        await table.put({
            "PK": pk, "SK": sk, "GSIPK": gsipk, "GSISK": gsisk,
            "type": "heal_incident",
            "data": inc.model_dump(mode="json"),
        })
        opened.append(inc_id)

    return opened
