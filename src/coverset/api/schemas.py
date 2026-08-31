"""Pydantic request/response schemas for the HTTP API."""

from __future__ import annotations

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


class ScreenplayAssetResponse(BaseModel):
    id: str
    production_id: str
    filename: str
    media: Literal["pdf", "text"]
    content_sha256: str
    storage_uri: str


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
    cast_ids: list[str]
    flags: dict[str, bool]
    confidence: float | None
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
