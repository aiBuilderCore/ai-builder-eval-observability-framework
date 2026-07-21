"""Agent-side remediation playbook — trace-grounded fixes per breached judge.

Self-Heal has NO access to the agent's source code — only its **trace** (the OTel /
OpenInference span tree: the PROMPT span's system prompt, the LLM response, tool-call
spans, retrieval spans, model params). So every recommendation here is grounded in
what the trace observably shows and phrased as a change the agent team makes — never
as code we pretend to have read. Where the fix is a system-prompt change, the prompt
itself lives in the trace's PROMPT span, so the UI can quote the exact offending
clause verbatim; `flags` are the offending phrase fragments to extract/highlight from
that captured prompt.

`surface`  = the part of the trace/agent to change.
`summary`  = the one-line mitigation.
`evidence` = what the trace shows that proves the breach (trace-only signal).
`steps`    = concrete recommended changes (advice to the agent team).
`fix`      = a recommended replacement *system-prompt clause* (prompt-fixable dims
             only; the "incorrect" side is pulled from the trace, not stored here).
`flags`    = offending prompt fragments to highlight in the captured system prompt.
`reference`= the standard the fix satisfies.

Deterministic guidance grounded in the failure class and the judge's research
pattern (see `models.judge_catalog`). Synthetic-safe; no fabricated metrics or code.
"""

from __future__ import annotations

from typing import Any

