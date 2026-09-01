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
    grounded_value_id: str = ""
    derived_from: Literal["excerpt", "full_content"] | None = None
    timezone: str | None = None
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


class ConstraintTranslationRequest(BaseModel):
    text: str = Field(min_length=1)
    actor_name: str = "Developer"


class ConstraintProposalDecisionRequest(BaseModel):
    decision: Literal["accept", "reject"] = "accept"
    actor_name: str = "Developer"
    actor_role: ActorRole = "first_ad"


class ConstraintProposalResponse(BaseModel):
    id: str
    production_id: str
    source_text: str
    status: str
    confidence: float
    payload: dict[str, Any] = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)
    created_by_name: str
    accepted_by_name: str | None = None
    accepted_by_role: str | None = None
    accepted_constraint_id: str | None = None


class GroundedValueCreate(BaseModel):
    normalized_value: dict[str, Any]
    units: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    source_span: str = "source text"
    query: str = "grounded value extraction"
    validator_family: str = "generic"
    validator_reason: str = "source span extracted and normalized"


class GroundedValueResponse(BaseModel):
    id: str
    production_id: str
    evidence_id: str
    fact_kind: str
    location_id: str
    target_date: dt.date
    normalized_value: dict[str, Any] = Field(default_factory=dict)
    units: str
    source_url: str
    source_quote: str
    source_span: str
    query: str
    provider_response_id: str
    content_hash: str
    derived_from: str
    validator_result: dict[str, Any] = Field(default_factory=dict)
    covering_date: bool
    context_source_urls: list[str] = Field(default_factory=list)


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
    approval_state: str = "approved"
    stripboard: str
    result: dict[str, Any]


class AuditEventResponse(BaseModel):
    id: str
    production_id: str | None = None
    event_type: str
    actor: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: dt.datetime


class AuditBigQueryExportResponse(BaseModel):
    production_id: str
    exported_count: int
    table: str


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
    monitored_source_id: str | None = None
    target_date: dt.date | None = None
    status: str = ""


class MonitoredSourceCreate(BaseModel):
    board_id: str
    source_url: str = Field(min_length=1)
    fact_kind: Literal["weather", "permit"]
    location_id: str = ""
    query: str = ""
    external_monitor_id: str = ""


class MonitoredSourceResponse(BaseModel):
    id: str
    production_id: str
    board_id: str
    source_url: str
    fact_kind: str
    location_id: str = ""
    query: str = ""
    provider: str
    external_monitor_id: str = ""
    status: str
    last_fingerprint: str = ""


class MonitorChangeEventResponse(BaseModel):
    id: str
    production_id: str
    monitored_source_id: str | None = None
    board_id: str
    status: str
    material: bool
    old_fingerprint: str = ""
    new_fingerprint: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    finding_id: str | None = None
    replan_request_id: str | None = None


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
    finding_id: str | None = None
    current_board_id: str
    requester_component: str
    source_kind: str = "monitor"
    source_id: str = ""
    reason: str = ""
    status: str
    affected_work_ids: list[str] = Field(default_factory=list)
    locked_days: list[str] = Field(default_factory=list)


class MonitorFindingDecisionResponse(BaseModel):
    finding: MonitorFindingResponse
    replan_request: ReplanRequestResponse | None = None


class ReplanOptionsRequest(BaseModel):
    max_options: int = Field(default=2, ge=1, le=4)


class ScheduleDiffResponse(BaseModel):
    id: str
    production_id: str
    base_board_id: str
    revised_board_id: str
    replan_request_id: str | None = None
    diff: dict[str, Any]
    required_approvals: list[str] = Field(default_factory=list)
    cost_delta: float = 0.0
    rendered_text: str = ""


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


class CoverageItemCreate(BaseModel):
    scene_id: str = Field(min_length=1)
    coverage_key: str = Field(min_length=1)
    coverage_type: str = Field(min_length=1)
    planned: dict[str, Any] = Field(default_factory=dict)


class CoverageShotUpdate(BaseModel):
    shot: dict[str, Any] = Field(default_factory=dict)


class CoverageFindingCreate(BaseModel):
    board_id: str | None = None
    message: str = Field(min_length=1)
    severity: str = "medium"
    actor_name: str = "Developer"
    actor_role: ActorRole = "script_supervisor"


class CoverageItemResponse(BaseModel):
    id: str
    production_id: str
    scene_id: str
    coverage_key: str
    coverage_type: str
    planned: dict[str, Any] = Field(default_factory=dict)
    shot: dict[str, Any] = Field(default_factory=dict)
    status: str


class CoverageFindingResponse(BaseModel):
    id: str
    production_id: str
    coverage_item_id: str
    board_id: str | None = None
    status: str
    severity: str
    message: str
    raised_by_name: str
    raised_by_role: str
    human_raised: bool


class PickupDecisionRequest(BaseModel):
    decision: Literal["request_pickup", "reject"] = "request_pickup"
    actor_name: str = "Developer"
    actor_role: ActorRole = "director"


class PickupConfirmRequest(BaseModel):
    pickup_spec: dict[str, Any]
    actor_name: str = "Developer"
    actor_role: ActorRole = "director"


class PickupReplanRequest(BaseModel):
    current_board_id: str
    cutoff_at: dt.datetime
    lock_policy: Literal["preserve_locked", "preserve_through_cutoff"]


class PickupTaskResponse(BaseModel):
    id: str
    production_id: str
    finding_id: str
    coverage_item_id: str
    board_id: str | None = None
    status: str
    scene_id: str
    pickup_spec: dict[str, Any] = Field(default_factory=dict)
    decision: dict[str, Any] = Field(default_factory=dict)
    requested_by_name: str
    requested_by_role: str
    confirmed_by_name: str | None = None
    confirmed_by_role: str | None = None


class CallSheetGenerateRequest(BaseModel):
    shoot_date: dt.date
    actor_name: str = "Developer"
    actor_role: ActorRole = "second_ad"


class CallSheetResponse(BaseModel):
    id: str
    production_id: str
    board_id: str
    schedule_run_id: str
    shoot_date: dt.date
    generated_by_name: str
    generated_by_role: str
    payload: dict[str, Any] = Field(default_factory=dict)
    rendered_text: str
    created_at: dt.datetime
