"""Application services that wrap Coverset's domain modules for HTTP/worker use."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import replace
from io import BytesIO, StringIO
from typing import Any, Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session

import coverset.breakdown as breakdown  # type: ignore[import-not-found]
from coverset.actors import Actor, AuthorityError, Role
from coverset.breakdown import RawScene  # type: ignore[import-not-found]
from coverset.call_sheet import (  # type: ignore[import-not-found]
    CallSheetInputError,
    build_call_sheet_payload,
    render_call_sheet_text,
)
from coverset.constraints import (
    AlgorithmSource,
    BlackoutDates,
    ConstraintError,
    ConstraintRecord,
    ConstraintSet,
    DateWindows,
    Family,
    GroundedSource,
    HumanSource,
    PinnedDay,
    Policy,
    Subject,
    SubjectKind,
)
from coverset.grounding import (
    Evidence,
    FactKind,
    GroundingError,
    SearchGrounder,
    SourceExcerpt,
)
from coverset.locations import Location
from coverset.scenes import CandidateStatus, SceneRecord
from coverset.solver import (
    ConflictSet,
    ProductionCalendar,
    ScheduleProblem,
    SolverError,
    solve,
)
from coverset.stripboard import stripboard
from coverset.work import DayNight

from .config import Settings, get_settings  # type: ignore[import-not-found]
from .constraints_io import (  # type: ignore[import-not-found]
    constraint_from_json,
    constraint_from_payload,
    constraint_to_json,
    evidence_to_json,
)
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
    MonitorFindingModel,
    PickupTaskModel,
    ProductionModel,
    ReplanRequestModel,
    SceneCandidateModel,
    ScheduleRunModel,
    ScreenplayAssetModel,
    ShootDayModel,
    new_id,
    utcnow,
)
from .serializers import (  # type: ignore[import-not-found]
    aliases_from_models,
    board_to_json,
    default_calendar,
    flags_from_json,
    flags_to_json,
    locations_from_models,
    roster_from_models,
    scene_from_json,
    scene_to_json,
)
from .storage import ObjectStorage, sha256_bytes  # type: ignore[import-not-found]

delete = sa.delete
select = sa.select


class ServiceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class HasExtract(Protocol):
    def extract(self, document: bytes, *, media: str) -> tuple[RawScene, ...]: ...


class HasGround(Protocol):
    def ground(self, kind: FactKind, location: Location, date: dt.date) -> Evidence: ...


class HasAuditSink(Protocol):
    def append_rows(self, rows: list[dict[str, Any]]) -> int: ...


def audit(
    session: Session,
    production_id: str | None,
    event_type: str,
    payload: dict,
    *,
    actor: str = "system",
) -> None:
    session.add(
        AuditEventModel(
            id=new_id("audit"),
            production_id=production_id,
            event_type=event_type,
            actor=actor,
            payload=payload,
        )
    )


ANSWER_KEY = (
    RawScene("INT. MAYA'S APARTMENT - NIGHT", ("MAYA", "DEV"), "1", 8, 0.95),
    RawScene(
        "EXT. BROOKLYN BRIDGE PARK - DAY", ("MAYA", "DEV"), "2", 6, 0.92, stunt=True
    ),
    RawScene("INT. WAREHOUSE - CONTINUOUS", ("RUTH",), None, 3, 0.88),
    RawScene(
        "EXT. FERRY TERMINAL / RIVER DOCK - DUSK", ("MAYA",), None, 4, 0.82, vfx=True
    ),
    RawScene("INT. MAYA'S APARTMENT - DAY", ("MAYA", "KID"), "3", 3, 0.70, minors=True),
)


class FixtureBreakdownAgent:
    """Deterministic demo agent for local smoke tests and deploy health checks."""

    def extract(self, document: bytes, *, media: str) -> tuple[RawScene, ...]:
        if not document:
            raise ServiceError("screenplay document is empty")
        return ANSWER_KEY


def _agent_for_mode(mode: str, *, settings: Settings) -> HasExtract:
    if mode == "fixture":
        return FixtureBreakdownAgent()
    if mode == "gemini":
        return breakdown.GeminiBreakdown()
    raise ServiceError(f"unsupported breakdown agent mode: {mode}")


def _actor_for_decision(
    name: str,
    role: str,
    *,
    capability: str | None = None,
) -> Actor:
    try:
        actor = Actor(name, Role(role))
        if capability is not None:
            actor.require(capability)
    except (AuthorityError, ValueError) as exc:
        raise ServiceError(str(exc), status_code=403) from exc
    return actor


def create_production(
    session: Session, *, title: str, seed_demo_data: bool = True
) -> ProductionModel:
    production = ProductionModel(id=new_id("prod"), title=title)
    session.add(production)
    session.flush()
    if seed_demo_data:
        seed_demo_entities(session, production.id)
    audit(session, production.id, "production.created", {"title": title})
    session.commit()
    return production


class FixtureGrounder:
    def ground(self, kind: FactKind, location: Location, date: dt.date) -> Evidence:
        if kind is FactKind.WEATHER:
            url = "https://fixtures.coverset.local/weather-forecast"
            quote = f"{date.isoformat()}: precipitation probability 85%."
        else:
            url = "https://fixtures.coverset.local/film-permits"
            quote = (
                f"{date.isoformat()}: Film permit allows exterior work from "
                "07:00 to 22:00."
            )
        return Evidence(
            kind=kind,
            location=location,
            date=date,
            sources=(
                SourceExcerpt(
                    url=url,
                    excerpts=(quote,),
                    title="Fixture grounded source",
                    publish_date=date.isoformat(),
                    full_content=quote,
                ),
            ),
            search_id=f"fixture-{kind.value}-{date.isoformat()}",
            session_id=f"fixture-{kind.value}",
            retrieved_at=dt.datetime.now(dt.UTC),
            escalated=True,
            covering_urls=(url,),
        )


def seed_demo_entities(session: Session, production_id: str) -> None:
    if session.scalars(
        select(CastMemberModel).where(CastMemberModel.production_id == production_id)
    ).first():
        return
    cast = (
        CastMemberModel(
            id=new_id("castrow"),
            production_id=production_id,
            cast_id="cast-maya",
            performer="A. Idowu",
            character="MAYA",
        ),
        CastMemberModel(
            id=new_id("castrow"),
            production_id=production_id,
            cast_id="cast-dev",
            performer="B. Whitfield",
            character="DEV",
        ),
        CastMemberModel(
            id=new_id("castrow"),
            production_id=production_id,
            cast_id="cast-ruth",
            performer="C. Okonkwo",
            character="RUTH",
        ),
        CastMemberModel(
            id=new_id("castrow"),
            production_id=production_id,
            cast_id="cast-kid",
            performer="D. Alvarez",
            character="KID",
            is_minor=True,
        ),
    )
    locations = (
        LocationModel(
            id=new_id("locrow"),
            production_id=production_id,
            location_id="maya-s-apartment",
            name="Maya's Apartment",
            city="Brooklyn",
            state="NY",
            latitude=40.700,
            longitude=-73.990,
            timezone="America/New_York",
        ),
        LocationModel(
            id=new_id("locrow"),
            production_id=production_id,
            location_id="brooklyn-bridge-park",
            name="Brooklyn Bridge Park",
            city="Brooklyn",
            state="NY",
            latitude=40.7002,
            longitude=-73.9967,
            timezone="America/New_York",
        ),
        LocationModel(
            id=new_id("locrow"),
            production_id=production_id,
            location_id="warehouse",
            name="Warehouse",
            city="Queens",
            state="NY",
            latitude=40.742,
            longitude=-73.938,
            timezone="America/New_York",
        ),
        LocationModel(
            id=new_id("locrow"),
            production_id=production_id,
            location_id="ferry-terminal",
            name="Ferry Terminal",
            city="Manhattan",
            state="NY",
            latitude=40.701,
            longitude=-74.013,
            timezone="America/New_York",
        ),
    )
    aliases = (
        LocationAliasModel(
            id=new_id("alias"),
            production_id=production_id,
            alias="FERRY TERMINAL / RIVER DOCK",
            location_id="ferry-terminal",
        ),
    )
    shoot_days = tuple(
        ShootDayModel(
            id=new_id("day"),
            production_id=production_id,
            shoot_date=day,
            day_order=i,
        )
        for i, day in enumerate(default_calendar().days)
    )
    session.add_all([*cast, *locations, *aliases, *shoot_days])
    audit(
        session,
        production_id,
        "production.demo_seeded",
        {"cast": 4, "locations": 4, "shoot_days": len(shoot_days)},
    )


def seed_demo_workflow_state(
    session: Session, production_id: str, board_id: str
) -> None:
    """Populate the demo production with persisted UI workflow state.

    The browser routes should render backend state after reload, not local placeholders.
    This seeds the demo through the same service calls used by the operational UI.
    """
    board = get_board(session, board_id)
    days = [
        dt.date.fromisoformat(str(day["date"]))
        for day in board.result_json.get("days", [])
        if day.get("date")
    ]
    strips = list(board.result_json.get("strips", []))
    if not days or not strips:
        return

    first_day = days[0]
    first_strip = dict(strips[0])
    location_id = str(first_strip.get("location_id") or "")
    scene_id = str(first_strip.get("scene_id") or "")
    work_id = str(first_strip.get("work_id") or scene_id)
    cast_ids = [str(cast_id) for cast_id in first_strip.get("cast_ids", [])]

    proposals = translate_constraint_text(
        session,
        production_id,
        text="Maximum daily hours 11",
        actor_name="R. Okonkwo",
    )
    for proposal in proposals:
        if proposal.status == "candidate" and not proposal.accepted_constraint_id:
            accept_constraint_proposal(
                session,
                proposal_id=proposal.id,
                actor_name="R. Okonkwo",
                actor_role="first_ad",
            )
            break

    evidence = ground_fact(
        session,
        production_id,
        kind="weather",
        location_id=location_id,
        target_date=first_day,
        grounder=FixtureGrounder(),
    )
    if evidence.status == "complete":
        source_url = str(evidence.evidence_json["covering_urls"][0])
        source_quote = str(evidence.evidence_json["sources"][0]["excerpts"][0])
        record_grounded_value(
            session,
            evidence_id=evidence.id,
            normalized_value={"condition": "rain", "probability": 0.85},
            units="probability_0_1",
            source_url=source_url,
            source_quote=source_quote,
            source_span="fixture forecast excerpt",
            query="weather risk for scheduled shoot day",
            validator_family="weather",
            validator_reason="fixture source covers the scheduled date",
        )

    monitor_source = register_monitored_source(
        session,
        production_id,
        board_id=board.id,
        source_url="https://fixtures.coverset.local/weather-forecast",
        fact_kind="weather",
        location_id=location_id,
        query="weather risk for scheduled shoot day",
        external_monitor_id=f"fixture-monitor-{board.id}",
    )
    monitor_event = process_monitor_change(
        session,
        production_id,
        payload={
            "monitored_source_id": monitor_source.id,
            "board_id": board.id,
            "source_url": monitor_source.source_url,
            "fact_kind": monitor_source.fact_kind,
            "old_fingerprint": "rain-20",
            "new_fingerprint": "rain-85",
            "old_value": {"probability": 0.2},
            "new_value": {"probability": 0.85},
            "affected_work_ids": [work_id],
            "material": True,
            "message": "fixture weather risk crossed the replan threshold",
        },
    )
    if monitor_event.replan_request_id:
        try:
            generate_replan_options(
                session,
                replan_request_id=monitor_event.replan_request_id,
                max_options=1,
            )
        except ServiceError as exc:
            audit(
                session,
                production_id,
                "production.demo_seed_replan_skipped",
                {"replan_request_id": monitor_event.replan_request_id, "error": str(exc)},
            )

    lock_board_day(
        session,
        board_id=board.id,
        shoot_date=first_day,
        call_sheet_version=f"actuals-{first_day.isoformat()}",
        actor_name="S. Patel",
        actor_role="script_supervisor",
    )
    generate_call_sheet(
        session,
        board_id=board.id,
        shoot_date=first_day,
        actor_name="T. Nguyen",
        actor_role="second_ad",
    )

    coverage = record_coverage_item(
        session,
        production_id,
        scene_id=scene_id,
        coverage_key=f"fixture-{scene_id}-insert-a",
        coverage_type="insert",
        planned={"shot": "insert", "source": "script supervisor actual"},
    )
    mark_coverage_item_shot(
        session,
        coverage_item_id=coverage.id,
        shot={"take": "A3", "usable": False},
    )
    finding = raise_coverage_finding(
        session,
        coverage_item_id=coverage.id,
        board_id=board.id,
        message="insert is unusable from camera shake",
        actor_name="S. Patel",
        actor_role="script_supervisor",
    )
    pickup = request_pickup_from_finding(
        session,
        finding_id=finding.id,
        actor_name="A. Kowalczyk",
        actor_role="director",
    )
    confirm_pickup_task(
        session,
        pickup_task_id=pickup.id,
        pickup_spec={
            "scene_id": scene_id,
            "coverage_type": "insert",
            "location_id": location_id,
            "cast_ids": cast_ids,
            "duration_minutes": 15,
            "priority": "must_have",
            "day_night": str(first_strip.get("day_night") or "day"),
        },
        actor_name="R. Okonkwo",
        actor_role="first_ad",
    )
    pickup_replan = create_pickup_replan(
        session,
        pickup_task_id=pickup.id,
        current_board_id=board.id,
        cutoff_at=dt.datetime.combine(
            first_day,
            dt.time(hour=12, tzinfo=dt.timezone(dt.timedelta(hours=-4))),
        ),
        lock_policy="preserve_locked",
    )
    diffs = generate_replan_options(
        session,
        replan_request_id=pickup_replan.id,
        max_options=1,
    )
    if diffs:
        diff = diffs[0]
        added_days = [
            dt.date.fromisoformat(day) for day in diff.diff_json.get("added_days", [])
        ]
        approve_cost(
            session,
            board_id=diff.revised_board_id,
            actor_name="M. Chen",
            actor_role="upm",
            cost_delta=diff.cost_delta or 0,
            added_shoot_days=added_days,
            decision="approved",
        )

    _seed_demo_infeasible_conflict(
        session,
        production_id=production_id,
        shoot_days=days,
        cast_ids=cast_ids,
    )


def _seed_demo_infeasible_conflict(
    session: Session,
    *,
    production_id: str,
    shoot_days: Sequence[dt.date],
    cast_ids: Sequence[str],
) -> None:
    """Persist one truthful infeasible run for the demo conflict screen.

    The temporary hard constraints are deactivated after the run so the seeded
    production keeps its selected optimal board while `/schedule-runs` still
    exposes real backend conflict metadata for the infeasible diagnostics route.
    """
    if len(shoot_days) < 2 or not cast_ids:
        return

    created: list[ConstraintModel] = []
    pairs = (("DEMO-CONFLICT-DEV-D2", cast_ids[-1], shoot_days[1]),)
    try:
        for constraint_id, cast_id, day in pairs:
            created.append(
                create_constraint(
                    session,
                    production_id,
                    payload={
                        "constraint_id": constraint_id,
                        "family": "cast",
                        "policy": "hard",
                        "subject_kind": "cast",
                        "subject_ref": cast_id,
                        "expression_type": "date_windows",
                        "windows": [{"start": day, "end": day}],
                        "statement": (
                            f"{cast_id} fixture availability is restricted "
                            f"to {day.isoformat()}."
                        ),
                        "active": True,
                    },
                )
            )
        run = run_scheduler(session, production_id=production_id)
        if run.status != "infeasible" or not run.conflict_json:
            audit(
                session,
                production_id,
                "production.demo_seed_conflict_skipped",
                {"schedule_run_id": run.id, "status": run.status},
            )
            session.commit()
    finally:
        for row in created:
            activate_constraint(
                session,
                constraint_row_id=row.id,
                active=False,
                actor_name="R. Okonkwo",
                actor_role="first_ad",
            )


def get_production(session: Session, production_id: str) -> ProductionModel:
    production = session.get(ProductionModel, production_id)
    if production is None:
        raise ServiceError(f"production not found: {production_id}", status_code=404)
    return production


def list_cast(session: Session, production_id: str) -> list[CastMemberModel]:
    return list(
        session.scalars(
            select(CastMemberModel).where(
                CastMemberModel.production_id == production_id
            )
        )
    )


def list_locations(session: Session, production_id: str) -> list[LocationModel]:
    return list(
        session.scalars(
            select(LocationModel).where(LocationModel.production_id == production_id)
        )
    )


def list_aliases(session: Session, production_id: str) -> list[LocationAliasModel]:
    return list(
        session.scalars(
            select(LocationAliasModel).where(
                LocationAliasModel.production_id == production_id
            )
        )
    )


def add_cast_member(
    session: Session,
    production_id: str,
    *,
    cast_id: str,
    performer: str,
    character: str,
    is_minor: bool = False,
) -> CastMemberModel:
    get_production(session, production_id)
    normalized_id = _stable_id(cast_id)
    if _cast_id_exists(session, production_id, normalized_id):
        raise ServiceError(f"cast id already exists: {normalized_id}", status_code=409)
    row = CastMemberModel(
        id=new_id("castrow"),
        production_id=production_id,
        cast_id=normalized_id,
        performer=performer.strip(),
        character=character.strip().upper(),
        is_minor=is_minor,
    )
    session.add(row)
    audit(
        session,
        production_id,
        "cast.created",
        {"cast_id": row.cast_id, "character": row.character},
    )
    session.commit()
    return row


def add_location(
    session: Session,
    production_id: str,
    *,
    location_id: str,
    name: str,
    city: str,
    state: str,
    latitude: float | None = None,
    longitude: float | None = None,
    timezone: str = "America/New_York",
    aliases: list[str] | None = None,
) -> LocationModel:
    get_production(session, production_id)
    normalized_id = _stable_id(location_id)
    if _location_id_exists(session, production_id, normalized_id):
        raise ServiceError(
            f"location id already exists: {normalized_id}", status_code=409
        )
    if latitude is not None and not -90 <= latitude <= 90:
        raise ServiceError("latitude must be between -90 and 90")
    if longitude is not None and not -180 <= longitude <= 180:
        raise ServiceError("longitude must be between -180 and 180")
    row = LocationModel(
        id=new_id("locrow"),
        production_id=production_id,
        location_id=normalized_id,
        name=name.strip(),
        city=city.strip(),
        state=state.strip(),
        latitude=latitude,
        longitude=longitude,
        timezone=timezone.strip() or "America/New_York",
    )
    session.add(row)
    for alias in aliases or []:
        cleaned = alias.strip()
        if cleaned:
            session.add(
                LocationAliasModel(
                    id=new_id("alias"),
                    production_id=production_id,
                    alias=cleaned,
                    location_id=row.location_id,
                )
            )
    audit(
        session,
        production_id,
        "location.created",
        {"location_id": row.location_id, "name": row.name},
    )
    session.commit()
    return row


def list_shoot_days(session: Session, production_id: str) -> list[ShootDayModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(ShootDayModel)
            .where(ShootDayModel.production_id == production_id)
            .order_by(ShootDayModel.day_order, ShootDayModel.shoot_date)
        )
    )


def set_calendar(
    session: Session, production_id: str, *, shoot_dates: list[dt.date]
) -> list[ShootDayModel]:
    get_production(session, production_id)
    unique_dates = tuple(sorted(set(shoot_dates)))
    if len(unique_dates) != len(shoot_dates):
        raise ServiceError("shoot dates must not contain duplicates")
    session.execute(
        delete(ShootDayModel).where(ShootDayModel.production_id == production_id)
    )
    rows = [
        ShootDayModel(
            id=new_id("day"),
            production_id=production_id,
            shoot_date=day,
            day_order=i,
        )
        for i, day in enumerate(unique_dates)
    ]
    session.add_all(rows)
    audit(
        session,
        production_id,
        "calendar.updated",
        {"shoot_dates": [day.isoformat() for day in unique_dates]},
    )
    session.commit()
    return rows


def _production_calendar(session: Session, production_id: str) -> ProductionCalendar:
    days = tuple(row.shoot_date for row in list_shoot_days(session, production_id))
    return ProductionCalendar(days) if days else default_calendar()


def _cast_id_exists(session: Session, production_id: str, cast_id: str) -> bool:
    return (
        session.scalars(
            select(CastMemberModel).where(
                CastMemberModel.production_id == production_id,
                CastMemberModel.cast_id == cast_id,
            )
        ).first()
        is not None
    )


def _location_id_exists(session: Session, production_id: str, location_id: str) -> bool:
    return (
        session.scalars(
            select(LocationModel).where(
                LocationModel.production_id == production_id,
                LocationModel.location_id == location_id,
            )
        ).first()
        is not None
    )


def _stable_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug or new_id("id")


def upload_screenplay(
    session: Session,
    *,
    production_id: str,
    filename: str,
    content: bytes,
    media: str | None = None,
    storage: ObjectStorage | None = None,
) -> ScreenplayAssetModel:
    get_production(session, production_id)
    detected = media or _detect_media(filename)
    if detected not in {"pdf", "text"}:
        raise ServiceError("screenplay upload must be a .pdf or .txt file")
    asset = ScreenplayAssetModel(
        id=new_id("asset"),
        production_id=production_id,
        filename=filename,
        media=detected,
        storage_uri="pending",
        content_sha256=sha256_bytes(content),
    )
    store = storage or ObjectStorage()
    asset.storage_uri = store.put(
        production_id=production_id,
        object_id=asset.id,
        filename=filename,
        content=content,
    )
    text, metadata, extraction_error = _extract_screenplay_text(
        content, media=detected, filename=filename
    )
    asset.extraction_metadata = metadata
    asset.extraction_error = extraction_error
    if text is not None:
        normalized = _normalize_screenplay_text(text).encode("utf-8")
        asset.normalized_text_uri = store.put(
            production_id=production_id,
            object_id=asset.id,
            filename=f"{filename}.normalized.txt",
            content=normalized,
        )
        asset.extraction_metadata = {
            **metadata,
            "normalized_sha256": sha256_bytes(normalized),
            "normalized_bytes": len(normalized),
        }
    session.add(asset)
    audit(
        session,
        production_id,
        "screenplay.uploaded",
        {
            "asset_id": asset.id,
            "media": detected,
            "content_sha256": asset.content_sha256,
            "extraction_error": bool(extraction_error),
        },
    )
    session.commit()
    return asset


def _detect_media(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "pdf"
    if lower.endswith(".txt") or lower.endswith(".fountain"):
        return "text"
    return "unknown"


def _extract_screenplay_text(
    content: bytes, *, media: str, filename: str
) -> tuple[str | None, dict[str, Any], str]:
    if media == "text":
        try:
            return (
                content.decode("utf-8"),
                {"strategy": "utf-8", "source": filename},
                "",
            )
        except UnicodeDecodeError as exc:
            return None, {"strategy": "utf-8", "source": filename}, str(exc)
    if media == "pdf":
        try:
            from pypdf import PdfReader  # type: ignore[import-not-found]

            reader = PdfReader(BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(page for page in pages if page.strip())
            if not text.strip():
                return (
                    None,
                    {"strategy": "pypdf", "pages": len(reader.pages)},
                    "PDF contained no extractable text",
                )
            return text, {"strategy": "pypdf", "pages": len(reader.pages)}, ""
        except Exception as exc:  # noqa: BLE001 - user-facing ingestion boundary
            return None, {"strategy": "pypdf", "source": filename}, str(exc)
    return None, {"strategy": "none", "source": filename}, "unsupported media"


def _normalize_screenplay_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip() + "\n"


def run_breakdown(
    session: Session,
    *,
    production_id: str,
    screenplay_asset_id: str,
    auto_accept_schedulable: bool = False,
    agent_mode: str | None = None,
    agent: HasExtract | None = None,
    storage: ObjectStorage | None = None,
    settings: Settings | None = None,
) -> BreakdownRunModel:
    resolved_settings = settings or get_settings()
    mode = agent_mode or resolved_settings.agent_mode
    get_production(session, production_id)
    asset = session.get(ScreenplayAssetModel, screenplay_asset_id)
    if asset is None or asset.production_id != production_id:
        raise ServiceError(
            f"screenplay asset not found: {screenplay_asset_id}", status_code=404
        )

    run = BreakdownRunModel(
        id=new_id("brk"),
        production_id=production_id,
        screenplay_asset_id=asset.id,
        status="running",
        agent_mode=mode,
    )
    session.add(run)
    session.commit()

    try:
        if asset.extraction_error:
            raise ServiceError(
                f"screenplay extraction failed: {asset.extraction_error}"
            )
        store = storage or ObjectStorage(resolved_settings)
        content_uri = asset.normalized_text_uri or asset.storage_uri
        content = store.get(content_uri)
        parse_media = "text" if asset.normalized_text_uri else asset.media
        records = breakdown.parse(
            content,
            media=parse_media,
            agent=agent or _agent_for_mode(mode, settings=resolved_settings),
        )
        locations = locations_from_models(list_locations(session, production_id))
        roster = roster_from_models(list_cast(session, production_id))
        aliases = aliases_from_models(list_aliases(session, production_id))
        located = breakdown.resolve_locations(
            records, locations=locations, aliases=aliases
        )
        casted = breakdown.resolve_cast(located.records, roster=roster)
        loc_errors = {
            scene_id: place for scene_id, place in located.unresolved_by_scene
        }
        cast_errors = {scene_id: cues for scene_id, cues in casted.unresolved_by_scene}

        for record in casted.records:
            errors = _resolution_errors(record, loc_errors, cast_errors)
            schedulable = _candidate_can_be_scheduled(record, errors)
            accepted = bool(auto_accept_schedulable and schedulable)
            active_scene = breakdown.activate(record) if accepted else None
            scene_snapshot = scene_to_json(record)
            session.add(
                SceneCandidateModel(
                    id=new_id("scene"),
                    production_id=production_id,
                    breakdown_run_id=run.id,
                    scene_id=record.scene_id,
                    scene_number=record.scene_number,
                    status=record.status.value,
                    accepted=accepted,
                    rejected=False,
                    schedulable=schedulable,
                    resolution_errors=errors,
                    proposal_scene_json=scene_snapshot,
                    scene_json=scene_snapshot,
                    active_scene_json=scene_to_json(active_scene)
                    if active_scene
                    else None,
                    reviewed_at=utcnow() if accepted else None,
                )
            )
        run.status = "complete"
        run.unresolved_locations = list(located.unresolved)
        run.unresolved_cast = list(casted.unresolved)
        run.completed_at = utcnow()
        audit(
            session,
            production_id,
            "breakdown.completed",
            {"run_id": run.id, "agent_mode": mode},
        )
    except Exception as exc:  # noqa: BLE001 - boundary records failures durably
        run.status = "failed"
        run.error = str(exc)
        run.completed_at = utcnow()
        audit(
            session,
            production_id,
            "breakdown.failed",
            {"run_id": run.id, "error": str(exc)},
        )
    session.commit()
    return run


def _resolution_errors(
    record: SceneRecord,
    loc_errors: dict[str, str],
    cast_errors: dict[str, tuple[str, ...]],
) -> list[str]:
    errors: list[str] = []
    if record.scene_id in loc_errors:
        errors.append(f"unresolved location: {loc_errors[record.scene_id]}")
    for cue in cast_errors.get(record.scene_id, ()):
        errors.append(f"unresolved cast cue: {cue}")
    if record.day_night is DayNight.UNKNOWN:
        errors.append("unresolved day/night")
    if record.day_night is DayNight.DUSK:
        errors.append("dusk scenes require manual scheduling until DAY-011")
    if record.day_night is DayNight.DAWN:
        errors.append("dawn scenes require manual scheduling until DAY-011")
    return errors


def _candidate_can_be_scheduled(record: SceneRecord, errors: list[str]) -> bool:
    return (
        record.status is CandidateStatus.CANDIDATE
        and not errors
        and record.day_night in (DayNight.DAY, DayNight.NIGHT)
    )


def review_candidate(
    session: Session, *, candidate_id: str, decision: str
) -> SceneCandidateModel:
    candidate = _get_candidate(session, candidate_id)
    if decision == "reject":
        candidate.rejected = True
        candidate.accepted = False
        candidate.status = CandidateStatus.REJECTED.value
        candidate.active_scene_json = None
        candidate.reviewed_at = utcnow()
        audit(
            session,
            candidate.production_id,
            "scene.rejected",
            {"candidate_id": candidate.id},
        )
        session.commit()
        return candidate
    if decision != "accept":
        raise ServiceError(f"unsupported candidate review decision: {decision}")
    if not candidate.schedulable:
        raise ServiceError(
            "candidate cannot be accepted for scheduling until it is fully resolved: "
            + "; ".join(candidate.resolution_errors)
        )
    record = replace(
        scene_from_json(candidate.scene_json), status=CandidateStatus.CANDIDATE
    )
    active = breakdown.activate(record)
    candidate.accepted = True
    candidate.rejected = False
    candidate.status = CandidateStatus.ACTIVE.value
    candidate.scene_json = scene_to_json(record)
    candidate.active_scene_json = scene_to_json(active)
    candidate.reviewed_at = utcnow()
    audit(
        session,
        candidate.production_id,
        "scene.accepted",
        {"candidate_id": candidate.id},
    )
    session.commit()
    return candidate


def update_candidate(
    session: Session, *, candidate_id: str, changes: dict[str, Any]
) -> SceneCandidateModel:
    candidate = _get_candidate(session, candidate_id)
    before = dict(candidate.scene_json)
    current = dict(candidate.scene_json)
    for key in (
        "scene_number",
        "slugline",
        "int_ext",
        "day_night",
        "location_ref",
        "page_eighths",
        "source_page_range",
    ):
        if key in changes and changes[key] is not None:
            current[key] = changes[key]
    if "cast_ids" in changes and changes["cast_ids"] is not None:
        current["cast_ids"] = [
            str(c).strip() for c in changes["cast_ids"] if str(c).strip()
        ]
    if "flags" in changes and changes["flags"] is not None:
        flags = flags_from_json(changes["flags"])
        current["flags"] = flags_to_json(flags)
    current["status"] = CandidateStatus.CANDIDATE.value
    try:
        record = scene_from_json(current)
    except (KeyError, TypeError, ValueError) as exc:
        raise ServiceError(f"invalid scene edit: {exc}") from exc
    record, errors, schedulable = _resolve_candidate_record(
        session, candidate.production_id, record
    )
    candidate.scene_json = scene_to_json(record)
    candidate.scene_number = record.scene_number
    candidate.status = record.status.value
    candidate.accepted = False
    candidate.rejected = False
    candidate.schedulable = schedulable
    candidate.resolution_errors = errors
    candidate.active_scene_json = None
    candidate.reviewed_at = None
    audit(
        session,
        candidate.production_id,
        "scene.edited",
        {"candidate_id": candidate.id, "before": before, "after": candidate.scene_json},
    )
    session.commit()
    return candidate


def batch_accept_candidates(
    session: Session, *, run_id: str
) -> tuple[list[str], dict[str, list[str]], list[SceneCandidateModel]]:
    get_breakdown_run(session, run_id)
    candidates = list_candidates_for_run(session, run_id)
    accepted: list[str] = []
    skipped: dict[str, list[str]] = {}
    for candidate in candidates:
        if candidate.accepted:
            accepted.append(candidate.id)
            continue
        if candidate.rejected:
            skipped[candidate.id] = ["candidate is rejected"]
            continue
        if not candidate.schedulable:
            skipped[candidate.id] = list(candidate.resolution_errors) or [
                "not schedulable"
            ]
            continue
        record = replace(
            scene_from_json(candidate.scene_json), status=CandidateStatus.CANDIDATE
        )
        active = breakdown.activate(record)
        candidate.accepted = True
        candidate.rejected = False
        candidate.status = CandidateStatus.ACTIVE.value
        candidate.scene_json = scene_to_json(record)
        candidate.active_scene_json = scene_to_json(active)
        candidate.reviewed_at = utcnow()
        accepted.append(candidate.id)
    audit(
        session,
        candidates[0].production_id if candidates else None,
        "scene.batch_accepted",
        {"run_id": run_id, "accepted": accepted, "skipped": skipped},
    )
    session.commit()
    return accepted, skipped, list_candidates_for_run(session, run_id)


def list_constraints(session: Session, production_id: str) -> list[ConstraintModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(ConstraintModel)
            .where(ConstraintModel.production_id == production_id)
            .order_by(ConstraintModel.created_at, ConstraintModel.constraint_id)
        )
    )


def list_constraint_proposals(
    session: Session, production_id: str
) -> list[ConstraintProposalModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(ConstraintProposalModel)
            .where(ConstraintProposalModel.production_id == production_id)
            .order_by(ConstraintProposalModel.created_at.desc())
        )
    )


def translate_constraint_text(
    session: Session,
    production_id: str,
    *,
    text: str,
    actor_name: str = "Developer",
) -> list[Any]:
    """Persist inactive typed constraint candidates from production prose."""
    from coverset.constraint_translation import (  # local: completion-layer service
        translate_plain_english_constraints,
    )

    from .models import ConstraintProposalModel

    get_production(session, production_id)
    try:
        candidates = translate_plain_english_constraints(
            production_id, text, created_by=actor_name
        )
    except ValueError as exc:
        raise ServiceError(str(exc)) from exc
    rows = [
        _constraint_proposal_row(session, production_id, candidate, actor_name)
        for candidate in candidates
    ]
    audit(
        session,
        production_id,
        "constraint.translation_created",
        {"proposal_ids": [row.id for row in rows], "count": len(rows)},
        actor=actor_name,
    )
    session.commit()
    return list(
        session.scalars(
            select(ConstraintProposalModel)
            .where(ConstraintProposalModel.production_id == production_id)
            .order_by(ConstraintProposalModel.created_at)
        )
    )


def _constraint_proposal_row(
    session: Session,
    production_id: str,
    candidate: Any,
    actor_name: str,
) -> Any:
    from .models import ConstraintProposalModel

    row = ConstraintProposalModel(
        id=new_id("cprop"),
        production_id=production_id,
        source_text=str(candidate.source_text),
        status="blocked" if candidate.validation_errors else "candidate",
        confidence=_candidate_confidence(candidate),
        payload_json=dict(candidate.constraint_payload),
        validation_errors_json=list(candidate.validation_errors),
        created_by_name=actor_name,
    )
    session.add(row)
    return row


def _candidate_confidence(candidate: Any) -> float:
    try:
        return float(candidate.confidence)
    except (TypeError, ValueError) as exc:
        raise ServiceError("constraint proposal confidence must be numeric") from exc


def accept_constraint_proposal(
    session: Session,
    *,
    proposal_id: str,
    actor_name: str = "Developer",
    actor_role: str = "first_ad",
) -> ConstraintModel:
    """Activate a typed candidate only after an attributed human acceptance."""
    from .models import ConstraintProposalModel

    proposal = session.get(ConstraintProposalModel, proposal_id)
    if proposal is None:
        raise ServiceError(
            f"constraint proposal not found: {proposal_id}", status_code=404
        )
    if proposal.accepted_constraint_id:
        row = session.get(ConstraintModel, proposal.accepted_constraint_id)
        if row is not None:
            return row
    if proposal.validation_errors_json:
        raise ServiceError(
            "constraint proposal has validation errors and cannot be accepted",
            status_code=409,
        )
    actor = _actor_for_decision(actor_name, actor_role)
    payload = dict(proposal.payload_json or {})
    payload["active"] = True
    payload["actor_name"] = actor.name
    payload["actor_role"] = actor.role.value
    constraint = create_constraint(session, proposal.production_id, payload=payload)
    proposal.status = "accepted"
    proposal.accepted_by_name = actor.name
    proposal.accepted_by_role = actor.role.value
    proposal.accepted_at = utcnow()
    proposal.accepted_constraint_id = constraint.id
    audit(
        session,
        proposal.production_id,
        "constraint.proposal_accepted",
        {"proposal_id": proposal.id, "constraint_id": constraint.id},
        actor=str(actor),
    )
    session.commit()
    return constraint


def reject_constraint_proposal(
    session: Session,
    *,
    proposal_id: str,
    actor_name: str = "Developer",
    actor_role: str = "first_ad",
) -> Any:
    from .models import ConstraintProposalModel

    proposal = session.get(ConstraintProposalModel, proposal_id)
    if proposal is None:
        raise ServiceError(
            f"constraint proposal not found: {proposal_id}", status_code=404
        )
    actor = _actor_for_decision(actor_name, actor_role)
    proposal.status = "rejected"
    proposal.accepted_by_name = actor.name
    proposal.accepted_by_role = actor.role.value
    proposal.accepted_at = utcnow()
    audit(
        session,
        proposal.production_id,
        "constraint.proposal_rejected",
        {"proposal_id": proposal.id},
        actor=str(actor),
    )
    session.commit()
    return proposal


def record_grounded_value(
    session: Session,
    *,
    evidence_id: str,
    normalized_value: dict[str, Any],
    units: str,
    source_url: str,
    source_quote: str,
    source_span: str = "source text",
    query: str = "grounded value extraction",
    validator_family: str = "generic",
    validator_reason: str = "source span extracted and normalized",
) -> Any:
    """Persist exact value-level provenance derived from grounded evidence."""
    from coverset.grounding import ValidatorResult
    from coverset.grounding.values import bind_grounded_value

    from .models import GroundedValueModel

    evidence_row = get_grounding_evidence(session, evidence_id)
    evidence = _evidence_domain_from_row(session, evidence_row)
    try:
        grounded = bind_grounded_value(
            evidence,
            value_id=new_id("gval"),
            normalized_value=normalized_value,
            units=units,
            source_url=source_url,
            source_quote=source_quote,
            source_span=source_span,
            query=query,
            validator_result=ValidatorResult(
                family=validator_family,
                passed=True,
                reason=validator_reason,
                validator="coverset.api.services.record_grounded_value",
            ),
            require_date_coverage=True,
        )
    except GroundingError as exc:
        raise ServiceError(str(exc)) from exc
    _raise_on_grounded_value_conflict(
        session, evidence_row, grounded.normalized_value, units
    )
    row = GroundedValueModel(
        id=grounded.id,
        production_id=evidence_row.production_id,
        evidence_id=evidence_row.id,
        fact_kind=grounded.kind.value,
        location_id=grounded.location_id,
        target_date=grounded.target_date,
        normalized_value_json=grounded.normalized_value,
        units=grounded.units,
        source_url=grounded.source_url,
        source_quote=grounded.source_quote,
        source_span=grounded.source_span,
        query=grounded.query,
        provider_response_id=grounded.provider_response_id,
        content_hash=grounded.content_hash,
        derived_from=grounded.derived_from.value,
        validator_result_json=grounded.validator_result.to_json(),
        covering_date=grounded.covering_date,
        context_source_urls_json=list(grounded.context_source_urls),
    )
    session.add(row)
    audit(
        session,
        evidence_row.production_id,
        "grounded_value.recorded",
        {"grounded_value_id": row.id, "evidence_id": evidence_row.id},
    )
    session.commit()
    return row


def _evidence_domain_from_row(
    session: Session, row: GroundingEvidenceModel
) -> Evidence:
    from .constraints_io import evidence_from_json

    data = dict(row.evidence_json or {})
    location = session.scalar(
        select(LocationModel).where(
            LocationModel.production_id == row.production_id,
            LocationModel.location_id == row.location_id,
        )
    )
    if location is None:
        raise ServiceError(
            f"location not found for grounded evidence: {row.location_id}",
            status_code=404,
        )
    raw_retrieved = str(data.get("retrieved_at") or row.created_at.isoformat())
    try:
        retrieved_at = dt.datetime.fromisoformat(raw_retrieved)
    except ValueError as exc:
        raise ServiceError(
            f"invalid evidence retrieval timestamp: {raw_retrieved}"
        ) from exc
    return Evidence(
        kind=FactKind(row.fact_kind),
        location=Location(
            location.name,
            location.city,
            location.state,
            id=location.location_id,
            latitude=location.latitude,
            longitude=location.longitude,
            timezone=location.timezone,
        ),
        date=row.target_date,
        sources=evidence_from_json(data),
        search_id=str(data.get("search_id") or row.id),
        session_id=str(data.get("session_id") or row.id),
        retrieved_at=retrieved_at,
        escalated=bool(data.get("escalated", False)),
        covering_urls=tuple(str(url) for url in data.get("covering_urls", ())),
    )


def _raise_on_grounded_value_conflict(
    session: Session,
    evidence_row: GroundingEvidenceModel,
    normalized_value: dict[str, Any],
    units: str,
) -> None:
    from .models import GroundedValueModel

    existing = session.scalars(
        select(GroundedValueModel).where(
            GroundedValueModel.production_id == evidence_row.production_id,
            GroundedValueModel.fact_kind == evidence_row.fact_kind,
            GroundedValueModel.location_id == evidence_row.location_id,
            GroundedValueModel.target_date == evidence_row.target_date,
            GroundedValueModel.units == units,
        )
    )
    for row in existing:
        validator = dict(row.validator_result_json or {})
        if (
            validator.get("passed", True)
            and row.normalized_value_json != normalized_value
        ):
            raise ServiceError(
                "conflicting grounded values for the same fact/date/location",
                status_code=409,
            )


def _constraint_activation_validation(
    record: ConstraintRecord,
    *,
    evidence_payload: dict[str, Any] | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Family-specific checks that must pass before activation."""
    errors: list[str] = []
    if isinstance(record.source, GroundedSource):
        source_urls = set(record.source.source_urls)
        if not source_urls:
            errors.append("grounded constraint has no source URLs")
        if evidence_payload is None:
            errors.append("grounded constraint evidence was not found")
        else:
            target_date = _date_from_payload(evidence_payload.get("date"))
            covering_urls = {
                str(url) for url in evidence_payload.get("covering_urls", [])
            }
            if record.family in (Family.WEATHER, Family.PERMIT):
                if target_date is None or not _constraint_expression_covers(
                    record, target_date
                ):
                    errors.append(
                        f"{record.family} expression does not cover evidence target date"
                    )
                if record.family is Family.WEATHER and not source_urls & covering_urls:
                    errors.append(
                        "weather constraint source does not cover target date"
                    )
            if record.family is Family.PERMIT:
                if (
                    payload is not None
                    and not str(payload.get("timezone") or "").strip()
                ):
                    errors.append("permit constraint requires a local IANA timezone")
                if not all(_looks_authoritative_permit_url(url) for url in source_urls):
                    errors.append(
                        "permit constraint requires authoritative source URLs"
                    )
    return {
        "passed": not errors,
        "errors": errors,
        "validator": "coverset.api.services._constraint_activation_validation",
    }


