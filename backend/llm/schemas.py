"""Pydantic schemas for structured LLM outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HiringManagerFeedback(BaseModel):
    overall_score: float = Field(ge=0.0, le=10.0)
    decision: str  # "YES" | "MAYBE" | "NO"
    first_impression: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    reasoning: str = ""


class CommunicationMetrics(BaseModel):
    pace: Literal["too_fast", "appropriate", "too_slow"]
    filler_words: list[str] = Field(default_factory=list)
    clarity: str = ""
    structure: str = ""


class QuestionAnalysis(BaseModel):
    question: str
    answer_summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    suggested_improvement: str = ""


class InterviewEvaluation(BaseModel):
    overall_score: float = Field(ge=0.0, le=10.0)
    decision: Literal["YES", "MAYBE", "NO"]
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    communication: CommunicationMetrics
    per_question: list[QuestionAnalysis] = Field(default_factory=list)
