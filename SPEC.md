# Coverset — Specification

`PROJECT_BRIEF.md` is the product narrative and says *why*. This document is the
implementation contract: what must be true, what data crosses each boundary, how it is
verified, and which parts are in the active demo path.

Every requirement has a stable ID. Tests declare what they verify with
`@pytest.mark.req("GRD-003")`, and `scripts/traceability.py` derives the matrix from the
suite itself rather than from a hand-maintained table, so it cannot drift into
reassurance. A requirement claiming implementation with no test is a reported gap and a
non-zero exit, as is a test citing an ID that does not exist here.

The central design is unchanged:

- **Gemini interprets** screenplays, constraints, and coverage.
- **Parallel grounds** mutable external facts at runtime.
- **Humans decide** where judgment or production authority is required.
- **OR-Tools CP-SAT schedules**; no language model emits a board.

---

## 1. Non-negotiables

| ID | Contract | Rationale |
|---|---|---|
| NNG-001 | Parallel Search is called at runtime for every externally grounded fact request. No cache, precomputed fact table, fixture, or offline fallback may stand in for Search in production runtime. | Track eligibility and grounding integrity. |
| NNG-002 | Gemini and other advisory agents may produce candidate records, findings, summaries, and explanations; they may not decide coverage, approve costs, select boards, or emit schedules. | Keeps advisory and deciding authority separate. |
| NNG-003 | A returned active schedule is produced by CP-SAT and independently validated against the active hard constraints. | Solver output alone is not enough proof if the model was miscompiled or underspecified. |
| NNG-004 | A mutable external fact can affect a board only through a typed, provenance-bearing, validated value. A URL alone is not a bound. | Prevents plausible-but-wrong bindings. |
| NNG-005 | Days already shot are immutable. Replans can reference them as constraints but cannot rewrite history. | Production reality cannot be rescheduled. |

---

## 2. Status, scope, and verification vocabulary

### Implementation maturity

| Maturity | Meaning |
|---|---|
| `not-started` | No meaningful implementation exists. |
| `domain-model` | Types/entities exist and enforce local invariants, but are not integrated into the full workflow. |
| `unit-built` | Behavior is implemented and covered by deterministic tests. |
| `integrated` | Behavior participates in a cross-module workflow. |
| `demo-ready` | Behavior is usable in the active demo path and has the required verification tier. |

### Verification tier

| Tier | Command / Evidence | Proves |
|---|---|---|
| `none` | No accepted verification yet. | Nothing. |
| `offline` | `uv run pytest` | Deterministic wiring, shape, invariants; no network/key. |
| `live` | `uv run pytest -m live` | Real provider behavior and fact-binding invariants. Requires `PARALLEL_API_KEY`. |
| `manual-demo` | Recorded/manual demo script plus artifacts. | End-to-end product journey where automated checking is not yet enough. |

### Active slices

| Slice | Purpose | Required outcome |
|---|---|---|
| `MVP-0` | Deterministic board from structured fixtures. | Produce a valid stripboard from pre-parsed scenes and typed constraints. |
| `MVP-1` | Grounded constraints. | Parallel Search/Extract feeds typed permit/weather records into constraints or risk policy. |
| `MVP-2` | Replan with locked history. | Re-solve after one changed fact while preserving already-shot days. |
| `MVP-3` | Human review to pickup to replan. | Coverage finding + human decision creates pickup work and revised options. |
| `POST` | Full productionization. | Monitor automation, union libraries, imports/exports, full call-sheet integration, multi-unit. |

### Requirement table columns

Requirement tables use:

| Column | Meaning |
|---|---|
| `ID` | Stable identifier used by tests and traceability. Existing IDs are preserved where possible. |
| `Requirement` | Testable statement. |
| `Maturity` | Implementation maturity from the vocabulary above. |
| `Verification` | Highest required verification tier. |
| `Slice` | Earliest slice where this requirement matters. |
| `Notes` | Implemented/missing details, partial scope, or design constraints. |

A use case is deliverable only when every exercised requirement is at least
`demo-ready` for the active slice, or is explicitly waived for that slice. `partial`
work from the original spec maps to `domain-model` or `unit-built`, but it is not a
finished use-case capability by itself.

---

## 3. MVP / demo scope

### MVP-0 — Deterministic board from structured inputs

MVP-0 deliberately bypasses Gemini PDF parsing and plain-English constraint translation.
It accepts structured fixture data and proves the central scheduling contract:

- scenes/work items exist;
- typed constraints exist;
- CP-SAT produces one or more valid boards;
- every returned board satisfies hard constraints;
- the board is readable in production terms.

Required MVP-0 capabilities:

- `SceneRecord` fixture import and validation.
- `ConstraintRecord` fixture import and validation.
- `ScheduleProblem` creation.
- CP-SAT solve for cast availability, location windows, daylight/day-night feasibility,
  turnaround, and company-move minimization.
- Independent board validation.
- Stripboard output.

### MVP-1 — Runtime grounding to typed facts

MVP-1 connects the existing Parallel grounding foundation to active scheduling inputs:

- runtime Search is mandatory;
- Extract is used when excerpts are insufficient;
- evidence is promoted to typed values only with value-level provenance;
- weather is classified by production policy before it affects scheduling.

### MVP-2 — Replan with locked days

MVP-2 proves the product's distinctive scheduling loop without full autonomous Monitor:

- a changed typed fact generates a `ReplanRequest`;
- days already shot are represented as `LockedDayRecord` constraints;
- revised boards do not mutate locked days;
- options state cost deltas in production terms.

### MVP-3 — Coverage review to pickup replan

