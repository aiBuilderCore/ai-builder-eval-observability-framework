"""Type-prefixed, lexicographically-sortable IDs (ULID-style).

A ULID is 48 bits of millisecond timestamp + 80 bits of randomness, Crockford
base32 encoded — so IDs sort by creation time and collide with negligible
probability. We keep a tiny self-contained implementation to avoid a runtime
dependency. Type prefixes (`p_`, `ss_`, `sim_`, `job_`, `vd_`) match the API
conventions so an ID is self-describing.
"""

from __future__ import annotations

import os
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def ulid() -> str:
    """A 26-char Crockford-base32 ULID."""
    ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    return _encode(ms, 10) + _encode(rand, 16)


# Prefix per entity family, per the framework API conventions.
PREFIX = {
    "persona": "p_",
    "seed_set": "ss_",
    "question": "q_",
    "run": "sim_",
    "trace": "trc_",
    "adapter": "adp_",
    "verdict_set": "vs_",
    "verdict": "vd_",
    "judge": "jd_",
    "jury": "jury_",
    "job": "job_",
    "monitor": "mon_",
    "incident": "inc_",
    "evidence": "ev_",
    "calibration": "cal_",
}


def new_id(kind: str) -> str:
    """Mint a fresh prefixed ID, e.g. new_id('run') -> 'sim_01HX...'."""
    if kind not in PREFIX:
        raise KeyError(f"unknown id kind: {kind!r}")
    return f"{PREFIX[kind]}{ulid()}"
