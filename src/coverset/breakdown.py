"""Screenplay breakdown -- the Gemini agent path: screenplay bytes to candidate scenes.

    screenplay PDF/text -> Gemini breakdown -> candidate SceneRecords
                        -> cast/location resolution -> human activation -> WorkItem

The twin of `coverset.grounding`. There an agent (Parallel) retrieves and the result
arrives as sourced *evidence* that decides nothing; here an agent (Gemini) interprets a
screenplay and the result arrives as *candidate* records that decide nothing. In both,
the model proposes and a person or a validator disposes -- SPEC NNG-002: "Gemini and
other advisory agents may produce candidate records ... they may not decide coverage,
approve costs, select boards, or emit schedules."

Two lines are drawn deliberately:

- **The structural spine is stable, the judgement is the model's.** BRK-012 requires
  that two parses of one document return the same scene list and the same INT/EXT and
  day/night. That is not anti-agent dogma: the product's headline is replan-on-change,
  and a schedule *diff* is only meaningful if re-reading an unchanged script yields the
  same scenes. So the sluglines the agent returns are folded into INT/EXT and day/night
  by a fixed grammar here, and every breakdown is memoised on the document's content
  hash -- a stochastic model called twice on identical bytes still yields one reading.
  Model variance is confined to cast and flags, which reach the solver only through
  resolution (BRK-004/013) and human activation.

- **Nothing here resolves by proximity.** A cue that is not on the roster and a slugline
  place that is not in the `LocationBook` stay unresolved and block the board (BRK-004,
  BRK-013). Mapping an unrecognised "SARA" onto the nearest "SARAH" is the exact silent
  failure this project keeps meeting; unresolved staying unresolved is the point.

The agent is injected, not hard-wired, so the offline suite exercises the folding,
resolution and gating against a recorded reading with no API key, exactly as the
grounding offline suite runs against a fake Parallel client. The real Gemini call lives
behind `GeminiBreakdown` and the deselected `live` tier.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol, runtime_checkable

from .locations import LocationBook
from .people import Roster
from .scenes import CandidateStatus, IntExt, SceneRecord
from .work import DayNight, WorkFlags

__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "BreakdownAgent",
    "BreakdownError",
    "BreakdownUnavailable",
    "CastResolution",
    "GeminiBreakdown",
    "LocationResolution",
    "RawScene",
    "activate",
    "clear_cache",
    "parse",
    "resolve_cast",
    "resolve_locations",
]

DEFAULT_CONFIDENCE_THRESHOLD = 0.75
"""Below this, a candidate is marked `needs_review` and cannot be activated (BRK-003).

A threshold, not a truth. It is the line past which the parser's own stated confidence
is too low to hand a crew day to without a person looking first. Overridable per call so
a production that trusts its source can lower it, or a nervous one raise it.
"""

CLIENT_MODEL = "gemini-2.5-pro"
"""The same model the grounding path declares to Parallel. One model for both agents."""

_MEDIA = {"pdf", "text"}


class BreakdownError(Exception):
    """The document, or the agent's reading of it, could not be turned into records."""


class BreakdownUnavailable(Exception):
    """The live breakdown agent could not be constructed.

    Distinct from `BreakdownError` on purpose, and mirroring `GroundingUnavailable`: a
    missing dependency or API key is an environment that is not set up, not a screenplay
    that failed to parse. The offline suite never hits this -- it injects an agent.
    """


@dataclass(frozen=True, slots=True)
class RawScene:
    """One scene as the agent read it, before the structural spine is folded.

    Deliberately close to what a language model can honestly emit: the heading line
    verbatim, the character cues as printed, and its own confidence. Everything typed --
    INT/EXT, day/night, the resolved cast and location -- is derived from these here, not
    trusted from the model, so the derivation is one fixed thing rather than per-call.
    """

    slugline: str
    cast_names: tuple[str, ...] = ()
    scene_number: str | None = None
    """The script's own number if the heading prints one, else `None` -> synthesised."""
    page_eighths: int | None = None
    confidence: float = 1.0
    source_page_range: str = ""
    stunt: bool = False
    minors: bool = False
    vfx: bool = False


@runtime_checkable
class BreakdownAgent(Protocol):
    """Anything that turns screenplay bytes into raw candidate scenes.

    One method, injected wherever a breakdown is produced, so the real Gemini client and
    a recorded reading are interchangeable and the offline suite needs no key.
    """

    def extract(self, document: bytes, *, media: str) -> tuple[RawScene, ...]:
        """Return the agent's raw reading of the document bytes."""
        ...


