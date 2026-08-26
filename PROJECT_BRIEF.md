# Coverset

**An agentic scheduling partner for first assistant directors.**

Gemini breaks down the script. A constraint solver builds the board. When the world
changes, the agent replans on its own.

> **Track: Parallel.** Decided 26 Aug 2026. Not reopening.
> The Parallel **Search API must be called at runtime** — this is the track eligibility
> requirement, not a design preference. Monitor and Extract are elective additions on
> top of it. Search must never be refactored out of the runtime path.

---

## The problem

The first assistant director turns a screenplay into a shooting schedule: which scenes
shoot on which day, in what order, at which location, with which cast. It is a
constrained optimization problem with a dozen interacting rule families — cast
availability windows, contracted day minimums, location and permit windows, daylight
for exteriors, minimum turnaround between wrap and next call, child labor limits,
company moves — and it is still done semi-manually in tools like Movie Magic
Scheduling.

The scheduling itself is only half the pain. The other half is that the schedule is
destroyed constantly. Weather kills an exterior. An actor gets sick. A location falls
through two days before the shoot. Each of those triggers a manual replan under time
pressure, at night, with a call sheet due in the morning — and the replan has to respect
everything already shot, because those days are immutable.

Getting it wrong is expensive in ways that compound: an unnecessary company move burns
half a shooting day, a turnaround violation triggers penalty pay, a missed permit window
means the location is simply unavailable.

## What Coverset does

Coverset takes a screenplay PDF and a set of production constraints stated in plain
English, and produces a shooting schedule and call sheets. It then watches the real-world
facts the schedule depends on — weather, permit pages, daylight — and replans
autonomously when they change, presenting the AD with a small set of viable options and
the cost of each.

When no valid schedule exists, it does not fail silently. It returns the minimal set of
constraints that cannot all be satisfied at once.

## Architecture

The central design decision: **the language model never produces a schedule.**

Gemini does the two things language models are genuinely good at:

1. **Script breakdown** — reading a screenplay PDF into structured scene data: scene
   number, INT/EXT, day/night, location, page eighths, cast present, and flags for
   stunts, minors, and VFX.
2. **Constraint translation** — converting an AD's plain English ("Sarah is only
   available the first two weeks", "keep days under twelve hours", "the church is
   Tuesdays only") into typed constraint records.

A deterministic CP-SAT solver does the thing that has to be correct: it produces the
schedule. Every board Coverset outputs provably satisfies its constraint set, because a
solver produced it. A model cannot emit an invalid schedule here, because a model never
emits a schedule at all.

This matters beyond correctness. It makes the system auditable — every scheduling
decision traces to an explicit constraint and an explicit objective, not to a generation.

### Components

| Component | Role |
|---|---|
| Breakdown agent | Screenplay PDF → structured scene records |
| Constraint agent | Plain English + retrieved web facts → typed constraints |
| Solver service | CP-SAT model; produces schedules and infeasibility explanations |
| Monitor loop | Watches external facts; triggers replanning on change |
| Web UI | Stripboard view, constraint panel, replan comparison, call sheets |

### Tools exposed to the agent

- `parse_screenplay` — PDF to structured scenes
- `ground_location_facts` — Parallel Search finds the authoritative page; Parallel
  Extract pulls its full contents; Gemini types the result into a constraint
- `compute_daylight` — sunrise, sunset, golden and magic hour from coordinates and
  date; deterministic, no retrieval
- `review_coverage` — Gemini reviews a scene's coverage and raises findings; advisory
  only, and the strongest effect it can have is putting the item in front of a human
- `record_review_decision` — the AD or Director's ruling; the only thing that can
  create pickup work
- `solve_schedule` — run the constraint model
- `explain_infeasibility` — return the minimal conflicting constraint set
- `diff_schedules` — compare two versions and quantify the delta
- `generate_call_sheet` — produce the day's call sheet

## How Parallel is used

Parallel is not a retrieval-augmented chat layer here. Retrieved facts become **hard
bounds on the solver's feasible region.** Three Parallel capabilities are used, each
doing distinct work.

### Search API — runtime, mandatory

The runtime path for every externally-grounded constraint:

```
location + date → Parallel Search → source URL + excerpt
               → Gemini extraction → validated typed constraint
               → CP-SAT bound
```

Search grounds the constraints that exist in no production database:

- Weather outlooks across the shoot period, informing exterior risk
- Municipal filming permit rules, restricted hours, and blackout dates

Daylight is deliberately *not* on this list. Sunrise, sunset and twilight are a
closed-form function of latitude, longitude and date, and are computed rather than
retrieved — see **Findings and learnings**. The facts that remain grounded are the
two that genuinely cannot be computed.

Every constraint carries its source URL, so any scheduling decision can be traced back
to the page it came from.

### Extract API — structured retrieval from difficult sources

