# Coverset — Specification

Requirements derived from `PROJECT_BRIEF.md`. The brief says *why*; this says *what
must be true*, in statements narrow enough to test.

Every requirement has a stable ID. Tests declare which requirements they verify with
`@pytest.mark.req("GRD-003")`, and `scripts/traceability.py` derives the matrix from
the test suite itself rather than from a hand-maintained table. A requirement with no
test is a reported gap, not a silent one.

## Status vocabulary

| Status | Meaning |
|---|---|
| `built` | Implemented and covered by at least one test |
| `partial` | Partly implemented, or implemented without full coverage |
| `planned` | Specified, not yet built |

## Verification tiers

Offline tests prove the wiring. They cannot prove the world agrees — every finding in
the brief's *Findings and learnings* came from a live run against fixtures that
encoded assumptions rather than reality. So external-facing requirements carry both:

| Tier | Command | Proves |
|---|---|---|
| Offline | `uv run pytest` | Wiring, shape, invariants. Deterministic, no network, no key. |
| Live | `uv run pytest -m live` | The external world behaves as assumed. Needs `PARALLEL_API_KEY`. |

A requirement that depends on an external service and has **no live test** is
under-verified even at 100% offline coverage. `scripts/traceability.py` reports this
separately.

---

## TRK — Track eligibility

Non-negotiable. Decided 26 Aug 2026, per the brief.

| ID | Requirement | Status |
|---|---|---|
| TRK-001 | Parallel Search is called at runtime for every externally-grounded fact request. No cache, precomputed fact table, or offline fallback may stand in for it. | `built` |
| TRK-002 | Parallel Extract retrieves full page contents where excerpt compression would discard the operative value. | `built` |
| TRK-003 | Parallel Monitor watches the sources a live schedule depends on and emits change events. | `planned` |

## GRD — Grounding

| ID | Requirement | Status |
|---|---|---|
| GRD-001 | Evidence carries the URL of every source behind it and cannot be constructed without at least one. | `built` |
| GRD-002 | A fact with no source raises rather than returning empty evidence or a default value. | `built` |
| GRD-003 | A date-specific fact must prove at least one source explicitly mentions the target date before any value may be bound to that date. | `built` |
| GRD-004 | A fact family whose rules are date-independent is exempt from GRD-003 and is not rejected for omitting the date. | `built` |
| GRD-005 | Permit retrieval is restricted to authoritative domains by default and is overridable per production. | `built` |
| GRD-006 | Weather retrieval excludes sources published before the forecast horizon. | `built` |
| GRD-007 | Extract failure degrades to excerpts and is reported as such, never silently presented as full content. | `built` |
| GRD-008 | Search and Extract calls within one replan share a Parallel session. | `built` |
| GRD-009 | Weekday-only labels are not accepted as evidence of date coverage. | `built` |
| GRD-010 | Weather distinguishes a near-term forecast with predictive skill from long-range climatology presented as forecast. | `planned` |
| GRD-011 | The search request declares the consuming model and geo-targets the location's country. | `built` |

## DAY — Daylight

| ID | Requirement | Status |
|---|---|---|
| DAY-001 | Daylight is computed from coordinates and date, never retrieved. | `built` |
| DAY-002 | Computed times agree with published almanac tables to within 2 minutes. | `built` |
| DAY-003 | Times are timezone-aware and DST-correct for the date in question. | `built` |
| DAY-004 | A window violating chronological invariants raises rather than being returned. | `built` |
| DAY-005 | Latitudes where the sun does not rise or set are reported as such, not crashed on. | `built` |
| DAY-006 | Coordinates without a timezone are rejected at construction. | `built` |
| DAY-007 | Horizon obstruction at a location can override astronomical sunset. | `planned` |

## BRK — Script breakdown

| ID | Requirement | Status |
|---|---|---|
| BRK-001 | A screenplay PDF is parsed into structured scene records: scene number, INT/EXT, day/night, location, page eighths, and cast present. | `planned` |
| BRK-002 | Scenes carry flags for stunts, minors, and VFX. | `planned` |