def _constraint_expression_covers(
    record: ConstraintRecord, target_date: dt.date
) -> bool:
    expression = record.expression
    if isinstance(expression, BlackoutDates):
        return target_date in set(expression.dates)
    if isinstance(expression, DateWindows):
        return any(window.covers(target_date) for window in expression.windows)
    if isinstance(expression, PinnedDay):
        return expression.day == target_date
    return True


def _looks_authoritative_permit_url(url: str) -> bool:
    lowered = url.lower()
    return ".gov" in lowered or "/permit" in lowered or "permits" in lowered


def create_constraint(
    session: Session, production_id: str, *, payload: dict[str, Any]
) -> ConstraintModel:
    get_production(session, production_id)
    if _constraint_id_exists(
        session, production_id, str(payload.get("constraint_id", ""))
    ):
        raise ServiceError(
            f"constraint id already exists: {payload.get('constraint_id')}",
            status_code=409,
        )
    evidence_payload: dict[str, Any] | None = None
    evidence_id = payload.get("evidence_id")
    if evidence_id:
        evidence = get_grounding_evidence(session, str(evidence_id))
        if evidence.production_id != production_id:
            raise ServiceError(
                "grounding evidence belongs to another production", status_code=404
            )
        if evidence.status != "complete":
            raise ServiceError(
                "failed grounding evidence cannot back an active constraint"
            )
        evidence_payload = dict(evidence.evidence_json or {})
    try:
        record = constraint_from_payload(payload, evidence=evidence_payload)
    except (ConstraintError, KeyError, TypeError, ValueError) as exc:
        raise ServiceError(f"invalid constraint: {exc}") from exc
    validation = _constraint_activation_validation(
        record, evidence_payload=evidence_payload, payload=payload
    )
    if record.active and not validation["passed"]:
        raise ServiceError(
            "constraint failed activation validation: "
            + "; ".join(validation["errors"])
        )
    snapshot = constraint_to_json(record)
    snapshot["activation_validation"] = validation
    snapshot["activation_payload"] = {
        key: payload[key]
        for key in ("timezone", "grounded_value_id", "derived_from")
        if key in payload
    }
    if record.active:
        snapshot["accepted_by"] = {
            "name": str(payload.get("actor_name") or "Developer"),
            "role": str(payload.get("actor_role") or "first_ad"),
            "accepted_at": record.activated_at.isoformat()
            if record.activated_at
            else "",
        }
    row = ConstraintModel(
        id=new_id("con"),
        production_id=production_id,
        constraint_id=record.constraint_id,
        family=record.family.value,
        policy=record.policy.value,
        active=record.active,
        constraint_json=snapshot,
        provenance_json=dict(snapshot.get("source", {})),
    )
    session.add(row)
    audit(
        session,
        production_id,
        "constraint.created",
        {"constraint_id": row.constraint_id, "active": row.active},
    )
    session.commit()
    return row