# --- Slugline grammar -------------------------------------------------------------
#
# A scene heading is a near-formal grammar, which is why folding it here rather than
# trusting the model's classification is both cheaper and what makes BRK-012 hold. The
# variance a language model genuinely adds is in cast and flags, not in whether "INT."
# means interior.

_SLUGLINE = re.compile(
    r"^\s*(?P<ie>INT\.?/EXT\.?|EXT\.?/INT\.?|INT\.?|EXT\.?|EST\.?|I\.?/E\.?|E\.?/I\.?)"
    r"[\.\s]+(?P<rest>.+?)\s*$",
    re.IGNORECASE,
)
_DASH = re.compile(r"\s+[-\u2013\u2014]+\s+")

_INT_EXT = {
    "INT": IntExt.INT,
    "EXT": IntExt.EXT,
    "EST": IntExt.EXT,
    "INT/EXT": IntExt.INT_EXT,
    "EXT/INT": IntExt.INT_EXT,
    "I/E": IntExt.INT_EXT,
    "E/I": IntExt.INT_EXT,
}

_DAY_NIGHT = (
    (DayNight.DAWN, ("DAWN", "SUNRISE", "SUNUP", "FIRST LIGHT")),
    (DayNight.DUSK, ("DUSK", "SUNSET", "SUNDOWN", "TWILIGHT", "MAGIC HOUR", "GOLDEN HOUR")),
    (DayNight.NIGHT, ("NIGHT", "MIDNIGHT", "EVENING", "LATE NIGHT")),
    (DayNight.DAY, ("DAY", "MORNING", "MIDDAY", "NOON", "AFTERNOON", "DAYTIME")),
)
"""Order matters: DAWN and DUSK are tested before DAY and NIGHT so "SUNSET" is dusk, not
a night that happens to contain no "NIGHT". Carry-forward markers (CONTINUOUS, LATER,
SAME, MOMENTS LATER) match nothing and fold to UNKNOWN -- the heading genuinely does not
state a time of day, and guessing one is how an exterior lands after dark."""


def _norm_ie(token: str) -> IntExt:
    key = token.upper().replace(".", "").replace(" ", "")
    return _INT_EXT.get(key, IntExt.UNKNOWN)


def _day_night(tod: str) -> DayNight:
    upper = tod.upper()
    for value, needles in _DAY_NIGHT:
        if any(n in upper for n in needles):
            return value
    return DayNight.UNKNOWN


def _parse_slugline(slugline: str) -> tuple[IntExt, DayNight, str]:
    """Fold one heading into (INT/EXT, day/night, location text).

    A heading that does not begin with a recognised INT/EXT token yields UNKNOWN rather
    than a guess; the caller lowers confidence so the record needs review instead of
    reaching the solver mislabelled.
    """
    match = _SLUGLINE.match(slugline)
    if match is None:
        return IntExt.UNKNOWN, DayNight.UNKNOWN, slugline.strip()
    int_ext = _norm_ie(match.group("ie"))
    parts = _DASH.split(match.group("rest"))
    if len(parts) >= 2:
        location_text = parts[0].strip()
        day_night = _day_night(parts[-1])
    else:
        location_text = match.group("rest").strip()
        day_night = DayNight.UNKNOWN
    return int_ext, day_night, location_text


def _slug(text: str) -> str:
    """The same id derivation `Location` uses, so a place resolves by its own slug."""
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


_LEADING_SCENE_NO = re.compile(
    r"^\s*\d{1,4}[A-Za-z]?[.)]?\s+(?=(?:INT|EXT|EST|I\.?/E|E\.?/I))",
    re.IGNORECASE,
)


def _strip_leading_number(slugline: str) -> str:
    """Drop a margin scene number a shooting script prints in front of the heading.

    A real breakdown returns the heading verbatim, and a shooting draft numbers both
    margins -- "1   INT. MAYA'S APARTMENT - NIGHT". That number is captured separately as
    the scene number; left on the front it stops the heading being read as a heading at
    all, which is precisely the gap the live tier caught against real Gemini. Stripped
    only when a slugline keyword follows, so a place that merely begins with a digit
    ("10 DOWNING STREET") is left alone.
    """
    return _LEADING_SCENE_NO.sub("", slugline.strip(), count=1).strip()