## CON — Constraint translation

| ID | Requirement | Status |
|---|---|---|
| CON-001 | Plain-English production constraints are translated into typed constraint records. | `planned` |
| CON-002 | A typed constraint derived from retrieved text is validated against known-good values rather than trusted. | `planned` |
| CON-003 | Extraction may bind a dated value only from a source that satisfies GRD-003. | `planned` |

## SOL — Solver

| ID | Requirement | Status |
|---|---|---|
| SOL-001 | The schedule is produced by CP-SAT. No language model emits a schedule. | `planned` |
| SOL-002 | Every board returned provably satisfies its constraint set. | `planned` |
| SOL-003 | When no valid schedule exists, the minimal conflicting constraint set is returned. | `planned` |
| SOL-004 | Days already shot are immutable across replans. | `planned` |
| SOL-005 | The objective minimises company moves, cast holding days, and overtime exposure. | `planned` |
| SOL-006 | Five constraint families are modelled: cast availability, location and permit windows, daylight matching, turnaround, company moves. | `planned` |

## MON — Monitoring and replanning

| ID | Requirement | Status |
|---|---|---|
| MON-001 | A change in a monitored source triggers replanning with no user action. | `planned` |
| MON-002 | Replanning returns multiple viable boards, each with its cost stated in production terms rather than solver terms. | `planned` |

## OUT — Outputs

| ID | Requirement | Status |
|---|---|---|
| OUT-001 | A call sheet is generated for a scheduled day. | `planned` |
| OUT-002 | Two schedule versions can be diffed with the delta quantified. | `planned` |

## REV — Coverage review and human decision

Gemini may flag a coverage item as needing attention. It may not decide the outcome.
The boundary is enforced structurally rather than by convention, for the same reason
the solver rather than a model produces the board.

| ID | Requirement | Status |
|---|---|---|
| REV-001 | A review finding is advisory. The only status transition a finding can cause is to *needs review*; it cannot accept, reject, or request a pickup. | `built` |
| REV-002 | A flagged coverage item is marked *needs review* and carries the finding that flagged it. | `built` |
| REV-003 | Only a decision attributed to a named human can accept, reject, or request a pickup. An automated agent is rejected as the decider. | `built` |
| REV-004 | A decision records who made it, when, and which finding it responds to. | `built` |
| REV-005 | An accepted item produces no pickup work. | `built` |
| REV-006 | A decision may only be applied to an item awaiting review. | `built` |
| REV-007 | An item cannot be flagged for review before it has been shot. | `built` |
| REV-008 | A finding may be raised by a human as well as by Gemini. | `planned` |

## PIK — Pickups and re-shoots

| ID | Requirement | Status |
|---|---|---|
| PIK-001 | A pickup task cannot be constructed without a human decision authorising it. | `built` |
| PIK-002 | A pickup task traces to the decision that authorised it and the finding that prompted it. | `built` |
| PIK-003 | A rejection or pickup request yields exactly one pickup task. | `built` |
| PIK-004 | A pickup task carries the scene, coverage type, cast, location and duration the solver needs to place it. | `built` |
| PIK-005 | Replanning admits a pickup task as required work while preserving cast, location, daylight, permit and weather constraints. | `planned` |
| PIK-006 | Replanning with a pickup treats already-shot days as immutable (see SOL-004). | `planned` |
| PIK-007 | Each revised board states the disruption cost of accommodating the pickup in production terms rather than solver terms. | `planned` |

## AUD — Auditability

Cross-cutting. This is the brief's central claim, so it is specified rather than assumed.

| ID | Requirement | Status |
|---|---|---|
| AUD-001 | Every scheduling decision traces to an explicit constraint and an explicit objective term. | `planned` |
| AUD-002 | Every constraint traces to either a source URL or a named deterministic algorithm. | `partial` |
| AUD-003 | A constraint records whether it was derived from full page content or from excerpts, so downstream confidence can reflect it. | `built` |
| AUD-004 | Every pickup task traces to a named human decision. No automated process can create shoot work. | `built` |