def activate_constraint(
    session: Session,
    *,
    constraint_row_id: str,
    active: bool,
    actor_name: str = "Developer",
    actor_role: str = "first_ad",
) -> ConstraintModel:
    row = session.get(ConstraintModel, constraint_row_id)
    if row is None:
        raise ServiceError(
            f"constraint not found: {constraint_row_id}", status_code=404
        )
    actor = _actor_for_decision(actor_name, actor_role)
    current = constraint_from_json(row.constraint_json)
    evidence_payload = _evidence_payload_for_constraint(session, current)
    validation = _constraint_activation_validation(
        current,
        evidence_payload=evidence_payload,
        payload=dict(row.constraint_json.get("activation_payload") or {}),
    )
    if active and not validation["passed"]:
        raise ServiceError(
            "constraint failed activation validation: "
            + "; ".join(validation["errors"])
        )
    record = replace(current, active=active, activated_at=utcnow() if active else None)
    row.active = active
    row.constraint_json = constraint_to_json(record)
    row.constraint_json["activation_validation"] = validation
    if active:
        row.constraint_json["accepted_by"] = {
            "name": actor.name,
            "role": actor.role.value,
            "accepted_at": record.activated_at.isoformat()
            if record.activated_at
            else "",
        }
    row.provenance_json = dict(row.constraint_json.get("source", {}))
    audit(
        session,
        row.production_id,
        "constraint.activated" if active else "constraint.deactivated",
        {"constraint_id": row.constraint_id, "actor_role": actor.role.value},
        actor=str(actor),
    )
    session.commit()
    return row


