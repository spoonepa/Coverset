"""Breakdown against real screenplays -- the `corpus` tier.

Deselected by default. Runs with:

    uv run pytest -m corpus

What this tier is for, and what it is not for:

A downloaded screenplay arrives with no breakdown. Nobody has written down that scene
14 is INT, plays DAY, runs 6/8 of a page and calls two performers. So nothing here can
assert that breakdown output is *right* -- checking the parser's reading against your
own reading of the same script is validating a method against itself, and this project
has a documented history of well-formed, type-correct, plausible, wrong values.

Correctness belongs to the authored screenplay, where the scene list was written first
and the pages written to match, so the answer key exists by construction (`BRK-009`).

What real scripts do prove is that the parser survives formatting nobody designed a
fixture around: dual dialogue, `CONT'D`, montages, `OMITTED` scenes, and four
different scene-numbering conventions. That is robustness, invariants and stability,
and it is exactly what an authored fixture cannot give you.

With no sources configured the tier skips and says so. It never passes empty.
"""

from __future__ import annotations

import pytest

from corpus import CorpusUnavailable, ensure_local, load_sources

pytestmark = pytest.mark.corpus

SOURCES = load_sources()


def _document(source):
    """Local bytes for a source, or a skip naming why the tier could not run."""
    try:
        return ensure_local(source).read_bytes()
    except CorpusUnavailable as exc:
        # Reported, never green. An FYC posting coming down is the normal end of its
        # life, and the tier has to say "did not check this" rather than "checked it".
        pytest.skip(f"corpus source unavailable: {exc}")


@pytest.mark.skipif(not SOURCES, reason="no corpus sources configured -- see fixtures/corpus/sources.toml")
@pytest.mark.req("BRK-008")
@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.id)
def test_the_document_is_what_the_corpus_recorded(source):
    """The precondition every other test in this file rests on."""
    assert _document(source), f"{source.id}: fetched an empty document"


@pytest.mark.skipif(not SOURCES, reason="no corpus sources configured -- see fixtures/corpus/sources.toml")
@pytest.mark.req("BRK-001", "BRK-009")
@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.id)
def test_breakdown_output_holds_its_invariants(source):
    """Real formatting in, well-formed candidate records out -- or a named failure.

    Deliberately says nothing about whether the records describe the film correctly.
    """
    breakdown = pytest.importorskip(
        "coverset.breakdown", reason="BRK-001 not implemented yet"
    )
    records = breakdown.parse(_document(source), media=source.media)

    assert records, f"{source.id}: parsed to no scenes at all"

    from coverset.scenes import CandidateStatus
    from coverset.work import DayNight

    for record in records:
        where = f"{source.id} scene {record.scene_number!r}"
        assert record.page_eighths > 0, f"{where}: page eighths must be positive"
        assert record.day_night in set(DayNight), f"{where}: {record.day_night!r} is not a day/night value"
        assert record.slugline.strip(), f"{where}: empty slugline"
        assert record.status is not CandidateStatus.ACTIVE, (
            f"{where}: a parsed record must arrive as a candidate. Only a human "
            f"activates, and an active record converts straight to solver work."
        )

    numbers = [r.scene_number for r in records]
    assert len(numbers) == len(set(numbers)), f"{source.id}: duplicate scene numbers"


@pytest.mark.skipif(not SOURCES, reason="no corpus sources configured -- see fixtures/corpus/sources.toml")
@pytest.mark.req("BRK-004")
@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.id)
def test_unknown_cast_is_reported_rather_than_invented(source):
    """A real script names people no roster has heard of, which is the point.

    The failure being guarded against is a parser that quietly maps an unrecognised
    name onto the nearest roster id -- the `SARA`/`SARAH` bug, arriving by a new road.
    Unresolved has to stay unresolved and block the board.
    """
    breakdown = pytest.importorskip(
        "coverset.breakdown", reason="BRK-001 not implemented yet"
    )
    from coverset.people import Roster

    result = breakdown.resolve_cast(
        breakdown.parse(_document(source), media=source.media), roster=Roster()
    )
    assert result.unresolved, (
        f"{source.id}: an empty roster resolved every name in a real screenplay, "
        f"which means names are being invented rather than resolved"
    )
    assert not result.records_ready_for_solver


@pytest.mark.skipif(not SOURCES, reason="no corpus sources configured -- see fixtures/corpus/sources.toml")
@pytest.mark.req("BRK-012")
@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.id)
def test_the_same_document_parses_the_same_way_twice(source):
    """Non-determinism in breakdown is a bug that hides as a difference of opinion.

    A model-backed parser can return a different reading on each call. If it does,
    every downstream comparison -- did the schedule change because the script changed,
    or because the parser felt differently? -- becomes unanswerable.
    """
    breakdown = pytest.importorskip(
        "coverset.breakdown", reason="BRK-001 not implemented yet"
    )
    document = _document(source)

    first = breakdown.parse(document, media=source.media)
    second = breakdown.parse(document, media=source.media)

    assert [r.scene_number for r in first] == [r.scene_number for r in second], (
        f"{source.id}: two parses of one document disagree on the scene list"
    )
    assert [(r.int_ext, r.day_night) for r in first] == [
        (r.int_ext, r.day_night) for r in second
    ], f"{source.id}: two parses of one document disagree on INT/EXT or day/night"
