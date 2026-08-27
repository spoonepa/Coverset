# Coverset — Stitch UI Generation Prompt

Use this prompt as UI-specific input for Google Stitch. `SPEC_FULL.md` defines the product and workflow contract; this file translates it into screens, layout, sample data, labels, and demo states that a UI generator can use.

---

## Stitch prompt

Design a high-fidelity web app dashboard for **Coverset**, an agentic shooting-schedule partner for film/TV first assistant directors.

Coverset helps a production team turn scenes, cast availability, location/permit constraints, daylight windows, and weather risk into a solver-produced shooting board. The app must feel like a serious production operations tool, not a marketing site. It should be dense, calm, scannable, and trustworthy under time pressure.

### Product contract

- Gemini agents advise: screenplay breakdown, constraint translation, and coverage review.
- Parallel grounds mutable external facts: weather and permit/source evidence.
- Humans decide: First AD selects boards, Director rules on coverage, UPM/Line Producer approves added shoot-day cost.
- CP-SAT solver schedules: no language model emits a shooting board.
- Already-shot days are locked and cannot be changed in replans.

### App type

A professional web dashboard for first assistant directors managing a shooting schedule.

Primary user: **First AD**  
Secondary users: **Director**, **Script Supervisor**, **UPM / Line Producer**, **Second AD**

### Design direction

- Quiet professional production dashboard.
- Dense, scannable, command-center feel.
- More like a scheduling/operations cockpit than a SaaS landing page.
- Use stripboard and timeline patterns.
- Use side panels for facts, sources, decisions, and audit trails.
- Use badges for authority boundaries and state transitions.
- Make solver confidence and human decision points very clear.
- Visual hierarchy should support a tired AD quickly answering: “What changed, what are my options, what costs money, what is locked?”

Suggested style:

- Background: warm off-white or charcoal-neutral workspace.
- Cards: subtle shadows, thin borders, production-board paper texture if tasteful.
- Accent colors:
  - blue for solver/valid board
  - amber for warning/risk
  - red for blocked/infeasible
  - green for approved/locked/validated
  - purple or indigo for Gemini advisory items
- Typography: compact, legible, tabular numbers for times/costs.
- Layout: desktop-first, responsive down to tablet. Mobile can collapse into stacked cards but does not need to be primary.

---

## Navigation model

Use a left navigation rail plus top context bar.

### Left nav

- Board
- Scenes
- Grounding
- Replans
- Coverage Review
- Call Sheets
- Audit Log

### Top context bar

Show:

- Production: `The Glasshouse` demo shoot
- Schedule version: `v4 — Active`
- Shoot day: `Day 8 of 20`
- Solver status: `Validated`
- Last grounded check: `12 min ago`
- Current role selector: `First AD`

---

## Primary screens

### 1. Stripboard schedule dashboard

This is the main screen.

Layout:

- Top summary row:
  - Active board version
  - Number of shoot days
  - Locked days count
  - Company moves
  - Holding-day cost
  - Weather risks
  - Required approvals
- Main center area: vertical stripboard grouped by shoot day.
- Right side panel: selected day / selected scene details.
- Bottom or side audit drawer: constraint validation summary.

Stripboard card fields:

- Day number and date
- Lock status: `Locked`, `Planned`, `Replanned`
- Location
- Scene IDs
- INT/EXT and DAY/NIGHT chips
- Cast chips
- Estimated call/wrap
- Constraint badges: `Cast OK`, `Permit OK`, `Daylight OK`, `Turnaround OK`, `Weather Risk`

Important buttons:

- `Generate Board`
- `Validate Board`
- `Compare Options`
- `Lock Day`
- `View Sources`
- `Export Stripboard`

States:

- Empty: “Load structured scenes and constraints to generate a board.”
- Loading: “CP-SAT solver is building viable boards…”
- Success: “Board validated against 42 hard constraints.”
- Warning: “2 soft exposures require review.”
- Error: “No valid board. View conflict set.”

### 2. Scene breakdown / review screen

Purpose: show scene records and whether they are active, candidate, rejected, or need review.

Layout:

- Table/list of scenes on the left.
- Detail inspector on the right.
- Confidence and source metadata for Gemini-derived breakdowns.

Scene row fields:

- Scene ID: `SC-012`
- Slugline: `EXT. CHURCH COURTYARD — DAY`
- Page eighths: `3/8`
- Cast: `SARAH`, `ELIAS`
- Location: `Church Courtyard`
- Flags: `minor`, `stunt`, `vfx`
- Status: `Active`, `Candidate`, `Needs Review`

