"""SQLAlchemy persistence models for the service boundary.

The scheduler/breakdown domain objects remain immutable dataclasses in `coverset.*`.
These models store durable product state and JSON snapshots at boundaries where full
normalisation would otherwise duplicate domain logic prematurely.
"""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSON = sa.JSON
Boolean = sa.Boolean
Date = sa.Date
DateTime = sa.DateTime
Float = sa.Float
ForeignKey = sa.ForeignKey
Integer = sa.Integer
String = sa.String
Text = sa.Text
UniqueConstraint = sa.UniqueConstraint


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    pass


class ProductionModel(Base):
    __tablename__ = "productions"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    cast_members: Mapped[list[CastMemberModel]] = relationship(
        back_populates="production", cascade="all, delete-orphan"
    )
    locations: Mapped[list[LocationModel]] = relationship(
        back_populates="production", cascade="all, delete-orphan"
    )
    location_aliases: Mapped[list[LocationAliasModel]] = relationship(
        back_populates="production", cascade="all, delete-orphan"
    )
    shoot_days: Mapped[list[ShootDayModel]] = relationship(
        back_populates="production", cascade="all, delete-orphan"
    )


class CastMemberModel(Base):
    __tablename__ = "cast_members"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    cast_id: Mapped[str] = mapped_column(String(120), nullable=False)
    performer: Mapped[str] = mapped_column(String(240), nullable=False)
    character: Mapped[str] = mapped_column(String(120), nullable=False)
    is_minor: Mapped[bool] = mapped_column(Boolean, default=False)

    production: Mapped[ProductionModel] = relationship(back_populates="cast_members")


class LocationModel(Base):
    __tablename__ = "locations"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    location_id: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    city: Mapped[str] = mapped_column(String(160), nullable=False)
    state: Mapped[str] = mapped_column(String(80), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False)

    production: Mapped[ProductionModel] = relationship(back_populates="locations")


class LocationAliasModel(Base):
    __tablename__ = "location_aliases"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    alias: Mapped[str] = mapped_column(String(240), nullable=False)
    location_id: Mapped[str] = mapped_column(String(120), nullable=False)

    production: Mapped[ProductionModel] = relationship(
        back_populates="location_aliases"
    )