MVP-3 extends the existing review/pickup authority model into the solver:

- advisory finding marks coverage as needing review;
- human decision authorizes pickup intent;
- human-confirmed pickup spec becomes required work;
- replan includes pickup work and preserves original constraints;
- extra shoot days remain pending cost approval until approved.

### Post-MVP

- Full screenplay PDF parsing through Gemini.
- Full plain-English constraint translation through Gemini.
- Parallel Monitor API subscriptions and callbacks.
- Production call sheets and distribution.
- Union and jurisdictional rule libraries.
- Multi-unit, split-day, equipment continuity, accounting integrations, import/export.

---

## 4. Constraint policy vocabulary

The solver receives constraints and objective terms with an explicit policy.

| Policy | Meaning | May an active board violate it? | Typical examples |
|---|---|---:|---|
| `hard` | Feasibility bound. | No. | permit unavailability, cast unavailable, child-labor legal limit, already-shot immutability. |
| `soft_penalty` | Cost/risk term optimized and surfaced. | Yes, as cost/exposure, not as hidden failure. | holding days, company moves, overtime exposure when allowed. |
| `waivable_by_role` | Bound that can be relaxed only through named approval. | Not while active; only as pending exception scenario. | waivable turnaround exception, added shoot day requiring UPM/Line Producer approval. |
| `objective_only` | Ranking term, not feasibility. | N/A. | minimizing company moves or holding days. |
| `informational` | Display/alert only. | N/A. | long-range climatology risk. |

Returned `viable_boards` must satisfy all active `hard` constraints and all unwaived
`waivable_by_role` constraints. If Coverset surfaces a schedule-like option that would
relax a constraint, it must be emitted separately as an `ExceptionScenario`, listing:

- violated/relaxed constraint IDs;
- production consequence;
- required approving role;
- activation status;
- whether re-solving is required after approval.

Exception scenarios are not active schedules until approved and validated.

---

## 5. Core domain model

These contracts make the requirement families implementable and testable. Field names
are normative even if the eventual Python names use idiomatic variants.

### 5.1 Actors and authority

The architecture is fundamentally a statement about authority: who may advise, who may
decide, and what may put work on a board.

| Actor class | May advise | May decide | May schedule |
|---|:---:|:---:|:---:|
| Gemini agents (breakdown, constraint, review) | yes | **no** | no |
| Parallel (Search, Extract) | supplies facts | no | no |
| Monitor loop | may trigger a replan | **no** | no |
| Human roles | yes | **yes, scoped by role** | no |
| CP-SAT solver | no | no | **yes** |

#### Human actors

| Role | Uses Coverset to | Authority |
|---|---|---|
| **First AD** | Own the board: supply constraints, choose among replan options, lock shot days, diagnose infeasibility | Scheduling decisions; board selection |
| **Director** | Review flagged coverage and rule on it | Creative acceptance of coverage |
| **Script Supervisor** | Raise coverage findings from the floor; record what was actually shot | Raise findings; record shot status |
| **UPM / Line Producer** | See what each option costs; approve work that adds a shoot day | Cost approval |
| **Second AD** | Generate and distribute call sheets | None over the schedule |

#### System actors

| Actor | Role | Boundary |
|---|---|---|
| **Breakdown agent** (Gemini) | Screenplay PDF to candidate scene records | Extractive; produces no schedule |
| **Constraint agent** (Gemini) | Plain English plus retrieved facts to candidate constraints | Advisory; candidates require validation |
| **Review agent** (Gemini) | Coverage to review findings | Advisory only; cannot decide an outcome |
| **Grounding service** (Parallel) | Search and Extract | Supplies facts; never interprets them |
| **Monitor loop** (Parallel Monitor) | Detects a changed fact, raises a replan request | Triggers only; never selects a board |
| **Solver** (CP-SAT) | Produces solver board proposals | The only component that may construct schedules; proposals become viable boards only after validation |

The Monitor boundary is the easiest one to lose. The brief's line is *"nobody presses
replan"* — the world changed and the agent acted. But acting means **generating
options**, not choosing among them. The First AD still picks. That is ACT-007, and
without this paragraph the rule looks like ceremony that could be simplified away.

#### Recipients and constraint sources

Cast and crew hold no authority over the schedule, but they are not outside the system
either, and the distinction is worth drawing precisely — most of the constraint set is
*about* them.

- **Recipients.** Cast and crew receive call sheets. That is a real interaction with the
  system, even though it is read-only and confers no authority (OUT-006, ACT-010).
- **Domain entities.** Availability windows, contracted day minimums, holding-day cost,
  turnaround and restricted hours for minors are constraint families in `CST`. They are
  modelled as typed entities, not names on a scene.

Location owners and permit authorities are different again: they neither operate
Coverset nor receive anything from it. Their rules reach the solver only through the
grounding path, as retrieved facts — which is why permits are a `GRD`/`CON` concern and
never an actor concern.

What none of them do is *decide*. That is the sense in which they are not actors, and
it is the only sense.

```text
Actor
- name: non-empty string
- role: Role

Role
- FIRST_AD
- DIRECTOR
- SCRIPT_SUPERVISOR
- UPM_OR_LINE_PRODUCER
- SECOND_AD
```

`UPM_OR_LINE_PRODUCER` represents the cost-approval authority for the demo. A later
production system may split UPM and Line Producer into separate roles, but the authority
boundary is the same: this role can approve costs and added shoot days, not select a
creative/scheduling board.

### 5.2 Scene and work records

