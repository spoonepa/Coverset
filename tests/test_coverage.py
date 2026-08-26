"""Tests for explicit-date detection.

These encode the rule that decides whether a retrieved page may be used to bind a
value to a shoot date. The negatives matter more than the positives: `September 11`
must not satisfy a query for September 1, and a weekday label must not satisfy
anything, because both failures are silent.
"""

from __future__ import annotations

import datetime as dt

import pytest

from coverset.grounding.coverage import covers_date

SHOOT_DATE = dt.date(2026, 9, 1)


@pytest.mark.req("GRD-003")
@pytest.mark.parametrize(
    "text",
    [
        "### Tue, Sep 1",
        "Wed 9/1",
        "September 1st, 2026",
        "September 01",
        "2026-09-01",
        "1 September",
        "09/01/2026",
        "Sept 1",
        "Monday September 1, 2026",
    ],
)
def test_explicit_date_forms_are_recognised(text):
    assert covers_date(text, SHOOT_DATE)


@pytest.mark.req("GRD-003")
@pytest.mark.parametrize(
    "text",
    [
        "### Tue, Aug 25",       # a different day
        "Wed 8/26",              # today, not the target
        "September 11",          # adjacent day number
        "September 10",
        "9/15",
        "19/12",                 # must not match on a substring
        "sunset 8:02 pm",        # plausible value, no date at all
        "",
    ],
)
def test_text_about_another_day_is_not_accepted(text):
    assert not covers_date(text, SHOOT_DATE)


@pytest.mark.req("GRD-009")
@pytest.mark.parametrize(
    "text",
    [
        "Tuesday: Showers and thunderstorms likely, mainly after 5pm.",
        "* Tuesday",
        "Tue",
    ],
)
def test_weekday_labels_alone_are_not_date_evidence(text):
    # Unambiguous inside a seven-day forecast and silently wrong outside one.
    # A shooting schedule routinely reaches further out than that.
    assert not covers_date(text, SHOOT_DATE)