class ShootDayModel(Base):
    __tablename__ = "shoot_days"
    __table_args__ = (
        UniqueConstraint("production_id", "shoot_date", name="uq_shoot_days_date"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    shoot_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    day_order: Mapped[int] = mapped_column(Integer, nullable=False)

    production: Mapped[ProductionModel] = relationship(back_populates="shoot_days")


class ConstraintModel(Base):
    __tablename__ = "constraints"
    __table_args__ = (
        UniqueConstraint("production_id", "constraint_id", name="uq_constraints_id"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    constraint_id: Mapped[str] = mapped_column(String(120), nullable=False)
    family: Mapped[str] = mapped_column(String(80), nullable=False)
    policy: Mapped[str] = mapped_column(String(80), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    constraint_json: Mapped[dict] = mapped_column(JSON, default=dict)
    provenance_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ConstraintProposalModel(Base):
    __tablename__ = "constraint_proposals"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="candidate")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    validation_errors_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by_name: Mapped[str] = mapped_column(String(120), default="Developer")
    accepted_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    accepted_by_role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    accepted_constraint_id: Mapped[str | None] = mapped_column(
        String(48), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    accepted_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class GroundingEvidenceModel(Base):
    __tablename__ = "grounding_evidence"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    location_id: Mapped[str] = mapped_column(String(120), nullable=False)
    fact_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="complete")
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class GroundedValueModel(Base):
    __tablename__ = "grounded_values"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("grounding_evidence.id"), index=True
    )
    fact_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    location_id: Mapped[str] = mapped_column(String(120), nullable=False)
    target_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    normalized_value_json: Mapped[dict] = mapped_column(JSON, default=dict)
    units: Mapped[str] = mapped_column(String(80), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_quote: Mapped[str] = mapped_column(Text, nullable=False)
    source_span: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    provider_response_id: Mapped[str] = mapped_column(String(160), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    derived_from: Mapped[str] = mapped_column(String(40), nullable=False)
    validator_result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    covering_date: Mapped[bool] = mapped_column(Boolean, default=False)
    context_source_urls_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ScreenplayAssetModel(Base):
    __tablename__ = "screenplay_assets"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    filename: Mapped[str] = mapped_column(String(240), nullable=False)
    media: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    extraction_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class BreakdownRunModel(Base):
    __tablename__ = "breakdown_runs"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    screenplay_asset_id: Mapped[str] = mapped_column(ForeignKey("screenplay_assets.id"))
    status: Mapped[str] = mapped_column(String(40), default="queued")
    agent_mode: Mapped[str] = mapped_column(String(40), default="gemini")
    error: Mapped[str] = mapped_column(Text, default="")
    unresolved_locations: Mapped[list[str]] = mapped_column(JSON, default=list)
    unresolved_cast: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SceneCandidateModel(Base):
    __tablename__ = "scene_candidates"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    breakdown_run_id: Mapped[str] = mapped_column(
        ForeignKey("breakdown_runs.id"), index=True
    )
    scene_id: Mapped[str] = mapped_column(String(120), nullable=False)
    scene_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    rejected: Mapped[bool] = mapped_column(Boolean, default=False)
    schedulable: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution_errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    proposal_scene_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scene_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    active_scene_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ScheduleRunModel(Base):
    __tablename__ = "schedule_runs"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued")
    error: Mapped[str] = mapped_column(Text, default="")
    input_hash: Mapped[str] = mapped_column(String(64), default="")
    board_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    diagnostics: Mapped[list[str]] = mapped_column(JSON, default=list)
    conflict_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BoardModel(Base):
    __tablename__ = "boards"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    schedule_run_id: Mapped[str] = mapped_column(
        ForeignKey("schedule_runs.id"), index=True
    )
    solver_status: Mapped[str] = mapped_column(String(40), nullable=False)
    approval_state: Mapped[str] = mapped_column(String(40), default="approved")
    stripboard: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class LockedDayModel(Base):
    __tablename__ = "locked_days"
    __table_args__ = (
        UniqueConstraint("board_id", "shoot_date", name="uq_locked_days_board_date"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    schedule_run_id: Mapped[str] = mapped_column(String(48), nullable=False)
    shoot_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    locked_assignments_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    locations_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    cast_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    call_sheet_version: Mapped[str] = mapped_column(String(120), nullable=False)
    recorded_by_name: Mapped[str] = mapped_column(String(120), nullable=False)
    recorded_by_role: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class MonitoredSourceModel(Base):
    __tablename__ = "monitored_sources"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    fact_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    location_id: Mapped[str] = mapped_column(String(120), default="")
    query: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(80), default="parallel_monitor")
    external_monitor_id: Mapped[str] = mapped_column(String(160), default="")
    status: Mapped[str] = mapped_column(String(40), default="active")
    last_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_checked_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MonitorChangeEventModel(Base):
    __tablename__ = "monitor_change_events"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    monitored_source_id: Mapped[str | None] = mapped_column(
        ForeignKey("monitored_sources.id"), nullable=True, index=True
    )
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="processed")
    material: Mapped[bool] = mapped_column(Boolean, default=False)
    old_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    new_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    finding_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    replan_request_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class MonitorFindingModel(Base):
    __tablename__ = "monitor_findings"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey("grounding_evidence.id"), nullable=True
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    fact_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="open")
    material: Mapped[bool] = mapped_column(Boolean, default=True)
    message: Mapped[str] = mapped_column(Text, default="")
    old_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    new_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    old_value_json: Mapped[dict] = mapped_column(JSON, default=dict)
    new_value_json: Mapped[dict] = mapped_column(JSON, default=dict)
    affected_work_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    requester_component: Mapped[str] = mapped_column(String(80), default="monitor")
    reviewed_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_by_role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ReplanRequestModel(Base):
    __tablename__ = "replan_requests"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    finding_id: Mapped[str | None] = mapped_column(
        ForeignKey("monitor_findings.id"), nullable=True, index=True
    )
    current_board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    requester_component: Mapped[str] = mapped_column(String(80), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(40), default="monitor")
    source_id: Mapped[str] = mapped_column(String(48), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="requested")
    affected_work_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    locked_days_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ScheduleDiffModel(Base):
    __tablename__ = "schedule_diffs"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    base_board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    revised_board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    replan_request_id: Mapped[str | None] = mapped_column(
        ForeignKey("replan_requests.id"), nullable=True, index=True
    )
    diff_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    required_approvals_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    cost_delta: Mapped[float] = mapped_column(Float, default=0.0)
    rendered_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class BoardSelectionModel(Base):
    __tablename__ = "board_selections"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    prior_board_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    selected_board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    prior_schedule_run_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    new_schedule_run_id: Mapped[str] = mapped_column(String(48), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class CostApprovalModel(Base):
    __tablename__ = "cost_approvals"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    approver_name: Mapped[str] = mapped_column(String(120), nullable=False)
    approver_role: Mapped[str] = mapped_column(String(80), nullable=False)
    cost_delta: Mapped[float] = mapped_column(Float, default=0.0)
    added_shoot_days_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    decision: Mapped[str] = mapped_column(String(40), default="approved")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class CoverageItemModel(Base):
    __tablename__ = "coverage_items"
    __table_args__ = (
        UniqueConstraint("production_id", "coverage_key", name="uq_coverage_items_key"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    scene_id: Mapped[str] = mapped_column(String(120), nullable=False)
    coverage_key: Mapped[str] = mapped_column(String(160), nullable=False)
    coverage_type: Mapped[str] = mapped_column(String(80), nullable=False)
    planned_json: Mapped[dict] = mapped_column(JSON, default=dict)
    shot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="planned")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class CoverageFindingModel(Base):
    __tablename__ = "coverage_findings"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    coverage_item_id: Mapped[str] = mapped_column(
        ForeignKey("coverage_items.id"), index=True
    )
    board_id: Mapped[str | None] = mapped_column(ForeignKey("boards.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="open")
    severity: Mapped[str] = mapped_column(String(40), default="medium")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    raised_by_name: Mapped[str] = mapped_column(String(120), nullable=False)
    raised_by_role: Mapped[str] = mapped_column(String(80), nullable=False)
    human_raised: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class PickupTaskModel(Base):
    __tablename__ = "pickup_tasks"
    __table_args__ = (UniqueConstraint("finding_id", name="uq_pickup_tasks_finding"),)

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    finding_id: Mapped[str] = mapped_column(
        ForeignKey("coverage_findings.id"), index=True
    )
    coverage_item_id: Mapped[str] = mapped_column(
        ForeignKey("coverage_items.id"), index=True
    )
    board_id: Mapped[str | None] = mapped_column(ForeignKey("boards.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="requested")
    scene_id: Mapped[str] = mapped_column(String(120), nullable=False)
    pickup_spec_json: Mapped[dict] = mapped_column(JSON, default=dict)
    decision_json: Mapped[dict] = mapped_column(JSON, default=dict)
    requested_by_name: Mapped[str] = mapped_column(String(120), nullable=False)
    requested_by_role: Mapped[str] = mapped_column(String(80), nullable=False)
    confirmed_by_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    confirmed_by_role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class CallSheetModel(Base):
    __tablename__ = "call_sheets"
    __table_args__ = (
        UniqueConstraint("board_id", "shoot_date", name="uq_call_sheets_board_date"),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str] = mapped_column(ForeignKey("productions.id"), index=True)
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), index=True)
    schedule_run_id: Mapped[str] = mapped_column(String(48), nullable=False)
    shoot_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    generated_by_name: Mapped[str] = mapped_column(String(120), nullable=False)
    generated_by_role: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    rendered_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class AuditEventModel(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str | None] = mapped_column(
        ForeignKey("productions.id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class JobModel(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    production_id: Mapped[str | None] = mapped_column(
        ForeignKey("productions.id"), nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    claimed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
