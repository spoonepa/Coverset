"""FastAPI entrypoint for the deployable Coverset API."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from .config import get_settings  # type: ignore[import-not-found]
from .db import get_session, init_db  # type: ignore[import-not-found]
from .models import (  # type: ignore[import-not-found]
    AuditEventModel,
    BoardModel,
    BoardSelectionModel,
    BreakdownRunModel,
    CallSheetModel,
    CastMemberModel,
    ConstraintModel,
    ConstraintProposalModel,
    CostApprovalModel,
    CoverageFindingModel,
    CoverageItemModel,
    GroundedValueModel,
    GroundingEvidenceModel,
    JobModel,
    LocationAliasModel,
    LocationModel,
    LockedDayModel,
    MonitorChangeEventModel,
    MonitoredSourceModel,
    MonitorFindingModel,
    PickupTaskModel,
    ProductionModel,
    ReplanRequestModel,
    SceneCandidateModel,
    ScheduleDiffModel,
    ScheduleRunModel,
    ScreenplayAssetModel,
)
from .schemas import (  # type: ignore[import-not-found]
    AuditBigQueryExportResponse,
    AuditEventResponse,
    BoardResponse,
    BoardSelectionRequest,
    BoardSelectionResponse,
    BreakdownRequest,
    BreakdownRunResponse,
    CalendarResponse,
    CalendarUpdate,
    CallSheetGenerateRequest,
    CallSheetResponse,
    CandidateBatchAcceptResponse,
    CandidateReviewRequest,
    CandidateUpdateRequest,
    CastMemberCreate,
    CastMemberResponse,
    ConstraintActivationRequest,
    ConstraintCreate,
    ConstraintProposalDecisionRequest,
    ConstraintProposalResponse,
    ConstraintResponse,
    ConstraintTranslationRequest,
    CostApprovalRequest,
    CostApprovalResponse,
    CoverageFindingCreate,
    CoverageFindingResponse,
    CoverageItemCreate,
    CoverageItemResponse,
    CoverageShotUpdate,
    GroundedValueCreate,
    GroundedValueResponse,
    GroundingEvidenceResponse,
    GroundingRequest,
    HealthResponse,
    JobResponse,
    LocationCreate,
    LocationResponse,
    LockDayRequest,
    LockedDayResponse,
    MonitorChangeEventResponse,
    MonitoredSourceCreate,
    MonitoredSourceResponse,
    MonitorFindingDecisionRequest,
    MonitorFindingDecisionResponse,
    MonitorFindingResponse,
    MonitorJobRequest,
    PickupConfirmRequest,
    PickupDecisionRequest,
    PickupReplanRequest,
    PickupTaskResponse,
    ProductionCreate,
    ProductionResponse,
    ReplanOptionsRequest,
    ReplanRequestResponse,
    SceneCandidateResponse,
    ScheduleDiffResponse,
    ScheduleRequest,
    ScheduleRunResponse,
    ScreenplayAssetResponse,
)
from .services import (  # type: ignore[import-not-found]
    ServiceError,
    accept_constraint_proposal,
    activate_constraint,
    add_cast_member,
    add_location,
    approve_cost,
    audit_event_to_json,
    audit_export_csv,
    audit_export_json,
    batch_accept_candidates,
    board_export_csv,
    board_export_json,
    call_sheet_export_json,
    confirm_pickup_task,
    create_constraint,
    create_pickup_replan,
    create_production,
    create_schedule_diff,
    decide_monitor_finding,
    enqueue_breakdown_job,
    enqueue_grounding_job,
    enqueue_monitor_job,
    enqueue_schedule_job,
    export_audit_events_to_bigquery,
    generate_call_sheet,
    generate_replan_options,
    get_board,
    get_breakdown_run,
    get_call_sheet,
    get_job,
    get_production,
    get_schedule_run,
    ground_fact,
    list_aliases,
    list_audit_events,
    list_breakdown_runs,
    list_call_sheets,
    list_candidates_for_run,
    list_cast,
    list_constraint_proposals,
    list_constraints,
    list_cost_approvals,
    list_cost_approvals_for_board,
    list_coverage_findings,
    list_coverage_items,
    list_grounded_values,
    list_grounded_values_for_evidence,
    list_grounding_evidence,
    list_jobs,
    list_locations,
    list_locked_days,
    list_monitor_findings,
    list_monitored_sources,
    list_pickup_tasks,
    list_replan_requests,
    list_schedule_diffs,
    list_schedule_runs,
    list_shoot_days,
    lock_board_day,
    mark_coverage_item_shot,
    materialize_demo_script,
    process_monitor_change,
    raise_coverage_finding,
    record_coverage_item,
    record_grounded_value,
    register_monitored_source,
    reject_constraint_proposal,
    request_pickup_from_finding,
    review_candidate,
    run_breakdown,
    run_scheduler,
    seed_demo_workflow_state,
    select_board,
    set_calendar,
    translate_constraint_text,
    update_candidate,
    upload_screenplay,
)
from .tasks import dispatch_job  # type: ignore[import-not-found]

settings = get_settings()


class ActorClaim:
    def __init__(
        self,
        *,
        present: bool,
        authenticated: bool,
        name: str,
        roles: tuple[str, ...],
    ) -> None:
        self.present = present
        self.authenticated = authenticated
        self.name = name
        self.roles = roles


def get_actor_claim(
    x_coverset_authenticated: Annotated[
        str | None, Header(alias="x-coverset-authenticated")
    ] = None,
    x_coverset_actor_name: Annotated[
        str | None, Header(alias="x-coverset-actor-name")
    ] = None,
    x_coverset_actor_roles: Annotated[
        str | None, Header(alias="x-coverset-actor-roles")
    ] = None,
) -> ActorClaim:
    roles = tuple(
        role.strip()
        for role in (x_coverset_actor_roles or "").split(",")
        if role.strip()
    )
    return ActorClaim(
        present=x_coverset_authenticated is not None,
        authenticated=(x_coverset_authenticated or "").lower() == "true",
        name=x_coverset_actor_name or "Authenticated user",
        roles=roles,
    )


def actor_name_value(claim: ActorClaim, *, requested_name: str) -> str:
    if not claim.present:
        return requested_name
    if not claim.authenticated:
        raise HTTPException(status_code=401, detail="authenticated user is required")
    return claim.name


def actor_values(
    claim: ActorClaim,
    *,
    requested_name: str,
    requested_role: str,
) -> tuple[str, str]:
    if not claim.present:
        return requested_name, requested_role
    if not claim.authenticated:
        raise HTTPException(status_code=401, detail="authenticated user is required")
    if requested_role not in claim.roles:
        raise HTTPException(
            status_code=403,
            detail=f"authenticated user lacks required role: {requested_role}",
        )
    return claim.name, requested_role


def actor_payload(
    payload: dict,
    claim: ActorClaim,
    *,
    requested_name: str,
    requested_role: str,
) -> dict:
    actor_name, actor_role = actor_values(
        claim, requested_name=requested_name, requested_role=requested_role
    )
    return {**payload, "actor_name": actor_name, "actor_role": actor_role}


ActorClaimDep = Annotated[ActorClaim, Depends(get_actor_claim)]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Coverset API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ServiceError)
def _service_error(_: object, exc: ServiceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(
        environment=settings.environment,
        storage_backend=settings.storage_backend,
    )


@app.get("/readyz", response_model=HealthResponse)
def readyz() -> HealthResponse:
    return healthz()


@app.post("/productions", response_model=ProductionResponse)
def create_production_endpoint(
    payload: ProductionCreate,
    session: Annotated[Session, Depends(get_session)],
) -> ProductionResponse:
    production = create_production(
        session, title=payload.title, seed_demo_data=payload.seed_demo_data
    )
    return _production_response(session, production)


@app.get("/productions/{production_id}", response_model=ProductionResponse)
def get_production_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> ProductionResponse:
    return _production_response(session, get_production(session, production_id))


@app.get("/productions/{production_id}/cast", response_model=list[CastMemberResponse])
def list_cast_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[CastMemberResponse]:
    get_production(session, production_id)
    return [_cast_response(row) for row in list_cast(session, production_id)]


@app.post("/productions/{production_id}/cast", response_model=CastMemberResponse)
def add_cast_endpoint(
    production_id: str,
    payload: CastMemberCreate,
    session: Annotated[Session, Depends(get_session)],
) -> CastMemberResponse:
    return _cast_response(
        add_cast_member(
            session,
            production_id,
            cast_id=payload.cast_id,
            performer=payload.performer,
            character=payload.character,
            is_minor=payload.is_minor,
        )
    )


@app.get(
    "/productions/{production_id}/locations", response_model=list[LocationResponse]
)
def list_locations_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[LocationResponse]:
    get_production(session, production_id)
    aliases = list_aliases(session, production_id)
    return [
        _location_response(row, aliases)
        for row in list_locations(session, production_id)
    ]


@app.post("/productions/{production_id}/locations", response_model=LocationResponse)
def add_location_endpoint(
    production_id: str,
    payload: LocationCreate,
    session: Annotated[Session, Depends(get_session)],
) -> LocationResponse:
    location = add_location(
        session,
        production_id,
        location_id=payload.location_id,
        name=payload.name,
        city=payload.city,
        state=payload.state,
        latitude=payload.latitude,
        longitude=payload.longitude,
        timezone=payload.timezone,
        aliases=payload.aliases,
    )
    return _location_response(location, list_aliases(session, production_id))


@app.get("/productions/{production_id}/calendar", response_model=CalendarResponse)
def get_calendar_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> CalendarResponse:
    return CalendarResponse(
        production_id=production_id,
        shoot_dates=[row.shoot_date for row in list_shoot_days(session, production_id)],
    )


@app.put("/productions/{production_id}/calendar", response_model=CalendarResponse)
def set_calendar_endpoint(
    production_id: str,
    payload: CalendarUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> CalendarResponse:
    days = set_calendar(session, production_id, shoot_dates=payload.shoot_dates)
    return CalendarResponse(
        production_id=production_id,
        shoot_dates=[row.shoot_date for row in days],
    )


@app.post(
    "/productions/{production_id}/screenplays", response_model=ScreenplayAssetResponse
)
async def upload_screenplay_endpoint(
    production_id: str,
    file: Annotated[UploadFile, File()],
    session: Annotated[Session, Depends(get_session)],
) -> ScreenplayAssetResponse:
    content = await file.read()
    asset = upload_screenplay(
        session,
        production_id=production_id,
        filename=file.filename or "screenplay.txt",
        content=content,
    )
    return _asset_response(asset)


@app.post("/productions/{production_id}/breakdowns/jobs", response_model=JobResponse)
def enqueue_breakdown_endpoint(
    production_id: str,
    payload: BreakdownRequest,
    session: Annotated[Session, Depends(get_session)],
) -> JobResponse:
    job = enqueue_breakdown_job(
        session,
        production_id,
        screenplay_asset_id=payload.screenplay_asset_id,
        auto_accept_schedulable=payload.auto_accept_schedulable,
        agent_mode=payload.agent_mode,
    )
    _dispatch_job_or_raise(job)
    return _job_response(job)


@app.post(
    "/productions/{production_id}/breakdowns", response_model=BreakdownRunResponse
)
def run_breakdown_endpoint(
    production_id: str,
    payload: BreakdownRequest,
    session: Annotated[Session, Depends(get_session)],
) -> BreakdownRunResponse:
    run = run_breakdown(
        session,
        production_id=production_id,
        screenplay_asset_id=payload.screenplay_asset_id,
        auto_accept_schedulable=payload.auto_accept_schedulable,
        agent_mode=payload.agent_mode,
    )
    return _breakdown_response(session, run)


@app.get(
    "/productions/{production_id}/breakdowns",
    response_model=list[BreakdownRunResponse],
)
def list_breakdowns_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[BreakdownRunResponse]:
    return [
        _breakdown_response(session, row)
        for row in list_breakdown_runs(session, production_id)
    ]


@app.get("/breakdowns/{run_id}", response_model=BreakdownRunResponse)
def get_breakdown_endpoint(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> BreakdownRunResponse:
    return _breakdown_response(session, get_breakdown_run(session, run_id))


@app.patch("/scene-candidates/{candidate_id}", response_model=SceneCandidateResponse)
def update_candidate_endpoint(
    candidate_id: str,
    payload: CandidateUpdateRequest,
    session: Annotated[Session, Depends(get_session)],
) -> SceneCandidateResponse:
    return _candidate_response(
        update_candidate(
            session,
            candidate_id=candidate_id,
            changes=payload.model_dump(exclude_unset=True),
        )
    )


@app.patch(
    "/scene-candidates/{candidate_id}/review", response_model=SceneCandidateResponse
)
def review_candidate_endpoint(
    candidate_id: str,
    payload: CandidateReviewRequest,
    session: Annotated[Session, Depends(get_session)],
) -> SceneCandidateResponse:
    return _candidate_response(
        review_candidate(session, candidate_id=candidate_id, decision=payload.decision)
    )


@app.post(
    "/breakdowns/{run_id}/candidates/batch-accept",
    response_model=CandidateBatchAcceptResponse,
)
def batch_accept_candidates_endpoint(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> CandidateBatchAcceptResponse:
    accepted, skipped, candidates = batch_accept_candidates(session, run_id=run_id)
    return CandidateBatchAcceptResponse(
        accepted=accepted,
        skipped=skipped,
        candidates=[_candidate_response(candidate) for candidate in candidates],
    )


@app.post("/productions/{production_id}/boards/solve/jobs", response_model=JobResponse)
def enqueue_solve_board_endpoint(
    production_id: str,
    _: ScheduleRequest,
    session: Annotated[Session, Depends(get_session)],
) -> JobResponse:
    job = enqueue_schedule_job(session, production_id)
    _dispatch_job_or_raise(job)
    return _job_response(job)


@app.get("/productions/{production_id}/jobs", response_model=list[JobResponse])
def list_jobs_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[JobResponse]:
    return [_job_response(job) for job in list_jobs(session, production_id)]


@app.get("/productions/{production_id}/audit", response_model=list[AuditEventResponse])
def list_audit_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[AuditEventResponse]:
    return [
        _audit_event_response(row) for row in list_audit_events(session, production_id)
    ]


@app.get("/productions/{production_id}/audit/export")
def export_audit_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
    format: Literal["json", "csv"] = Query("json"),
) -> Response:
    rows = list_audit_events(session, production_id)
    if format == "csv":
        return Response(
            audit_export_csv(rows),
            media_type="text/csv",
            headers=_attachment_headers(f"{production_id}-audit.csv"),
        )
    return Response(
        json.dumps(audit_export_json(rows), sort_keys=True),
        media_type="application/json",
        headers=_attachment_headers(f"{production_id}-audit.json"),
    )


@app.post(
    "/productions/{production_id}/audit/bigquery",
    response_model=AuditBigQueryExportResponse,
)
def export_audit_bigquery_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> AuditBigQueryExportResponse:
    count = export_audit_events_to_bigquery(session, production_id, settings=settings)
    return AuditBigQueryExportResponse(
        production_id=production_id,
        exported_count=count,
        table=f"{settings.project_id}.{settings.bigquery_dataset}.{settings.bigquery_audit_table}",
    )


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job_endpoint(
    job_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> JobResponse:
    return _job_response(get_job(session, job_id))


@app.post("/productions/{production_id}/grounding/jobs", response_model=JobResponse)
def enqueue_grounding_endpoint(
    production_id: str,
    payload: GroundingRequest,
    session: Annotated[Session, Depends(get_session)],
) -> JobResponse:
    job = enqueue_grounding_job(
        session,
        production_id,
        kind=payload.kind,
        location_id=payload.location_id,
        target_date=payload.target_date,
    )
    _dispatch_job_or_raise(job)
    return _job_response(job)


@app.post(
    "/productions/{production_id}/grounding", response_model=GroundingEvidenceResponse
)
def ground_fact_endpoint(
    production_id: str,
    payload: GroundingRequest,
    session: Annotated[Session, Depends(get_session)],
) -> GroundingEvidenceResponse:
    return _grounding_response(
        ground_fact(
            session,
            production_id,
            kind=payload.kind,
            location_id=payload.location_id,
            target_date=payload.target_date,
        )
    )


@app.get(
    "/productions/{production_id}/grounding",
    response_model=list[GroundingEvidenceResponse],
)
def list_grounding_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[GroundingEvidenceResponse]:
    return [
        _grounding_response(row)
        for row in list_grounding_evidence(session, production_id)
    ]


@app.get(
    "/productions/{production_id}/grounded-values",
    response_model=list[GroundedValueResponse],
)
def list_grounded_values_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[GroundedValueResponse]:
    return [
        _grounded_value_response(row)
        for row in list_grounded_values(session, production_id)
    ]


@app.get(
    "/grounding/{evidence_id}/values",
    response_model=list[GroundedValueResponse],
)
def list_grounded_values_for_evidence_endpoint(
    evidence_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[GroundedValueResponse]:
    return [
        _grounded_value_response(row)
        for row in list_grounded_values_for_evidence(session, evidence_id)
    ]


@app.post(
    "/grounding/{evidence_id}/values",
    response_model=GroundedValueResponse,
)
def record_grounded_value_endpoint(
    evidence_id: str,
    payload: GroundedValueCreate,
    session: Annotated[Session, Depends(get_session)],
) -> GroundedValueResponse:
    return _grounded_value_response(
        record_grounded_value(
            session,
            evidence_id=evidence_id,
            **payload.model_dump(mode="json"),
        )
    )


@app.post(
    "/productions/{production_id}/constraints/translate",
    response_model=list[ConstraintProposalResponse],
)
def translate_constraints_endpoint(
    production_id: str,
    payload: ConstraintTranslationRequest,
    session: Annotated[Session, Depends(get_session)],
    claim: ActorClaimDep,
) -> list[ConstraintProposalResponse]:
    return [
        _constraint_proposal_response(row)
        for row in translate_constraint_text(
            session,
            production_id,
            text=payload.text,
            actor_name=actor_name_value(claim, requested_name=payload.actor_name),
        )
    ]


@app.get(
    "/productions/{production_id}/constraint-proposals",
    response_model=list[ConstraintProposalResponse],
)
def list_constraint_proposals_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[ConstraintProposalResponse]:
    return [
        _constraint_proposal_response(row)
        for row in list_constraint_proposals(session, production_id)
    ]


@app.post(
    "/constraint-proposals/{proposal_id}/accept",
    response_model=ConstraintResponse,
)
def accept_constraint_proposal_endpoint(
    proposal_id: str,
    payload: ConstraintProposalDecisionRequest,
    session: Annotated[Session, Depends(get_session)],
    claim: ActorClaimDep,
) -> ConstraintResponse:
    actor_name, actor_role = actor_values(
        claim, requested_name=payload.actor_name, requested_role=payload.actor_role
    )
    return _constraint_response(
        accept_constraint_proposal(
            session,
            proposal_id=proposal_id,
            actor_name=actor_name,
            actor_role=actor_role,
        )
    )


@app.post(
    "/constraint-proposals/{proposal_id}/reject",
    response_model=ConstraintProposalResponse,
)
def reject_constraint_proposal_endpoint(
    proposal_id: str,
    payload: ConstraintProposalDecisionRequest,
    session: Annotated[Session, Depends(get_session)],
    claim: ActorClaimDep,
) -> ConstraintProposalResponse:
    actor_name, actor_role = actor_values(
        claim, requested_name=payload.actor_name, requested_role=payload.actor_role
    )
    return _constraint_proposal_response(
        reject_constraint_proposal(
            session,
            proposal_id=proposal_id,
            actor_name=actor_name,
            actor_role=actor_role,
        )
    )


@app.post("/productions/{production_id}/constraints", response_model=ConstraintResponse)
def create_constraint_endpoint(
    production_id: str,
    payload: ConstraintCreate,
    session: Annotated[Session, Depends(get_session)],
    claim: ActorClaimDep,
) -> ConstraintResponse:
    return _constraint_response(
        create_constraint(
            session,
            production_id,
            payload=actor_payload(
                payload.model_dump(exclude_unset=True),
                claim,
                requested_name=payload.actor_name,
                requested_role=payload.actor_role,
            ),
        )
    )


@app.get(
    "/productions/{production_id}/constraints", response_model=list[ConstraintResponse]
)
def list_constraints_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[ConstraintResponse]:
    return [
        _constraint_response(row) for row in list_constraints(session, production_id)
    ]


@app.patch("/constraints/{constraint_id}/activation", response_model=ConstraintResponse)
def activate_constraint_endpoint(
    constraint_id: str,
    payload: ConstraintActivationRequest,
    session: Annotated[Session, Depends(get_session)],
    claim: ActorClaimDep,
) -> ConstraintResponse:
    actor_name, actor_role = actor_values(
        claim, requested_name=payload.actor_name, requested_role=payload.actor_role
    )
    return _constraint_response(
        activate_constraint(
            session,
            constraint_row_id=constraint_id,
            active=payload.active,
            actor_name=actor_name,
            actor_role=actor_role,
        )
    )


@app.post("/boards/{board_id}/locks", response_model=LockedDayResponse)
def lock_board_day_endpoint(
    board_id: str,
    payload: LockDayRequest,
    session: Annotated[Session, Depends(get_session)],
    claim: ActorClaimDep,
) -> LockedDayResponse:
    actor_name, actor_role = actor_values(
        claim, requested_name=payload.actor_name, requested_role=payload.actor_role
    )
    return _locked_day_response(
        lock_board_day(
            session,
            board_id=board_id,
            shoot_date=payload.shoot_date,
            call_sheet_version=payload.call_sheet_version,
            actor_name=actor_name,
            actor_role=actor_role,
        )
    )


@app.get("/productions/{production_id}/locks", response_model=list[LockedDayResponse])
def list_locked_days_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[LockedDayResponse]:
    return [
        _locked_day_response(row) for row in list_locked_days(session, production_id)
    ]


@app.post(
    "/productions/{production_id}/monitored-sources",
    response_model=MonitoredSourceResponse,
)
def register_monitored_source_endpoint(
    production_id: str,
    payload: MonitoredSourceCreate,
    session: Annotated[Session, Depends(get_session)],
) -> MonitoredSourceResponse:
    return _monitored_source_response(
        register_monitored_source(
            session,
            production_id,
            **payload.model_dump(mode="json"),
        )
    )


@app.get(
    "/productions/{production_id}/monitored-sources",
    response_model=list[MonitoredSourceResponse],
)
def list_monitored_sources_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[MonitoredSourceResponse]:
    return [
        _monitored_source_response(row)
        for row in list_monitored_sources(session, production_id)
    ]


@app.post(
    "/productions/{production_id}/monitor/events",
    response_model=MonitorChangeEventResponse,
)
def process_monitor_change_endpoint(
    production_id: str,
    payload: MonitorJobRequest,
    session: Annotated[Session, Depends(get_session)],
) -> MonitorChangeEventResponse:
    return _monitor_change_event_response(
        process_monitor_change(
            session,
            production_id,
            payload=payload.model_dump(mode="json"),
        )
    )


@app.post("/productions/{production_id}/monitor/jobs", response_model=JobResponse)
def enqueue_monitor_endpoint(
    production_id: str,
    payload: MonitorJobRequest,
    session: Annotated[Session, Depends(get_session)],
) -> JobResponse:
    job = enqueue_monitor_job(
        session,
        production_id,
        payload=payload.model_dump(mode="json"),
    )
    _dispatch_job_or_raise(job)
    return _job_response(job)


@app.get(
    "/productions/{production_id}/monitor/findings",
    response_model=list[MonitorFindingResponse],
)
def list_monitor_findings_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[MonitorFindingResponse]:
    return [
        _monitor_finding_response(row)
        for row in list_monitor_findings(session, production_id)
    ]


@app.patch(
    "/monitor/findings/{finding_id}",
    response_model=MonitorFindingDecisionResponse,
)
def decide_monitor_finding_endpoint(
    finding_id: str,
    payload: MonitorFindingDecisionRequest,
    session: Annotated[Session, Depends(get_session)],
    claim: ActorClaimDep,
) -> MonitorFindingDecisionResponse:
    actor_name, actor_role = actor_values(
        claim, requested_name=payload.actor_name, requested_role=payload.actor_role
    )
    finding, replan = decide_monitor_finding(
        session,
        finding_id=finding_id,
        decision=payload.decision,
        actor_name=actor_name,
        actor_role=actor_role,
    )
    return MonitorFindingDecisionResponse(
        finding=_monitor_finding_response(finding),
        replan_request=_replan_request_response(replan) if replan else None,
    )


@app.get(
    "/productions/{production_id}/replan-requests",
    response_model=list[ReplanRequestResponse],
)
def list_replan_requests_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[ReplanRequestResponse]:
    return [
        _replan_request_response(row)
        for row in list_replan_requests(session, production_id)
    ]


@app.post(
    "/replan-requests/{replan_request_id}/options",
    response_model=list[ScheduleDiffResponse],
)
def generate_replan_options_endpoint(
    replan_request_id: str,
    payload: ReplanOptionsRequest,
    session: Annotated[Session, Depends(get_session)],
) -> list[ScheduleDiffResponse]:
    return [
        _schedule_diff_response(row)
        for row in generate_replan_options(
            session,
            replan_request_id=replan_request_id,
            max_options=payload.max_options,
        )
    ]


@app.get(
    "/productions/{production_id}/schedule-diffs",
    response_model=list[ScheduleDiffResponse],
)
def list_schedule_diffs_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[ScheduleDiffResponse]:
    return [
        _schedule_diff_response(row)
        for row in list_schedule_diffs(session, production_id)
    ]


@app.post(
    "/boards/{base_board_id}/diffs/{revised_board_id}",
    response_model=ScheduleDiffResponse,
)
def create_schedule_diff_endpoint(
    base_board_id: str,
    revised_board_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> ScheduleDiffResponse:
    return _schedule_diff_response(
        create_schedule_diff(
            session,
            base_board_id=base_board_id,
            revised_board_id=revised_board_id,
        )
    )


@app.post("/boards/{board_id}/selection", response_model=BoardSelectionResponse)
def select_board_endpoint(
    board_id: str,
    payload: BoardSelectionRequest,
    session: Annotated[Session, Depends(get_session)],
    claim: ActorClaimDep,
) -> BoardSelectionResponse:
    actor_name, actor_role = actor_values(
        claim, requested_name=payload.actor_name, requested_role=payload.actor_role
    )
    return _board_selection_response(
        select_board(
            session,
            board_id=board_id,
            actor_name=actor_name,
            actor_role=actor_role,
            prior_board_id=payload.prior_board_id,
        )
    )


@app.get(
    "/productions/{production_id}/cost-approvals",
    response_model=list[CostApprovalResponse],
)
def list_cost_approvals_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[CostApprovalResponse]:
    return [
        _cost_approval_response(row)
        for row in list_cost_approvals(session, production_id)
    ]


@app.get(
    "/boards/{board_id}/cost-approvals",
    response_model=list[CostApprovalResponse],
)
def list_cost_approvals_for_board_endpoint(
    board_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[CostApprovalResponse]:
    return [
        _cost_approval_response(row)
        for row in list_cost_approvals_for_board(session, board_id)
    ]


@app.post("/boards/{board_id}/cost-approvals", response_model=CostApprovalResponse)
def approve_cost_endpoint(
    board_id: str,
    payload: CostApprovalRequest,
    session: Annotated[Session, Depends(get_session)],
    claim: ActorClaimDep,
) -> CostApprovalResponse:
    actor_name, actor_role = actor_values(
        claim, requested_name=payload.actor_name, requested_role=payload.actor_role
    )
    return _cost_approval_response(
        approve_cost(
            session,
            board_id=board_id,
            actor_name=actor_name,
            actor_role=actor_role,
            cost_delta=payload.cost_delta,
            added_shoot_days=payload.added_shoot_days,
            decision=payload.decision,
        )
    )


@app.get(
    "/productions/{production_id}/coverage-items",
    response_model=list[CoverageItemResponse],
)
def list_coverage_items_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[CoverageItemResponse]:
    return [
        _coverage_item_response(row)
        for row in list_coverage_items(session, production_id)
    ]


@app.get(
    "/productions/{production_id}/coverage-findings",
    response_model=list[CoverageFindingResponse],
)
def list_coverage_findings_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[CoverageFindingResponse]:
    return [
        _coverage_finding_response(row)
        for row in list_coverage_findings(session, production_id)
    ]


@app.get(
    "/productions/{production_id}/pickup-tasks",
    response_model=list[PickupTaskResponse],
)
def list_pickup_tasks_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[PickupTaskResponse]:
    return [
        _pickup_task_response(row) for row in list_pickup_tasks(session, production_id)
    ]


@app.post(
    "/productions/{production_id}/coverage-items",
    response_model=CoverageItemResponse,
)
def record_coverage_item_endpoint(
    production_id: str,
    payload: CoverageItemCreate,
    session: Annotated[Session, Depends(get_session)],
) -> CoverageItemResponse:
    return _coverage_item_response(
        record_coverage_item(
            session,
            production_id,
            **payload.model_dump(mode="json"),
        )
    )


@app.post(
    "/coverage-items/{coverage_item_id}/shot", response_model=CoverageItemResponse
)
def mark_coverage_item_shot_endpoint(
    coverage_item_id: str,
    payload: CoverageShotUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> CoverageItemResponse:
    return _coverage_item_response(
        mark_coverage_item_shot(
            session,
            coverage_item_id=coverage_item_id,
            shot=payload.shot,
        )
    )


@app.post(
    "/coverage-items/{coverage_item_id}/findings",
    response_model=CoverageFindingResponse,
)
def raise_coverage_finding_endpoint(
    coverage_item_id: str,
    payload: CoverageFindingCreate,
    session: Annotated[Session, Depends(get_session)],
    claim: ActorClaimDep,
) -> CoverageFindingResponse:
    actor_name, actor_role = actor_values(
        claim, requested_name=payload.actor_name, requested_role=payload.actor_role
    )
    return _coverage_finding_response(
        raise_coverage_finding(
            session,
            coverage_item_id=coverage_item_id,
            board_id=payload.board_id,
            message=payload.message,
            actor_name=actor_name,
            actor_role=actor_role,
            severity=payload.severity,
        )
    )


@app.post(
    "/coverage-findings/{finding_id}/pickup",
    response_model=PickupTaskResponse,
)
def request_pickup_from_finding_endpoint(
    finding_id: str,
    payload: PickupDecisionRequest,
    session: Annotated[Session, Depends(get_session)],
    claim: ActorClaimDep,
) -> PickupTaskResponse:
    actor_name, actor_role = actor_values(
        claim, requested_name=payload.actor_name, requested_role=payload.actor_role
    )
    return _pickup_task_response(
        request_pickup_from_finding(
            session,
            finding_id=finding_id,
            actor_name=actor_name,
            actor_role=actor_role,
            decision=payload.decision,
        )
    )


@app.post("/pickup-tasks/{pickup_task_id}/confirm", response_model=PickupTaskResponse)
def confirm_pickup_task_endpoint(
    pickup_task_id: str,
    payload: PickupConfirmRequest,
    session: Annotated[Session, Depends(get_session)],
    claim: ActorClaimDep,
) -> PickupTaskResponse:
    actor_name, actor_role = actor_values(
        claim, requested_name=payload.actor_name, requested_role=payload.actor_role
    )
    return _pickup_task_response(
        confirm_pickup_task(
            session,
            pickup_task_id=pickup_task_id,
            pickup_spec=payload.pickup_spec,
            actor_name=actor_name,
            actor_role=actor_role,
        )
    )


@app.post(
    "/pickup-tasks/{pickup_task_id}/replan",
    response_model=ReplanRequestResponse,
)
def create_pickup_replan_endpoint(
    pickup_task_id: str,
    payload: PickupReplanRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ReplanRequestResponse:
    return _replan_request_response(
        create_pickup_replan(
            session,
            pickup_task_id=pickup_task_id,
            current_board_id=payload.current_board_id,
            cutoff_at=payload.cutoff_at,
            lock_policy=payload.lock_policy,
        )
    )


@app.post("/boards/{board_id}/call-sheets", response_model=CallSheetResponse)
def generate_call_sheet_endpoint(
    board_id: str,
    payload: CallSheetGenerateRequest,
    session: Annotated[Session, Depends(get_session)],
    claim: ActorClaimDep,
) -> CallSheetResponse:
    actor_name, actor_role = actor_values(
        claim, requested_name=payload.actor_name, requested_role=payload.actor_role
    )
    return _call_sheet_response(
        generate_call_sheet(
            session,
            board_id=board_id,
            shoot_date=payload.shoot_date,
            actor_name=actor_name,
            actor_role=actor_role,
        )
    )


@app.get("/boards/{board_id}/call-sheets", response_model=list[CallSheetResponse])
def list_call_sheets_endpoint(
    board_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[CallSheetResponse]:
    return [_call_sheet_response(row) for row in list_call_sheets(session, board_id)]


@app.get("/call-sheets/{call_sheet_id}", response_model=CallSheetResponse)
def get_call_sheet_endpoint(
    call_sheet_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> CallSheetResponse:
    return _call_sheet_response(get_call_sheet(session, call_sheet_id))


@app.get("/call-sheets/{call_sheet_id}/export")
def export_call_sheet_endpoint(
    call_sheet_id: str,
    session: Annotated[Session, Depends(get_session)],
    format: Literal["json", "text"] = Query("text"),
) -> Response:
    sheet = get_call_sheet(session, call_sheet_id)
    if format == "text":
        return Response(
            sheet.rendered_text,
            media_type="text/plain",
            headers=_attachment_headers(f"{sheet.id}-call-sheet.txt"),
        )
    return Response(
        json.dumps(call_sheet_export_json(sheet), sort_keys=True),
        media_type="application/json",
        headers=_attachment_headers(f"{sheet.id}.json"),
    )


@app.post(
    "/productions/{production_id}/boards/solve", response_model=ScheduleRunResponse
)
def solve_board_endpoint(
    production_id: str,
    _: ScheduleRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ScheduleRunResponse:
    return _schedule_response(run_scheduler(session, production_id=production_id))


@app.get(
    "/productions/{production_id}/schedule-runs",
    response_model=list[ScheduleRunResponse],
)
def list_schedule_runs_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[ScheduleRunResponse]:
    return [_schedule_response(run) for run in list_schedule_runs(session, production_id)]


@app.get("/schedule-runs/{run_id}", response_model=ScheduleRunResponse)
def get_schedule_run_endpoint(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> ScheduleRunResponse:
    return _schedule_response(get_schedule_run(session, run_id))


@app.get("/boards/{board_id}", response_model=BoardResponse)
def get_board_endpoint(
    board_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> BoardResponse:
    return _board_response(get_board(session, board_id))


@app.get("/boards/{board_id}/export")
def export_board_endpoint(
    board_id: str,
    session: Annotated[Session, Depends(get_session)],
    format: Literal["json", "csv", "text"] = Query("json"),
) -> Response:
    board = get_board(session, board_id)
    if format == "text":
        return Response(
            board.stripboard,
            media_type="text/plain",
            headers=_attachment_headers(f"{board.id}-stripboard.txt"),
        )
    if format == "csv":
        return Response(
            board_export_csv(board),
            media_type="text/csv",
            headers=_attachment_headers(f"{board.id}-strips.csv"),
        )
    return Response(
        json.dumps(board_export_json(board), sort_keys=True),
        media_type="application/json",
        headers=_attachment_headers(f"{board.id}.json"),
    )


@app.post("/demo/run", response_model=BoardResponse)
def run_demo_endpoint(
    session: Annotated[Session, Depends(get_session)],
) -> BoardResponse:
    production = create_production(session, title="The Ferry Job", seed_demo_data=True)
    asset = upload_screenplay(
        session,
        production_id=production.id,
        filename="the_ferry_job.txt",
        content=materialize_demo_script(),
        media="text",
    )
    run_breakdown(
        session,
        production_id=production.id,
        screenplay_asset_id=asset.id,
        auto_accept_schedulable=True,
        agent_mode="fixture",
    )
    schedule_run = run_scheduler(session, production_id=production.id)
    if not schedule_run.board_id:
        raise ServiceError(schedule_run.error or "demo did not produce a board")
    seed_demo_workflow_state(session, production.id, schedule_run.board_id)
    return _board_response(get_board(session, schedule_run.board_id))


def _production_response(
    session: Session, production: ProductionModel
) -> ProductionResponse:
    return ProductionResponse(
        id=production.id,
        title=production.title,
        cast_count=len(list_cast(session, production.id)),
        location_count=len(list_locations(session, production.id)),
        shoot_day_count=len(list_shoot_days(session, production.id)),
    )


def _cast_response(row: CastMemberModel) -> CastMemberResponse:
    return CastMemberResponse(
        id=row.id,
        production_id=row.production_id,
        cast_id=row.cast_id,
        performer=row.performer,
        character=row.character,
        is_minor=row.is_minor,
    )


def _location_response(
    row: LocationModel, aliases: list[LocationAliasModel]
) -> LocationResponse:
    return LocationResponse(
        id=row.id,
        production_id=row.production_id,
        location_id=row.location_id,
        name=row.name,
        city=row.city,
        state=row.state,
        latitude=row.latitude,
        longitude=row.longitude,
        timezone=row.timezone,
        aliases=[
            alias.alias for alias in aliases if alias.location_id == row.location_id
        ],
    )


def _dispatch_job_or_raise(job: JobModel) -> None:
    try:
        dispatch_job(settings, job_id=job.id)
    except Exception as exc:  # noqa: BLE001 - API boundary for cloud dispatch
        raise ServiceError(
            f"queued job {job.id} but failed to dispatch worker task: {exc}",
            status_code=502,
        ) from exc


def _job_response(job: JobModel) -> JobResponse:
    return JobResponse(
        id=job.id,
        production_id=job.production_id,
        job_type=job.job_type,
        target_id=job.target_id,
        status=job.status,
        attempts=job.attempts,
        error=job.error or "",
        result=job.result_json or {},
    )


def _attachment_headers(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


def _audit_event_response(row: AuditEventModel) -> AuditEventResponse:
    return AuditEventResponse(**audit_event_to_json(row))


def _grounding_response(row: GroundingEvidenceModel) -> GroundingEvidenceResponse:
    return GroundingEvidenceResponse(
        id=row.id,
        production_id=row.production_id,
        location_id=row.location_id,
        fact_kind=row.fact_kind,
        target_date=row.target_date,
        status=row.status,
        error=row.error or "",
        evidence=row.evidence_json or {},
    )


def _constraint_proposal_response(
    row: ConstraintProposalModel,
) -> ConstraintProposalResponse:
    return ConstraintProposalResponse(
        id=row.id,
        production_id=row.production_id,
        source_text=row.source_text,
        status=row.status,
        confidence=row.confidence,
        payload=row.payload_json or {},
        validation_errors=list(row.validation_errors_json or []),
        created_by_name=row.created_by_name,
        accepted_by_name=row.accepted_by_name,
        accepted_by_role=row.accepted_by_role,
        accepted_constraint_id=row.accepted_constraint_id,
    )


def _grounded_value_response(row: GroundedValueModel) -> GroundedValueResponse:
    return GroundedValueResponse(
        id=row.id,
        production_id=row.production_id,
        evidence_id=row.evidence_id,
        fact_kind=row.fact_kind,
        location_id=row.location_id,
        target_date=row.target_date,
        normalized_value=row.normalized_value_json or {},
        units=row.units,
        source_url=row.source_url,
        source_quote=row.source_quote,
        source_span=row.source_span,
        query=row.query,
        provider_response_id=row.provider_response_id,
        content_hash=row.content_hash,
        derived_from=row.derived_from,
        validator_result=row.validator_result_json or {},
        covering_date=row.covering_date,
        context_source_urls=list(row.context_source_urls_json or []),
    )


def _constraint_response(row: ConstraintModel) -> ConstraintResponse:
    return ConstraintResponse(
        id=row.id,
        production_id=row.production_id,
        constraint_id=row.constraint_id,
        family=row.family,
        policy=row.policy,
        active=row.active,
        constraint=row.constraint_json or {},
        provenance=row.provenance_json or {},
    )


def _locked_day_response(row: LockedDayModel) -> LockedDayResponse:
    return LockedDayResponse(
        id=row.id,
        production_id=row.production_id,
        board_id=row.board_id,
        schedule_run_id=row.schedule_run_id,
        shoot_date=row.shoot_date,
        locked_assignments=list(row.locked_assignments_json or []),
        locations=list(row.locations_json or []),
        cast=list(row.cast_json or []),
        call_sheet_version=row.call_sheet_version,
        recorded_by_name=row.recorded_by_name,
        recorded_by_role=row.recorded_by_role,
    )


def _monitored_source_response(row: MonitoredSourceModel) -> MonitoredSourceResponse:
    return MonitoredSourceResponse(
        id=row.id,
        production_id=row.production_id,
        board_id=row.board_id,
        source_url=row.source_url,
        fact_kind=row.fact_kind,
        location_id=row.location_id,
        query=row.query,
        provider=row.provider,
        external_monitor_id=row.external_monitor_id,
        status=row.status,
        last_fingerprint=row.last_fingerprint,
    )


def _monitor_change_event_response(
    row: MonitorChangeEventModel,
) -> MonitorChangeEventResponse:
    return MonitorChangeEventResponse(
        id=row.id,
        production_id=row.production_id,
        monitored_source_id=row.monitored_source_id,
        board_id=row.board_id,
        status=row.status,
        material=row.material,
        old_fingerprint=row.old_fingerprint,
        new_fingerprint=row.new_fingerprint,
        payload=row.payload_json or {},
        finding_id=row.finding_id,
        replan_request_id=row.replan_request_id,
    )


def _monitor_finding_response(row: MonitorFindingModel) -> MonitorFindingResponse:
    return MonitorFindingResponse(
        id=row.id,
        production_id=row.production_id,
        board_id=row.board_id,
        evidence_id=row.evidence_id,
        source_url=row.source_url,
        fact_kind=row.fact_kind,
        status=row.status,
        material=row.material,
        message=row.message,
        old_fingerprint=row.old_fingerprint,
        new_fingerprint=row.new_fingerprint,
        old_value=row.old_value_json or {},
        new_value=row.new_value_json or {},
        affected_work_ids=list(row.affected_work_ids_json or []),
        requester_component=row.requester_component,
        reviewed_by_name=row.reviewed_by_name,
        reviewed_by_role=row.reviewed_by_role,
    )


def _replan_request_response(row: ReplanRequestModel) -> ReplanRequestResponse:
    return ReplanRequestResponse(
        id=row.id,
        production_id=row.production_id,
        finding_id=row.finding_id,
        current_board_id=row.current_board_id,
        requester_component=row.requester_component,
        source_kind=row.source_kind,
        source_id=row.source_id,
        reason=row.reason,
        status=row.status,
        affected_work_ids=list(row.affected_work_ids_json or []),
        locked_days=list(row.locked_days_json or []),
    )


def _schedule_diff_response(row: ScheduleDiffModel) -> ScheduleDiffResponse:
    return ScheduleDiffResponse(
        id=row.id,
        production_id=row.production_id,
        base_board_id=row.base_board_id,
        revised_board_id=row.revised_board_id,
        replan_request_id=row.replan_request_id,
        diff=row.diff_json or {},
        required_approvals=list(row.required_approvals_json or []),
        cost_delta=row.cost_delta,
        rendered_text=row.rendered_text,
    )


def _board_selection_response(row: BoardSelectionModel) -> BoardSelectionResponse:
    return BoardSelectionResponse(
        id=row.id,
        production_id=row.production_id,
        prior_board_id=row.prior_board_id,
        selected_board_id=row.selected_board_id,
        prior_schedule_run_id=row.prior_schedule_run_id,
        new_schedule_run_id=row.new_schedule_run_id,
        actor_name=row.actor_name,
        actor_role=row.actor_role,
    )


def _cost_approval_response(row: CostApprovalModel) -> CostApprovalResponse:
    return CostApprovalResponse(
        id=row.id,
        production_id=row.production_id,
        board_id=row.board_id,
        approver_name=row.approver_name,
        approver_role=row.approver_role,
        cost_delta=row.cost_delta,
        added_shoot_days=[
            dt.date.fromisoformat(day) for day in row.added_shoot_days_json or []
        ],
        decision=row.decision,
    )


def _coverage_item_response(row: CoverageItemModel) -> CoverageItemResponse:
    return CoverageItemResponse(
        id=row.id,
        production_id=row.production_id,
        scene_id=row.scene_id,
        coverage_key=row.coverage_key,
        coverage_type=row.coverage_type,
        planned=row.planned_json or {},
        shot=row.shot_json or {},
        status=row.status,
    )


def _coverage_finding_response(row: CoverageFindingModel) -> CoverageFindingResponse:
    return CoverageFindingResponse(
        id=row.id,
        production_id=row.production_id,
        coverage_item_id=row.coverage_item_id,
        board_id=row.board_id,
        status=row.status,
        severity=row.severity,
        message=row.message,
        raised_by_name=row.raised_by_name,
        raised_by_role=row.raised_by_role,
        human_raised=row.human_raised,
    )


def _pickup_task_response(row: PickupTaskModel) -> PickupTaskResponse:
    return PickupTaskResponse(
        id=row.id,
        production_id=row.production_id,
        finding_id=row.finding_id,
        coverage_item_id=row.coverage_item_id,
        board_id=row.board_id,
        status=row.status,
        scene_id=row.scene_id,
        pickup_spec=row.pickup_spec_json or {},
        decision=row.decision_json or {},
        requested_by_name=row.requested_by_name,
        requested_by_role=row.requested_by_role,
        confirmed_by_name=row.confirmed_by_name,
        confirmed_by_role=row.confirmed_by_role,
    )


def _call_sheet_response(row: CallSheetModel) -> CallSheetResponse:
    return CallSheetResponse(
        id=row.id,
        production_id=row.production_id,
        board_id=row.board_id,
        schedule_run_id=row.schedule_run_id,
        shoot_date=row.shoot_date,
        generated_by_name=row.generated_by_name,
        generated_by_role=row.generated_by_role,
        payload=dict(row.payload_json or {}),
        rendered_text=row.rendered_text,
        created_at=row.created_at,
    )


def _asset_response(asset: ScreenplayAssetModel) -> ScreenplayAssetResponse:
    media = "pdf" if asset.media == "pdf" else "text"
    return ScreenplayAssetResponse(
        id=asset.id,
        production_id=asset.production_id,
        filename=asset.filename,
        media=media,
        content_sha256=asset.content_sha256,
        storage_uri=asset.storage_uri,
        normalized_text_uri=asset.normalized_text_uri,
        extraction_metadata=asset.extraction_metadata or {},
        extraction_error=asset.extraction_error or "",
    )


def _scene_page_eighths(scene: dict) -> int:
    value = scene.get("page_eighths", 0)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _candidate_response(candidate: SceneCandidateModel) -> SceneCandidateResponse:
    scene = candidate.scene_json
    return SceneCandidateResponse(
        id=candidate.id,
        scene_id=candidate.scene_id,
        scene_number=candidate.scene_number,
        slugline=str(scene.get("slugline", "")),
        int_ext=str(scene.get("int_ext", "unknown")),
        day_night=str(scene.get("day_night", "unknown")),
        location_ref=str(scene.get("location_ref", "")),
        page_eighths=_scene_page_eighths(scene),
        cast_ids=list(scene.get("cast_ids", [])),
        flags=dict(scene.get("flags", {})),
        source_page_range=str(scene.get("source_page_range", "")),
        confidence=scene.get("confidence"),
        proposal_scene=candidate.proposal_scene_json or scene,
        status=candidate.status,
        accepted=candidate.accepted,
        rejected=candidate.rejected,
        schedulable=candidate.schedulable,
        resolution_errors=list(candidate.resolution_errors),
        number_synthesized=bool(scene.get("number_synthesized", False)),
    )


def _breakdown_response(
    session: Session, run: BreakdownRunModel
) -> BreakdownRunResponse:
    return BreakdownRunResponse(
        id=run.id,
        production_id=run.production_id,
        screenplay_asset_id=run.screenplay_asset_id,
        status=run.status,
        agent_mode=run.agent_mode,
        error=run.error,
        unresolved_locations=list(run.unresolved_locations),
        unresolved_cast=list(run.unresolved_cast),
        candidates=[
            _candidate_response(c) for c in list_candidates_for_run(session, run.id)
        ],
    )


def _schedule_response(run: ScheduleRunModel) -> ScheduleRunResponse:
    return ScheduleRunResponse(
        id=run.id,
        production_id=run.production_id,
        status=run.status,
        error=run.error,
        input_hash=run.input_hash,
        board_id=run.board_id,
        diagnostics=list(run.diagnostics),
        conflict=dict(run.conflict_json or {}),
    )


def _board_response(board: BoardModel) -> BoardResponse:
    return BoardResponse(
        id=board.id,
        production_id=board.production_id,
        schedule_run_id=board.schedule_run_id,
        solver_status=board.solver_status,
        approval_state=board.approval_state,
        stripboard=board.stripboard,
        result=board.result_json,
    )
