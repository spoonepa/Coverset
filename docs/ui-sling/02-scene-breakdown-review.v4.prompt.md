
VISUAL STYLE TO BORROW FROM docs/ui (visual inspiration only):
- Dark production operations cockpit, not light SaaS dashboard.
- Background #131313 / near-black, panels #201f1f / #2a2a2a, subtle borders #434655.
- Compact 64px left rail, top command/status bar, dense cards, 8px gutters, 12px card padding.
- Tabular/mono data for times, costs, scene IDs, source IDs, schedule versions.
- Explicit text status pills, not color alone: LOCKED, PLANNED, VALIDATED, GEMINI ADVISORY, GROUNDED BY PARALLEL, EXCEPTION SCENARIO.
- Status colors: green for validated/approved, amber for risk/warning, red for blocked/exception, indigo for Gemini advisory, blue for CP-SAT/solver.
- More like a film production command center / stripboard control room than a generic SaaS product.
- Strong scan hierarchy: left nav, top status rail, main operational table/board, right inspector/provenance panel.


CANONICAL PRODUCT SEMANTICS FROM docs/ui-sling / SPEC.md:
- Gemini advises only. Never label anything as AI scheduled or AI decided.
- Parallel grounds mutable external facts: weather and permit sources. Parallel does NOT ground daylight.
- Daylight is computed locally with NOAA solar algorithm.
- CP-SAT produces board proposals; independent validator validates boards.
- Humans decide: First AD selects boards, Director rules on coverage, Script Supervisor records/raises findings, UPM / Line Producer approves added shoot-day cost.
- Exception scenarios are NOT active schedules and must be visually separate from viable boards.
- Weather-risk waiver is not UPM cost approval unless it adds shoot-day cost.
- Use one demo jurisdiction consistently: Savannah, Georgia; Eastern Time; Savannah Film Office / City of Savannah permit source; First African Baptist Church. Do not use City of LA, filmla/filmala, Pasadena, or PST.
- Treat Stitch HTML as prototype reference; product data semantics remain from SPEC.md.


Relevant current validation baseline:

# Coverset Stitch UI Validation

Generated with Stitch via `@google/stitch-sdk` using `STITCH_PROMPT.md` and `SPEC.md` as source context. API credentials were used only through the environment and are not stored in this directory.

## Artifacts

Project metadata and download URLs are in:

- `docs/ui-sling/manifest.json` — initial generation
- `docs/ui-sling/iteration-2-manifest.json` — first authority/provenance correction pass
- `docs/ui-sling/iteration-3-manifest.json` — missing screen plus targeted fixes/high-resolution exports

Each screen may have:

- `*.html` / `*.png` — initial Stitch output
- `*.v2.html` / `*.v2.png` — corrected output after authority/provenance validation
- `*.v3.html` / `*.v3.png` — targeted fixes from the second review pass
- `*.final.hires.png` — local high-resolution screenshot generated from the final HTML baseline
- `*.prompt.md` — generation prompt used for the initial screen

## Current implementation-reference baseline

Use these files as the current UI reference set:

| Screen | Final HTML | Final high-res screenshot | Purpose |
|---|---|---|---|
| Stripboard dashboard | `01-stripboard-dashboard.v2.html` | `01-stripboard-dashboard.v2.final.hires.png` | Main First AD board view |
| Scene breakdown / review | `01b-scene-breakdown-review.v1.html` | `01b-scene-breakdown-review.v1.final.hires.png` | Gemini candidate scene-record review and activation |
| Replan options | `02-replan-options.v3.html` | `02-replan-options.v3.final.hires.png` | Weather-triggered replan comparison |
| Grounded facts | `03-grounded-facts.v3.html` | `03-grounded-facts.v3.final.hires.png` | Parallel source/value provenance |
| Coverage pickup | `04-coverage-pickup.v2.html` | `04-coverage-pickup.v2.final.hires.png` | Gemini advisory finding to human pickup decision |
| Call sheet | `05-call-sheet.v2.html` | `05-call-sheet.v2.final.hires.png` | Second AD call sheet preview |
| Audit log | `06-audit-log.v3.html` | `06-audit-log.v3.final.hires.png` | System/human provenance ledger |