Buttons:

- `Accept Scene Record`
- `Send to Review`
- `Edit Cast`
- `Resolve Location`
- `Convert to Work Item`

Empty/error states:

- “No scenes loaded yet.”
- “3 scene records need cast resolution before solving.”
- “Low-confidence breakdown: human acceptance required.”

### 3. Grounded facts / source panel

Purpose: show Parallel Search/Extract-backed facts and exactly what value became a constraint.

Layout:

- Facts grouped by kind: Weather, Permit, Location Rules.
- Source cards with URL, retrieval time, source span/table row, full-content/excerpt status.
- Right panel showing normalized typed value and validator result.

Fact card fields:

- Fact kind: `Weather Forecast`
- Target date: `Apr 18`
- Normalized value: `Rain probability 85%`
- Source: `weather.gov/...`
- Source mode: `Extracted full content`
- Validator: `Passed date coverage`
- Used by: `WEA-001`, `CON-006`, `SOL-006`

Buttons:

- `Open Source`
- `View Extracted Span`
- `Re-run Search`
- `Mark Conflict`
- `Promote to Constraint`

States:

- Loading: “Searching live sources with Parallel…”
- Warning: “Excerpt only — full extract failed.”
- Error: “Conflicting authoritative values found.”
- Error: “No source explicitly mentions Apr 18.”

### 4. Replan alert and option comparison

Purpose: show what changed and let the First AD choose among valid boards.

Layout:

- Top alert card: material fact change.
- Three option comparison columns or table rows.
- Each option has constraint validation, cost deltas, and approval requirements.
- Right side panel: locked-day preservation proof.

Alert example:

“Rain forecast increased from 20% to 85% for Day 14 exterior scenes. Three valid boards generated. Days 1–8 are locked.”

Option fields:

- Option name: `Option A — Move exteriors earlier`
- Validity: `Validated`
- Added shoot days: `0`
- Company moves: `+1`
- Holding cost: `+$1,200`
- Turnaround exposure: `None`
- Weather risk: `Reduced`
- Required approval: `None` or `UPM approval required`

Buttons:

- `Select Option`
- `View Diff`
- `View Constraint Proof`
- `Request Cost Approval`
- `Dismiss Replan`

States:

- Loading: “Re-solving against locked days…”
- Success: “3 viable boards validated.”
- Warning: “1 exception scenario requires approval before activation.”
- Error: “No valid board. View irreducible conflict set.”

### 5. Coverage review / pickup screen

Purpose: show Gemini-advisory coverage findings and enforce human decision boundaries.

Layout:

- Coverage items list.
- Advisory finding card.
- Human decision panel.
- Pickup task preview.

Coverage item fields:

- Scene: `SC-018`
- Coverage type: `Reverse`
- Status: `Needs Director Review`
- Finding source: `Gemini review agent`
- Finding: “Eyeline may not match previous wide shot.”
- Confidence: `Medium`

Decision buttons:

- `Accept Coverage`
- `Reject Coverage`
- `Request Pickup`
- `Add Human Finding`

After `Request Pickup`, show task spec form:

- Scene
- Coverage/shot type
- Cast
- Location
- Estimated duration
- Priority
- Must complete by

States:

- Advisory badge: “Gemini cannot decide. Human ruling required.”
- Pickup created: “Pickup task authorized by Director Maya Chen.”
- Cost warning: “Adds one shoot day — UPM approval required.”

### 6. Call sheet preview

Purpose: preview a scheduled day’s call sheet for Second AD distribution.

Layout:

- Header with production, date, day number, weather, nearest hospital placeholder.
- Scene list.
- Cast call times.
- Crew call/wrap estimate.
- Location and permit notes.
- Turnaround notes.
- Recipient panel.

Buttons:

- `Generate Call Sheet`
- `Preview PDF`
- `Send to Cast & Crew`
- `Copy Call Times`

States:

- Empty: “Select a scheduled day to generate call sheet.”
- Warning: “Board must be validated before call sheet distribution.”
- Success: “Call sheet generated from schedule v4.”

### 7. Audit log screen

Purpose: make authority and provenance inspectable.

Rows:

- `Parallel Search called for weather, Apr 18`
- `Extract retrieved full content from weather.gov`
- `Constraint CON-WEA-014 activated`
- `Board v4 generated by CP-SAT`
- `Board v4 independently validated`
- `First AD selected Option B`
- `Director requested pickup for SC-018 reverse`
- `UPM approved added shoot day`

