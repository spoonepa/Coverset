"""Application services that wrap Coverset's domain modules for HTTP/worker use."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
from dataclasses import replace
from io import BytesIO, StringIO
from typing import Any, Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session

import coverset.breakdown as breakdown  # type: ignore[import-not-found]
from coverset.actors import Actor, AuthorityError, Role
from coverset.breakdown import RawScene  # type: ignore[import-not-found]
from coverset.constraints import (
    ConstraintError,
    ConstraintRecord,
    ConstraintSet,
    Family,
    HumanSource,
    PinnedDay,
    Policy,
    Subject,
    SubjectKind,
)
from coverset.grounding import Evidence, FactKind, GroundingError, SearchGrounder
from coverset.locations import Location
from coverset.scenes import CandidateStatus, SceneRecord
from coverset.solver import ProductionCalendar, ScheduleProblem, SolverError, solve
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


def list_constraints(session: Session, production_id: str) -> list[ConstraintModel]:
    get_production(session, production_id)
    return list(
        session.scalars(
            select(ConstraintModel)
            .where(ConstraintModel.production_id == production_id)
            .order_by(ConstraintModel.created_at, ConstraintModel.constraint_id)
        )
    )


def create_constraint(
    session: Session, production_id: str, *, payload: dict[str, Any]
) -> ConstraintModel:
    get_production(session, production_id)
    if _constraint_id_exists(session, production_id, str(payload.get("constraint_id", ""))):
        raise ServiceError(
            f"constraint id already exists: {payload.get('constraint_id')}",
            status_code=409,
        )
    evidence_payload: dict[str, Any] | None = None
    evidence_id = payload.get("evidence_id")
    if evidence_id:
        evidence = get_grounding_evidence(session, str(evidence_id))
        if evidence.production_id != production_id:
            raise ServiceError("grounding evidence belongs to another production", status_code=404)
        if evidence.status != "complete":
            raise ServiceError("failed grounding evidence cannot back an active constraint")
        evidence_payload = dict(evidence.evidence_json or {})
    try:
        record = constraint_from_payload(payload, evidence=evidence_payload)
    except (ConstraintError, KeyError, TypeError, ValueError) as exc:
        raise ServiceError(f"invalid constraint: {exc}") from exc
    snapshot = constraint_to_json(record)
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
        raise ServiceError(f"constraint not found: {constraint_row_id}", status_code=404)
    record = replace(
        constraint_from_json(row.constraint_json),
        active=active,
        activated_at=utcnow() if active else None,
    )
    row.active = active
    row.constraint_json = constraint_to_json(record)
    row.provenance_json = dict(row.constraint_json.get("source", {}))
    actor = _actor_for_decision(actor_name, actor_role)
    audit(
        session,
        row.production_id,
        "constraint.activated" if active else "constraint.deactivated",
        {"constraint_id": row.constraint_id, "actor_role": actor.role.value},
        actor=str(actor),
    )
    session.commit()
    return row


def get_grounding_evidence(session: Session, evidence_id: str) -> GroundingEvidenceModel:
    row = session.get(GroundingEvidenceModel, evidence_id)
    if row is None:
        raise ServiceError(f"grounding evidence not found: {evidence_id}", status_code=404)
    return row


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
        location = locations_from_models(list_locations(session, production_id))[location_id]
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
        evidence = (grounder or SearchGrounder()).ground(fact_kind, location, target_date)
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
    cast = sorted({cast_id for item in locked_assignments for cast_id in item["cast_ids"]})
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
            raise ServiceError("evidence belongs to another production", status_code=404)
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
        raise ServiceError(f"monitor finding is already {finding.status}", status_code=409)
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

    locked = list_locked_days(session, finding.production_id)
    replan = ReplanRequestModel(
        id=new_id("replan"),
        production_id=finding.production_id,
        finding_id=finding.id,
        current_board_id=finding.board_id,
        requester_component=finding.requester_component,
        status="requested",
        affected_work_ids_json=list(finding.affected_work_ids_json or []),
        locked_days_json=[row.id for row in locked],
    )
    finding.status = "accepted"
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
    prior_run_id: str | None = None
    if prior_board_id:
        prior = get_board(session, prior_board_id)
        if prior.production_id != board.production_id:
            raise ServiceError("prior board belongs to another production", status_code=404)
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
        select(JobModel).where(JobModel.status == "queued").order_by(JobModel.created_at)
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
                screenplay_asset_id=str(payload.get("screenplay_asset_id") or job.target_id),
                auto_accept_schedulable=bool(payload.get("auto_accept_schedulable", False)),
                agent_mode=payload.get("agent_mode"),
                storage=storage,
                settings=settings,
            )
            if run.status != "complete":
                raise ServiceError(run.error or f"breakdown {run.status}")
            job.result_json = {"breakdown_run_id": run.id, "status": run.status}
        elif job.job_type == "schedule":
            run = run_scheduler(session, production_id=str(job.production_id or job.target_id))
            if run.status == "failed" or not run.board_id:
                raise ServiceError(run.error or f"schedule {run.status}")
            job.result_json = {
                "schedule_run_id": run.id,
                "board_id": run.board_id,
                "status": run.status,
            }
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
            finding = create_monitor_finding(
                session,
                str(job.production_id),
                payload=payload,
                requester_component="monitor",
            )
            job.result_json = {"finding_id": finding.id, "status": finding.status}
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


def _constraint_id_exists(session: Session, production_id: str, constraint_id: str) -> bool:
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
            raise ServiceError(f"stored constraint {row.constraint_id} is invalid: {exc}") from exc
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
            constraints=_constraint_set(session, production_id),
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
                result_json=board_to_json(
                    board,
                    work_items=problem.work_items,
                    locations=locations,
                    roster=roster,
                    constraints=problem.constraints,
                ),
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


def list_audit_events(
    session: Session, production_id: str
) -> list[AuditEventModel]:
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
                "cast_ids": ";".join(str(cast_id) for cast_id in strip.get("cast_ids", [])),
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
            raise ServiceError("BigQuery audit export is not configured", status_code=503)
        try:
            import google.auth  # type: ignore[import-untyped]
            from google.auth.transport.requests import (  # type: ignore[import-untyped]
                AuthorizedSession,
            )
        except ImportError as exc:  # pragma: no cover - depends on deployed deps
            raise ServiceError("google-auth is not available for BigQuery export", status_code=503) from exc
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
                "rows": [
                    {"insertId": row["id"], "json": row}
                    for row in rows
                ],
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
    audit(session, production_id, "job.enqueued", {"job_id": job.id, "job_type": job_type})
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