Search returns compressed excerpts, and compression discards precisely the operative
value. Both grounded fact families needed **Extract** for the same reason from opposite
directions: a forecast page's excerpt keeps the current-conditions headline and drops
the per-day table, while an ordinance page's excerpt keeps the prose and drops the table
of permitted hours. In each case Search locates the authoritative page and **Extract
retrieves its full contents** before Gemini types the result.

This removes a real silent-corruption path: reconstructing a permit rule — or a
particular day's forecast — from fragments is exactly where a plausible-but-wrong
constraint enters the model unnoticed.

### Monitor API — the autonomous replan trigger

Coverset monitors the weather sources and permit pages its current schedule depends on.
When one changes, the agent identifies the affected scenes, re-solves against
already-shot days, and surfaces options:

> *Rain forecast increased from 20% → 85% for Day 14. Three alternative boards
> generated.*

Nobody presses "replan." The world changed, and the agent acted.

**Grounding with Parallel on Vertex AI** connects Gemini models directly to Parallel web
data for the grounding path.

### Extraction validation

Because typed constraints are derived from retrieved text, extraction is validated
against known-good values rather than trusted. A misparsed sunset time produces a
schedule that looks entirely valid and is wrong — the worst failure mode in the system,
because nothing downstream detects it.

## Constraint families

1. **Cast availability** — per-actor date windows, contracted day minimums, holding-day
   cost
2. **Location and permit windows** — allowed dates, restricted hours, blackout dates
3. **Daylight matching** — day/night scenes scheduled against actual sunrise/sunset for
   the date and location, computed from coordinates (NOAA solar position algorithm),
   timezone- and DST-correct
4. **Turnaround** — minimum rest between wrap and the next call time
5. **Company moves** — minimized; unit moves consume shooting time

**Objective:** minimize company moves, cast holding days, and overtime exposure —
which is what a first AD actually optimizes.

**Immutability:** days already shot are locked. Replanning on day 8 cannot move days 1
through 7.

## Pickups and re-shoots

A scene's coverage is a set of shots — establishing, wide, close-up, reverse, insert.
Any of them can turn out to be unusable, and finding that out late is expensive: the
work recurs, but the schedule around it has already hardened.

Gemini can help spot it. Gemini cannot decide it.

1. Gemini reviews a scene's coverage and raises a **finding** when something may need
   attention — an eyeline that does not match the reverse, coverage that looks short.
2. The item is marked **Needs AD/Director Review**. That is the entire effect a finding
   can have.
3. The AD or Director accepts it, rejects the coverage, or requests a pickup.
4. A rejection or pickup request creates a **PickupTask**: required work, carrying the
   scene, coverage type, cast, location and duration the solver needs.
5. The solver replans the remaining days with already-shot days locked, the pickup
   admitted as required work, and every original constraint — cast, location, daylight,
   permit, weather — still in force.
6. Coverset presents the revised boards and what each one costs.

**The boundary is structural, not procedural.** A `ReviewFinding` has no disposition
field, so it cannot express an outcome even in principle. A `ReviewDecision` refuses to
name an automated agent as its decider. A `PickupTask` cannot be constructed without a
decision that authorises one. Three separate locks, because the realistic failure is not
someone deliberately overriding the rule — it is a well-meant refactor that wires the
advisory path into the acting path, and a docstring does not survive that.

The same division as everywhere else in the system: **Gemini interprets, a human
decides, OR-Tools schedules.** A pickup day costs a crew day, so nothing automated puts
one on the board.

## Demo scenario

A 20-day shoot, day 8. A monitored weather advisory changes for the location scheduled
for day 14, an exterior.

> *Rain forecast increased from 20% → 85% for Day 14. Three alternative boards
> generated.*

Coverset re-solves within seconds and returns three viable boards. Each cost is stated
in terms a non-specialist can weigh:

- **Option A** — 2 turnaround violations *(crew rest drops below the contractual
  minimum on two nights)*
- **Option B** — burns 1 of Sarah's 12 contracted days *(paid whether she works or not)*
- **Option C** — church scenes fall outside the permit window *(location unavailable
  on that date)*

The AD picks. Coverset writes a new schedule version and regenerates the call sheet.

## Technology

- **Google Cloud:** Gemini via Agent Development Kit (ADK), Agent Engine, Cloud Run,
  Document processing for screenplay parsing
- **Partner (Parallel track):** via the `parallel-web` Python SDK —
  **Search API** (called at runtime; track eligibility requirement),
  **Extract API** (full-content retrieval from permit and ordinance pages),
  **Monitor API** (change detection driving autonomous replanning);
  plus Grounding with Parallel on Vertex AI
- **Solver:** Google OR-Tools CP-SAT
- **Frontend:** web application, deployed on Cloud Run

## Scope and honest limits

This is demonstrated at reduced scale: a single production, roughly 25–30 scenes,
8–10 speaking roles, 5–6 locations, a 20-day board, and five constraint families.

A real production would need union agreement rules (SAG-AFTRA, IATSE, DGA) encoded as
constraint libraries, second-unit and split-day scheduling, equipment and crew
continuity, and integration with existing production accounting and call-sheet systems.
The architecture accommodates those as additional constraint families — the solver
scales further than this demonstration exercises it.

