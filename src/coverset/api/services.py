"""Application services that wrap Coverset's domain modules for HTTP/worker use."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import replace
from io import BytesIO
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import coverset.breakdown as breakdown  # type: ignore[import-not-found]
from coverset.breakdown import RawScene  # type: ignore[import-not-found]
from coverset.constraints import ConstraintSet
from coverset.scenes import CandidateStatus, SceneRecord
from coverset.solver import ProductionCalendar, ScheduleProblem, SolverError, solve
from coverset.stripboard import stripboard
from coverset.work import DayNight

from .config import Settings, get_settings  # type: ignore[import-not-found]
from .models import (  # type: ignore[import-not-found]
    AuditEventModel,
    BoardModel,
    BreakdownRunModel,
    CastMemberModel,
    JobModel,
    LocationAliasModel,
    LocationModel,
    ProductionModel,
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


class ServiceError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class HasExtract(Protocol):
    def extract(self, document: bytes, *, media: str) -> tuple[RawScene, ...]: ...


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


def run_scheduler(session: Session, *, production_id: str) -> ScheduleRunModel:
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
        if not scenes:
            raise SolverError("no accepted, schedulable scenes are available to solve")
        work_items = tuple(scene.to_work_item() for scene in scenes)
        roster = roster_from_models(list_cast(session, production_id))
        locations = locations_from_models(list_locations(session, production_id))
        problem = ScheduleProblem(
            problem_id=f"{production_id}-mvp",
            production_calendar=_production_calendar(session, production_id),
            work_items=work_items,
            constraints=ConstraintSet(()),
            roster=roster,
            locations=locations,
        )
        result = solve(problem, seed=0)
        run.status = str(result.status)
        run.diagnostics = list(result.diagnostics)
        run.input_hash = _input_hash(scenes, problem.constraint_snapshot_hash)
        if result.viable_boards:
            board = result.board
            rendered = stripboard(
                board, work_items=problem.work_items, locations=locations, roster=roster
            )
            persisted = BoardModel(
                id=new_id("board"),
                production_id=production_id,
                schedule_run_id=run.id,
                solver_status=str(board.solver_status),
                stripboard=rendered,
                result_json=board_to_json(board),
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
            {"run_id": run.id, "status": run.status},
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


def list_candidates_for_run(session: Session, run_id: str) -> list[SceneCandidateModel]:
    return list(
        session.scalars(
            select(SceneCandidateModel).where(
                SceneCandidateModel.breakdown_run_id == run_id
            )
        )
    )


def get_schedule_run(session: Session, run_id: str) -> ScheduleRunModel:
    run = session.get(ScheduleRunModel, run_id)
    if run is None:
        raise ServiceError(f"schedule run not found: {run_id}", status_code=404)
    return run


def get_board(session: Session, board_id: str) -> BoardModel:
    board = session.get(BoardModel, board_id)
    if board is None:
        raise ServiceError(f"board not found: {board_id}", status_code=404)
    return board


def audit(
    session: Session, production_id: str | None, event_type: str, payload: dict
) -> None:
    session.add(
        AuditEventModel(
            id=new_id("audit"),
            production_id=production_id,
            event_type=event_type,
            payload=payload,
        )
    )


def enqueue_job(session: Session, *, job_type: str, target_id: str) -> JobModel:
    job = JobModel(
        id=new_id("job"), job_type=job_type, target_id=target_id, status="queued"
    )
    session.add(job)
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