def _clamp01(value: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


# --- Folding ----------------------------------------------------------------------


def _fold(raw: tuple[RawScene, ...], *, threshold: float) -> tuple[SceneRecord, ...]:
    """Turn raw agent scenes into candidate records with the spine folded in.

    Scene ids are the parser's position, independent of the script's numbering, so an
    unnumbered script and a duplicate-numbered one both yield stable, unique ids without
    inventing a number that reads as the production's own.
    """
    records: list[SceneRecord] = []
    for i, r in enumerate(raw):
        heading = _strip_leading_number(r.slugline)
        int_ext, day_night, location_text = _parse_slugline(heading)

        printed = (r.scene_number or "").strip()
        synthesised = not printed
        scene_number = printed if printed else f"S{i + 1}"

        raw_eighths = r.page_eighths
        if isinstance(raw_eighths, int) and not isinstance(raw_eighths, bool) and raw_eighths > 0:
            page_eighths, eighths_ok = raw_eighths, True
        else:
            page_eighths, eighths_ok = 1, False

        # Structural uncertainty pulls the stated confidence down: a heading that did not
        # yield an INT/EXT or a location, or a scene with no page count, is exactly the
        # kind a person should see before it becomes a crew day.
        effective = _clamp01(r.confidence)
        if int_ext is IntExt.UNKNOWN:
            effective = min(effective, 0.4)
        if not location_text:
            effective = min(effective, 0.4)
        if not eighths_ok:
            effective = min(effective, 0.5)

        status = (
            CandidateStatus.NEEDS_REVIEW
            if effective < threshold
            else CandidateStatus.CANDIDATE
        )

        cast_names = tuple(n.strip() for n in r.cast_names if n and n.strip())

        records.append(
            SceneRecord(
                scene_id=f"BRK-{i + 1:03d}",
                scene_number=scene_number,
                slugline=heading,
                int_ext=int_ext,
                day_night=day_night,
                # Holds the screenplay's place text until resolve_locations swaps it for
                # a LocationBook id. Never blank -- SceneRecord requires a place.
                location_ref=location_text or heading or "UNRESOLVED",
                page_eighths=page_eighths,
                # Character cues, not roster ids, until resolve_cast maps them.
                cast_ids=cast_names,
                flags=WorkFlags(stunts=r.stunt, minors=r.minors, vfx=r.vfx),
                source_page_range=r.source_page_range,
                confidence=effective,
                status=status,
                number_synthesized=synthesised,
            )
        )
    return tuple(records)


# --- Parse (memoised on document content) -----------------------------------------

_CACHE: dict[tuple[str, str], tuple[SceneRecord, ...]] = {}


def clear_cache() -> None:
    """Drop the content-hash cache. For tests that reparse identical bytes with a
    different injected reading; production never needs it."""
    _CACHE.clear()


def parse(
    document: bytes,
    *,
    media: str,
    agent: BreakdownAgent | None = None,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> tuple[SceneRecord, ...]:
    """Break a screenplay down into candidate `SceneRecord`s (BRK-001).

    The result is memoised on the document's content hash, so two parses of one document
    return the identical scene list even though the agent behind them is stochastic --
    the invariant BRK-012 rests on and every schedule diff after it.

    Args:
        document: the screenplay bytes, exactly as uploaded -- the same in test as in
            production, which is why acquiring them is not this function's concern.
        media: "pdf" or "text".
        agent: the reading agent. Defaults to the live `GeminiBreakdown`; the offline
            suite injects a recorded reading.
        threshold: confidence below which a record is `needs_review` (BRK-003).

    Raises:
        BreakdownError: the media is unknown, or the agent returned nothing usable.
        BreakdownUnavailable: no agent was given and the live one cannot be built.
    """
    if media not in _MEDIA:
        raise BreakdownError(f"media must be one of {', '.join(sorted(_MEDIA))}, got {media!r}")

    key = (hashlib.sha256(document).hexdigest(), media)
    if key in _CACHE:
        return _CACHE[key]

    reader = agent if agent is not None else GeminiBreakdown()
    raw = tuple(reader.extract(document, media=media))
    if not raw:
        raise BreakdownError("the breakdown agent returned no scenes for this document")

    records = _fold(raw, threshold=threshold)
    _CACHE[key] = records
    return records


# --- Cast resolution (BRK-004) ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class CastResolution:
    """The outcome of mapping candidate cues to roster ids.

    `records` carries the cue names replaced by the ids that resolved; a name that did
    not resolve is dropped from the record and named in `unresolved`, never mapped to the
    nearest roster id. While anything is unresolved the whole set is withheld from the
    solver, because a board built on a partial cast is a board that called the wrong
    people (BRK-004).
    """

    records: tuple[SceneRecord, ...]
    unresolved: tuple[str, ...]
    unresolved_by_scene: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def records_ready_for_solver(self) -> tuple[SceneRecord, ...]:
        return () if self.unresolved else self.records


def resolve_cast(records: tuple[SceneRecord, ...], *, roster: Roster) -> CastResolution:
    """Resolve every scene's candidate cues to roster ids, or report them unresolved.

    A cue matches an id outright, or a cast member's character (case-insensitively), and
    nothing else. "SARA" against a roster holding "SARAH" stays unresolved -- the whole
    reason cast are typed entities rather than names on a scene.
    """
    id_set = {m.id for m in roster}
    by_character: dict[str, str] = {}
    for m in roster:
        by_character.setdefault(m.character.casefold(), m.id)

    resolved: list[SceneRecord] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    by_scene: list[tuple[str, tuple[str, ...]]] = []

    for rec in records:
        ids: list[str] = []
        missing: list[str] = []
        for name in rec.cast_ids:
            if name in id_set:
                ids.append(name)
            elif (mapped := by_character.get(name.casefold())) is not None:
                ids.append(mapped)
            else:
                missing.append(name)
                if name not in seen:
                    seen.add(name)
                    unresolved.append(name)
        resolved.append(replace(rec, cast_ids=tuple(ids)))
        if missing:
            by_scene.append((rec.scene_id, tuple(missing)))

    return CastResolution(tuple(resolved), tuple(unresolved), tuple(by_scene))


# --- Location resolution (BRK-013) ------------------------------------------------


@dataclass(frozen=True, slots=True)
class LocationResolution:
    """The outcome of mapping candidate slugline places to `LocationBook` ids.

    Same discipline as cast: a place resolves to exactly one unit location or stays
    unresolved and blocks the board. A heading naming two places resolves to the one unit
    location the company travels to, given as an alias, or is reported -- never to the
    nearer of the two.
    """

    records: tuple[SceneRecord, ...]
    unresolved: tuple[str, ...]
    unresolved_by_scene: tuple[tuple[str, str], ...] = ()

    @property
    def records_ready_for_solver(self) -> tuple[SceneRecord, ...]:
        return () if self.unresolved else self.records


def resolve_locations(
    records: tuple[SceneRecord, ...],
    *,
    locations: LocationBook,
    aliases: Mapping[str, str] | None = None,
) -> LocationResolution:
    """Resolve each scene's slugline place to a `LocationBook` id, or report it.

    Resolution is by exact slug: the place text is slugged the way `Location` slugs its
    own name, and matched against the book's ids and name-slugs. `aliases` maps a
    screenplay place (a sub-location, or a two-place heading) to the unit location the
    company travels to and permits attach to -- the one thing a nearest-match would
    misprice. An alias pointing off the book is an error, not a silent miss.
    """
    alias_map = {_slug(k): v for k, v in (aliases or {}).items()}
    book_ids = {loc.id for loc in locations}
    name_slugs: dict[str, str] = {}
    for loc in locations:
        name_slugs.setdefault(_slug(loc.name), loc.id)

    resolved: list[SceneRecord] = []
    unresolved: list[str] = []
    seen: set[str] = set()
    by_scene: list[tuple[str, str]] = []

    for rec in records:
        candidate = _slug(rec.location_ref)
        target: str | None = None
        if candidate in alias_map:
            target = alias_map[candidate]
            if target not in book_ids:
                raise BreakdownError(
                    f"{rec.scene_id}: alias for {rec.location_ref!r} points to "
                    f"{target!r}, which is not on the production's locations"
                )
        elif candidate in book_ids:
            target = candidate
        elif candidate in name_slugs:
            target = name_slugs[candidate]

        if target is not None:
            resolved.append(replace(rec, location_ref=target))
        else:
            resolved.append(rec)
            by_scene.append((rec.scene_id, rec.location_ref))
            if rec.location_ref not in seen:
                seen.add(rec.location_ref)
                unresolved.append(rec.location_ref)

    return LocationResolution(tuple(resolved), tuple(unresolved), tuple(by_scene))


# --- Activation -------------------------------------------------------------------


def activate(record: SceneRecord) -> SceneRecord:
    """Promote a reviewed candidate to an active record the solver may schedule.

    The narrow gate every candidate passes through, and the reason breakdown output
    cannot reach the solver on the model's say-so. A record below the confidence
    threshold refuses activation until a person has reviewed it (BRK-003); a rejected one
    cannot be revived by re-activating it.

    Raises:
        BreakdownError: the record is not eligible for activation.
    """
    if record.status is CandidateStatus.ACTIVE:
        return record
    if record.status is CandidateStatus.NEEDS_REVIEW:
        raise BreakdownError(
            f"{record.scene_id}: confidence {record.confidence} is below the review "
            f"threshold; a person must review it before it can be scheduled (BRK-003)"
        )
    if record.status is CandidateStatus.REJECTED:
        raise BreakdownError(
            f"{record.scene_id}: a rejected record cannot be activated; break the "
            f"document down again if it should return"
        )
    return replace(record, status=CandidateStatus.ACTIVE)


# --- The live agent ---------------------------------------------------------------

_PROMPT = """You are a film script supervisor doing a scene breakdown.

Read the screenplay and return a JSON array. One object per scene heading (slugline),
in the order they appear, with these fields:

- "slugline": the scene heading line, VERBATIM, exactly as printed (e.g.
  "INT. MAYA'S APARTMENT - NIGHT"). Do not normalise, expand, or reorder it.
- "scene_number": the script's own scene number as a string if the heading prints one
  (e.g. "14", "12A"), otherwise null. Never invent a number.
- "cast": array of character cue names that appear in the scene, as printed (uppercase
  cue names). Do not include extras described only in action unless they are cued.
- "page_eighths": integer estimate of the scene's length in eighths of a page (1 to ~8+).
- "confidence": your confidence in this scene's reading, 0.0 to 1.0.
- "stunt": true if the scene involves a stunt.
- "minors": true if a minor (child) performer is in the scene.
- "vfx": true if the scene needs visual effects.
- "source_page_range": the page(s) this scene spans, as a string, if determinable.

Return only the JSON array, no prose. Read the whole document; do not stop early."""


class GeminiBreakdown:
    """Breaks a screenplay down with Gemini (SPEC 5: "the Breakdown agent").

    Extractive only: it produces candidate records and no schedule, and it decides
    nothing. Gemini ingests the PDF or text directly, so there is no separate extraction
    step to garble a heading. Temperature is pinned to zero and the reading is memoised
    upstream on the document hash, together giving BRK-012 the stability a stochastic
    model cannot give on its own.
    """

    def __init__(
        self,
        client: object | None = None,
        *,
        model: str = CLIENT_MODEL,
        api_key: str | None = None,
    ) -> None:
        self._model = model
        self._client: Any
        if client is not None:
            self._client = client
            return
        try:
            from google import genai  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover -- exercised only without the dep
            raise BreakdownUnavailable(
                "google-genai is not installed; run `uv add google-genai` to use the "
                "live breakdown agent, or inject an agent for offline use"
            ) from exc
        key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise BreakdownUnavailable(
                "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set; the live breakdown agent "
                "needs a key, or inject an agent for offline use"
            )
        self._client = genai.Client(api_key=key)

    def extract(self, document: bytes, *, media: str) -> tuple[RawScene, ...]:
        """Send the document to Gemini and return its raw reading.

        Raises:
            BreakdownError: Gemini's response was not the JSON array of scenes asked for.
        """
        from google.genai import types  # type: ignore[import-not-found]

        mime = "application/pdf" if media == "pdf" else "text/plain"
        response = self._client.models.generate_content(
            model=self._model,
            contents=[
                _PROMPT,
                types.Part.from_bytes(data=document, mime_type=mime),
            ],
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        return _raw_from_json(response.text)


def _raw_from_json(text: str | None) -> tuple[RawScene, ...]:
    """Parse the agent's JSON array into `RawScene`s, tolerant of missing fields."""
    if not text or not text.strip():
        raise BreakdownError("the breakdown agent returned an empty response")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BreakdownError(f"the breakdown agent returned invalid JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise BreakdownError(
            f"expected a JSON array of scenes, got {type(payload).__name__}"
        )

    scenes: list[RawScene] = []
    for i, item in enumerate(payload):
        if not isinstance(item, dict):
            raise BreakdownError(f"scene[{i}] is {type(item).__name__}, not an object")
        slugline = str(item.get("slugline", "")).strip()
        if not slugline:
            raise BreakdownError(f"scene[{i}] has no slugline")
        number = item.get("scene_number")
        cast = item.get("cast") or ()
        scenes.append(
            RawScene(
                slugline=slugline,
                cast_names=tuple(str(c) for c in cast if str(c).strip()),
                scene_number=str(number) if number not in (None, "") else None,
                page_eighths=item.get("page_eighths")
                if isinstance(item.get("page_eighths"), int)
                else None,
                confidence=_clamp01(item.get("confidence", 1.0)),
                source_page_range=str(item.get("source_page_range", "")),
                stunt=bool(item.get("stunt", False)),
                minors=bool(item.get("minors", False)),
                vfx=bool(item.get("vfx", False)),
            )
        )
    return tuple(scenes)