def _evidence_payload_for_constraint(
    session: Session, record: ConstraintRecord
) -> dict[str, Any] | None:
    source = record.source
    evidence_id = getattr(source, "evidence_id", "")
    if not evidence_id:
        return None
    evidence = session.get(GroundingEvidenceModel, str(evidence_id))
    if evidence is None:
        return None
    return dict(evidence.evidence_json or {})


def get_grounding_evidence(
    session: Session, evidence_id: str
) -> GroundingEvidenceModel:
    row = session.get(GroundingEvidenceModel, evidence_id)
    if row is None:
        raise ServiceError(
            f"grounding evidence not found: {evidence_id}", status_code=404
        )
    return row


def list_grounded_values(
    session: Session, production_id: str
) -> list[GroundedValueModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(GroundedValueModel)
            .where(GroundedValueModel.production_id == production_id)
            .order_by(GroundedValueModel.created_at.desc())
        )
    )


def list_grounded_values_for_evidence(
    session: Session, evidence_id: str
) -> list[GroundedValueModel]:
    evidence = get_grounding_evidence(session, evidence_id)
    return list(
        session.scalars(
            select(GroundedValueModel)
            .where(GroundedValueModel.evidence_id == evidence.id)
            .order_by(GroundedValueModel.created_at.desc())
        )
    )


def list_grounding_evidence(
    session: Session, production_id: str
) -> list[GroundingEvidenceModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(GroundingEvidenceModel)
            .where(GroundingEvidenceModel.production_id == production_id)
            .order_by(GroundingEvidenceModel.created_at)
        )
    )


def ground_fact(
    session: Session,
    production_id: str,
    *,
    kind: str,
    location_id: str,
    target_date: dt.date,
    grounder: HasGround | None = None,
) -> GroundingEvidenceModel:
    get_production(session, production_id)
    try:
        location = locations_from_models(list_locations(session, production_id))[
            location_id
        ]
        fact_kind = FactKind(kind)
    except (KeyError, ValueError) as exc:
        raise ServiceError(f"invalid grounding request: {exc}") from exc
    row = GroundingEvidenceModel(
        id=new_id("ev"),
        production_id=production_id,
        location_id=location_id,
        fact_kind=fact_kind.value,
        target_date=target_date,
        status="running",
    )
    session.add(row)
    session.commit()
    try:
        evidence = (grounder or SearchGrounder()).ground(
            fact_kind, location, target_date
        )
        row.status = "complete"
        row.evidence_json = evidence_to_json(evidence)
        row.error = ""
        audit(
            session,
            production_id,
            "grounding.completed",
            {"evidence_id": row.id, "kind": fact_kind.value},
        )
    except GroundingError as exc:
        row.status = "failed"
        row.error = str(exc)
        audit(
            session,
            production_id,
            "grounding.failed",
            {"evidence_id": row.id, "kind": fact_kind.value, "error": row.error},
        )
    session.commit()
    return row


def _board_day_snapshot(board: BoardModel, shoot_date: dt.date) -> dict[str, Any]:
    for day in board.result_json.get("days", []):
        if str(day.get("date")) == shoot_date.isoformat():
            return dict(day)
    raise ServiceError(
        f"board {board.id} has no shoot day {shoot_date.isoformat()}",
        status_code=404,
    )


def list_locked_days(session: Session, production_id: str) -> list[LockedDayModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(LockedDayModel)
            .where(LockedDayModel.production_id == production_id)
            .order_by(LockedDayModel.shoot_date, LockedDayModel.created_at)
        )
    )


def lock_board_day(
    session: Session,
    *,
    board_id: str,
    shoot_date: dt.date,
    call_sheet_version: str,
    actor_name: str,
    actor_role: str,
) -> LockedDayModel:
    board = get_board(session, board_id)
    actor = _actor_for_decision(actor_name, actor_role, capability="lock_day")
    existing = session.scalars(
        select(LockedDayModel).where(
            LockedDayModel.board_id == board_id,
            LockedDayModel.shoot_date == shoot_date,
        )
    ).first()
    if existing is not None:
        return existing

    day = _board_day_snapshot(board, shoot_date)
    strips = list(day.get("strips") or day.get("assignments") or [])
    if not strips:
        raise ServiceError(f"board {board.id} has no locked work on {shoot_date}")
    locked_assignments: list[dict[str, Any]] = []
    for sequence, strip in enumerate(strips):
        cast_ids = [str(cast_id) for cast_id in strip.get("cast_ids", [])]
        locked_assignments.append(
            {
                "work_id": str(strip.get("work_id") or ""),
                "sequence": strip.get("sequence", sequence),
                "location_id": str(strip.get("location_id") or ""),
                "planned_call_time": strip.get("planned_call_time"),
                "planned_wrap_time": strip.get("planned_wrap_time"),
                "cast_ids": cast_ids,
            }
        )
    locations = sorted(
        {item["location_id"] for item in locked_assignments if item["location_id"]}
    )
    cast = sorted(
        {cast_id for item in locked_assignments for cast_id in item["cast_ids"]}
    )
    row = LockedDayModel(
        id=new_id("lock"),
        production_id=board.production_id,
        board_id=board.id,
        schedule_run_id=board.schedule_run_id,
        shoot_date=shoot_date,
        locked_assignments_json=locked_assignments,
        locations_json=locations,
        cast_json=cast,
        call_sheet_version=call_sheet_version.strip(),
        recorded_by_name=actor.name,
        recorded_by_role=actor.role.value,
    )
    session.add(row)
    audit(
        session,
        board.production_id,
        "day.locked",
        {
            "board_id": board.id,
            "shoot_date": shoot_date.isoformat(),
            "work_ids": [item["work_id"] for item in locked_assignments],
        },
        actor=str(actor),
    )
    session.commit()
    return row


def _affected_work_ids(board: BoardModel, payload: dict[str, Any]) -> list[str]:
    provided = [str(value) for value in payload.get("affected_work_ids", []) if value]
    if provided:
        return provided
    return [
        str(strip.get("work_id"))
        for strip in board.result_json.get("strips", [])
        if strip.get("work_id")
    ]


def register_monitored_source(
    session: Session,
    production_id: str,
    *,
    board_id: str,
    source_url: str,
    fact_kind: str,
    location_id: str = "",
    query: str = "",
    external_monitor_id: str = "",
    monitor_client: Any | None = None,
) -> Any:
    """Register a mutable external source, optionally creating a provider monitor."""
    from .models import MonitoredSourceModel

    get_production(session, production_id)
    board = get_board(session, board_id)
    if board.production_id != production_id:
        raise ServiceError("board belongs to another production", status_code=404)
    if monitor_client is not None and not external_monitor_id:
        try:
            external_monitor_id = str(
                monitor_client.create_monitor(
                    production_id=production_id,
                    board_id=board_id,
                    source_url=source_url,
                    fact_kind=fact_kind,
                    query=query or source_url,
                )
            )
        except Exception as exc:  # noqa: BLE001 - provider boundary
            raise ServiceError(f"monitor provider registration failed: {exc}") from exc
    row = MonitoredSourceModel(
        id=new_id("msrc"),
        production_id=production_id,
        board_id=board_id,
        source_url=source_url,
        fact_kind=fact_kind,
        location_id=location_id,
        query=query or source_url,
        external_monitor_id=external_monitor_id,
        metadata_json={"registered_by": "coverset.api"},
    )
    session.add(row)
    audit(
        session,
        production_id,
        "monitor.source_registered",
        {"monitored_source_id": row.id, "board_id": board_id, "source_url": source_url},
    )
    session.commit()
    return row


def list_monitored_sources(session: Session, production_id: str) -> list[Any]:
    from .models import MonitoredSourceModel

    get_production(session, production_id)
    return list(
        session.scalars(
            select(MonitoredSourceModel)
            .where(MonitoredSourceModel.production_id == production_id)
            .order_by(MonitoredSourceModel.created_at)
        )
    )