## Validation checklist

### Product authority boundaries

| Rule | Result | Evidence |
|---|---:|---|
| Gemini is advisory only, not scheduler/decider | Pass | Coverage screen says “Gemini can flag this; only a human can decide it.” Audit log uses “Gemini Constraint Agent” only for candidate typing. |
| CP-SAT/solver is source of board proposals | Pass | Stripboard uses “CP-SAT Scheduled”; audit log shows “CP-SAT Solver Board v5 generated.” |
| Independent validation is visible | Pass | Stripboard inspector says “Validated by independent validator”; audit log has an “Independent Validator” row. |
| First AD selects replan options | Pass | Replan options show First AD authority for valid options; audit log records First AD option selection. |
| Director rules on coverage | Pass | Coverage screen has “Director Decision Needed” and decision buttons. |
| UPM / Line Producer approves added shoot-day cost | Pass | Audit log records “UPM / Line Producer Approved added shoot day cost.” |
| Call-sheet recipients are read-only | Pass | Call sheet uses “Viewers (Read-only).” |

### Scheduling and replan semantics

| Rule | Result | Evidence |
|---|---:|---|
| Locked days are visually immutable | Pass | Replan screen has “Locked History IMMUTABLE” and days 1–8 locked. |
| Viable boards are separated from exception scenarios | Pass | Replan screen shows Option A/B as validated and “EXCEPTION SCENARIO C” as “NOT AN ACTIVE SCHEDULE.” |
| Replan explains material fact change | Pass | Replan screen says “Material Weather Fact Changed” instead of constraint violation. |
| Cost/risk deltas are visible | Pass | Replan options show company moves, holding cost, added days, overtime exposure, and risk. |
| Weather-risk exception does not ask for UPM cost approval | Pass in v3 | `02-replan-options.v3.html` uses `Request Weather Waiver`; UPM/Line Producer approval remains for added shoot-day cost. |

### Scene breakdown / Gemini upload flow

| Rule | Result | Evidence |
|---|---:|---|
| Scene breakdown/review screen exists | Pass | `01b-scene-breakdown-review.v1.html` added. |
| Candidate scene records are visible | Pass | Screen includes Candidate / Needs Review scene rows and SceneRecord inspector. |
| Low-confidence/unresolved fields block solving | Pass | Screen shows unresolved cast warning and “Human validation required before this scene can be scheduled by the solver.” |
| Human review actions are present | Pass | Includes `Accept Scene Record`, `Reject Candidate`, `Send to Review`, `Resolve Cast Discrepancy`, `Resolve Location`, and `Convert to Work Item`. |

### Grounding/provenance semantics

| Rule | Result | Evidence |
|---|---:|---|
| Parallel Search is visible | Pass | Grounded facts and audit log mention Parallel Search. |
| Parallel Extract, not Gemini, retrieves full content | Pass | Grounded facts shows “Retrieval Chain: Parallel Search -> Parallel Extract”; audit log has “Parallel Extract Retrieved full content.” |
| Value-level provenance is visible | Pass | Grounded facts shows source span, content hash, provider response ID, retrieval chain, table row, normalized value, and validator result. |
| Demo permit source label is no longer City of LA | Pass in v3 | `03-grounded-facts.v3.html` says “Checking Savannah Film Office permit page.” |
| Avoids “AI confidence” as sole provenance | Pass | v2/v3 emphasize validator/source fields rather than confidence percentage. |

### Visual/export quality

| Rule | Result | Evidence |
|---|---:|---|
| Audit log extraction icon does not render as broken text | Pass in v3 HTML | `06-audit-log.v3.html` replaces `data_extraction` with the supported `article` icon. |
| High-resolution screenshots exist | Pass | `*.final.hires.png` files are 2048 × 1638 and were rendered from the final local HTML baselines. |