```text
SceneRecord
- scene_id: stable string
- scene_number: screenplay scene number/string
- slugline: original heading
- int_ext: INT | EXT | INT_EXT | UNKNOWN
- day_night: DAY | NIGHT | DAWN | DUSK | UNKNOWN
- location_ref: location id or unresolved candidate
- page_eighths: positive integer eighth count
- cast_ids: tuple of cast ids
- flags:
  - stunts: bool
  - minors: bool
  - vfx: bool
- source_page_range: page span or script offset
- confidence: 0.0..1.0 for LLM-derived records
- candidate_status: candidate | active | rejected | needs_review
```

```text
WorkItem
- work_id: stable string
- kind: scene | pickup
- scene_id: string
- location_id: string
- cast_ids: tuple
- estimated_duration_minutes: positive integer
- day_night: DAY | NIGHT | DAWN | DUSK
- flags: stunts/minors/vfx
- must_complete_by: optional date
- source_record_id: SceneRecord or PickupTask id
```

### 5.3 Locations, cast, and production calendar

```text
Location
- location_id
- name
- city/country
- coordinates: lat/lon when daylight is needed
- timezone
```

```text
CastMember
- cast_id
- performer_name
- character_name
- availability_windows
- contracted_day_minimum
- holding_day_cost
- is_minor
- max_work_minutes_per_day when restricted
- turnaround_minutes
```

```text
ProductionCalendar
- shoot_start
- shoot_end
- shoot_days
- dark_days
- default_crew_turnaround_minutes
- default_max_work_minutes
```

### 5.4 Evidence and grounded values

```text
Evidence
- evidence_id
- kind: weather | permit | other
- query
- parallel_session_id
- search_response_id
- extract_response_ids
- retrieved_at
- sources: SourceExcerpt[]
- covering_source_urls
```

```text
SourceExcerpt
- url
- title
- published_at or effective_at when available
- excerpt
- full_content optional
- content_hash
- retrieval_mode: search_excerpt | extracted_full_content
```

```text
GroundedValue
- value_id
- fact_kind
- normalized_value
- units
- valid_for_date or date_range
- source_url
- source_span_or_table_row
- source_content_hash
- retrieved_at
- provider_response_id
- evidence_id
- validator_result
```

A source URL alone is insufficient provenance for a grounded value.

### 5.5 Constraint records

```text
ConstraintRecord
- constraint_id
- family: cast | location | permit | daylight | turnaround | company_move | weather | lock | budget
- policy: hard | soft_penalty | waivable_by_role | objective_only | informational
- subject: cast/location/work/day/schedule reference
- expression: typed value/window/rule
- source:
  - grounded_value_id, evidence_id and source_urls; or
  - algorithm name/version; or
  - human-entered production rule
- derived_from: full_content | excerpt | algorithm | human_input | fixture
- validated_against
- created_by: Actor or system component
- active: bool
```

### 5.6 Schedule problem and board output

```text
ScheduleProblem
- problem_id
- production_calendar
- work_items
- constraints
- objective_terms
- locked_days
- created_at
- constraint_snapshot_hash
```

```text
Assignment
- work_id
- shoot_day
- sequence
- location_id
- planned_call_time
- planned_wrap_time
```

```text
LockedDayRecord
- shoot_day
- schedule_version_id
- assignments
- actual_shot_status
- location_ids
- cast_ids
- call_sheet_version
- actual_call_time
- actual_wrap_time
- recorded_by
- recorded_at
```

```text
Board
- board_id
- schedule_version_id
- assignments
- objective_breakdown
- required_approvals
- constraint_snapshot_hash
- solver_status
- solver_objective_value
- validation_result
```

```text
SolveResult
- status: optimal | feasible | infeasible | unknown | error
- viable_boards
- exception_scenarios
- conflict_set when infeasible
- diagnostics
```

No board may be returned as viable unless `status` is `optimal` or `feasible` and
`validation_result` passes.

---

## 6. ACT — Actors and authority

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| ACT-001 | Every decision that changes the schedule records the actor who made it and the role they made it under. | domain-model | offline | MVP-2 | Existing actor model exists; board/cost decision records still needed. |
| ACT-002 | An advisory agent cannot be constructed as a deciding actor. Deciding requires a human role. | unit-built | offline | MVP-0 | Existing tests cover advisory names/roles. |
| ACT-003 | Ruling on coverage requires Director or First AD authority. | unit-built | offline | MVP-3 | Existing review tests cover this. |
| ACT-004 | Selecting a board among replan options requires First AD authority and creates a `BoardSelection` audit record. | domain-model | offline | MVP-2 | Existing role capability exists; selection record/action missing. |
| ACT-005 | Any board or pickup path that adds a shoot day remains pending until cost approval is recorded by UPM/Line Producer authority. | domain-model | offline | MVP-3 | Existing UPM capability exists; approval workflow missing. |
| ACT-006 | The Script Supervisor may raise findings and record what was shot, and may not rule on coverage. | unit-built | offline | MVP-3 | Existing tests cover authority. |
| ACT-007 | The monitor loop may trigger a replan request and may not select among resulting boards. | not-started | offline | POST | Monitor automation post-MVP; manual changed-fact trigger used in MVP-2. |
| ACT-008 | A `CostApproval` records approver, role, cost delta, added shoot days, approval/rejection, and timestamp. | not-started | offline | MVP-3 | New explicit approval artifact. |
| ACT-009 | A `BoardSelection` records First AD, selected option, prior schedule version, new schedule version, and timestamp. | not-started | offline | MVP-2 | New explicit selection artifact. |
| ACT-010 | Cast, crew, location owners and permit authorities are recipients or constraint sources, never deciding actors. No `Role` exists for them, so they cannot be constructed as one. | unit-built | offline | MVP-0 | Enforced structurally by the `Role` enum; guards against re-introducing them as users. |