Each row should show:

- timestamp
- actor/component
- artifact ID
- source/decision link
- status badge

---

## Main demo click path

Design the UI so the following click path is obvious and presentable:

1. Start on an empty Board screen.
2. Click `Load Demo Production`.
3. Show structured scenes, cast, locations, and constraints loaded.
4. Click `Generate Board`.
5. Show active stripboard with validated constraints.
6. Show Days 1–8 as locked.
7. Trigger weather alert: rain risk for Day 14 exterior increases to 85%.
8. Replan panel opens with 2–3 options.
9. Select Option B and show schedule diff.
10. Open Grounding panel and show the exact source span behind the weather risk.
11. Open Coverage Review and show Gemini finding on Scene 18.
12. Director clicks `Request Pickup`.
13. Pickup task preview appears.
14. Replan with pickup shows added shoot day and `UPM approval required`.
15. UPM approves cost.
16. Board becomes active schedule version `v5`.
17. Preview call sheet for the next day.

---

## Sample data

### Production

- Title: `The Glasshouse`
- Shoot length: `20 days`
- Current day: `Day 8`
- Active schedule version: `v4`
- Location base: `Pasadena, CA`

### Cast

| Cast ID | Performer | Character | Availability | Notes |
|---|---|---|---|---|
| SARAH | Nina Park | Sarah | Days 1–12 | Contracted 12 days; holding cost $600/day |
| ELIAS | Mateo Reyes | Elias | Days 1–20 | Adult performer |
| LUCY | Ava Brooks | Lucy | Days 5–16 | Minor; max 6 work hours/day |

### Locations

| Location ID | Name | Type | Rules |
|---|---|---|---|
| CHURCH | St. Mark's Church | exterior/interior | Tuesdays and Thursdays only; exterior daylight required |
| HOUSE | Glasshouse Residence | interior/exterior | available all shoot days; no company move after 6pm |

### Scenes

| Scene | Slugline | Pages | Cast | Location | Flags |
|---|---|---:|---|---|---|
| SC-003 | INT. GLASSHOUSE KITCHEN — NIGHT | 2/8 | SARAH, ELIAS | HOUSE | none |
| SC-007 | EXT. CHURCH COURTYARD — DAY | 3/8 | SARAH, LUCY | CHURCH | minor |
| SC-012 | INT. CHURCH VESTRY — DAY | 1/8 | ELIAS | CHURCH | none |
| SC-014 | EXT. GLASSHOUSE DRIVEWAY — DUSK | 2/8 | SARAH, ELIAS | HOUSE | stunt |
| SC-018 | INT. GLASSHOUSE HALLWAY — NIGHT | 4/8 | SARAH, LUCY | HOUSE | minor |
| SC-021 | EXT. CHURCH STEPS — DAY | 2/8 | SARAH, ELIAS, LUCY | CHURCH | minor, vfx |

### Current board excerpt

| Day | Date | Status | Location | Scenes | Notes |
|---|---|---|---|---|---|
| 1 | Apr 04 | Locked | HOUSE | SC-003 | Shot; immutable |
| 2 | Apr 05 | Locked | HOUSE | SC-018 partial | Hallway coverage pending review |
| 8 | Apr 11 | Locked | CHURCH | SC-012 | Shot; permit verified |
| 14 | Apr 18 | Planned | CHURCH | SC-007, SC-021 | Exterior daylight; weather risk changed |
| 15 | Apr 19 | Planned | HOUSE | SC-014 | Dusk scene |

### Weather alert

- Previous value: `20% rain probability for Apr 18`
- New value: `85% rain probability for Apr 18`
- Source: `weather.gov/forecast/pasadena/apr-18`
- Retrieval mode: `Extracted full content`
- Source span: `Daily forecast table row for Apr 18`
- Materiality: `material; exterior scene risk threshold exceeded`

### Replan options

| Option | Summary | Validity | Cost delta | Risk / approval |
|---|---|---|---|---|
| Option A | Move church exteriors to Day 12, interiors remain Day 14 | Validated | +1 company move, +$600 holding | No approval required |
| Option B | Swap Day 14 CHURCH with Day 15 HOUSE | Validated | 0 added days, +30 min overtime exposure | First AD can select |
| Exception Scenario C | Keep Day 14 exteriors despite forecast | Not active schedule | Weather risk high | Requires explicit weather-risk waiver |