## Corrections applied in iteration 2

The first Stitch pass was visually useful but had several spec violations:

- `01-stripboard-dashboard`: said “AI Scheduled,” which violated the authority model.
- `02-replan-options`: framed the weather change as a constraint violation and used “AI Advised.”
- `03-grounded-facts`: used DarkSky and blurred Gemini vs Parallel extraction responsibilities.
- `04-coverage-pickup`: used “AI Flag” rather than Gemini Advisory.
- `05-call-sheet`: showed First AD rather than Second AD for the call-sheet workflow.
- `06-audit-log`: said “Gemini Extract” retrieved full content, but full-content retrieval belongs to Parallel Extract.

Iteration 2 corrected these with screen-specific Stitch edit prompts. See `iteration-2-manifest.json` for the exact edit prompts and corrected screen IDs.

## Corrections applied in iteration 3

The second review pass found five remaining issues. They are now addressed:

1. **Missing Scene breakdown/review screen** — added `01b-scene-breakdown-review.v1.html` and PNG exports.
2. **Wrong weather-exception action** — `02-replan-options.v3.html` now uses `Request Weather Waiver` instead of UPM cost approval.
3. **Wrong permit source placeholder** — `03-grounded-facts.v3.html` now says `Checking Savannah Film Office permit page`.
4. **Audit log icon/layout issue** — `06-audit-log.v3.html` uses the supported `article` icon instead of rendering `data_extraction` as text.
5. **Low-resolution exports** — final high-resolution PNGs were rendered from local HTML at 2048 × 1638.

## Remaining design nits

These are not blockers, but should be handled before frontend implementation hardens around these screens:

1. **Canonical fixture alignment.** Stitch invented some scene/person details beyond `STITCH_PROMPT.md`. Once MVP-0 fixtures exist, normalize the UI sample data to the committed fixture JSON.
2. **Role-specific top bar consistency.** Most screens use First AD, while Call Sheet uses Second AD. That is fine for screen-specific demos, but a real prototype should make role switching explicit.
3. **Stitch HTML is prototype code.** Treat it as visual direction and content reference, not production frontend architecture.

## Notes on the Stitch MCP route

The baseline above was generated through `@google/stitch-sdk`. A separate attempt went
through the Stitch **MCP server** against a different project
(`13355501855075038394`, one screen only). It is not part of the baseline and its
output is not kept, but the behaviour is worth recording before anyone tries that route
again.

**A timeout does not mean failure.** `generate_screen_from_text` timed out on every
call. The first one nonetheless appeared in `list_screens` about two minutes later. Do
not retry on timeout — poll instead.

**Consecutive submissions stopped producing anything.** After the first success, seven
further generations were fired in close succession and none ever appeared, including
one submitted without a `designSystem` parameter, which rules the design system out as
the cause. Most likely rate limiting. Space submissions out rather than batching them.

**`update_design_system` reported success witho

Relevant spec context:

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

### 4.1 Declared objective weights

`SOL-005` requires the objective to optimize against *declared* weights. These are the
declaration; the solver reads them and refuses to build an objective from anything it
was not given.

| Term | Weight | Unit |
|---|---:|---|
| Company move | 3.0 | per move |
| Cast holding day | 1.0 | per held day, per performer |
| Overtime exposure | 0.5 | per hour beyond the standard day |

Holding days are the numeraire: one company move is worth three of them, one overtime
hour half of one. The ratio is a production judgement rather than a fact, and it is
recorded here because it decides what the board looks like — a move-averse weigh

Generate screen:

Create a dark dense Scene Breakdown / Review screen for Gemini upload flow. Must show candidate SceneRecord rows, Active/Candidate/Needs Review statuses, low-confidence fields, unresolved cast/location warnings, confidence badges, and right inspector with SceneRecord fields. Actions: Accept Scene Record, Reject Candidate, Send to Review, Resolve Cast, Resolve Location, Convert to Work Item. Must say Gemini produces candidate scene records only; human validation is required before solver scheduling; unresolved cast/location blocks solving.