---

## 7. CST — Cast and crew

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| CST-001 | Cast members are typed entities carrying availability, contract, and status, not bare names on a scene. | unit-built | offline | MVP-0 | Existing model/tests. |
| CST-002 | A cast id that is not on the roster is rejected, reporting every unknown id at once rather than the first. | unit-built | offline | MVP-0 | Existing model/tests. |
| CST-003 | A cast member with no stated availability is available for the whole shoot. | unit-built | offline | MVP-0 | Existing model/tests. |
| CST-004 | A performer held between first and last work day accrues holding days paid whether worked or not. | unit-built | offline | MVP-0 | Existing model/tests; must be integrated into objective breakdown. |
| CST-005 | Billable days are the greater of engagement span and contracted guarantee. | unit-built | offline | MVP-0 | Existing model/tests. |
| CST-006 | A minor carries a restricted maximum working day. | unit-built | offline | MVP-0 | Existing model/tests; legal libraries post-MVP. |
| CST-007 | Minimum turnaround between wrap and next call is modeled for cast individually and crew as a unit. | unit-built | offline | MVP-0 | Existing cast/company model; solver integration missing. |
| CST-008 | Union agreements and jurisdiction-specific child-labor limits are pluggable constraint libraries. Defaults are illustrative production norms, not authority. | not-started | offline | POST | Keep out of MVP. |
| CST-009 | Any scene/work item referencing cast validates all cast IDs against the active roster before solving. | not-started | offline | MVP-0 | Existing coverage path validates cast IDs, but solver work-item validation is not implemented. |
| CST-010 | A cast availability or minor-work constraint compiled into CP-SAT is also independently evaluable against a returned board. | not-started | offline | MVP-0 | Needed for independent validation. |

---

## 8. SCN / BRK — Scenes and screenplay breakdown

MVP-0 accepts structured scene fixtures. Gemini PDF parsing is post-MVP unless time
permits; Gemini-derived records are candidates until accepted.

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| SCN-001 | A `SceneRecord` has stable id, scene number, slugline, INT/EXT enum, day/night enum, location reference, page eighths, cast IDs, flags, and source span. | not-started | offline | MVP-0 | New schema requirement. |
| SCN-002 | Scene fixture import rejects missing required fields, invalid enum values, non-positive page eighths, and unknown cast/location references. | not-started | offline | MVP-0 | Enables deterministic solver fixtures. |
| SCN-003 | A valid active `SceneRecord` can be converted to a schedulable `WorkItem`. | not-started | offline | MVP-0 | Bridge into solver. |
| BRK-001 | A screenplay PDF can be parsed into candidate `SceneRecord` values. | not-started | offline | POST | Existing broad requirement narrowed to candidate output. |
| BRK-002 | Breakdown flags stunts, minors, and VFX as candidate flags requiring validation/acceptance before activation. | not-started | offline | POST | Existing requirement reframed. |
| BRK-003 | Gemini-derived scene records below the configured confidence threshold are marked `needs_review` and cannot feed the solver. | not-started | offline | POST | Prevents wrong candidate records becoming active. |
| BRK-004 | Cast extracted from a screenplay is resolved to roster IDs or reported as unresolved; unresolved cast blocks board generation. | not-started | offline | POST | Test with fixture screenplay/candidate output. |
| BRK-005 | Page eighths are rounded by a documented rule and keep enough provenance to audit the source page/line. | not-started | offline | POST | Avoids untestable page-count claims. |

---

## 9. TRK — Parallel track eligibility

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| TRK-001 | Parallel Search is called at runtime for every externally grounded fact request. No cache, precomputed fact table, or offline fallback may stand in for it. | unit-built | live | MVP-1 | Existing offline + live tests. |
| TRK-002 | Parallel Extract retrieves full page contents where excerpt compression would discard the operative value. | unit-built | live | MVP-1 | Existing tests. |
| TRK-003 | Parallel Monitor watches mutable weather and permit source URLs that a live schedule depends on and emits change events. | not-started | live | POST | Daylight is not monitored. |
| TRK-004 | Search, Extract, and downstream grounded values in one replan share a Parallel session or explicit correlation ID. | not-started | live | MVP-1 | Existing GRD-008 covers Search/Extract evidence session sharing; downstream grounded-value correlation is not implemented. |
| TRK-005 | A track-critical requirement with live verification required cannot be reported demo-ready without at least one live test or an explicit documented exemption. | not-started | live | MVP-1 | Strengthens status gating. |

---

