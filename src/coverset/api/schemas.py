"""Pydantic request/response schemas for the HTTP API."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field


ActorRole = Literal[
    "first_ad", "director", "script_supervisor", "upm", "line_producer", "second_ad"
]


class HealthResponse(BaseModel):
    ok: bool = True
    service: str = "coverset-api"
    environment: str
    storage_backend: str


class ProductionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    seed_demo_data: bool = True


class ProductionResponse(BaseModel):
    id: str
    title: str
    cast_count: int = 0
    location_count: int = 0
    shoot_day_count: int = 0


class CastMemberCreate(BaseModel):
    cast_id: str = Field(min_length=1, max_length=120)
    performer: str = Field(min_length=1, max_length=240)
    character: str = Field(min_length=1, max_length=120)
    is_minor: bool = False


class CastMemberResponse(BaseModel):
    id: str
    production_id: str
    cast_id: str
    performer: str
    character: str
    is_minor: bool


class LocationCreate(BaseModel):
    location_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=240)
    city: str = Field(min_length=1, max_length=160)
    state: str = Field(min_length=1, max_length=80)
    latitude: float | None = None
    longitude: float | None = None
    timezone: str = Field(default="America/New_York", min_length=1, max_length=80)
    aliases: list[str] = Field(default_factory=list)


class LocationResponse(BaseModel):
    id: str
    production_id: str
    location_id: str
    name: str
    city: str
    state: str
    latitude: float | None = None
    longitude: float | None = None
    timezone: str
    aliases: list[str] = Field(default_factory=list)


class CalendarUpdate(BaseModel):
    shoot_dates: list[dt.date] = Field(min_length=1)


class CalendarResponse(BaseModel):
    production_id: str
    shoot_dates: list[dt.date]


class ScreenplayAssetResponse(BaseModel):
    id: str
    production_id: str
    filename: str
    media: Literal["pdf", "text"]
    content_sha256: str
    storage_uri: str
    normalized_text_uri: str | None = None
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)
    extraction_error: str = ""


class BreakdownRequest(BaseModel):
    screenplay_asset_id: str
    auto_accept_schedulable: bool = False
    agent_mode: Literal["gemini", "fixture"] | None = None


class SceneCandidateResponse(BaseModel):
    id: str
    scene_id: str
    scene_number: str
    slugline: str
    int_ext: str
    day_night: str
    location_ref: str
    page_eighths: int
    cast_ids: list[str]
    flags: dict[str, bool]
    source_page_range: str = ""
    confidence: float | None
    proposal_scene: dict[str, Any] | None = None
    status: str
    accepted: bool
    rejected: bool
    schedulable: bool
    resolution_errors: list[str]
    number_synthesized: bool


class BreakdownRunResponse(BaseModel):
    id: str
    production_id: str
    screenplay_asset_id: str
    status: str
    agent_mode: str
    error: str = ""
    unresolved_locations: list[str] = Field(default_factory=list)
    unresolved_cast: list[str] = Field(default_factory=list)
    candidates: list[SceneCandidateResponse] = Field(default_factory=list)


class CandidateReviewRequest(BaseModel):
    decision: Literal["accept", "reject"]


class CandidateUpdateRequest(BaseModel):
    scene_number: str | None = Field(default=None, min_length=1, max_length=40)
    slugline: str | None = Field(default=None, min_length=1, max_length=240)
    int_ext: Literal["int", "ext", "int_ext", "unknown"] | None = None
    day_night: Literal["day", "night", "dawn", "dusk", "unknown"] | None = None
    location_ref: str | None = Field(default=None, min_length=1, max_length=120)
    page_eighths: int | None = Field(default=None, gt=0)
    cast_ids: list[str] | None = None
    flags: dict[str, bool] | None = None
    source_page_range: str | None = None


class CandidateBatchAcceptResponse(BaseModel):
    accepted: list[str] = Field(default_factory=list)
    skipped: dict[str, list[str]] = Field(default_factory=dict)
    candidates: list[SceneCandidateResponse] = Field(default_factory=list)


class JobResponse(BaseModel):
    id: str
    production_id: str | None = None
    job_type: str
    target_id: str
    status: str
    attempts: int
    error: str = ""
    result: dict[str, Any] = Field(default_factory=dict)


class GroundingRequest(BaseModel):
    kind: Literal["weather", "permit"]
    location_id: str = Field(min_length=1, max_length=120)
    target_date: dt.date


class GroundingEvidenceResponse(BaseModel):
    id: str
    production_id: str
    location_id: str
    fact_kind: str
    target_date: dt.date
    status: str
    error: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


class DateWindowPayload(BaseModel):
    start: dt.date
    end: dt.date


class ConstraintCreate(BaseModel):
    constraint_id: str = Field(min_length=1, max_length=120)
    family: Literal[
        "cast",
        "location",
        "permit",
        "daylight",
        "turnaround",
        "company_move",
        "weather",
        "lock",
        "budget",
    ]
    policy: Literal[
        "hard",
        "soft_penalty",
        "waivable_by_role",
        "objective_only",
        "informational",
    ] = "hard"
    subject_kind: Literal["cast", "location", "work", "day", "schedule"]
    subject_ref: str = ""
    expression_type: Literal[
        "date_windows",
        "blackout_dates",
        "daylight_bound",
        "minimum_rest",
        "maximum_daily_hours",
        "pinned_day",
    ]
    day: dt.date | None = None
    dates: list[dt.date] = Field(default_factory=list)
    windows: list[DateWindowPayload] = Field(default_factory=list)
    hours: float | None = None
    evidence_id: str | None = None
    actor_name: str = "Developer"
    actor_role: ActorRole = "first_ad"
    statement: str = "Production entered constraint"
    active: bool = False


class ConstraintActivationRequest(BaseModel):
    active: bool = True
    actor_name: str = "Developer"
    actor_role: ActorRole = "first_ad"


class ConstraintResponse(BaseModel):
    id: str
    production_id: str
    constraint_id: str
    family: str
    policy: str
    active: bool
    constraint: dict[str, Any]
    provenance: dict[str, Any] = Field(default_factory=dict)


class ScheduleRequest(BaseModel):
    accepted_only: bool = True


class ScheduleRunResponse(BaseModel):
    id: str
    production_id: str
    status: str
    error: str = ""
    input_hash: str = ""
    board_id: str | None = None
    diagnostics: list[str] = Field(default_factory=list)


class BoardResponse(BaseModel):
    id: str
    production_id: str
    schedule_run_id: str
    solver_status: str
    stripboard: str
    result: dict[str, Any]


class LockDayRequest(BaseModel):
    shoot_date: dt.date
    call_sheet_version: str = Field(min_length=1, max_length=120)
    actor_name: str = "Developer"
    actor_role: ActorRole = "first_ad"


class LockedDayResponse(BaseModel):
    id: str
    production_id: str
    board_id: str
    schedule_run_id: str
    shoot_date: dt.date
    locked_assignments: list[dict[str, Any]] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    cast: list[str] = Field(default_factory=list)
    call_sheet_version: str
    recorded_by_name: str
    recorded_by_role: str


class MonitorJobRequest(BaseModel):
    board_id: str
    source_url: str = Field(min_length=1)
    fact_kind: Literal["weather", "permit"]
    old_fingerprint: str = ""
    new_fingerprint: str = ""
    old_value: dict[str, Any] = Field(default_factory=dict)
    new_value: dict[str, Any] = Field(default_factory=dict)
    material: bool = True
    message: str = ""
    affected_work_ids: list[str] = Field(default_factory=list)
    evidence_id: str | None = None


class MonitorFindingResponse(BaseModel):
    id: str
    production_id: str
    board_id: str
    evidence_id: str | None = None
    source_url: str
    fact_kind: str
    status: str
    material: bool
    message: str
    old_fingerprint: str = ""
    new_fingerprint: str = ""
    old_value: dict[str, Any] = Field(default_factory=dict)
    new_value: dict[str, Any] = Field(default_factory=dict)
    affected_work_ids: list[str] = Field(default_factory=list)
    requester_component: str
    reviewed_by_name: str | None = None
    reviewed_by_role: str | None = None


class MonitorFindingDecisionRequest(BaseModel):
    decision: Literal["accept", "reject"]
    actor_name: str = "Developer"
    actor_role: ActorRole = "first_ad"


class ReplanRequestResponse(BaseModel):
    id: str
    production_id: str
    finding_id: str
    current_board_id: str
    requester_component: str
    status: str
    affected_work_ids: list[str] = Field(default_factory=list)
    locked_days: list[str] = Field(default_factory=list)


class MonitorFindingDecisionResponse(BaseModel):
    finding: MonitorFindingResponse
    replan_request: ReplanRequestResponse | None = None


class BoardSelectionRequest(BaseModel):
    prior_board_id: str | None = None
    actor_name: str = "Developer"
    actor_role: ActorRole = "first_ad"


class BoardSelectionResponse(BaseModel):
    id: str
    production_id: str
    prior_board_id: str | None = None
    selected_board_id: str
    prior_schedule_run_id: str | None = None
    new_schedule_run_id: str
    actor_name: str
    actor_role: str


class CostApprovalRequest(BaseModel):
    cost_delta: float = Field(ge=0)
    added_shoot_days: list[dt.date] = Field(default_factory=list)
    decision: Literal["approved", "rejected"] = "approved"
    actor_name: str = "Developer"
    actor_role: ActorRole = "upm"


class CostApprovalResponse(BaseModel):
    id: str
    production_id: str
    board_id: str
    approver_name: str
    approver_role: str
    cost_delta: float
    added_shoot_days: list[dt.date] = Field(default_factory=list)
    decision: str