### Coverage finding

- Scene: `SC-018`
- Coverage item: `Reverse on Lucy`
- Finding source: `Gemini review agent`
- Finding: `Eyeline may not match Sarah close-up from earlier setup.`
- Status: `Needs Director Review`
- Director decision: `Request Pickup`
- Pickup task: `SC-018 reverse, LUCY + SARAH, HOUSE, 45 minutes, priority high`
- Cost impact: `May add one shoot day; UPM approval required if selected board adds day.`

---

## Component and label requirements

Use exact or near-exact labels:

### Status badges

- `Validated`
- `Solver Proposed`
- `Needs Human Decision`
- `Gemini Advisory`
- `Grounded by Parallel`
- `Extracted Full Content`
- `Excerpt Fallback`
- `Locked`
- `Pending Cost Approval`
- `Exception Scenario`
- `Conflict Set`

### Primary actions

- `Load Demo Production`
- `Generate Board`
- `Validate Board`
- `View Sources`
- `Compare Options`
- `Select Option`
- `Request Cost Approval`
- `Approve Cost`
- `Reject Cost`
- `Request Pickup`
- `Generate Call Sheet`

### Empty/loading/error language

- Empty board: “Load structured scenes and typed constraints to generate a board.”
- Solver loading: “CP-SAT is searching for valid boards against active constraints.”
- Grounding loading: “Calling Parallel Search at runtime.”
- Extract loading: “Retrieving full source content.”
- Infeasible: “No valid board. View irreducible conflict set.”
- Unknown solver status: “Solver did not return a validated schedule.”
- Advisory boundary: “Gemini can flag this; only a human can decide it.”

---

## Responsive expectations

Desktop:

- Left nav + top bar.
- Main board/replan area with right inspector panel.
- Comparison tables can show 2–3 options side by side.

Tablet:

- Left nav collapses to icons.
- Inspector becomes slide-over drawer.
- Replan options become stacked cards.

Mobile:

- Read-only review mode is acceptable.
- Primary demo should still show board cards, alert card, and option cards.
- Avoid trying to show the full stripboard table on small screens.

---

## What not to design

- Do not make a public landing page.
- Do not make a generic project-management board.
- Do not make Gemini look like it can approve, decide, or schedule.
- Do not hide source provenance behind vague “AI confidence.”
- Do not present invalid/exception scenarios as active viable schedules.
- Do not make cast/crew call-sheet recipients look like scheduling decision-makers.

---

## Desired output from Stitch

Generate a polished multi-screen web app prototype with:

1. A primary stripboard dashboard.
2. A replan alert/option comparison flow.
3. Grounded facts/source inspection panel.
4. Coverage review and pickup decision flow.
5. Call sheet preview.
6. Audit log.
7. Realistic sample data filled in.
8. Empty, loading, warning, and error states.
9. Desktop-first responsive layout.


---
Use SPEC.md as product truth. Relevant spec excerpt follows for authority and requirements context:
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

### Intent tags

A requirement that belongs to no use case is not necessarily a gap. It may be an
invariant, an edge case, or tooling. But *not necessarily a gap* is not the same as
*deliberately outside*, and the difference is the whole value of the report — so the
reason is stated rather than inferred.

A requirement exercised by no use case carries a leading tag in its Notes cell:

| Tag | Meaning |
|---|---|
| `[invariant]` | A correctness property of a capability some journey already exercises. |
| `[edge-case]` | A rare path that no ordinary journey reaches. |
| `[cross-cutting]` | Applies across many journeys and belongs to none of them. |
| `[meta]` | Constrains the tooling or status reporting, not the product. |
| `[deferred]` | Post-MVP by design; the journey that needs it does not exist yet. |

Traceability groups unexercised requirements by tag and reports untagged ones
separately. That last group is the actionable one: a requirement outside every
journey with no stated reason is a forgotten workflow requirement until someone says
otherwise.

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
either, and the distinction is worth drawing prec

---
Generate this screen now:
Create the Call Sheet Preview screen for the Second AD. It must show schedule v4, day/date, scenes, locations, cast call times, crew call, wrap estimate, daylight window, turnaround notes, permit notes, recipients as read-only, and Generate Call Sheet / Preview PDF / Send to Cast & Crew buttons.

Return a high-fidelity desktop web app screen. Do not create a landing page. Do not let Gemini appear to decide or schedule. Keep exception scenarios visually distinct from viable boards.