## 10. GRD — Grounding and value provenance

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| GRD-001 | Evidence carries the URL of every source behind it and cannot be constructed without at least one. | unit-built | live | MVP-1 | Existing tests. |
| GRD-002 | A fact with no source raises rather than returning empty evidence or a default value. | unit-built | offline | MVP-1 | Live exempt: cannot reliably provoke no-results. |
| GRD-003 | A date-specific fact must prove at least one source explicitly mentions the target date before any value may be bound to that date. | unit-built | live | MVP-1 | Existing tests. |
| GRD-004 | A date-independent rule family is exempt from GRD-003 and is not rejected for omitting the target date. | unit-built | live | MVP-1 | Existing permit tests. |
| GRD-005 | Permit retrieval is restricted to authoritative domains by default and overridable per production. | unit-built | live | MVP-1 | Existing tests. |
| GRD-006 | Weather retrieval excludes sources published before the forecast horizon. | unit-built | live | MVP-1 | Existing tests. |
| GRD-007 | Extract failure degrades to excerpts and is reported as such, never silently presented as full content. | unit-built | offline | MVP-1 | Failure-path live exempt. |
| GRD-008 | Search and Extract calls within one replan share a Parallel session. | unit-built | live | MVP-1 | Existing tests. |
| GRD-009 | Weekday-only labels are not accepted as evidence of date coverage. | unit-built | offline | MVP-1 | Existing tests. |
| GRD-010 | Weather distinguishes near-term forecasts with predictive skill from long-range climatology/risk priors. | not-started | live | MVP-1 | See WEA section. |
| GRD-011 | The search request declares the consuming model and geo-targets the location's country. | unit-built | live | MVP-1 | Existing tests. |
| GRD-012 | A grounded value records the exact source span, quote, or table row that produced the normalized value. A URL alone is insufficient. | not-started | offline | MVP-1 | New value-level provenance. |
| GRD-013 | A grounded value records query, retrieval timestamp, provider response ID, content hash, full-content/excerpt flag, normalized value, units, and validator result. | not-started | offline | MVP-1 | New audit contract. |
| GRD-014 | Conflicting authoritative values raise `GroundingConflict` and cannot silently bind a constraint. | not-started | offline | MVP-1 | Need conflict fixture. |
| GRD-015 | A dated value may bind only from sources recorded as covering the target date; non-covering sources in the same evidence set are context only. | not-started | offline | MVP-1 | Clarifies CON-003 / source-level binding. |

---

## 11. DAY — Daylight

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| DAY-001 | Daylight is computed from coordinates and date, never retrieved. | unit-built | offline | MVP-0 | Existing tests. |
| DAY-002 | Computed times agree with published almanac tables to within 2 minutes. | unit-built | offline | MVP-0 | Existing tests. |
| DAY-003 | Times are timezone-aware and DST-correct for the date in question. | unit-built | offline | MVP-0 | Existing tests. |
| DAY-004 | A window violating chronological invariants raises rather than being returned. | unit-built | offline | MVP-0 | Existing tests. |
| DAY-005 | Latitudes where the sun does not rise or set are reported as polar day/night, not crashed on. | unit-built | offline | MVP-0 | Existing tests. |
| DAY-006 | Coordinates without a timezone are rejected at construction. | unit-built | offline | MVP-0 | Existing tests. |
| DAY-007 | Horizon obstruction at a location can override astronomical sunset. | not-started | offline | POST | Not needed for MVP. |
| DAY-008 | Deterministic daylight algorithms are rerun during solve/replan; they are not monitored as mutable external sources. | not-started | offline | MVP-0 | Daylight computation exists; solve/replan integration is not implemented. |
| DAY-009 | A daylight constraint compiled into CP-SAT is independently evaluable against a returned board. | not-started | offline | MVP-0 | Needed for board validation. |

---

## 12. WEA — Weather

Weather is not automatically hard or soft. Retrieved weather becomes a typed risk fact;
production policy decides whether that fact is a hard constraint, a soft penalty, a
waivable condition, or informational.

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| WEA-001 | Weather evidence is normalized into `ForecastRisk` values with issued_at, valid_for_date, horizon, condition, probability/intensity, source, and confidence tier. | not-started | live | MVP-1 | Connects grounding to scheduler. |
| WEA-002 | The forecast horizon is explicit. Values outside the horizon are classified as climatology/risk prior, not forecast. | not-started | live | MVP-1 | Makes GRD-010 testable. |
| WEA-003 | Production policy declares how each weather risk maps to constraint policy: hard, soft_penalty, waivable_by_role, or informational. | not-started | offline | MVP-1 | Solves weather ambiguity. |
| WEA-004 | Monitor-triggered replans may use near-term forecast changes, not long-range climatology changes, unless production policy explicitly allows it. | not-started | live | POST | Avoids false replan triggers. |
| WEA-005 | Weather facts used as solver constraints preserve value-level provenance from GRD-012/013. | not-started | offline | MVP-1 | Auditability. |

---

## 13. CON — Constraint translation and activation

Plain-English translation is advisory until candidate constraints are validated and
accepted. MVP-0 may load typed constraints from fixtures; MVP-1 may derive permit/weather
constraints from grounded values; full Gemini translation is post-MVP.

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| CON-001 | Plain-English production constraints are translated into candidate typed constraint records. | not-started | offline | POST | Existing broad requirement reframed as candidate output. |
| CON-002 | A typed constraint derived from retrieved text is validated by fact-family-specific checks before activation. | not-started | offline | MVP-1 | Define validators below. |
| CON-003 | Extraction may bind a dated value only from evidence sources recorded as covering the target date. | not-started | offline | MVP-1 | Source-level date binding. |
| CON-004 | A typed fixture constraint validates against the `ConstraintRecord` schema before entering `ScheduleProblem`. | not-started | offline | MVP-0 | Enables MVP-0. |
| CON-005 | A candidate constraint with unknown cast, location, work item, units, or date range blocks solving until corrected, accepted with explicit waiver, or rejected. | not-started | offline | MVP-0 | Prevents silent omissions. |
| CON-006 | Weather probability validators enforce units/ranges and forecast/climatology classification. | not-started | offline | MVP-1 | Fact-family validator. |
| CON-007 | Permit-window validators enforce local timezone, chronological order, date/effective range, and authoritative source provenance. | not-started | offline | MVP-1 | Fact-family validator. |
| CON-008 | Daylight constraints cite the deterministic algorithm/version rather than source URLs. | not-started | offline | MVP-0 | Daylight windows cite algorithm provenance; ConstraintRecord-level daylight constraints are not implemented. |
| CON-009 | Constraint activation records who/what created it, who accepted it when human acceptance is required, and when it became active. | not-started | offline | MVP-1 | Audit artifact. |

