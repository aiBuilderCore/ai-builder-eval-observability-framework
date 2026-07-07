"""Unit tests for the shared core: ids, keys, hashing, deterministic provider."""

from __future__ import annotations

import time

import pytest

from eeof_core.dataplane import keys, subject_matches
from eeof_core.ids import new_id, ulid
from eeof_core.messaging import config_hash
from eeof_core.models import bump, slug
from eeof_core.providers.echo import EchoProvider


def test_ulid_is_time_sortable():
    a = ulid()
    time.sleep(0.002)
    b = ulid()
    assert a < b  # lexicographic order tracks creation time


def test_prefixed_ids():
    assert new_id("run").startswith("sim_")
    assert new_id("verdict").startswith("vd_")


def test_config_hash_is_order_independent():
    assert config_hash({"a": 1, "b": 2}) == config_hash({"b": 2, "a": 1})
    assert config_hash({"a": 1}) != config_hash({"a": 2})


def test_key_layout():
    assert keys.persona_pk("acme") == "TENANT#acme#PERSONA"
    assert keys.persona_sk("persona_x", "1.2.0") == "PERSONA#persona_x#1.2.0"
    gsipk, gsisk = keys.run_gsi("acme", "ready", "2026-05-04T09:51:07Z")
    assert gsipk == "TENANT#acme#RUN_BY_STATE"
    assert gsisk == "ready#2026-05-04T09:51:07Z"


def test_subject_matching():
    assert subject_matches("status.>", "status.sim.job_1")
    assert subject_matches("status.sim.*", "status.sim.job_1")
    assert not subject_matches("status.sim.*", "status.eval.job_1")
    assert subject_matches("trace.events.>", "trace.events.sim_123")


def test_semver_helpers():
    assert slug("Onboarding Olivia") == "onboarding_olivia"
    assert bump("1.2.0", "major") == "2.0.0"
    assert bump("1.2.0", "minor") == "1.3.0"
    assert bump("1.2.3", "patch") == "1.2.4"


@pytest.mark.asyncio
async def test_echo_provider_is_deterministic():
    p = EchoProvider()
    s1 = await p.score(rubric="helpfulness", prompt="hi", response="hello")
    s2 = await p.score(rubric="helpfulness", prompt="hi", response="hello")
    assert s1 == s2
    assert 0.0 <= s1["score"] <= 1.0
    assert isinstance(s1["passed"], bool)