def process_monitor_change(
    session: Session,
    production_id: str,
    *,
    payload: dict[str, Any],
) -> Any:
    """Process a provider page-change event into finding/replan/audit records."""
    from .models import MonitorChangeEventModel, MonitoredSourceModel

    get_production(session, production_id)
    source = None
    source_id = str(payload.get("monitored_source_id") or "")
    if source_id:
        source = session.get(MonitoredSourceModel, source_id)
        if source is None or source.production_id != production_id:
            raise ServiceError("monitored source not found", status_code=404)
    board_id = str(payload.get("board_id") or getattr(source, "board_id", ""))
    board = get_board(session, board_id)
    if board.production_id != production_id:
        raise ServiceError("board belongs to another production", status_code=404)
    event_status = str(payload.get("status") or "processed")
    if event_status in {"failed", "stale"}:
        event = MonitorChangeEventModel(
            id=new_id("mevt"),
            production_id=production_id,
            monitored_source_id=source_id or None,
            board_id=board_id,
            status=event_status,
            material=False,
            payload_json=dict(payload),
        )
        session.add(event)
        audit(
            session,
            production_id,
            "monitor.alert",
            {"event_id": event.id, "status": event_status, "board_id": board_id},
            actor="monitor",
        )
        session.commit()
        return event

    old_fingerprint = str(
        payload.get("old_fingerprint") or getattr(source, "last_fingerprint", "")
    )
    new_fingerprint = str(payload.get("new_fingerprint") or "")
    material = bool(payload.get("material", old_fingerprint != new_fingerprint))
    target_date = _date_from_payload(payload.get("target_date"))
    if (
        material
        and target_date is not None
        and _date_is_locked(session, board.production_id, target_date)
    ):
        event = MonitorChangeEventModel(
            id=new_id("mevt"),
            production_id=production_id,
            monitored_source_id=source_id or None,
            board_id=board_id,
            status="retroactive_exception",
            material=True,
            old_fingerprint=old_fingerprint,
            new_fingerprint=new_fingerprint,
            payload_json={
                **payload,
                "future_recommendation": "apply this fact only to unshot days or a new pickup",
            },
        )
        session.add(event)
        audit(
            session,
            production_id,
            "monitor.retroactive_exception",
            {"event_id": event.id, "target_date": target_date.isoformat()},
            actor="monitor",
        )
        session.commit()
        return event
    finding_payload = {
        **payload,
        "board_id": board_id,
        "source_url": str(
            payload.get("source_url") or getattr(source, "source_url", "")
        ),
        "fact_kind": str(payload.get("fact_kind") or getattr(source, "fact_kind", "")),
        "old_fingerprint": old_fingerprint,
        "new_fingerprint": new_fingerprint,
        "material": material,
    }
    finding = create_monitor_finding(
        session,
        production_id,
        payload=finding_payload,
        requester_component="monitor",
    )
    replan = _request_replan_for_finding(session, finding) if material else None
    event = MonitorChangeEventModel(
        id=new_id("mevt"),
        production_id=production_id,
        monitored_source_id=source_id or None,
        board_id=board_id,
        status="material" if material else "non_material",
        material=material,
        old_fingerprint=old_fingerprint,
        new_fingerprint=new_fingerprint,
        payload_json=dict(payload),
        finding_id=finding.id,
        replan_request_id=replan.id if replan else None,
    )
    if source is not None:
        source.last_fingerprint = new_fingerprint or old_fingerprint
        source.last_checked_at = utcnow()
    session.add(event)
    audit(
        session,
        production_id,
        "monitor.change_processed",
        {
            "event_id": event.id,
            "material": material,
            "finding_id": finding.id,
            "replan_request_id": event.replan_request_id,
        },
        actor="monitor",
    )
    session.commit()
    return event


def _date_from_payload(value: Any) -> dt.date | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise ServiceError(f"invalid monitor target_date: {value}") from exc


def _date_is_locked(session: Session, production_id: str, target_date: dt.date) -> bool:
    return any(
        row.shoot_date == target_date
        for row in list_locked_days(session, production_id)
    )


def _request_replan_for_finding(
    session: Session,
    finding: MonitorFindingModel,
) -> ReplanRequestModel:
    existing = session.scalars(
        select(ReplanRequestModel).where(
            ReplanRequestModel.production_id == finding.production_id,
            ReplanRequestModel.source_kind == "monitor",
            ReplanRequestModel.source_id == finding.id,
        )
    ).first()
    if existing is not None:
        return existing
    locked = list_locked_days(session, finding.production_id)
    replan = ReplanRequestModel(
        id=new_id("replan"),
        production_id=finding.production_id,
        finding_id=finding.id,
        current_board_id=finding.board_id,
        requester_component=finding.requester_component,
        source_kind="monitor",
        source_id=finding.id,
        reason=finding.message,
        status="requested",
        affected_work_ids_json=list(finding.affected_work_ids_json or []),
        locked_days_json=[row.id for row in locked],
    )
    session.add(replan)
    audit(
        session,
        finding.production_id,
        "replan.requested",
        {
            "finding_id": finding.id,
            "replan_request_id": replan.id,
            "locked_day_ids": replan.locked_days_json,
        },
        actor=finding.requester_component,
    )
    return replan


def create_monitor_finding(
    session: Session,
    production_id: str,
    *,
    payload: dict[str, Any],
    requester_component: str = "monitor",
) -> MonitorFindingModel:
    get_production(session, production_id)
    board = get_board(session, str(payload.get("board_id") or ""))
    if board.production_id != production_id:
        raise ServiceError("board belongs to another production", status_code=404)
    evidence_id = payload.get("evidence_id")
    if evidence_id:
        evidence = get_grounding_evidence(session, str(evidence_id))
        if evidence.production_id != production_id:
            raise ServiceError(
                "evidence belongs to another production", status_code=404
            )
    old_fingerprint = str(payload.get("old_fingerprint") or "")
    new_fingerprint = str(payload.get("new_fingerprint") or "")
    material = bool(payload.get("material", old_fingerprint != new_fingerprint))
    if old_fingerprint == new_fingerprint and material:
        raise ServiceError("unchanged fingerprints cannot be material")
    row = MonitorFindingModel(
        id=new_id("mon"),
        production_id=production_id,
        board_id=board.id,
        evidence_id=str(evidence_id) if evidence_id else None,
        source_url=str(payload.get("source_url") or ""),
        fact_kind=str(payload.get("fact_kind") or ""),
        status="open" if material else "non_material",
        material=material,
        message=str(payload.get("message") or "changed monitored fact"),
        old_fingerprint=old_fingerprint,
        new_fingerprint=new_fingerprint,
        old_value_json=dict(payload.get("old_value") or {}),
        new_value_json=dict(payload.get("new_value") or {}),
        affected_work_ids_json=_affected_work_ids(board, payload),
        requester_component=requester_component,
    )
    if not row.source_url.strip() or not row.fact_kind.strip():
        raise ServiceError("monitor finding requires source_url and fact_kind")
    session.add(row)
    audit(
        session,
        production_id,
        "monitor.finding_created",
        {"finding_id": row.id, "material": row.material, "board_id": board.id},
        actor=requester_component,
    )
    session.commit()
    return row


def list_monitor_findings(
    session: Session, production_id: str
) -> list[MonitorFindingModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(MonitorFindingModel)
            .where(MonitorFindingModel.production_id == production_id)
            .order_by(MonitorFindingModel.created_at.desc())
        )
    )


def decide_monitor_finding(
    session: Session,
    *,
    finding_id: str,
    decision: str,
    actor_name: str,
    actor_role: str,
) -> tuple[MonitorFindingModel, ReplanRequestModel | None]:
    finding = session.get(MonitorFindingModel, finding_id)
    if finding is None:
        raise ServiceError(f"monitor finding not found: {finding_id}", status_code=404)
    actor = _actor_for_decision(actor_name, actor_role, capability="select_board")
    if finding.status not in {"open", "non_material"}:
        raise ServiceError(
            f"monitor finding is already {finding.status}", status_code=409
        )
    finding.reviewed_by_name = actor.name
    finding.reviewed_by_role = actor.role.value
    finding.reviewed_at = utcnow()
    if decision == "reject":
        finding.status = "rejected"
        audit(
            session,
            finding.production_id,
            "monitor.finding_rejected",
            {"finding_id": finding.id, "board_id": finding.board_id},
            actor=str(actor),
        )
        session.commit()
        return finding, None
    if decision != "accept":
        raise ServiceError(f"unsupported monitor finding decision: {decision}")
    if not finding.material:
        raise ServiceError("non-material finding cannot create a replan request")

    replan = _request_replan_for_finding(session, finding)
    finding.status = "accepted"
    audit(
        session,
        finding.production_id,
        "monitor.finding_accepted",
        {"finding_id": finding.id, "replan_request_id": replan.id},
        actor=str(actor),
    )
    session.commit()
    return finding, replan


def list_replan_requests(
    session: Session, production_id: str
) -> list[ReplanRequestModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(ReplanRequestModel)
            .where(ReplanRequestModel.production_id == production_id)
            .order_by(ReplanRequestModel.created_at.desc())
        )
    )


def create_schedule_diff(
    session: Session,
    *,
    base_board_id: str,
    revised_board_id: str,
    replan_request_id: str | None = None,
) -> Any:
    from coverset.schedule_diff import build_schedule_diff, render_schedule_diff_text

    from .models import ScheduleDiffModel

    base = get_board(session, base_board_id)
    revised = get_board(session, revised_board_id)
    if base.production_id != revised.production_id:
        raise ServiceError("boards belong to different productions", status_code=404)
    if replan_request_id:
        replan = session.get(ReplanRequestModel, replan_request_id)
        if replan is None or replan.production_id != base.production_id:
            raise ServiceError("replan request not found", status_code=404)
    existing = session.scalars(
        select(ScheduleDiffModel).where(
            ScheduleDiffModel.base_board_id == base_board_id,
            ScheduleDiffModel.revised_board_id == revised_board_id,
            ScheduleDiffModel.replan_request_id == replan_request_id,
        )
    ).first()
    if existing is not None:
        return existing
    diff = build_schedule_diff(
        base_board_id=base_board_id,
        revised_board_id=revised_board_id,
        base=dict(base.result_json or {}),
        revised=dict(revised.result_json or {}),
    )
    row = ScheduleDiffModel(
        id=new_id("sdiff"),
        production_id=base.production_id,
        base_board_id=base_board_id,
        revised_board_id=revised_board_id,
        replan_request_id=replan_request_id,
        diff_json=diff.to_json(),
        required_approvals_json=list(diff.required_approvals),
        cost_delta=diff.cost_delta,
        rendered_text=render_schedule_diff_text(diff),
    )
    session.add(row)
    _apply_cost_approval_state(revised, row)
    audit(
        session,
        base.production_id,
        "schedule.diff_created",
        {
            "schedule_diff_id": row.id,
            "base_board_id": base_board_id,
            "revised_board_id": revised_board_id,
            "required_approvals": row.required_approvals_json,
        },
    )
    session.commit()
    return row


def generate_replan_options(
    session: Session,
    *,
    replan_request_id: str,
    max_options: int = 2,
) -> list[Any]:
    from .models import ScheduleDiffModel

    replan = session.get(ReplanRequestModel, replan_request_id)
    if replan is None:
        raise ServiceError(
            f"replan request not found: {replan_request_id}", status_code=404
        )
    existing = list(
        session.scalars(
            select(ScheduleDiffModel)
            .where(ScheduleDiffModel.replan_request_id == replan_request_id)
            .order_by(ScheduleDiffModel.created_at)
        )
    )
    if existing:
        return existing
    options: list[Any] = []
    for seed in range(max(1, max_options)):
        run = run_scheduler(session, production_id=replan.production_id, seed=seed)
        if run.status == "failed" or not run.board_id:
            continue
        options.append(
            create_schedule_diff(
                session,
                base_board_id=replan.current_board_id,
                revised_board_id=run.board_id,
                replan_request_id=replan.id,
            )
        )
    if not options:
        replan.status = "failed"
        audit(
            session,
            replan.production_id,
            "replan.options_failed",
            {"replan_request_id": replan.id},
        )
        session.commit()
        raise ServiceError("no viable replan options could be generated")
    replan.status = "options_ready"
    audit(
        session,
        replan.production_id,
        "replan.options_ready",
        {"replan_request_id": replan.id, "option_count": len(options)},
    )
    session.commit()
    return options


def list_schedule_diffs(session: Session, production_id: str) -> list[Any]:
    from .models import ScheduleDiffModel

    get_production(session, production_id)
    return list(
        session.scalars(
            select(ScheduleDiffModel)
            .where(ScheduleDiffModel.production_id == production_id)
            .order_by(ScheduleDiffModel.created_at.desc())
        )
    )


def _apply_cost_approval_state(board: BoardModel, diff_row: Any) -> None:
    approvals = list(diff_row.required_approvals_json or [])
    result = dict(board.result_json or {})
    result["schedule_diff_id"] = diff_row.id
    result["required_approvals"] = approvals
    result["cost_delta"] = diff_row.cost_delta
    if "upm_or_line_producer_cost_approval" in approvals:
        board.approval_state = "pending_cost_approval"
    result["approval_state"] = board.approval_state
    board.result_json = result


def _ensure_board_cost_approval_resolved(
    session: Session, board: BoardModel
) -> None:
    result = dict(board.result_json or {})
    required_approvals = {str(value) for value in result.get("required_approvals", [])}
    cost_required = (
        board.approval_state == "pending_cost_approval"
        or "upm_or_line_producer_cost_approval" in required_approvals
    )
    if board.approval_state == "cost_rejected":
        raise ServiceError(
            "cost approval was rejected for this board", status_code=409
        )
    if not cost_required:
        return
    approved = session.scalars(
        select(CostApprovalModel).where(
            CostApprovalModel.board_id == board.id,
            CostApprovalModel.decision == "approved",
        )
    ).first()
    if approved is None or board.approval_state != "approved":
        raise ServiceError(
            "cost approval is required before board selection", status_code=409
        )