---

## 14. SOL — Solver and schedule validation

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| SOL-001 | The schedule is produced by CP-SAT. No language model emits a schedule. | not-started | offline | MVP-0 | Requires OR-Tools dependency/module. |
| SOL-002 | Every returned viable board satisfies all active hard constraints and all unwaived waivable constraints. Soft costs and exposures are represented as objective terms or required approvals. | not-started | offline | MVP-0 | Replaces ambiguous all-constraints wording. |
| SOL-003 | When no valid schedule exists, Coverset returns an irreducible conflicting constraint subset: removing any one listed constraint makes the reported conflict no longer proven. | not-started | offline | MVP-0 | Avoids ambiguous cardinality-minimal promise. |
| SOL-004 | Days already shot are immutable across replans. | not-started | offline | MVP-2 | Critical path. |
| SOL-005 | The objective minimizes company moves, cast holding days, and overtime/turnaround exposure according to declared weights. | not-started | offline | MVP-0 | Weights/config must be explicit. |
| SOL-006 | MVP constraint families are modeled: cast availability, location/permit windows, daylight/day-night feasibility, turnaround/rest, company moves, and lock constraints. Weather participates when production policy maps it to feasibility or objective cost. | not-started | offline | MVP-0 | Adds weather policy link. |
| SOL-007 | No board may be returned unless solver status is `FEASIBLE` or `OPTIMAL` and an independent validator checks every active hard constraint against the board. `UNKNOWN` and unvalidated solutions are not schedules. | not-started | offline | MVP-0 | New safety requirement. |
| SOL-008 | A returned board records solver status, model version, objective value, constraint snapshot hash, and validation result. | not-started | offline | MVP-0 | Audit. |
| SOL-009 | Objective breakdown reports company moves, holding-day cost/days, overtime/turnaround exposure, weather risk cost when applicable, and added shoot days separately. | not-started | offline | MVP-0 | Production-readable costs. |
| SOL-010 | A `ScheduleProblem` with a two-day/two-scene fixture schedules deterministically and validates cleanly. | not-started | offline | MVP-0 | First acceptance fixture. |
| SOL-011 | A fixture with impossible cast availability returns a conflict set containing the expected constraint IDs. | not-started | offline | MVP-0 | Infeasibility acceptance. |
| SOL-012 | A replan fixture cannot move, delete, resequence, or reassign work on `LockedDayRecord`s. | not-started | offline | MVP-2 | Immutability acceptance. |

---

## 15. LCK — Shot-day locking and actuals

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| LCK-001 | A `LockedDayRecord` includes scheduled scenes, actual shot status, date, locations, cast, call/wrap times, call sheet version, recorder, and timestamp. | not-started | offline | MVP-2 | Defines immutability object. |
| LCK-002 | The solver may reference locked records as constraints but must not mutate, delete, resequence, or reassign them. | not-started | offline | MVP-2 | Same principle as SOL-004, explicit. |
| LCK-003 | Replans start after an explicit cutoff day/time; in-progress or partial days require an explicit lock policy. | not-started | offline | MVP-2 | Avoids accidental rewrite of current day. |
| LCK-004 | Retroactive fact changes create audit exceptions and future recommendations, not edits to past schedules. | not-started | offline | MVP-2 | Preserves history. |

---

## 16. MON — Monitoring and replanning

MVP-2 can simulate changed typed facts without the Monitor API. Post-MVP uses Parallel
Monitor to detect changes in mutable source URLs.

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| MON-001 | A material change in a monitored typed fact triggers replanning with no user action. | not-started | live | POST | Full autonomous Monitor. |
| MON-002 | Replanning returns multiple boards satisfying hard constraints, each with production-readable cost deltas and required approvals stated. | not-started | offline | MVP-2 | Valid boards only. |
| MON-003 | A monitor page-change event becomes a replan trigger only after Coverset re-extracts the watched fact, normalizes old/new values, and proves a material schedule-relevant change under the fact family's threshold. | not-started | live | POST | Prevents ad/header churn replans. |
| MON-004 | Non-material page changes do not trigger replanning. Source disappearance, monitor failure, or stale facts emit alerts and cannot silently leave a schedule marked current. | not-started | live | POST | Failure handling. |
| MON-005 | A `MonitoredSource` records schedule version, evidence/value id, URL, fact kind, affected work IDs, fingerprint, and monitor subscription id. | not-started | offline | POST | Source registry. |
| MON-006 | A `ChangeEvent` records URL, detected_at, old/new fingerprints, old/new normalized values when available, and materiality result. | not-started | offline | MVP-2 | Can be simulated before real Monitor. |
| MON-007 | A `ReplanRequest` records trigger event, current board, locked days, affected work IDs, and requester component. | not-started | offline | MVP-2 | Boundary between detect and solve. |
| MON-008 | Monitor-generated options have no selected board until First AD `BoardSelection` is recorded. | not-started | offline | POST | Authority boundary. |

---

## 17. OUT — Outputs

