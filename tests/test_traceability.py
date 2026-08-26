"""Tests for the specification integrity checks.

The traceability report is only as trustworthy as its ability to read SPEC.md, and
its original failure mode was silence: a row it could not parse was skipped, which
removed the requirement from every report and left no symptom except a total nobody
had memorised. A typo could quietly retire a requirement.

These tests drive the parser with deliberately broken spec fragments. They matter
more than most, because a validator with no tests is exactly the thing that stops
working without anyone noticing.
"""

from __future__ import annotations

import pytest

from traceability import parse_spec

HEADER = "| ID | Requirement | Maturity | Verification | Slice | Notes |\n|---|---|---|---|---|---|\n"
GOOD = "| DAY-001 | Daylight is computed, never retrieved. | unit-built | offline | MVP-0 | ok |\n"


def defects(text: str) -> list[str]:
    return [str(d) for d in parse_spec(text).defects]


def only_defect(text: str) -> str:
    found = parse_spec(text).defects
    assert len(found) == 1, f"expected exactly one defect, got {[str(d) for d in found]}"
    return str(found[0])


# --------------------------------------------------------------------------
# A well-formed spec parses cleanly
# --------------------------------------------------------------------------


@pytest.mark.req("TRC-001")
def test_a_well_formed_requirement_parses_with_no_defects():
    spec = parse_spec(HEADER + GOOD)

    assert not spec.defects
    assert spec.requirements["DAY-001"].maturity == "unit-built"
    assert spec.requirements["DAY-001"].slice == "MVP-0"


@pytest.mark.req("TRC-001")
def test_a_non_negotiable_row_has_its_own_shape():
    spec = parse_spec("| NNG-001 | Search is called at runtime. | Track eligibility. |\n")

    assert not spec.defects
    assert [n.id for n in spec.non_negotiables] == ["NNG-001"]


# --------------------------------------------------------------------------
# Malformed rows are reported, never skipped
# --------------------------------------------------------------------------


@pytest.mark.req("TRC-001")
def test_a_row_with_too_few_cells_is_a_defect_not_a_silent_skip():
    text = HEADER + "| DAY-007 | Horizon obstruction. | not-started | POST |\n"

    assert "malformed requirement row DAY-007" in only_defect(text)
    assert "found 3" in only_defect(text)
    assert "DAY-007" not in parse_spec(text).requirements   # and it did not sneak in


@pytest.mark.req("TRC-001")
def test_a_row_with_too_many_cells_is_a_defect():
    text = HEADER + "| DAY-001 | Stmt. | unit-built | offline | MVP-0 | notes | extra |\n"

    assert "malformed requirement row" in only_defect(text)


@pytest.mark.req("TRC-001")
def test_an_empty_statement_is_a_defect():
    text = HEADER + "|  DAY-001 |  | unit-built | offline | MVP-0 | ok |\n"

    assert "empty statement" in only_defect(text)


@pytest.mark.req("TRC-001")
def test_a_malformed_non_negotiable_is_a_defect():
    assert "malformed non-negotiable row NNG-001" in only_defect("| NNG-001 | Only one cell. |\n")


# --------------------------------------------------------------------------
# Vocabulary -- a typo must not retire a requirement
# --------------------------------------------------------------------------


@pytest.mark.req("TRC-004")
@pytest.mark.parametrize(
    ("cell", "bad", "label"),
    [
        (2, "unit_built", "maturity"),      # underscore instead of hyphen
        (3, "offiline", "verification tier"),
        (4, "MVP-9", "slice"),
    ],
)
def test_a_value_outside_its_vocabulary_is_reported(cell, bad, label):
    cells = ["| DAY-001 ", " Stmt. ", " unit-built ", " offline ", " MVP-0 ", " ok |"]
    cells[cell] = f" {bad} "
    text = HEADER + "|".join(cells) + "\n"

    defect = only_defect(text)
    assert f"unknown {label} {bad!r}" in defect
    assert "expected one of" in defect          # names the legal values
    assert not parse_spec(text).requirements    # and the row is not counted


@pytest.mark.req("TRC-004")
def test_a_defective_row_reports_its_line_number():
    text = "intro\n\n" + HEADER + "| DAY-001 | Stmt. | nonsense | offline | MVP-0 | ok |\n"

    assert only_defect(text).startswith("SPEC.md:5")


@pytest.mark.req("TRC-004")
def test_several_faults_in_one_row_are_all_reported():
    text = HEADER + "| DAY-001 | Stmt. | nope | nope | nope | ok |\n"

    assert len(defects(text)) == 3


# --------------------------------------------------------------------------
# Duplicates
# --------------------------------------------------------------------------


@pytest.mark.req("TRC-002")
def test_a_duplicate_requirement_id_is_reported_with_both_lines():
    text = HEADER + GOOD + "| DAY-001 | A conflicting claim. | not-started | offline | POST | x |\n"

    defect = only_defect(text)
    assert "duplicate requirement id DAY-001" in defect
    assert "first defined at line 3" in defect


@pytest.mark.req("TRC-002")
def test_the_first_definition_wins_so_a_duplicate_cannot_overwrite():
    text = HEADER + GOOD + "| DAY-001 | A conflicting claim. | not-started | offline | POST | x |\n"

    assert parse_spec(text).requirements["DAY-001"].maturity == "unit-built"


@pytest.mark.req("TRC-002")
def test_a_duplicate_use_case_id_is_reported():
    text = HEADER + GOOD + (
        "### UC-01 — First\n**Exercises:** DAY-001\n"
        "### UC-01 — Second\n**Exercises:** DAY-001\n"
    )

    assert "duplicate use case id UC-01" in only_defect(text)


# --------------------------------------------------------------------------
# Use-case references
# --------------------------------------------------------------------------


@pytest.mark.req("TRC-003")
def test_a_use_case_citing_an_unknown_requirement_is_reported():
    text = HEADER + GOOD + "### UC-01 — Journey\n**Exercises:** DAY-001, SOL-999\n"

    assert "UC-01 cites unknown requirement SOL-999" in only_defect(text)


@pytest.mark.req("TRC-003")
def test_a_use_case_citing_a_requirement_that_failed_to_parse_is_reported():
    # The cascade that matters: a typo retires DAY-001, and every journey that
    # depended on it now cites something that does not exist.
    text = HEADER + "| DAY-001 | Stmt. | unit_built | offline | MVP-0 | ok |\n" \
                  + "### UC-01 — Journey\n**Exercises:** DAY-001\n"

    assert any("cites unknown requirement DAY-001" in d for d in defects(text))


@pytest.mark.req("TRC-005")
def test_a_use_case_with_no_exercises_line_is_reported():
    text = HEADER + GOOD + "### UC-01 — Journey with no requirements\n\nsome prose\n"

    assert "UC-01 exercises no requirements" in only_defect(text)


@pytest.mark.req("TRC-005")
def test_a_second_exercises_line_is_reported():
    text = HEADER + GOOD + "### UC-01 — Journey\n**Exercises:** DAY-001\n**Exercises:** DAY-001\n"

    assert "more than one Exercises line" in only_defect(text)


# --------------------------------------------------------------------------
# The real document
# --------------------------------------------------------------------------


@pytest.mark.req("TRC-006")
def test_the_committed_spec_has_no_defects():
    import pathlib

    spec = parse_spec((pathlib.Path(__file__).parent.parent / "SPEC.md").read_text())

    assert [str(d) for d in spec.defects] == []
    assert len(spec.requirements) > 100
    assert spec.non_negotiables
    assert spec.use_cases