def select_board(
    session: Session,
    *,
    board_id: str,
    actor_name: str,
    actor_role: str,
    prior_board_id: str | None = None,
) -> BoardSelectionModel:
    board = get_board(session, board_id)
    actor = _actor_for_decision(actor_name, actor_role, capability="select_board")
    _ensure_board_cost_approval_resolved(session, board)
    prior_run_id: str | None = None
    if prior_board_id:
        prior = get_board(session, prior_board_id)
        if prior.production_id != board.production_id:
            raise ServiceError(
                "prior board belongs to another production", status_code=404
            )
        prior_run_id = prior.schedule_run_id
    row = BoardSelectionModel(
        id=new_id("sel"),
        production_id=board.production_id,
        prior_board_id=prior_board_id,
        selected_board_id=board.id,
        prior_schedule_run_id=prior_run_id,
        new_schedule_run_id=board.schedule_run_id,
        actor_name=actor.name,
        actor_role=actor.role.value,
    )
    session.add(row)
    audit(
        session,
        board.production_id,
        "board.selected",
        {
            "selection_id": row.id,
            "selected_board_id": board.id,
            "prior_board_id": prior_board_id,
        },
        actor=str(actor),
    )
    session.commit()
    return row


def list_cost_approvals(
    session: Session, production_id: str
) -> list[CostApprovalModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(CostApprovalModel)
            .where(CostApprovalModel.production_id == production_id)
            .order_by(CostApprovalModel.created_at.desc())
        )
    )


def list_cost_approvals_for_board(
    session: Session, board_id: str
) -> list[CostApprovalModel]:
    board = get_board(session, board_id)
    return list(
        session.scalars(
            select(CostApprovalModel)
            .where(CostApprovalModel.board_id == board.id)
            .order_by(CostApprovalModel.created_at.desc())
        )
    )


def approve_cost(
    session: Session,
    *,
    board_id: str,
    actor_name: str,
    actor_role: str,
    cost_delta: float,
    added_shoot_days: list[dt.date],
    decision: str = "approved",
) -> CostApprovalModel:
    board = get_board(session, board_id)
    actor = _actor_for_decision(actor_name, actor_role, capability="approve_cost")
    if decision not in {"approved", "rejected"}:
        raise ServiceError("cost approval decision must be approved or rejected")
    if cost_delta > 0 and not added_shoot_days:
        raise ServiceError("cost exposure must name the added shoot days")
    row = CostApprovalModel(
        id=new_id("cost"),
        production_id=board.production_id,
        board_id=board.id,
        approver_name=actor.name,
        approver_role=actor.role.value,
        cost_delta=cost_delta,
        added_shoot_days_json=[day.isoformat() for day in added_shoot_days],
        decision=decision,
    )
    session.add(row)
    result = dict(board.result_json or {})
    if decision == "approved":
        board.approval_state = "approved"
    else:
        board.approval_state = "cost_rejected"
    result["approval_state"] = board.approval_state
    board.result_json = result
    audit(
        session,
        board.production_id,
        "cost.approved" if decision == "approved" else "cost.rejected",
        {
            "approval_id": row.id,
            "board_id": board.id,
            "cost_delta": cost_delta,
            "added_shoot_days": row.added_shoot_days_json,
        },
        actor=str(actor),
    )
    session.commit()
    return row


def list_coverage_items(
    session: Session, production_id: str
) -> list[CoverageItemModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(CoverageItemModel)
            .where(CoverageItemModel.production_id == production_id)
            .order_by(
                CoverageItemModel.updated_at.desc(), CoverageItemModel.created_at.desc()
            )
        )
    )


def list_coverage_findings(
    session: Session, production_id: str
) -> list[CoverageFindingModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(CoverageFindingModel)
            .where(CoverageFindingModel.production_id == production_id)
            .order_by(CoverageFindingModel.created_at.desc())
        )
    )


def list_pickup_tasks(session: Session, production_id: str) -> list[PickupTaskModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(PickupTaskModel)
            .where(PickupTaskModel.production_id == production_id)
            .order_by(PickupTaskModel.created_at.desc())
        )
    )


def record_coverage_item(
    session: Session,
    production_id: str,
    *,
    scene_id: str,
    coverage_key: str,
    coverage_type: str,
    planned: dict[str, Any] | None = None,
) -> Any:
    from .models import CoverageItemModel

    get_production(session, production_id)
    existing = session.scalars(
        select(CoverageItemModel).where(
            CoverageItemModel.production_id == production_id,
            CoverageItemModel.coverage_key == coverage_key,
        )
    ).first()
    if existing is not None:
        return existing
    row = CoverageItemModel(
        id=new_id("cov"),
        production_id=production_id,
        scene_id=scene_id,
        coverage_key=coverage_key,
        coverage_type=coverage_type,
        planned_json=dict(planned or {}),
    )
    session.add(row)
    audit(
        session,
        production_id,
        "coverage.item_recorded",
        {"coverage_item_id": row.id, "coverage_key": coverage_key},
    )
    session.commit()
    return row


def mark_coverage_item_shot(
    session: Session,
    *,
    coverage_item_id: str,
    shot: dict[str, Any] | None = None,
) -> Any:
    from .models import CoverageItemModel

    row = session.get(CoverageItemModel, coverage_item_id)
    if row is None:
        raise ServiceError(
            f"coverage item not found: {coverage_item_id}", status_code=404
        )
    row.status = "shot"
    row.shot_json = dict(shot or {})
    row.updated_at = utcnow()
    audit(
        session,
        row.production_id,
        "coverage.item_shot",
        {"coverage_item_id": row.id, "coverage_key": row.coverage_key},
    )
    session.commit()
    return row


def raise_coverage_finding(
    session: Session,
    *,
    coverage_item_id: str,
    board_id: str | None,
    message: str,
    actor_name: str,
    actor_role: str,
    severity: str = "medium",
) -> Any:
    from .models import CoverageFindingModel, CoverageItemModel

    item = session.get(CoverageItemModel, coverage_item_id)
    if item is None:
        raise ServiceError(
            f"coverage item not found: {coverage_item_id}", status_code=404
        )
    actor = _actor_for_decision(actor_name, actor_role, capability="raise_finding")
    if item.status != "shot":
        raise ServiceError("coverage item must be shot before it can be flagged")
    if board_id is not None:
        board = get_board(session, board_id)
        if board.production_id != item.production_id:
            raise ServiceError("board belongs to another production", status_code=404)
    item.status = "needs_review"
    item.updated_at = utcnow()
    row = CoverageFindingModel(
        id=new_id("cfnd"),
        production_id=item.production_id,
        coverage_item_id=item.id,
        board_id=board_id,
        severity=severity,
        message=message,
        raised_by_name=actor.name,
        raised_by_role=actor.role.value,
        human_raised=True,
    )
    session.add(row)
    audit(
        session,
        item.production_id,
        "coverage.finding_raised",
        {"finding_id": row.id, "coverage_item_id": item.id},
        actor=str(actor),
    )
    session.commit()
    return row


def request_pickup_from_finding(
    session: Session,
    *,
    finding_id: str,
    actor_name: str,
    actor_role: str,
    decision: str = "request_pickup",
) -> Any:
    from .models import CoverageFindingModel, CoverageItemModel, PickupTaskModel

    finding = session.get(CoverageFindingModel, finding_id)
    if finding is None:
        raise ServiceError(f"coverage finding not found: {finding_id}", status_code=404)
    item = session.get(CoverageItemModel, finding.coverage_item_id)
    if item is None:
        raise ServiceError(
            f"coverage item not found: {finding.coverage_item_id}", status_code=404
        )
    actor = _actor_for_decision(actor_name, actor_role, capability="rule_on_coverage")
    existing = session.scalars(
        select(PickupTaskModel).where(PickupTaskModel.finding_id == finding_id)
    ).first()
    if existing is not None:
        return existing
    if finding.status != "open":
        raise ServiceError(
            f"coverage finding is already {finding.status}", status_code=409
        )
    task = PickupTaskModel(
        id=new_id("ptask"),
        production_id=finding.production_id,
        finding_id=finding.id,
        coverage_item_id=finding.coverage_item_id,
        board_id=finding.board_id,
        scene_id=item.scene_id,
        status="requested",
        pickup_spec_json={},
        decision_json={
            "decision": decision,
            "actor_name": actor.name,
            "actor_role": actor.role.value,
            "decided_at": utcnow().isoformat(),
        },
        requested_by_name=actor.name,
        requested_by_role=actor.role.value,
    )
    finding.status = "pickup_requested"
    session.add(task)
    audit(
        session,
        finding.production_id,
        "pickup.requested",
        {"pickup_task_id": task.id, "finding_id": finding.id},
        actor=str(actor),
    )
    session.commit()
    return task


def confirm_pickup_task(
    session: Session,
    *,
    pickup_task_id: str,
    pickup_spec: dict[str, Any],
    actor_name: str,
    actor_role: str,
) -> Any:
    from .models import PickupTaskModel

    task = session.get(PickupTaskModel, pickup_task_id)
    if task is None:
        raise ServiceError(f"pickup task not found: {pickup_task_id}", status_code=404)
    actor = _actor_for_decision(actor_name, actor_role, capability="rule_on_coverage")
    spec = _validated_pickup_spec(task, pickup_spec)
    task.pickup_spec_json = spec
    task.scene_id = str(spec["scene_id"])
    task.status = "schedulable"
    task.confirmed_by_name = actor.name
    task.confirmed_by_role = actor.role.value
    task.confirmed_at = utcnow()
    audit(
        session,
        task.production_id,
        "pickup.confirmed",
        {"pickup_task_id": task.id, "work_id": f"pickup-{task.id}"},
        actor=str(actor),
    )
    session.commit()
    return task


def create_pickup_replan(
    session: Session,
    *,
    pickup_task_id: str,
    current_board_id: str,
    cutoff_at: dt.datetime,
    lock_policy: str,
) -> ReplanRequestModel:
    from .models import PickupTaskModel

    task = session.get(PickupTaskModel, pickup_task_id)
    if task is None:
        raise ServiceError(f"pickup task not found: {pickup_task_id}", status_code=404)
    if task.status != "schedulable":
        raise ServiceError("pickup task must be confirmed before replanning")
    if cutoff_at.tzinfo is None:
        raise ServiceError("pickup replan cutoff must be timezone-aware")
    if lock_policy not in {"preserve_locked", "preserve_through_cutoff"}:
        raise ServiceError("in-progress pickup replans require an explicit lock policy")
    board = get_board(session, current_board_id)
    if board.production_id != task.production_id:
        raise ServiceError("board belongs to another production", status_code=404)
    existing = session.scalars(
        select(ReplanRequestModel).where(
            ReplanRequestModel.production_id == task.production_id,
            ReplanRequestModel.source_kind == "pickup",
            ReplanRequestModel.source_id == task.id,
        )
    ).first()
    if existing is not None:
        return existing
    locked = list_locked_days(session, task.production_id)
    row = ReplanRequestModel(
        id=new_id("replan"),
        production_id=task.production_id,
        finding_id=None,
        current_board_id=board.id,
        requester_component="pickup",
        source_kind="pickup",
        source_id=task.id,
        reason=f"pickup task {task.id}; cutoff={cutoff_at.isoformat()}; lock_policy={lock_policy}",
        status="requested",
        affected_work_ids_json=[f"pickup-{task.id}"],
        locked_days_json=[locked_day.id for locked_day in locked],
    )
    session.add(row)
    audit(
        session,
        task.production_id,
        "replan.requested",
        {
            "replan_request_id": row.id,
            "pickup_task_id": task.id,
            "cutoff_at": cutoff_at.isoformat(),
            "lock_policy": lock_policy,
        },
        actor="pickup",
    )
    session.commit()
    return row


def _validated_pickup_spec(task: Any, pickup_spec: dict[str, Any]) -> dict[str, Any]:
    spec = dict(pickup_spec)
    required = (
        "scene_id",
        "coverage_type",
        "location_id",
        "cast_ids",
        "duration_minutes",
        "priority",
    )
    missing = [
        field_name for field_name in required if spec.get(field_name) in (None, "", [])
    ]
    if missing:
        raise ServiceError("pickup spec missing required fields: " + ", ".join(missing))
    try:
        duration = int(spec["duration_minutes"])
        day_night = DayNight(str(spec.get("day_night") or "day"))
    except (TypeError, ValueError) as exc:
        raise ServiceError(f"invalid pickup spec: {exc}") from exc
    if duration <= 0:
        raise ServiceError("pickup duration must be positive")
    spec["duration_minutes"] = duration
    spec["estimated_duration_minutes"] = duration
    spec["day_night"] = day_night.value
    spec["cast_ids"] = [str(cast_id) for cast_id in spec.get("cast_ids", [])]
    spec.setdefault("flags", {})
    spec.setdefault("requires_daylight", day_night.needs_daylight)
    spec.setdefault("authorization_trace", task.decision_json)
    return spec


def enqueue_breakdown_job(
    session: Session,
    production_id: str,
    *,
    screenplay_asset_id: str,
    auto_accept_schedulable: bool = False,
    agent_mode: str | None = None,
) -> JobModel:
    get_production(session, production_id)
    return enqueue_job(
        session,
        job_type="breakdown",
        target_id=screenplay_asset_id,
        production_id=production_id,
        payload={
            "screenplay_asset_id": screenplay_asset_id,
            "auto_accept_schedulable": auto_accept_schedulable,
            "agent_mode": agent_mode,
        },
    )


def enqueue_schedule_job(session: Session, production_id: str) -> JobModel:
    get_production(session, production_id)
    return enqueue_job(
        session,
        job_type="schedule",
        target_id=production_id,
        production_id=production_id,
        payload={"production_id": production_id},
    )


def enqueue_grounding_job(
    session: Session,
    production_id: str,
    *,
    kind: str,
    location_id: str,
    target_date: dt.date,
) -> JobModel:
    get_production(session, production_id)
    return enqueue_job(
        session,
        job_type="grounding",
        target_id=location_id,
        production_id=production_id,
        payload={
            "kind": kind,
            "location_id": location_id,
            "target_date": target_date.isoformat(),
        },
    )


def enqueue_monitor_job(
    session: Session,
    production_id: str,
    *,
    payload: dict[str, Any],
) -> JobModel:
    get_production(session, production_id)
    board_id = str(payload.get("board_id") or "")
    if not board_id:
        raise ServiceError("monitor job requires board_id")
    board = get_board(session, board_id)
    if board.production_id != production_id:
        raise ServiceError("board belongs to another production", status_code=404)
    return enqueue_job(
        session,
        job_type="monitor",
        target_id=board_id,
        production_id=production_id,
        payload={**payload, "board_id": board_id},
    )


