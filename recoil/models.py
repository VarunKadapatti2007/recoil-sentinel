"""Pydantic data contracts mirroring the SQLite schema (see recoil/db.py)."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high", "critical"]
CaseStatus = Literal["active", "muted"]
Verdict = Literal["PASS", "BLOCK"]
Priority = Literal["P1", "P2", "P3", "P4"]


class TriageOutput(BaseModel):
    """Structured output contract of the demo agent under test."""

    queue: str
    priority: Priority
    escalate: bool
    on_call_paged: bool
    reason: str


class Span(BaseModel):
    name: str
    type: Literal["llm", "tool", "retrieval"]
    start_ms: float
    end_ms: float
    model: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class AgentVersion(BaseModel):
    id: str
    label: str
    system_prompt: str
    model: str
    params: dict[str, Any] = Field(default_factory=dict)
    parent_version_id: Optional[str] = None
    is_published: bool = False
    created_at: str


class Run(BaseModel):
    id: str
    agent_version_id: str
    input: dict[str, Any]
    output: dict[str, Any]
    spans: list[Span] = Field(default_factory=list)
    ground_truth_ref: Optional[str] = None
    latency_ms: float
    total_cost_usd: float
    created_at: str


class EvalCase(BaseModel):
    id: str
    source_run_id: Optional[str] = None
    title: str
    input: dict[str, Any]
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    rubric: str
    reference_behavior: str
    severity: Severity = "medium"
    status: CaseStatus = "active"
    first_failed_version_id: Optional[str] = None
    fixed_in_version_id: Optional[str] = None
    created_at: str


class EvalResult(BaseModel):
    id: str
    eval_case_id: str
    agent_version_id: str
    passed: bool
    score: float
    judge_rationale: str
    actual_output: dict[str, Any]
    output_hash: str
    from_cache: bool = False
    created_at: str


class GateRun(BaseModel):
    id: str
    candidate_version_id: str
    baseline_version_id: str
    total_cases: int
    passed_count: int
    failed_count: int
    regressed_case_ids: list[str] = Field(default_factory=list)
    newly_fixed_case_ids: list[str] = Field(default_factory=list)
    verdict: Verdict
    created_at: str


class JudgeVerdict(BaseModel):
    """What the judge returns for a single (input, output) pair."""

    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    rationale: str
    reference_output: str = ""


class CaseClassification(BaseModel):
    """Per-case gate classification (baseline vs candidate)."""

    eval_case_id: str
    title: str
    severity: Severity
    baseline_passed: Optional[bool]
    candidate_passed: bool
    kind: Literal["regression", "newly_fixed", "still_passing", "still_failing", "new_case"]


class GateReport(BaseModel):
    candidate_version_id: str
    candidate_label: str
    baseline_version_id: str
    baseline_label: str
    cases: list[CaseClassification]
    verdict: Verdict
    total_cases: int
    passed_count: int
    failed_count: int
    regressed_case_ids: list[str]
    newly_fixed_case_ids: list[str]
    gate_run_id: Optional[str] = None
