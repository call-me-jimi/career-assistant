"""Pydantic schemas for structured LLM outputs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HiringManagerFeedback(BaseModel):
    overall_score: float = Field(ge=0.0, le=10.0)
    decision: str  # "YES" | "MAYBE" | "NO"
    first_impression: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    reasoning: str = ""


class ComparisonResult(BaseModel):
    recommended_version_id: str
    reasoning: str = ""
