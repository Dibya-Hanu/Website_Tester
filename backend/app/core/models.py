"""Shared report contract. Tool observations and AI judgments stay distinguishable."""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Pillar(StrEnum):
    FUNCTIONALITY = "functionality"
    SECURITY = "security"
    PERFORMANCE = "performance"
    ACCESSIBILITY = "accessibility"


class Severity(StrEnum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"
    INFO = "Info"


class Location(BaseModel):
    url: str
    selector: str | None = None
    header: str | None = None


class Evidence(BaseModel):
    kind: Literal["snippet", "screenshot", "metric", "observation"] = "snippet"
    detail: str = Field(default="", max_length=6000)
    file: str | None = None


class VerificationSpec(BaseModel):
    kind: str
    data: dict[str, Any] = Field(default_factory=dict)


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    title: str = Field(max_length=240)
    pillar: Pillar
    severity: Severity
    status: Literal["Verified", "Possible"] = "Possible"
    category: str
    location: Location
    evidence: list[Evidence] = Field(default_factory=list)
    explanation: str = Field(max_length=6000)
    suggested_fix: str = Field(max_length=6000)
    sources: list[str] = Field(default_factory=list)
    verification_note: str = "Not independently re-tested."
    ai_assisted: bool = False
    suppressed_reason: str | None = None
    # Never expose request recipes to frontend clients or persist sensitive payloads.
    check: VerificationSpec | None = Field(default=None, exclude=True)
    contradicted: bool = Field(default=False, exclude=True)


class InputField(BaseModel):
    id: str
    selector: str
    name: str = ""
    label: str = ""
    type: str = "text"
    required: bool = False
    min_length: int | None = None
    max_length: int | None = None
    minimum: str | None = None
    maximum: str | None = None
    pattern: str | None = None


class Form(BaseModel):
    id: str
    page_id: str
    selector: str
    action: str
    method: str
    fields: list[InputField]
    text: str = ""
    virtual: bool = False


class PageInfo(BaseModel):
    id: str
    url: str
    depth: int
    title: str = ""
    status_code: int | None = None
    text: str = ""
    links: list[dict[str, str]] = Field(default_factory=list)
    forms: list[Form] = Field(default_factory=list)
    screenshots: dict[str, str] = Field(default_factory=dict)
    classification: str = "other"
    observed_get_requests: list[str] = Field(default_factory=list)
    readiness: dict[str, Any] = Field(default_factory=dict)


class Step(BaseModel):
    id: str
    title: str
    pillar: Pillar | None = None
    status: Literal["pending", "running", "completed", "partial", "skipped", "blocked", "failed"] = "pending"
    detail: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None


class ScanResult(BaseModel):
    status: Literal["completed", "partial", "skipped", "blocked", "failed"] = "completed"
    reason: str = ""
    findings: list[Finding] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class PillarScore(BaseModel):
    score: int | None
    status: Literal["complete", "partial", "blocked", "not_selected", "unassessed"]
    coverage: int
    completed_checks: int
    total_checks: int
    issues: int


class Report(BaseModel):
    schema_version: str = "1.0"
    sample: bool = False
    id: str
    url: str
    created_at: str
    finished_at: str
    duration_seconds: float
    selected_pillars: list[Pillar]
    authorized: bool
    overall_score: int | None
    coverage: int
    partial: bool
    summary: str
    priorities: list[str] = Field(default_factory=list)
    scores: dict[Pillar, PillarScore]
    findings: list[Finding]
    suppressed_findings: list[Finding] = Field(default_factory=list)
    steps: list[Step]
    pages: list[PageInfo]
    flows: list[dict[str, Any]] = Field(default_factory=list)
    diagnostic_plan: list[dict[str, Any]] = Field(default_factory=list)
    test_cases: list[dict[str, Any]] = Field(default_factory=list)
    ai_tasks: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    tool_versions: dict[str, str] = Field(default_factory=dict)


class CreateJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=2048)
    pillars: list[Pillar] = Field(default_factory=lambda: list(Pillar), min_length=1, max_length=4)

    @field_validator("pillars")
    @classmethod
    def distinct(cls, value: list[Pillar]) -> list[Pillar]:
        return list(dict.fromkeys(value))