def get_job(session: Session, job_id: str) -> JobModel:
    job = session.get(JobModel, job_id)
    if job is None:
        raise ServiceError(f"job not found: {job_id}", status_code=404)
    return job


def list_jobs(session: Session, production_id: str) -> list[JobModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(JobModel)
            .where(JobModel.production_id == production_id)
            .order_by(JobModel.created_at.desc())
        )
    )


def run_next_job(
    session: Session,
    *,
    storage: ObjectStorage | None = None,
    settings: Settings | None = None,
) -> int:
    job = session.scalars(
        select(JobModel)
        .where(JobModel.status == "queued")
        .order_by(JobModel.created_at)
    ).first()
    if job is None:
        return 0
    run_job(session, job_id=job.id, storage=storage, settings=settings)
    return 1


def run_job(
    session: Session,
    *,
    job_id: str,
    storage: ObjectStorage | None = None,
    settings: Settings | None = None,
) -> JobModel:
    job = get_job(session, job_id)
    if job.status == "complete":
        return job
    if job.status not in {"queued", "failed"}:
        raise ServiceError(f"job {job.id} is {job.status}, not runnable")
    job.status = "running"
    job.attempts += 1
    job.error = ""
    job.claimed_at = utcnow()
    job.updated_at = utcnow()
    session.commit()
    try:
        payload = dict(job.payload_json or {})
        if job.job_type == "breakdown":
            run = run_breakdown(
                session,
                production_id=str(job.production_id),
                screenplay_asset_id=str(
                    payload.get("screenplay_asset_id") or job.target_id
                ),
                auto_accept_schedulable=bool(
                    payload.get("auto_accept_schedulable", False)
                ),
                agent_mode=payload.get("agent_mode"),
                storage=storage,
                settings=settings,
            )
            if run.status != "complete":
                raise ServiceError(run.error or f"breakdown {run.status}")
            job.result_json = {"breakdown_run_id": run.id, "status": run.status}
        elif job.job_type == "schedule":
            run = run_scheduler(
                session, production_id=str(job.production_id or job.target_id)
            )
            job.result_json = {
                "schedule_run_id": run.id,
                "board_id": run.board_id,
                "status": run.status,
                "conflict": dict(run.conflict_json or {}),
            }
            if run.status == "failed" or not run.board_id:
                raise ServiceError(run.error or f"schedule {run.status}")
        elif job.job_type == "grounding":
            evidence = ground_fact(
                session,
                str(job.production_id),
                kind=str(payload.get("kind")),
                location_id=str(payload.get("location_id") or job.target_id),
                target_date=dt.date.fromisoformat(str(payload.get("target_date"))),
            )
            if evidence.status != "complete":
                raise ServiceError(evidence.error or f"grounding {evidence.status}")
            job.result_json = {
                "evidence_id": evidence.id,
                "status": evidence.status,
                "kind": evidence.fact_kind,
            }
        elif job.job_type == "monitor":
            event = process_monitor_change(
                session,
                str(job.production_id),
                payload=payload,
            )
            job.result_json = {
                "monitor_event_id": event.id,
                "finding_id": event.finding_id,
                "replan_request_id": event.replan_request_id,
                "status": event.status,
            }
        else:
            raise ServiceError(f"unsupported job type: {job.job_type}")
        job.status = "complete"
    except Exception as exc:  # noqa: BLE001 - durable job boundary
        job.status = "failed"
        job.error = str(exc)
    job.completed_at = utcnow()
    job.updated_at = utcnow()
    session.commit()
    return job


def _constraint_id_exists(
    session: Session, production_id: str, constraint_id: str
) -> bool:
    return (
        session.scalars(
            select(ConstraintModel).where(
                ConstraintModel.production_id == production_id,
                ConstraintModel.constraint_id == constraint_id,
            )
        ).first()
        is not None
    )


def _constraint_set(session: Session, production_id: str) -> ConstraintSet:
    records: list[ConstraintRecord] = []
    for row in list_constraints(session, production_id):
        try:
            records.append(constraint_from_json(row.constraint_json))
        except (ConstraintError, KeyError, TypeError, ValueError) as exc:
            raise ServiceError(
                f"stored constraint {row.constraint_id} is invalid: {exc}"
            ) from exc
    records.extend(_locked_day_constraints(session, production_id))
    return ConstraintSet(tuple(records))


def _locked_day_constraints(
    session: Session, production_id: str
) -> list[ConstraintRecord]:
    records: list[ConstraintRecord] = []
    for row in list_locked_days(session, production_id):
        actor = _actor_for_decision(row.recorded_by_name, row.recorded_by_role)
        for assignment in row.locked_assignments_json or []:
            work_id = str(assignment.get("work_id") or "")
            if not work_id:
                continue
            records.append(
                ConstraintRecord(
                    constraint_id=f"locked-{row.id}-{work_id}",
                    family=Family.LOCK,
                    policy=Policy.HARD,
                    subject=Subject(SubjectKind.WORK, work_id),
                    expression=PinnedDay(row.shoot_date),
                    source=HumanSource(
                        actor,
                        f"Locked day {row.shoot_date.isoformat()} from call sheet "
                        f"{row.call_sheet_version}",
                    ),
                    created_by=str(actor),
                    validated_against="coverset.locked_day",
                    active=True,
                    activated_at=row.created_at,
                )
            )
    return records


def _get_candidate(session: Session, candidate_id: str) -> SceneCandidateModel:
    candidate = session.get(SceneCandidateModel, candidate_id)
    if candidate is None:
        raise ServiceError(
            f"scene candidate not found: {candidate_id}", status_code=404
        )
    return candidate


def _resolve_candidate_record(
    session: Session, production_id: str, record: SceneRecord
) -> tuple[SceneRecord, list[str], bool]:
    locations = locations_from_models(list_locations(session, production_id))
    roster = roster_from_models(list_cast(session, production_id))
    aliases = aliases_from_models(list_aliases(session, production_id))
    located = breakdown.resolve_locations(
        (record,), locations=locations, aliases=aliases
    )
    casted = breakdown.resolve_cast(located.records, roster=roster)
    loc_errors = {scene_id: place for scene_id, place in located.unresolved_by_scene}
    cast_errors = {scene_id: cues for scene_id, cues in casted.unresolved_by_scene}
    resolved = casted.records[0]
    errors = _resolution_errors(resolved, loc_errors, cast_errors)
    schedulable = _candidate_can_be_scheduled(resolved, errors)
    return resolved, errors, schedulable


def run_scheduler(
    session: Session, *, production_id: str, seed: int = 0
) -> ScheduleRunModel:
    get_production(session, production_id)
    run = ScheduleRunModel(
        id=new_id("sched"), production_id=production_id, status="running"
    )
    session.add(run)
    session.commit()
    try:
        candidates = list(
            session.scalars(
                select(SceneCandidateModel).where(
                    SceneCandidateModel.production_id == production_id,
                    SceneCandidateModel.accepted.is_(True),
                )
            )
        )
        scenes = tuple(scene_from_json(c.active_scene_json or {}) for c in candidates)
        scene_work_items = tuple(scene.to_work_item() for scene in scenes)
        pickup_work_items = _pickup_work_items(session, production_id)
        work_items = scene_work_items + pickup_work_items
        if not work_items:
            raise SolverError("no accepted, schedulable scenes are available to solve")
        roster = roster_from_models(list_cast(session, production_id))
        locations = locations_from_models(list_locations(session, production_id))
        constraints = _constraint_set(session, production_id)
        constraints = _constraint_set_with_lock_blackouts(
            session, production_id, work_items, constraints
        )
        problem = ScheduleProblem(
            problem_id=f"{production_id}-mvp",
            production_calendar=_production_calendar(session, production_id),
            work_items=work_items,
            constraints=constraints,
            roster=roster,
            locations=locations,
        )
        result = solve(problem, seed=seed)
        run.status = str(result.status)
        run.diagnostics = list(result.diagnostics)
        run.conflict_json = _conflict_to_json(result.conflict_set, problem)
        run.input_hash = _input_hash(scenes, problem.constraint_snapshot_hash)
        if result.viable_boards:
            board = result.board
            rendered = stripboard(
                board, work_items=problem.work_items, locations=locations, roster=roster
            )
            result_json = board_to_json(
                board,
                work_items=problem.work_items,
                locations=locations,
                roster=roster,
                constraints=problem.constraints,
            )
            if violations := _locked_day_immutability_violations(
                session, production_id, result_json
            ):
                raise SolverError(
                    "locked day immutability violation: " + "; ".join(violations)
                )
            persisted = BoardModel(
                id=new_id("board"),
                production_id=production_id,
                schedule_run_id=run.id,
                solver_status=str(board.solver_status),
                stripboard=rendered,
                result_json=result_json,
            )
            session.add(persisted)
            session.flush()
            run.board_id = persisted.id
        else:
            run.error = str(result.conflict_set or "no viable board")
        run.completed_at = utcnow()
        audit(
            session,
            production_id,
            "schedule.completed",
            {"run_id": run.id, "status": run.status, "seed": seed},
        )
    except Exception as exc:  # noqa: BLE001 - boundary records failures durably
        run.status = "failed"
        run.error = str(exc)
        run.completed_at = utcnow()
        audit(
            session,
            production_id,
            "schedule.failed",
            {"run_id": run.id, "error": str(exc)},
        )
    session.commit()
    return run


def _constraint_set_with_lock_blackouts(
    session: Session,
    production_id: str,
    work_items: tuple[Any, ...],
    constraints: ConstraintSet,
) -> ConstraintSet:
    from coverset.constraints import BlackoutDates

    locked_days = list_locked_days(session, production_id)
    if not locked_days:
        return constraints
    locked_work_by_date = {
        row.shoot_date: {
            str(item.get("work_id") or "") for item in row.locked_assignments_json or []
        }
        for row in locked_days
    }
    records = list(constraints.records)
    for work in work_items:
        for locked_date, locked_work_ids in locked_work_by_date.items():
            if work.work_id in locked_work_ids:
                continue
            actor = _actor_for_decision(
                locked_days[0].recorded_by_name,
                locked_days[0].recorded_by_role,
            )
            records.append(
                ConstraintRecord(
                    constraint_id=f"locked-day-open-{locked_date.isoformat()}-{work.work_id}",
                    family=Family.LOCK,
                    policy=Policy.HARD,
                    subject=Subject(SubjectKind.WORK, work.work_id),
                    expression=BlackoutDates((locked_date,)),
                    source=HumanSource(
                        actor,
                        f"Locked day {locked_date.isoformat()} admits no new work",
                    ),
                    created_by=str(actor),
                    validated_against="coverset.locked_day",
                    active=True,
                    activated_at=locked_days[0].created_at,
                )
            )
    return ConstraintSet(tuple(records))


def _locked_day_immutability_violations(
    session: Session, production_id: str, board_json: dict[str, Any]
) -> list[str]:
    by_work = {
        str(strip.get("work_id")): dict(strip)
        for strip in board_json.get("strips", [])
        if strip.get("work_id")
    }
    violations: list[str] = []
    for locked_day in list_locked_days(session, production_id):
        locked_work_ids = {
            str(locked.get("work_id") or "")
            for locked in locked_day.locked_assignments_json or []
            if locked.get("work_id")
        }
        scheduled_on_locked_day = {
            str(strip.get("work_id") or "")
            for strip in board_json.get("strips", [])
            if strip.get("shoot_day") == locked_day.shoot_date.isoformat()
        }
        for extra in sorted(scheduled_on_locked_day - locked_work_ids):
            violations.append(
                f"{extra} was inserted into locked day {locked_day.shoot_date}"
            )
        for locked in locked_day.locked_assignments_json or []:
            work_id = str(locked.get("work_id") or "")
            if not work_id:
                continue
            strip = by_work.get(work_id)
            if strip is None:
                violations.append(
                    f"{work_id} was deleted from locked day {locked_day.shoot_date}"
                )
                continue
            expected = {
                "shoot_day": locked_day.shoot_date.isoformat(),
                "sequence": locked.get("sequence"),
                "location_id": locked.get("location_id"),
                "planned_call_time": locked.get("planned_call_time"),
                "planned_wrap_time": locked.get("planned_wrap_time"),
            }
            for field_name, expected_value in expected.items():
                if str(strip.get(field_name)) != str(expected_value):
                    violations.append(
                        f"{work_id} changed {field_name}: {expected_value} -> {strip.get(field_name)}"
                    )
    return violations


