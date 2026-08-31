"""FastAPI entrypoint for the deployable Coverset API."""

from __future__ import annotations

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
    BreakdownRunModel,
    CastMemberModel,
    LocationAliasModel,
    LocationModel,
    ProductionModel,
    SceneCandidateModel,
    ScheduleRunModel,
    ScreenplayAssetModel,
)
from .schemas import (  # type: ignore[import-not-found]
    BoardResponse,
    BreakdownRequest,
    BreakdownRunResponse,
    CalendarResponse,
    CalendarUpdate,
    CandidateBatchAcceptResponse,
    CandidateReviewRequest,
    CandidateUpdateRequest,
    CastMemberCreate,
    CastMemberResponse,
    HealthResponse,
    LocationCreate,
    LocationResponse,
    ProductionCreate,
    ProductionResponse,
    SceneCandidateResponse,
    ScheduleRequest,
    ScheduleRunResponse,
    ScreenplayAssetResponse,
)
from .services import (  # type: ignore[import-not-found]
    ServiceError,
    add_cast_member,
    add_location,
    batch_accept_candidates,
    create_production,
    get_board,
    get_breakdown_run,
    get_production,
    get_schedule_run,
    list_aliases,
    list_candidates_for_run,
    list_cast,
    list_locations,
    list_shoot_days,
    materialize_demo_script,
    review_candidate,
    run_breakdown,
    run_scheduler,
    set_calendar,
    update_candidate,
    upload_screenplay,
)

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
