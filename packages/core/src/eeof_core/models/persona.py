"""Persona contract — Persona Lab's single output (see persona-lab spec)."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from .common import iso

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class Tone(StrEnum):
    formal = "formal"
    casual = "casual"
    blunt = "blunt"
    frustrated = "frustrated"
    playful = "playful"


class TechSavviness(StrEnum):
    novice = "novice"
    intermediate = "intermediate"
    advanced = "advanced"


class Hue(StrEnum):
    ochre = "ochre"
    sage = "sage"
    rose = "rose"
    olive = "olive"
    plum = "plum"
    rust = "rust"
    terracotta = "terracotta"


class PersonaDraft(BaseModel):
    name: str
    quote: str = ""
    role: str = ""
    age_band: str = ""
    locale: str = ""
    tech_savviness: TechSavviness = TechSavviness.intermediate
    tone: Tone = Tone.casual
    goals: list[str] = Field(default_factory=list)
    edge_cases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    hue: Hue = Hue.ochre
    version: str = "1.0.0"
    # Downstream-contract fields (planned in the spec; accepted here with defaults).
    primary_rubric: str = "helpfulness"
    default_shapes: list[str] = Field(default_factory=list)
    default_scenarios: list[str] = Field(default_factory=list)

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not SEMVER.match(v):
            raise ValueError("version must be semver (\\d+.\\d+.\\d+)")
        return v


class Persona(PersonaDraft):
    id: str
    created_at: str = Field(default_factory=iso)
    updated_at: str = Field(default_factory=iso)
    created_by: str = "nitin@acme"
    archived: bool = False


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "persona"


def bump(version: str, level: str) -> str:
    major, minor, patch = (int(x) for x in version.split("."))
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"