def _pickup_work_items(session: Session, production_id: str) -> tuple[Any, ...]:
    from coverset.work import WorkItem, WorkKind

    from .models import PickupTaskModel

    rows = session.scalars(
        select(PickupTaskModel)
        .where(
            PickupTaskModel.production_id == production_id,
            PickupTaskModel.status == "schedulable",
        )
        .order_by(PickupTaskModel.created_at)
    )
    work: list[Any] = []
    for row in rows:
        spec = dict(row.pickup_spec_json or {})
        try:
            duration = int(
                spec.get("estimated_duration_minutes") or spec["duration_minutes"]
            )
            day_night = DayNight(str(spec.get("day_night") or "day"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ServiceError(f"invalid pickup task spec for {row.id}: {exc}") from exc
        work.append(
            WorkItem(
                work_id=f"pickup-{row.id}",
                kind=WorkKind.PICKUP,
                scene_id=row.scene_id,
                location_id=str(spec.get("location_id") or ""),
                day_night=day_night,
                estimated_duration_minutes=duration,
                cast_ids=tuple(str(cast_id) for cast_id in spec.get("cast_ids", [])),
                flags=flags_from_json(dict(spec.get("flags") or {})),
                source_record_id=row.id,
                requires_daylight=spec.get("requires_daylight"),
            )
        )
    return tuple(work)


def _input_hash(scenes: tuple[SceneRecord, ...], constraint_hash: str) -> str:
    h = hashlib.sha256()
    for scene in scenes:
        h.update(repr(scene_to_json(scene)).encode())
    h.update(constraint_hash.encode())
    return h.hexdigest()


def get_breakdown_run(session: Session, run_id: str) -> BreakdownRunModel:
    run = session.get(BreakdownRunModel, run_id)
    if run is None:
        raise ServiceError(f"breakdown run not found: {run_id}", status_code=404)
    return run


def list_breakdown_runs(
    session: Session, production_id: str
) -> list[BreakdownRunModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(BreakdownRunModel)
            .where(BreakdownRunModel.production_id == production_id)
            .order_by(BreakdownRunModel.created_at.desc())
        )
    )


def list_candidates_for_run(session: Session, run_id: str) -> list[SceneCandidateModel]:
    return list(
        session.scalars(
            select(SceneCandidateModel).where(
                SceneCandidateModel.breakdown_run_id == run_id
            )
        )
    )


def list_schedule_runs(session: Session, production_id: str) -> list[ScheduleRunModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(ScheduleRunModel)
            .where(ScheduleRunModel.production_id == production_id)
            .order_by(ScheduleRunModel.created_at.desc())
        )
    )


def get_schedule_run(session: Session, run_id: str) -> ScheduleRunModel:
    run = session.get(ScheduleRunModel, run_id)
    if run is None:
        raise ServiceError(f"schedule run not found: {run_id}", status_code=404)
    return run


def _source_metadata(source: Any) -> dict[str, Any]:
    if isinstance(source, GroundedSource):
        return {
            "kind": "source_url",
            "label": "SOURCE URL",
            "description": source.describe(),
            "evidence_id": source.evidence_id,
            "grounded_value_id": source.grounded_value_id,
            "source_urls": list(source.source_urls),
            "derived_from": source.derived_from.value,
        }
    if isinstance(source, AlgorithmSource):
        return {
            "kind": "algorithm",
            "label": "ALGORITHM",
            "description": source.describe(),
            "name": source.name,
            "version": source.version,
            "derived_from": source.derived_from.value,
        }
    if isinstance(source, HumanSource):
        return {
            "kind": "human_rule",
            "label": "HUMAN RULE",
            "description": source.describe(),
            "actor": str(source.author),
            "statement": source.statement,
            "derived_from": source.derived_from.value,
        }
    return {
        "kind": type(source).__name__.replace("Source", "").casefold(),
        "label": type(source).__name__.replace("Source", "").upper(),
        "description": source.describe() if hasattr(source, "describe") else str(source),
        "derived_from": getattr(getattr(source, "derived_from", None), "value", ""),
    }


def _conflict_record_metadata(record: ConstraintRecord) -> dict[str, Any]:
    return {
        "constraint_id": record.constraint_id,
        "family": record.family.value,
        "policy": record.policy.value,
        "subject": str(record.subject),
        "expression": f"{type(record.expression).__name__}({record.expression})",
        "source": _source_metadata(record.source),
        "relaxable": record.policy.bounds_feasibility,
        "active": record.active,
    }


def _conflict_to_json(
    conflict: ConflictSet | None, problem: ScheduleProblem
) -> dict[str, Any]:
    if conflict is None:
        return {}
    binding = list(problem.constraints.binding)
    by_id = {record.constraint_id: record for record in binding}
    records = [
        _conflict_record_metadata(by_id[constraint_id])
        for constraint_id in conflict.constraint_ids
        if constraint_id in by_id
    ]
    remaining = [
        record.constraint_id
        for record in binding
        if record.constraint_id not in set(conflict.constraint_ids)
    ]
    relaxed_status = "not_applicable"
    if conflict.constraint_ids:
        from coverset.solver import _infeasible_with

        relaxed_status = (
            "still_infeasible"
            if _infeasible_with(problem, remaining)
            else "feasible_after_relaxation"
        )
    return {
        "status": "infeasible",
        "constraint_ids": list(conflict.constraint_ids),
        "structural_causes": list(conflict.structural_causes),
        "irreducible": conflict.irreducible,
        "detail": conflict.detail,
        "binding_constraint_count": len(binding),
        "constraint_snapshot_hash": problem.constraint_snapshot_hash,
        "relaxable_constraints": records,
        "relaxation_check": {
            "relaxed_constraint_ids": list(conflict.constraint_ids),
            "remaining_constraint_ids": remaining,
            "status": relaxed_status,
        },
    }


def get_board(session: Session, board_id: str) -> BoardModel:
    board = session.get(BoardModel, board_id)
    if board is None:
        raise ServiceError(f"board not found: {board_id}", status_code=404)
    return board


def generate_call_sheet(
    session: Session,
    *,
    board_id: str,
    shoot_date: dt.date,
    actor_name: str,
    actor_role: str,
) -> CallSheetModel:
    board = get_board(session, board_id)
    actor = _actor_for_decision(
        actor_name, actor_role, capability="generate_call_sheet"
    )
    existing = session.scalars(
        select(CallSheetModel).where(
            CallSheetModel.board_id == board_id,
            CallSheetModel.shoot_date == shoot_date,
        )
    ).first()
    if existing is not None:
        return existing
    try:
        payload = build_call_sheet_payload(
            production_id=board.production_id,
            board_id=board.id,
            schedule_run_id=board.schedule_run_id,
            board_result=board.result_json or {},
            shoot_date=shoot_date,
            generated_by=actor.name,
            generated_by_role=actor.role.value,
            roster=roster_from_models(list_cast(session, board.production_id)),
            locations=locations_from_models(
                list_locations(session, board.production_id)
            ),
            active_constraints=_constraint_set(session, board.production_id).active,
        )
    except (CallSheetInputError, KeyError, ValueError) as exc:
        raise ServiceError(str(exc)) from exc
    row = CallSheetModel(
        id=new_id("cs"),
        production_id=board.production_id,
        board_id=board.id,
        schedule_run_id=board.schedule_run_id,
        shoot_date=shoot_date,
        generated_by_name=actor.name,
        generated_by_role=actor.role.value,
        payload_json=payload,
        rendered_text=render_call_sheet_text(payload),
    )
    session.add(row)
    audit(
        session,
        board.production_id,
        "call_sheet.generated",
        {
            "call_sheet_id": row.id,
            "board_id": board.id,
            "shoot_date": shoot_date.isoformat(),
            "recipients": len(payload.get("recipients", [])),
        },
        actor=str(actor),
    )
    session.commit()
    return row


def list_call_sheets(session: Session, board_id: str) -> list[CallSheetModel]:
    board = get_board(session, board_id)
    return list(
        session.scalars(
            select(CallSheetModel)
            .where(CallSheetModel.board_id == board.id)
            .order_by(CallSheetModel.shoot_date, CallSheetModel.created_at)
        )
    )


def get_call_sheet(session: Session, call_sheet_id: str) -> CallSheetModel:
    row = session.get(CallSheetModel, call_sheet_id)
    if row is None:
        raise ServiceError(f"call sheet not found: {call_sheet_id}", status_code=404)
    return row


def call_sheet_export_json(row: CallSheetModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "production_id": row.production_id,
        "board_id": row.board_id,
        "schedule_run_id": row.schedule_run_id,
        "shoot_date": row.shoot_date.isoformat(),
        "generated_by_name": row.generated_by_name,
        "generated_by_role": row.generated_by_role,
        "payload": dict(row.payload_json or {}),
        "rendered_text": row.rendered_text,
        "created_at": row.created_at.isoformat(),
    }


def list_audit_events(session: Session, production_id: str) -> list[AuditEventModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(AuditEventModel)
            .where(AuditEventModel.production_id == production_id)
            .order_by(AuditEventModel.created_at, AuditEventModel.id)
        )
    )


def audit_event_to_json(row: AuditEventModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "production_id": row.production_id,
        "event_type": row.event_type,
        "actor": row.actor,
        "payload": dict(row.payload or {}),
        "created_at": row.created_at.isoformat(),
    }


def board_export_json(board: BoardModel) -> dict[str, Any]:
    return {
        "id": board.id,
        "production_id": board.production_id,
        "schedule_run_id": board.schedule_run_id,
        "solver_status": board.solver_status,
        "stripboard": board.stripboard,
        "result": dict(board.result_json or {}),
    }


def board_export_csv(board: BoardModel) -> str:
    output = StringIO()
    columns = [
        "shoot_day",
        "sequence",
        "work_id",
        "scene_id",
        "kind",
        "day_night",
        "location_id",
        "location_name",
        "cast_ids",
        "planned_call_time",
        "planned_wrap_time",
    ]
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for strip in (board.result_json or {}).get("strips", []):
        location = dict(strip.get("location") or {})
        writer.writerow(
            {
                "shoot_day": strip.get("shoot_day", ""),
                "sequence": strip.get("sequence", ""),
                "work_id": strip.get("work_id", ""),
                "scene_id": strip.get("scene_id", ""),
                "kind": strip.get("kind", ""),
                "day_night": strip.get("day_night", ""),
                "location_id": strip.get("location_id", ""),
                "location_name": location.get("name", ""),
                "cast_ids": ";".join(
                    str(cast_id) for cast_id in strip.get("cast_ids", [])
                ),
                "planned_call_time": strip.get("planned_call_time", ""),
                "planned_wrap_time": strip.get("planned_wrap_time", ""),
            }
        )
    return output.getvalue()


def audit_export_json(rows: list[AuditEventModel]) -> list[dict[str, Any]]:
    return [audit_event_to_json(row) for row in rows]


def audit_export_csv(rows: list[AuditEventModel]) -> str:
    output = StringIO()
    columns = ["id", "production_id", "event_type", "actor", "created_at", "payload"]
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        payload = json.dumps(row.payload or {}, sort_keys=True, separators=(",", ":"))
        writer.writerow(
            {
                "id": row.id,
                "production_id": row.production_id or "",
                "event_type": row.event_type,
                "actor": row.actor,
                "created_at": row.created_at.isoformat(),
                "payload": payload,
            }
        )
    return output.getvalue()


def bigquery_audit_rows(rows: list[AuditEventModel]) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "production_id": row.production_id,
            "event_type": row.event_type,
            "actor": row.actor,
            "payload": json.dumps(row.payload or {}, sort_keys=True),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def export_audit_events_to_sink(
    session: Session, production_id: str, *, sink: HasAuditSink
) -> int:
    rows = bigquery_audit_rows(list_audit_events(session, production_id))
    return sink.append_rows(rows)


class BigQueryAuditSink:
    def __init__(self, *, project_id: str, dataset: str, table: str) -> None:
        self.project_id = project_id
        self.dataset = dataset
        self.table = table

    @property
    def configured(self) -> bool:
        return bool(self.project_id and self.dataset and self.table)

    def append_rows(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        if not self.configured:
            raise ServiceError(
                "BigQuery audit export is not configured", status_code=503
            )
        try:
            import google.auth  # type: ignore[import-untyped]
            from google.auth.transport.requests import (  # type: ignore[import-untyped]
                AuthorizedSession,
            )
        except ImportError as exc:  # pragma: no cover - depends on deployed deps
            raise ServiceError(
                "google-auth is not available for BigQuery export", status_code=503
            ) from exc
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/bigquery.insertdata"]
        )
        authed = AuthorizedSession(credentials)
        table_ref = f"{self.project_id}.{self.dataset}.{self.table}"
        url = (
            "https://bigquery.googleapis.com/bigquery/v2/projects/"
            f"{self.project_id}/datasets/{self.dataset}/tables/{self.table}/insertAll"
        )
        response = authed.post(
            url,
            json={
                "kind": "bigquery#tableDataInsertAllRequest",
                "skipInvalidRows": False,
                "ignoreUnknownValues": False,
                "rows": [{"insertId": row["id"], "json": row} for row in rows],
            },
            timeout=15,
        )
        if response.status_code >= 400:
            raise ServiceError(
                f"BigQuery audit export failed for {table_ref}: HTTP {response.status_code}",
                status_code=502,
            )
        errors = response.json().get("insertErrors", [])
        if errors:
            raise ServiceError(
                f"BigQuery audit export rejected {len(errors)} row(s) for {table_ref}",
                status_code=502,
            )
        return len(rows)


def export_audit_events_to_bigquery(
    session: Session,
    production_id: str,
    *,
    settings: Settings | None = None,
) -> int:
    active_settings = settings or get_settings()
    return export_audit_events_to_sink(
        session,
        production_id,
        sink=BigQueryAuditSink(
            project_id=active_settings.project_id,
            dataset=active_settings.bigquery_dataset,
            table=active_settings.bigquery_audit_table,
        ),
    )


def enqueue_job(
    session: Session,
    *,
    job_type: str,
    target_id: str,
    production_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> JobModel:
    job = JobModel(
        id=new_id("job"),
        production_id=production_id,
        job_type=job_type,
        target_id=target_id,
        status="queued",
        payload_json=payload or {},
        result_json={},
    )
    session.add(job)
    audit(
        session, production_id, "job.enqueued", {"job_id": job.id, "job_type": job_type}
    )
    session.commit()
    return job


def materialize_demo_script() -> bytes:
    return (
        b"THE FERRY JOB\n\n"
        b"1   INT. MAYA'S APARTMENT - NIGHT\n"
        b"MAYA and DEV study the ferry schedule.\n\n"
        b"2   EXT. BROOKLYN BRIDGE PARK - DAY\n"
        b"MAYA and DEV sprint through cyclists. STUNT.\n\n"
        b"INT. WAREHOUSE - CONTINUOUS\n"
        b"RUTH opens the evidence locker.\n\n"
        b"EXT. FERRY TERMINAL / RIVER DOCK - DUSK\n"
        b"MAYA sees the boat pull away. VFX: skyline replacement.\n\n"
        b"3   INT. MAYA'S APARTMENT - DAY\n"
        b"MAYA comforts KID before the call. MINOR.\n"
    )
