"""FastAPI entrypoint for the deployable Coverset API."""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .config import get_settings  # type: ignore[import-not-found]
from .db import get_session, init_db  # type: ignore[import-not-found]
from .models import (  # type: ignore[import-not-found]
    BoardModel,
    BoardSelectionModel,
    BreakdownRunModel,
    CastMemberModel,
    ConstraintModel,
    CostApprovalModel,
    GroundingEvidenceModel,
    JobModel,
    LocationAliasModel,
    LocationModel,
    LockedDayModel,
    MonitorFindingModel,
    ProductionModel,
    ReplanRequestModel,
    SceneCandidateModel,
    ScheduleRunModel,
    ScreenplayAssetModel,
)
from .schemas import (  # type: ignore[import-not-found]
    BoardResponse,
    BoardSelectionRequest,
    BoardSelectionResponse,
    BreakdownRequest,
    BreakdownRunResponse,
    CalendarResponse,
    CalendarUpdate,
    CandidateBatchAcceptResponse,
    CandidateReviewRequest,
    CandidateUpdateRequest,
    CastMemberCreate,
    CastMemberResponse,
    ConstraintActivationRequest,
    ConstraintCreate,
    ConstraintResponse,
    CostApprovalRequest,
    CostApprovalResponse,
    GroundingEvidenceResponse,
    GroundingRequest,
    HealthResponse,
    JobResponse,
    LocationCreate,
    LocationResponse,
    LockDayRequest,
    LockedDayResponse,
    MonitorFindingDecisionRequest,
    MonitorFindingDecisionResponse,
    MonitorFindingResponse,
    MonitorJobRequest,
    ProductionCreate,
    ProductionResponse,
    ReplanRequestResponse,
    SceneCandidateResponse,
    ScheduleRequest,
    ScheduleRunResponse,
    ScreenplayAssetResponse,
)
from .services import (  # type: ignore[import-not-found]
    ServiceError,
    activate_constraint,
    add_cast_member,
    add_location,
    approve_cost,
    batch_accept_candidates,
    create_constraint,
    create_production,
    decide_monitor_finding,
    enqueue_breakdown_job,
    enqueue_grounding_job,
    enqueue_monitor_job,
    enqueue_schedule_job,
    get_board,
    get_breakdown_run,
    get_job,
    get_production,
    get_schedule_run,
    ground_fact,
    list_aliases,
    list_candidates_for_run,
    list_cast,
    list_constraints,
    list_grounding_evidence,
    list_jobs,
    list_locations,
    list_locked_days,
    list_monitor_findings,
    list_replan_requests,
    list_shoot_days,
    lock_board_day,
    materialize_demo_script,
    review_candidate,
    run_breakdown,
    run_scheduler,
    select_board,
    set_calendar,
    update_candidate,
    upload_screenplay,
)
from .tasks import dispatch_job  # type: ignore[import-not-found]

settings = get_settings()


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


@app.post(
    "/productions/{production_id}/breakdowns/jobs", response_model=JobResponse
)
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


@app.post(
    "/productions/{production_id}/boards/solve/jobs", response_model=JobResponse
)
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


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job_endpoint(
    job_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> JobResponse:
    return _job_response(get_job(session, job_id))


@app.post(
    "/productions/{production_id}/grounding/jobs", response_model=JobResponse
)
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


@app.post(
    "/productions/{production_id}/constraints", response_model=ConstraintResponse
)
def create_constraint_endpoint(
    production_id: str,
    payload: ConstraintCreate,
    session: Annotated[Session, Depends(get_session)],
) -> ConstraintResponse:
    return _constraint_response(
        create_constraint(
            session,
            production_id,
            payload=payload.model_dump(exclude_unset=True),
        )
    )


@app.get(
    "/productions/{production_id}/constraints", response_model=list[ConstraintResponse]
)
def list_constraints_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[ConstraintResponse]:
    return [_constraint_response(row) for row in list_constraints(session, production_id)]


@app.patch("/constraints/{constraint_id}/activation", response_model=ConstraintResponse)
def activate_constraint_endpoint(
    constraint_id: str,
    payload: ConstraintActivationRequest,
    session: Annotated[Session, Depends(get_session)],
) -> ConstraintResponse:
    return _constraint_response(
        activate_constraint(
            session,
            constraint_row_id=constraint_id,
            active=payload.active,
            actor_name=payload.actor_name,
            actor_role=payload.actor_role,
        )
    )


@app.post("/boards/{board_id}/locks", response_model=LockedDayResponse)
def lock_board_day_endpoint(
    board_id: str,
    payload: LockDayRequest,
    session: Annotated[Session, Depends(get_session)],
) -> LockedDayResponse:
    return _locked_day_response(
        lock_board_day(
            session,
            board_id=board_id,
            shoot_date=payload.shoot_date,
            call_sheet_version=payload.call_sheet_version,
            actor_name=payload.actor_name,
            actor_role=payload.actor_role,
        )
    )


@app.get("/productions/{production_id}/locks", response_model=list[LockedDayResponse])
def list_locked_days_endpoint(
    production_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> list[LockedDayResponse]:
    return [_locked_day_response(row) for row in list_locked_days(session, production_id)]


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
) -> MonitorFindingDecisionResponse:
    finding, replan = decide_monitor_finding(
        session,
        finding_id=finding_id,
        decision=payload.decision,
        actor_name=payload.actor_name,
        actor_role=payload.actor_role,
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
        _replan_request_response(row) for row in list_replan_requests(session, production_id)
    ]


@app.post("/boards/{board_id}/selection", response_model=BoardSelectionResponse)
def select_board_endpoint(
    board_id: str,
    payload: BoardSelectionRequest,
    session: Annotated[Session, Depends(get_session)],
) -> BoardSelectionResponse:
    return _board_selection_response(
        select_board(
            session,
            board_id=board_id,
            actor_name=payload.actor_name,
            actor_role=payload.actor_role,
            prior_board_id=payload.prior_board_id,
        )
    )


@app.post("/boards/{board_id}/cost-approvals", response_model=CostApprovalResponse)
def approve_cost_endpoint(
    board_id: str,
    payload: CostApprovalRequest,
    session: Annotated[Session, Depends(get_session)],
) -> CostApprovalResponse:
    return _cost_approval_response(
        approve_cost(
            session,
            board_id=board_id,
            actor_name=payload.actor_name,
            actor_role=payload.actor_role,
            cost_delta=payload.cost_delta,
            added_shoot_days=payload.added_shoot_days,
            decision=payload.decision,
        )
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
        status=row.status,
        affected_work_ids=list(row.affected_work_ids_json or []),
        locked_days=list(row.locked_days_json or []),
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
    )


def _board_response(board: BoardModel) -> BoardResponse:
    return BoardResponse(
        id=board.id,
        production_id=board.production_id,
        schedule_run_id=board.schedule_run_id,
        solver_status=board.solver_status,
        stripboard=board.stripboard,
        result=board.result_json,
    )