The screenplay used is public domain.

## What's next

*Post-hackathon direction — deliberately out of scope for the submission.*

- Union agreement rule libraries (SAG-AFTRA, IATSE, DGA) as pluggable constraint sets
- Candidate-space exploration: enumerate the feasible region rather than a single
  optimum, and let the AD query it — *"show me boards where Sarah wraps by day 10 with
  under two company moves."* At that scale the candidate store becomes a genuine
  analytical workload; today's 20-day board does not.
- Integration with existing scheduling tools via import/export
- Multi-unit and split-day scheduling

### A note on scope discipline

Coverset uses one partner service, not several. Every component is load-bearing: Gemini
interprets, Parallel grounds, OR-Tools decides. Additional infrastructure would make the
architecture look driven by the submission requirements rather than by the problem — and
a 20-day board does not need a data warehouse.

## Findings and learnings

*Captured during the build.*

### The retrieved sunset that was confidently wrong

The first grounding path treated sunrise and sunset as web facts. Against the live
Search API it failed in the most dangerous way available: **zero of eight sources
contained the date that was asked about**, while three were dense with plausible clock
times — correct for the current day rather than the shoot date. Two results were pages
for the wrong month entirely.

The error was not small. Reading the "today" headline instead of the target date's row
was seven minutes off; reading the wrong month's row was thirty-four.

What makes this the worst failure mode in the system is that nothing about it looks
wrong. A misbound sunset time is type-correct, range-correct, and cites a genuine
authoritative URL. The provenance is real; only the *binding* is wrong. Extraction
succeeds, the solver proves the board satisfies its constraints, and the board is wrong.

The mechanism generalises beyond sunset: almanac and forecast sites are one URL per
**place**, with the date as a query parameter or page default. Relevance ranking
therefore returns the right site showing the wrong day, and excerpt compression keeps
the prominent headline number while discarding the table row that actually answers the
question. The excerpt is maximally on-topic and contains exactly the value that must
not be used.

### Which reframed the question: is daylight a web fact at all?

It is not. Sunrise, sunset and twilight are a closed-form function of latitude,
longitude and date. They only resembled web facts because sunrise-sunset websites
exist. Implemented directly, the NOAA solar position algorithm agrees with published
almanac tables to within about a minute.

So daylight is computed and only weather and permits are retrieved. This is a smaller
change than it looks: Search's runtime role is untouched, and the two facts that remain
grounded are the two that genuinely cannot be computed — which is a more honest use of
retrieval than having it fetch arithmetic.

### Computing a value does not make it safe; it makes it *checkable*

The first computed implementation hardcoded a UTC offset, which puts sunset a full hour
late on the far side of a DST boundary — the same plausible-but-wrong class of failure,
now inside the deterministic path. A twenty-day board crosses a DST boundary routinely.

The real advantage of computation is not exactness, it is that the result can be
asserted against invariants and against published known-good values. A retrieved value
can only be compared against another retrieval. The failure mode moves from undetectable
to detectable — the same argument the architecture already makes for CP-SAT over a
generated schedule, applied one layer out.

### Date binding is per fact kind, not a global rule

Weather is *about* a specific day and must prove its sources mention that day. A permit
ordinance carries no date at all — "no filming in the Historic District after 10pm" is a
standing rule — so requiring the shoot date to appear would reject the authority itself
and keep only incidental news coverage that happens to name the day.

Encoding date coverage as one global rule would have broken permits. It is a property of
the fact family.

Relatedly: **weekday labels are not date evidence.** "Tuesday" is unambiguous inside a
seven-day forecast and silently wrong outside one, and a shooting schedule reaches
further out than that.

### The guard binds dates, not credibility

Testing the coverage guard seventy-five days out, it passed — and the match was real: a
long-range site publishes a page titled for that exact date. But a seventy-five-day
"forecast" is climatology presented as meteorology.

The guard's contract is *does this text concern the date*. Whether the source's claim
about that date carries any predictive skill is a separate question, and one worth
modelling: weather is arguably two fact types, a near-term forecast that drives the
Monitor replan loop, and a seasonal climatology that serves as a risk prior at initial
scheduling. Monitoring the latter for changes would generate replan noise with no
underlying signal.

### Offline tests prove wiring, not truth

The grounding suite drives the real SDK through a mock transport, which caught genuine
serialization details and would catch an SDK drift. It could not have caught any of the
above, because the fixtures encoded what the API was *assumed* to return. Every finding
here came from the first live run. Both layers are necessary and they verify different
things.

### Smaller notes

- Restricting permit search to `.gov` worked better than expected — it went straight to
  the municipal ordinance rather than to aggregators.
- Source freshness filtering is load-bearing for weather: a cached forecast page reads
  as confident and current while describing weather already superseded.
- One weather excerpt returned 191 characters in total, which is a reminder that excerpt
  length is not correlated with whether the operative value survived compression.