MVP-0 output is a stripboard. Full call sheets and schedule diffs come later, but their
schemas are specified now.

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| OUT-001 | A call sheet is generated for a scheduled day. | not-started | offline | POST | Existing requirement; schema below. |
| OUT-002 | Two schedule versions can be diffed with the delta quantified in production terms. | not-started | offline | MVP-2 | Needed for replan options. |
| OUT-003 | A stripboard output lists shoot days, ordered work items, scene IDs, locations, day/night, cast, and estimated call/wrap windows. | not-started | offline | MVP-0 | MVP output. |
| OUT-004 | `CallSheet` includes day, scenes, locations, cast calls, crew call, wrap estimate, daylight windows, turnaround notes, permit notes, recipients, and schedule version. | not-started | offline | POST | Full call-sheet schema. |
| OUT-005 | `ScheduleDiff` reports added days, moved scenes, changed call times, added pickups, cast holding delta, company move delta, overtime/turnaround delta, and required approvals. | not-started | offline | MVP-2 | Production-readable delta. |
| OUT-006 | Recipients receive call sheets read-only and have no scheduling authority by receiving them. | not-started | offline | POST | Actor boundary. |

---

## 18. REV — Coverage review and human decision

Gemini may flag a coverage item as needing attention. It may not decide the outcome.
The existing implementation is strong here; additions mostly connect review decisions to
solver-ready pickup work.

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| REV-001 | A review finding is advisory. The only status transition a finding can cause is to needs review; it cannot accept, reject, or request a pickup. | unit-built | offline | MVP-3 | Existing tests. |
| REV-002 | A flagged coverage item is marked needs review and carries the finding that flagged it. | unit-built | offline | MVP-3 | Existing tests. |
| REV-003 | Only a decision attributed to a named human can accept, reject, or request a pickup. An automated agent is rejected as decider. | unit-built | offline | MVP-3 | Existing tests. |
| REV-004 | A decision records who made it, when, and which finding it responds to. | unit-built | offline | MVP-3 | Existing tests. |
| REV-005 | An accepted item produces no pickup work. | unit-built | offline | MVP-3 | Existing tests. |
| REV-006 | A decision may only be applied to an item awaiting review. | unit-built | offline | MVP-3 | Existing tests. |
| REV-007 | An item cannot be flagged for review before it has been shot. | unit-built | offline | MVP-3 | Existing tests. |
| REV-008 | A finding may be raised by a human as well as by Gemini. | not-started | offline | MVP-3 | Existing actor capability, finding path missing. |
| REV-009 | LLM-generated review findings include confidence and source coverage reference; low-confidence findings are display-only until human confirmation. | not-started | offline | POST | Prevents overacting on weak findings. |

---

## 19. PIK — Pickups and re-shoots

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| PIK-001 | A pickup task cannot be constructed without a human decision authorizing it. | unit-built | offline | MVP-3 | Existing tests. |
| PIK-002 | A pickup task traces to the decision that authorized it and the finding that prompted it. | unit-built | offline | MVP-3 | Existing tests. |
| PIK-003 | A rejection or pickup request yields exactly one pickup intent/task for the decision and coverage key. | unit-built | offline | MVP-3 | Existing tests; idempotence should be explicit. |
| PIK-004 | A pickup task carries the scene, coverage type, cast, location, and duration the solver needs to place it. | unit-built | offline | MVP-3 | Existing tests. |
| PIK-005 | Replanning admits a pickup task as required work while preserving cast, location, daylight, permit, weather, and lock constraints. | not-started | offline | MVP-3 | Solver integration missing. |
| PIK-006 | Replanning with a pickup treats already-shot days as immutable. | not-started | offline | MVP-3 | Depends on LCK/SOL. |
| PIK-007 | Each revised board states the disruption cost of accommodating the pickup in production terms rather than solver terms. | not-started | offline | MVP-3 | Depends on OUT/SOL diff. |
| PIK-008 | A `ReviewDecision` authorizes pickup intent; the task becomes schedulable only after a human-confirmed task spec defines scene, coverage/shot, cast, location, duration, and priority. | not-started | offline | MVP-3 | Avoids blindly scheduling incomplete pickup intent. |
| PIK-009 | Pickup task creation is idempotent by decision id and coverage key. | not-started | offline | MVP-3 | Prevent duplicate work. |
| PIK-010 | A board adding a shoot day or exceeding declared budget remains `pending_cost_approval` until UPM/Line Producer approval is recorded. | not-started | offline | MVP-3 | Connects pickup to ACT-005. |
| PIK-011 | `PickupTask` converts to a solver `WorkItem` with kind `pickup`, preserving authorization trace. | not-started | offline | MVP-3 | Bridge into solver. |

---

## 20. AUD — Auditability

| ID | Requirement | Maturity | Verification | Slice | Notes |
|---|---|---|---|---|---|
| AUD-001 | Every scheduling decision traces to explicit active constraints and objective terms. | not-started | offline | MVP-0 | Requires Board/ScheduleProblem. |
| AUD-002 | Every constraint traces to either source URL/value provenance, a named deterministic algorithm, or a human-entered production rule. | domain-model | live | MVP-1 | Offline covers deterministic/algorithm provenance; live is required for externally grounded constraints. Full ConstraintRecord is still missing. |
| AUD-003 | Every constraint records whether it was derived from full page content, excerpt, algorithm, fixture, or human input. | domain-model | offline | MVP-1 | Evidence has extraction mode; constraints missing. |
| AUD-004 | Every pickup task traces to a named human decision. No automated process can create shoot work. | unit-built | offline | MVP-3 | Existing tests. |
| AUD-005 | Every active board records the constraint snapshot hash used to solve and validate it. | not-started | offline | MVP-0 | New board audit. |
| AUD-006 | A schedule version records parent version, creation trigger, selected board, selecting actor when applicable, and approval state. | not-started | offline | MVP-2 | Needed for replans. |
| AUD-007 | A live-grounded requirement declares whether live verification is required, exempt, or manual, and traceability reports missing live coverage separately from offline coverage. | not-started | live | MVP-1 | Strengthens traceability. |