REMEDIATION_PLAYBOOK: dict[str, dict[str, Any]] = {
    "no_financial_advice": {
        "surface": "System prompt (PROMPT span) + response guardrail",
        "summary": "Constrain the agent to educator-not-fiduciary scope and reject "
        "individualized buy/sell/allocation directives in the response.",
        "evidence": "The captured system prompt directs the agent to give an "
        "individualized recommendation — name specific funds and an allocation, say "
        "whether to buy or sell, and skip the advisor referral.",
        "steps": [
            "Rewrite the scope clause in the system prompt: educate and present options; "
            "never name specific securities/tickers or allocations, and never tell the "
            "user to buy/sell/hold — defer individualized decisions to a licensed advisor.",
            "Add a response guardrail (regex + classifier) that blocks or rewrites any "
            "answer containing directives or ticker symbols before it returns.",
            "Re-assert the scope in the per-turn preamble so multi-turn follow-ups don't "
            "inherit the user's “just tell me what to buy” framing.",
        ],
        "fix": "Educate and lay out the trade-offs. Do not name specific funds, tickers, "
        "or allocations, and do not tell the user to buy/sell/hold. Direct individualized "
        "decisions to a licensed advisor.",
        "flags": [
            "individualized recommendation", "name specific funds", "target allocation",
            "buy or sell", "do not tell them to consult a licensed financial advisor",
        ],
        "reference": "FINRA Rule 2111 (suitability) — fiduciary scope",
    },
    "regulatory_disclosure": {
        "surface": "System prompt (PROMPT span) + response template",
        "summary": "Require the mandatory disclaimers whenever the answer touches tax, "
        "legal, or performance topics.",
        "evidence": "The captured system prompt suppresses disclaimers (“do not add "
        "disclaimers”, “do not hedge”), and the response omits the required language.",
        "steps": [
            "Remove the disclaimer-suppression clause from the system prompt.",
            "Attach the required disclaimer block (from a versioned template) whenever a "
            "disclosure trigger — tax/legal guidance, projections, past performance — appears.",
            "Add a response check that fails when a trigger is present but the disclaimer "
            "is missing.",
        ],
        "fix": "When you discuss tax, legal, or performance topics, state that this is "
        "general information (not tax/legal advice), that past performance is not "
        "indicative of future results, and to consult a licensed professional.",
        "flags": ["do not add disclaimers", "do not hedge"],
        "reference": "Required-disclaimer checklist",
    },
    "numeric_accuracy": {
        "surface": "Response numbers vs. tool spans",
        "summary": "Move quoted numbers out of the model into a deterministic tool, and "
        "recompute anything the response cites.",
        "evidence": "The response quotes figures (limits, match, projections) that no "
        "tool span produced — they came from the model, and the verifier couldn't reconcile them.",
        "steps": [
            "Compute contribution limits, employer match, and projections in a calculator "
            "tool and have the agent cite the tool result, not compute inline.",
            "Add a numeric post-validator that recomputes every figure the answer quotes "
            "and blocks on any mismatch.",
            "Ground IRS limits and match rules in a versioned config, not model memory.",
        ],
        "fix": None,
        "flags": [],
        "reference": "Deterministic arithmetic verifier",
    },
    "hallucination": {
        "surface": "Retrieval spans + system prompt (PROMPT span)",
        "summary": "Require source-grounded claims and cite-or-abstain; refresh the "
        "stale knowledge the breach surfaced.",
        "evidence": "The system prompt pushes the agent to be maximally decisive and "
        "“give the answer they want”, and the response makes claims with no supporting "
        "retrieval span.",
        "steps": [
            "Instruct the agent to answer only from retrieved context and cite the source "
            "span; say it doesn't know when unsupported.",
            "Add a groundedness check (NLI / claim-verifier) over the answer vs the "
            "retrieved context and fail closed on unsupported claims.",
            "Re-index / refresh the knowledge-base entries the incident's traces flagged.",
        ],
        "fix": "Answer only from the retrieved context and cite the source span. If the "
        "context doesn't cover it, say you don't have that information.",
        "flags": ["be maximally helpful and decisive", "just give them the answer they want"],
        "reference": "Lynx / HaluBench groundedness",
    },
    "faithfulness": {
        "surface": "Retrieval spans",
        "summary": "Constrain the answer to claims entailed by the retrieved context.",
        "evidence": "Claims in the response aren't entailed by the spans returned by the "
        "RETRIEVER — the supporting context is missing or wasn't used.",
        "steps": [
            "Verify each drafted claim is entailed by the retrieved context before returning.",
            "Tighten retrieval (chunking + re-rank) so the supporting spans are actually "
            "in context.",
            "Drop or flag any claim with no supporting span.",
        ],
        "fix": None,
        "flags": [],
        "reference": "RAGAS claim decomposition",
    },
    "answer_relevance": {
        "surface": "System prompt (PROMPT span) + response",
        "summary": "Tighten answer-to-question alignment and route off-topic queries to a "
        "clarifying turn.",
        "evidence": "The response is coherent but doesn't address the user turn captured "
        "in the trace — the regenerated question diverges from what was asked.",
        "steps": [
            "Have the agent restate the user's actual question before answering.",
            "Add a relevance self-check (regenerate the question from the answer; bail if "
            "it diverges).",
            "Route ambiguous or off-topic queries to a clarification prompt instead of "
            "answering something adjacent.",
        ],
        "fix": None,
        "flags": [],
        "reference": "RAGAS answer-relevance round-trip",
    },
    "pii_leakage": {
        "surface": "Response egress",
        "summary": "Add a PII/PHI egress filter that redacts entities not present in the "
        "user's own turn.",
        "evidence": "The response emits personal/protected data (names, account, health "
        "facts) that doesn't appear in the user turn captured in the trace.",
        "steps": [
            "Run a Presidio-style detector on every response (and on tool outputs before "
            "they reach the model).",
            "Redact or block names, SSNs, account/health data the user didn't provide.",
            "Scope retrieval so records for other users can't enter context.",
        ],
        "fix": None,
        "flags": [],
        "reference": "Presidio-style PII/PHI detection",
    },
    "toxicity": {
        "surface": "Response egress",
        "summary": "Add a toxicity classifier on the response and regenerate above threshold.",
        "evidence": "The response text captured in the trace scores above the toxicity gate.",
        "steps": [
            "Score every response with a toxicity classifier before return.",
            "Regenerate (or fall back to a safe template) when the score crosses the gate.",
            "Log flagged generations for prompt/guardrail tuning.",
        ],
        "fix": None,
        "flags": [],
        "reference": "Detoxify-style classifier",
    },
    "refusal_correctness": {
        "surface": "System prompt (PROMPT span) + exemplars",
        "summary": "Calibrate the refusal policy — refuse cleanly when required, stop "
        "over-refusing benign requests.",
        "evidence": "The trace shows the agent refusing a benign request (or answering one "
        "it should refuse) — the refusal decision is miscalibrated.",
        "steps": [
            "Add expected-behavior exemplars for both directions (must-refuse and "
            "must-answer) to the system prompt.",
            "Give a clean, reasoned refusal template instead of a curt block.",
            "Add benign-request exemplars to cut false refusals.",
        ],
        "fix": None,
        "flags": [],
        "reference": "Expected-behavior-aware refusal",
    },
    "role_adherence": {
        "surface": "System prompt (PROMPT span)",
        "summary": "Strengthen persona/system anchoring and add a role-consistency check.",
        "evidence": "The response drifts out of the role defined in the captured system "
        "prompt (tone break, or system-instruction leakage in the completion).",
        "steps": [
            "Anchor the role at the top of every turn and forbid revealing system "
            "instructions.",
            "Add a role-consistency check across the conversation; flag out-of-character drift.",
            "Add prompt-leak guards (never echo the system prompt).",
        ],
        "fix": None,
        "flags": [],
        "reference": "DeepEval role-adherence",
    },
    "tool_call_correctness": {
        "surface": "Tool-call spans",
        "summary": "Validate tool calls, guard arguments, and cap retry depth to stop "
        "loops and wrong-argument calls.",
        "evidence": "The TOOL spans show malformed arguments / a retry loop (e.g. null "
        "argument re-tried, or depth exceeded) against the golden trajectory.",
        "steps": [
            "Validate every tool call against its JSON schema and reject malformed args.",
            "Short-circuit null-argument retries and cap tool-call depth with a fall-back.",
            "Add golden-trajectory regression tests for the flows the incident flagged.",
        ],
        "fix": None,
        "flags": [],
        "reference": "AgentBench trajectory match",
    },
    "coherence_multiturn": {
        "surface": "Conversation spans",
        "summary": "Carry a running state summary and check for cross-turn contradictions.",
        "evidence": "Across the turn spans, the agent contradicts an earlier turn or drops "
        "a thread it committed to.",
        "steps": [
            "Maintain a compact running summary of commitments/facts across turns.",
            "Add a contradiction check against prior turns before replying.",
            "Resolve or surface dropped threads instead of silently forgetting them.",
        ],
        "fix": None,
        "flags": [],
        "reference": "DeepEval conversation-completeness",
    },
    "demographic_fairness": {
        "surface": "Response (counterfactual)",
        "summary": "Add a counterfactual token-swap parity test and debias the prompt.",
        "evidence": "Swapping demographic tokens in the user turn shifts the response's "
        "quality or stance — the trace pair scores unequally.",
        "steps": [
            "Add a CI check that swaps demographic tokens and fails when answer "
            "quality/stance shifts.",
            "Remove demographic conditioning from the prompt; treat equivalent users equally.",
            "Track parity as a release gate for this agent.",
        ],
        "fix": None,
        "flags": [],
        "reference": "Counterfactual token-swap (CrowS-Pairs)",
    },
    "factual_consistency": {
        "surface": "Response vs. reference",
        "summary": "Gate the answer on an AlignScore-style NLI consistency check.",
        "evidence": "The response is not entailed by the reference text — NLI consistency "
        "is below the gate.",
        "steps": [
            "Score answer-vs-reference consistency with an NLI model before return.",
            "Block or flag responses below the consistency gate.",
            "Ground claims in the reference text.",
        ],
        "fix": None,
        "flags": [],
        "reference": "AlignScore NLI",
    },
    "helpfulness": {
        "surface": "System prompt (PROMPT span) + response",
        "summary": "Improve instruction-following so the answer actually resolves the ask.",
        "evidence": "The response captured in the trace leaves part of the user's request "
        "unaddressed.",
        "steps": [
            "Add form-fill / rubric exemplars of a complete answer for this task.",
            "Have the agent confirm it addressed each part of the request.",
            "Pair with a helpfulness-rubric persona in the next eval to confirm the lift.",
        ],
        "fix": None,
        "flags": [],
        "reference": "G-Eval helpfulness rubric",
    },
}

DEFAULT_RECOMMENDATION: dict[str, Any] = {
    "surface": "System prompt + response guardrail",
    "summary": "Harden the agent for this dimension and lock it in with a test.",
    "evidence": "The flagged traces show the breaching behaviour for this dimension.",
    "steps": [
        "Review the flagged traces to pin the exact failing behaviour.",
        "Tighten the system prompt for this dimension and add a response guardrail.",
        "Add a regression test on the flagged traces so the breach can't silently return.",
    ],
    "fix": None,
    "flags": [],
    "reference": None,
}


def recommendation_for(dim: str | None) -> dict[str, Any]:
    """Return the agent-side remediation recommendation for a breached dimension,
    falling back to a sensible generic playbook entry."""
    if not dim:
        return DEFAULT_RECOMMENDATION
    return REMEDIATION_PLAYBOOK.get(dim.split("@")[0], DEFAULT_RECOMMENDATION)
