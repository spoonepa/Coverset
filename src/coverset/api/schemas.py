"""Pydantic request/response schemas for the HTTP API."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field


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
