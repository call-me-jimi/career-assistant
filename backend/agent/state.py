"""LangGraph state for the Personal Application Assistant."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class CoverLetterVersion(BaseModel):
    version_id: str
    text: str
    iteration: int
    hm_score: float | None = None
    hm_feedback: dict[str, Any] | None = None


class QAItem(BaseModel):
    kind: Literal["motivation", "salary", "experience", "custom"]
    question: str
    answer: str = ""


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ExportResult(BaseModel):
    kind: str  # "pdf" | "md" | "json" | "sheets"
    path: str


def _last_write_wins(a: Any, b: Any) -> Any:
    return b if b is not None else a


ASSISTANT_TYPE = Literal["cover_letter", "interview_prep", "career_advisor"]


class ApplicationState(BaseModel):
    """Full application state. LangGraph merges partial updates per node return."""

    session_id: str
    assistant_type: ASSISTANT_TYPE = "cover_letter"

    # Applicant / profile
    applicant_name: str = ""
    profile_id: str | None = None
    profile_reused: bool = False  # True only when an existing profile was loaded via greeting
    cv_text: str = ""
    candidate_profile: str = ""

    # Job / company
    job_url: str = ""
    job_raw_text: str = ""
    job_title: str = ""
    company_name: str = ""
    job_description: str = ""
    company_description: str = ""
    location: str = ""
    job_source_type: Literal["direct", "recruiter", ""] = ""

    # Strategy
    alignment_strategy: str = ""
    inferred_role_context: str = ""
    positioning_strategy: str = ""

    # Cover letter loop
    cover_letter_versions: list[CoverLetterVersion] = Field(default_factory=list)
    best_version_id: str | None = None
    cover_letter: str = ""  # the selected best
    hm_iterations: int = 0

    # Per-revision feedback captured during cl_review (for learning loop)
    revision_feedback: list[dict[str, Any]] = Field(default_factory=list)

    # End-of-session learning synthesis handoff (populated by synthesize_learning,
    # consumed by review_learned_suggestion). None when there is no suggestion to surface.
    pending_suggestion: dict[str, Any] | None = None

    # Q&A
    qa_items: list[QAItem] = Field(default_factory=list)

    # Interview prep
    interview_context: str = ""
    interview_briefing: str = ""
    interview_briefing_versions: list[dict[str, Any]] = Field(default_factory=list)
    interview_revision_feedback: list[dict[str, Any]] = Field(default_factory=list)
    mock_interview_transcript: list[ChatTurn] = Field(default_factory=list)
    interview_extras: list[dict[str, Any]] = Field(default_factory=list)

    # Career advisor
    advisor_transcript: list[ChatTurn] = Field(default_factory=list)
    advisor_swot: str = ""

    # Export
    export_selection: list[str] = Field(default_factory=list)
    export_results: list[ExportResult] = Field(default_factory=list)
    export_delivery: Literal["download", "folder", "both", ""] = ""

    # Phase tracking (for UI / sessions table)
    phase: str = "greeting"

    model_config = ConfigDict(arbitrary_types_allowed=True)
