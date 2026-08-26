"""Who may do what.

The architecture is a statement about authority. Gemini advises, a human decides,
CP-SAT schedules — and among humans the authority is scoped, because a Director
ruling that coverage is unusable and a UPM ruling that the production can afford
another day are different judgements made by different people.

Authority is typed rather than checked. `Role` enumerates human production roles and
nothing else, so an advisory agent cannot be constructed as a deciding actor — there
is no enum member for it. That is a stronger guarantee than a name blocklist, which
only catches the names someone thought of. The blocklist survives underneath as a
second line, for the case where an agent's *name* is passed into a human role.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = ["ADVISORY_AGENTS", "Actor", "AuthorityError", "Role"]

ADVISORY_AGENTS = frozenset(
    {"gemini", "coverset", "system", "auto", "automatic", "agent", "ai", "model", "bot"}
)
"""Names that may not be given to a human actor.

Second line of defence. `Role` already makes an agent unconstructible as a decider;
this catches code that passes an agent's name into a legitimate human role.
"""


class AuthorityError(Exception):
    """An actor was asked to do something their role does not permit."""


class Role(StrEnum):
    """Human production roles. Deliberately has no member for an automated agent."""

    FIRST_AD = "first_ad"
    DIRECTOR = "director"
    SCRIPT_SUPERVISOR = "script_supervisor"
    UPM = "upm"
    SECOND_AD = "second_ad"


@dataclass(frozen=True, slots=True)
class Actor:
    """A named person acting in a production role."""

    name: str
    role: Role

    def __post_init__(self) -> None:
        who = self.name.strip()
        if not who:
            raise AuthorityError(
                "an actor must be named -- an unattributed decision cannot be "
                "audited back to a person"
            )
        if who.casefold() in ADVISORY_AGENTS:
            raise AuthorityError(
                f"{self.name!r} is an advisory agent and cannot act in the role "
                f"{self.role}. Gemini flags; a person decides."
            )

    def __str__(self) -> str:
        return f"{self.name} ({self.role.replace('_', ' ')})"

    # -- scoped authority --------------------------------------------------

    @property
    def may_rule_on_coverage(self) -> bool:
        """Accept, reject, or order a pickup. A creative judgement."""
        return self.role in (Role.DIRECTOR, Role.FIRST_AD)

    @property
    def may_raise_finding(self) -> bool:
        """Flag coverage for review from the floor, as Gemini also may."""
        return self.role in (Role.SCRIPT_SUPERVISOR, Role.DIRECTOR, Role.FIRST_AD)

    @property
    def may_select_board(self) -> bool:
        """Choose among the boards a replan produced. The First AD owns the board."""
        return self.role is Role.FIRST_AD

    @property
    def may_lock_day(self) -> bool:
        """Record a day as shot, making it immutable to later replans."""
        return self.role in (Role.FIRST_AD, Role.SCRIPT_SUPERVISOR)

    @property
    def may_approve_cost(self) -> bool:
        """Authorise work that adds a shoot day."""
        return self.role in (Role.UPM,)

    def require(self, capability: str) -> None:
        """Raise unless this actor holds `capability`, naming the role that does.

        Used at the point of action so the failure names the person and the
        authority they lack, rather than surfacing as a generic permission error.
        """
        attr = f"may_{capability}"
        if not hasattr(self, attr):
            raise ValueError(f"unknown capability {capability!r}")
        if not getattr(self, attr):
            holders = [r for r in Role if getattr(Actor("check", r), attr)]
            raise AuthorityError(
                f"{self} may not {capability.replace('_', ' ')}; "
                f"that is held by {', '.join(str(r) for r in holders)}"
            )