---

## 21. Use cases

A use case is a journey through requirements, not a requirement. It names the IDs it
exercises so traceability can report both requirement coverage and journey readiness.

### UC-00 — Build an MVP board from structured fixtures

The First AD loads pre-parsed scenes and typed constraints, then Coverset produces a
valid stripboard.

**Actors:** First AD · Solver  
**Exercises:** SCN-001, SCN-002, SCN-003, CON-004, SOL-001, SOL-002, SOL-005, SOL-006, SOL-007, SOL-008, SOL-009, SOL-010, OUT-003, AUD-001, AUD-005

### UC-01 — Build the initial board from a screenplay

The First AD hands Coverset a screenplay and the production's constraints, and gets a
board back.

**Actors:** First AD · Breakdown agent · Constraint agent · Solver  
**Exercises:** BRK-001, BRK-002, BRK-003, BRK-004, CON-001, CON-002, CON-003, CST-001, CST-002, CST-003, DAY-001, GRD-005, TRK-001, SOL-001, SOL-002, SOL-006, SOL-007

### UC-02 — State a constraint in plain English

The First AD says, “Sarah is only available the first two weeks. The church is Tuesdays
only.” The constraint agent proposes candidate typed constraints. Grounded constraints
bind only through validated evidence and human/validation activation.

**Actors:** First AD · Constraint agent · Grounding service  
**Exercises:** CON-001, CON-002, CON-003, CON-005, CON-007, CST-001, CST-003, GRD-001, GRD-002, GRD-003, GRD-005, GRD-012, GRD-013, GRD-014, GRD-015, AUD-003, TRK-001, TRK-002

### UC-03 — Replan when the world changes

A schedule-relevant forecast or permit fact changes. Coverset generates revised options
against locked days; the First AD picks one.

**Actors:** Change detector / Monitor loop · Solver · First AD  
**Exercises:** TRK-003, MON-001, MON-002, MON-003, MON-006, MON-007, MON-008, GRD-006, GRD-010, WEA-001, WEA-002, WEA-003, CST-004, CST-005, SOL-004, SOL-012, LCK-001, LCK-002, ACT-004, ACT-007, ACT-009, OUT-002, OUT-005, AUD-006

### UC-04 — Review coverage and order a pickup

Gemini flags a coverage item. The Director rules. Only then does re-shoot work reach
the board.

**Actors:** Review agent · Director · Solver  
**Exercises:** ACT-001, ACT-002, ACT-003, REV-001, REV-002, REV-003, REV-004, REV-005, REV-006, PIK-001, PIK-002, PIK-003, PIK-004, PIK-005, PIK-006, PIK-007, PIK-008, PIK-011, AUD-004, SOL-004

### UC-05 — Produce a call sheet

The Second AD generates the day's call sheet, with call times honoring daylight and
turnaround.

**Actors:** Second AD  
**Exercises:** OUT-001, OUT-004, OUT-006, ACT-010, DAY-001, DAY-003, CST-007

### UC-06 — Diagnose an impossible schedule

No valid board exists. The First AD gets the irreducible conflicting constraint subset,
not a generic solver failure.

**Actors:** First AD · Solver  
**Exercises:** SOL-003, SOL-011, AUD-001, AUD-002

### UC-07 — Lock the day as the shoot progresses

The Script Supervisor records what was actually shot. Those days become immutable.

**Actors:** Script Supervisor · First AD  
**Exercises:** ACT-006, REV-007, SOL-004, SOL-012, LCK-001, LCK-002, LCK-003, PIK-006

### UC-08 — Approve the cost of a pickup day

A pickup needs a day the schedule does not have. The UPM/Line Producer sees the cost
and rules on it.

**Actors:** UPM/Line Producer  
**Exercises:** ACT-005, ACT-008, CST-004, CST-005, PIK-007, PIK-010, OUT-002, OUT-005

---

## 22. Traceability expectations

The existing pytest marker approach remains correct:

```python
@pytest.mark.req("GRD-003")
def test_weather_for_the_wrong_day_is_refused_rather_than_bound(...):
    ...
```

Traceability should evolve to report:

1. requirements by maturity;
2. requirements by verification tier;
3. missing offline tests for implemented requirements;
4. missing live tests for live-required requirements;
5. use-case readiness by active slice;
6. partial/domain-model-only blockers separately from not-started blockers;
7. exception/exemption table for live tests that cannot be provoked.

A future traceability summary should distinguish:

- `covered offline`;
- `covered live`;
- `implemented but not integrated`;
- `integrated but not demo-ready`;
- `blocked by missing model/schema`;
- `blocked by missing external provider verification`.

---

## 23. Immediate implementation order implied by this spec

1. Add `SceneRecord`, `WorkItem`, `ConstraintRecord`, `ScheduleProblem`, `Board`, and
   `SolveResult` domain models.
2. Add structured fixture import and validation.
3. Add OR-Tools dependency and a tiny CP-SAT solver for a two-day/two-scene fixture.
4. Add independent board validator.
5. Add stripboard output.
6. Promote grounded permit/weather evidence to `GroundedValue` and `ConstraintRecord`.
7. Add weather policy classification.
8. Add locked-day records and replan request flow.
9. Connect pickup work items to solver.
10. Add cost approval and schedule diff.
11. Add Monitor API automation.
12. Add Gemini PDF/constraint translation candidate flows.

This ordering intentionally builds the scheduling spine before investing further in
satellite automation.
