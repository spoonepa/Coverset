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

### A bound with no record is a bound with no second reading

`SYN-DAYLIGHT` exists because a bound that appears in no constraint set reaches no
snapshot hash, no conflict set and no validation report. The company's maximum day was
the same shape of bound and had not been given the same treatment: it was compiled
straight from `Company.maximum_day_hours` into an unconditional CP-SAT constraint.

Three consequences, each of which looked fine from every angle except the right one.
A board an hour over the company day put to the validator came back **passed, with
zero checks performed** — `validate_board` took a `company` argument and never read
it, so the day length was the one hard bound in the system read exactly once. Two
productions with different maximum days produced the **same constraint snapshot hash**,
so boards solved under a twelve-hour day and a sixteen-hour day compared as
equivalent. And a schedule impossible *only* because of the twelve-hour day was
reported as **structurally** impossible — structure being, by definition, the category
of cause no relaxation can fix. Authorising a fourteen-hour day fixes it. The AD was
handed a dead end and told it was physics.

The fix is the one the codebase already knew: synthesise the record. `SYN-COMPANY-DAY`
now carries the production's maximum day, so it compiles through the same
record-driven path as everything else, gets an assumption literal, reaches the hash,
and is re-read by the validator. The unconditional cap left with it — except for
twenty-four hours, which stays, because a calendar day is not a policy anyone can
authorise their way past. That distinction is what keeps a twenty-five-hour scene
reported as structural while a thirteen-hour one is reported as the company day.

**And the term nobody was checking.** Company moves and holding days were each read
twice and compared; overtime was compiled, minimised, and then reported from a
measurement nothing compared against. Corrupting the moves reading was caught
immediately; corrupting the overtime reading produced a board carrying ninety-nine
invented overtime hours, cheerfully returned. It is now the third term in the
comparison, and the figure in the breakdown *is* the compared figure rather than a
second call that could drift from it.

**Still outstanding, same shape.** `Company.minimum_turnaround_hours`,
`CastMember.minimum_turnaround_hours` and `WorkItem.must_complete_by` are declared on
domain types and reach neither CP-SAT nor the validator. `Company.turnaround_satisfied`
has no callers at all. Unlike the maximum day, giving these records would change which
boards are feasible, so it is a decision rather than a repair.

### The shared misconception the cross-check could not see

Two guards in this codebase compare a compiled model against an independent reading of
the finished board, and both had been earning their keep. Neither could see this one,
because both readings were wrong in the same direction and therefore agreed.

**Python subtracts two aware datetimes naively when they share a tzinfo object.** The
language defines it that way: "if both are aware and have the same tzinfo attribute,
the common tzinfo attribute is ignored and the result is a timedelta". Every time on a
board carries the same `Location.zone`, so `wrap - call` returned the *wall-clock*
difference. On the night the clocks go back, a call at 17:53 EDT and a wrap at 05:53
EST measured twelve hours and really ran thirteen. The company's twelve-hour day
passed. The crew were billed two overtime hours and worked three.

Spring forward is the direction that hurts a person rather than a budget: a wrap at
23:00 EST and a call at 11:00 EDT is eleven hours of turnaround, certified as twelve
by every reading in the system. The constraint exists precisely to stop that.

This is the same *hour-shaped* bug as the retrieved sunset further down this file, but
it arrived by a different road. That one came from a hardcoded UTC offset, and was
caught by comparing against published almanac values — a second source. This one could
not be caught that way at all, because the model and the validator were not two
sources. They were one misconception, read twice.

**What that changes about the design rule.** `CLAUDE.md` already says cross-checks
catch disagreement and never a shared misconception; this is the first time that cost
something. The fix is therefore not a third reading but a single definition both sides
call — `clock.elapsed` and `clock.advance`, with the reasoning in the module docstring
so the next person does not reintroduce `+=` on an aware datetime. The solver's clock
variables now count absolute minutes from a fixed instant rather than minutes past a
local midnight, because durations are real minutes and the coordinate has to match.

A related disagreement died with it. The model and the emitted timeline each derived
the day's call time independently and could differ — at a location in polar day or
polar night the model assumed an 18:00 night call while the timeline fell through to
07:00, an eleven-hour gap that surfaced as a turnaround miscompile and was really two
fallbacks disagreeing. There is now one `_call_time`, and both callers use it.

**Also found, same round.** The objective's own counters were pinned to the truth by
one-sided bounds that only optimality closed. Stop the search early — or weight a term
at zero, which is permitted — and a counter sits slack above the count measured off
the finished board, so the cost cross-check refused a board that had already passed
independent validation, reporting a miscompile that was not there. The guard was
right that the two numbers disagreed and wrong about which one to distrust. Counters
are now exact at every solver status, not merely at `OPTIMAL`.

### Two readings agreeing is not two readings being right

A second review round found four more faults, all of which the suite was green
through, and three of which surfaced as `ERROR` — the model proving a board the
validator then rejected. The guards held; nothing bad shipped. But `ERROR` was
reported as *"the compiled model does not match the constraint records"*, which named
a miscompile when the real cause was usually a bound the model had never expressed.
An accurate guard with an inaccurate diagnosis still sends someone the wrong way.

**Calendar position is not calendar distance.** The model priced clock times and
holding days off a day's *index* in the production calendar. A calendar skips dark
days, weekends and holds, so the moment one is missed every clock time lands on the
wrong date and a performer held across a dark day is priced as though the dark day did
not exist. Both now work in calendar-day offsets, which is what `Engagement.held_days`
has always counted.

**A bound on a total says nothing about when the total happens.** Daylight was
compiled as an aggregate: the sum of sun-bound minutes had to fit the window. In
December, a two-hour exterior queued behind a seven-hour interior wraps well after
sunset while the aggregate still fits comfortably. The first fix — require the whole
day inside the window — was sound and too blunt: it forbids exterior-morning then
interior-afternoon, which in winter is not an edge case but the standard shape of a
day. The model now orders sun-bound locations to the front of the day and bounds only
that prefix, so the exterior finishes before sunset and the interior is free to run
past it.

**Two components can mean different things by the same words.** A cast daily-hours
limit meant "sum of scene durations" in the solver and "call to wrap" in the
validator. For a minor's limit the validator is right — a performer waiting through a
company move is still at work — so the solver now bounds the day that contains them.

**An enum value with no implementation behind it.** `DAWN` and `DUSK` were accepted
and scheduled as ordinary day work at a 07:00 call, against a civil dawn of 06:08.
That is not a dawn scene; it is a dawn scene shot in daylight. Refused at the solver
boundary until twilight windows exist (`DAY-010`, `DAY-011`), on the same reasoning
that makes `WorkItem` refuse `UNKNOWN`.

The round also produced a DST bug *inside the check meant to catch this class of bug*:
the model/board timeline comparison added minutes to a zone-aware midnight, which is
absolute arithmetic and slips an hour across a boundary. A board spanning 1 November
would have reported drift that was not there.

The lesson worth keeping is from the previous round, now confirmed twice: the
independent validator and the cost cross-check catch *disagreement*. They cannot catch
two components sharing a wrong definition, a bound nobody compiled, or a check that is
itself wrong. Each of those needed someone to re-derive the requirement from what it
means, not from what the code already said.

### The confident wrong answer migrated into the diagnosis

Review of the first solver found four faults that the whole 321-test suite was green
through. Three were degrees of the same thing: the system was sure, and wrong.

**A conflict set that named the wrong constraint.** A scene longer than the maximum
shooting day is infeasible before any constraint applies — but the day-length bound
was compiled without an assumption literal, so CP-SAT could not cite it. It returned
whatever assumption was to hand, the deletion filter could not shrink below one member
(it never tested the empty set), and a `len(core) == 1` shortcut in the irreducibility
proof declared the survivor load-bearing without testing it. The First AD was told to
renegotiate the daylight constraint. Relaxing it would have changed nothing.

With no daylight record present the same problem returned an **empty** conflict set
marked irreducible: "no schedule exists", asserted as minimal, naming nothing. That is
worse than silence, because it reads as an answer.

Both are now unconstructible. `ConflictSet` requires either a relaxable constraint or
a named structural cause, and refuses to call a conflict irreducible when it names no
constraints. Where nothing relaxable is at fault, a structural pass names why —
`STRUCT-DAY-LENGTH`, `STRUCT-DAY-NIGHT-SPLIT`, `STRUCT-TOTAL-CAPACITY` — reporting all
of them at once rather than the first.

**A hard bound with no record behind it.** Daylight capacity was compiled
unconditionally, so an eleven-hour exterior scene was correctly refused in December by
a constraint that appeared in no constraint set, no snapshot hash and no validation
report. Nobody could trace it, waive it, or deactivate it. Daylight binds because the
sun does — but the binding still has to be *stated*, so `ScheduleProblem` now
synthesises an explicit `SYN-DAYLIGHT` record when work needs the sun and the set is
silent, and the capacity bound is gated on that record like any other.

**Company moves undercounted, in both readings at once.** A move was modelled as
"consecutive days sharing no location". Play the park then the studio on Monday and
return to the park on Tuesday, and the days share the park, so no overnight move was
counted — while the trucks plainly drove from the studio back to the park. The cost
cross-check could not catch it, because the measurement was wrong the same way as the
model. That is the limit of cross-checking two readings: it catches disagreement, not
shared misconception. Only re-deriving the definition from what a company move *is*
found it.

The fix models each day's start and end location, and paid for itself immediately: given
the freedom to choose where a day wraps, the solver now orders Monday as studio-then-park
so Tuesday calls where Monday finished — a genuine one-move board where the old model
had been claiming one move for a two-move schedule.

**Turnaround compiled as something else.** Minimum rest was approximated as a cap on
day *length*, which says nothing about a night wrap at 00:06 running into a 06:36
sunrise call. The validator caught the violation, so no bad board shipped — but the
result was no board at all plus a diagnosis blaming a miscompiled model, when the model
had simply never expressed the bound. A conservative approximation that reports its
failures as somebody else's bug is not conservative. The model now carries absolute
call and wrap times, and rest is compiled against them exactly.

The through-line: the independent validator is a strong guarantee about *values on a
board*, and it says nothing about explanations, about bounds nobody declared, or about
a definition that both readings share. Those needed separate structural answers.

### CP-SAT's infeasibility core is sufficient, not minimal

`SOL-003` promises an irreducible conflict set: remove any listed constraint and the
conflict is no longer proven. CP-SAT's `sufficient_assumptions_for_infeasibility`
does not promise that, and probing found the gap is not theoretical. On the
two-performer conflict fixture — one scene needing two people whose availability
windows do not overlap — CP-SAT returns a core of **three**, including a location
window that has nothing to do with the collision. Dropping it changes nothing.

A deletion filter re-proves the conflict without each member in turn and reduces it to
the two records that actually collide. Without that pass, Coverset would hand a First
AD a third constraint to go and renegotiate, confidently, for no reason — the same
shape of failure as the misbound sunset, in the explanation rather than the value.

Two synthetic probes beforehand both returned minimal cores, which would have been
enough to conclude the filter was unnecessary. The real fixture disagreed. Probes
built to test a mechanism are not evidence about the problem the mechanism will meet.

### A board's identity depends on the solver's parameters, not just the problem

Same problem, same weights, different random seed: **different board, identical
objective value.** Ties among equally optimal boards are broken by search order, and
search order is a function of the seed and the worker count. Multi-worker solving adds
wall-clock nondeterminism on top.

This matters for an auditable product. "Reproduce the board that was approved on
Tuesday" needs the seed, not just the constraint snapshot — so `Board` records
`seed`, worker count and model version alongside the snapshot hash, and solving pins
`num_workers=1`. Without that the audit trail names a board nobody can regenerate.

Recording the seed is necessary and was not sufficient. The first implementation also
passed `max_time_in_seconds`, a **wall-clock** budget — so a solve cut off at the
limit resolves differently on a fast machine than a slow one, whatever the seed says.
The determinism the seed buys is given straight back by the cutoff, and the failure is
invisible: both boards are valid, both are optimal-looking, and the discrepancy only
shows up when someone tries to regenerate one. CP-SAT's `max_deterministic_time` cuts
off at the same point in the search on every machine, and that is what the solver uses.

Comparing against a mature retail workforce scheduler sharpened this. That codebase
runs `num_search_workers = 8` with a wall-clock limit and sets no seed at all, so the
same inputs produce different rosters run to run. For retail rostering that is close
to harmless — one balanced roster is as good as another. For a board a First AD signs
off and a production spends money against, it is not.

### The independent validator caught a real miscompile immediately

The arrangement where the solver and the validator read the same `ConstraintRecord`s
through two pieces of code that share nothing paid for itself during the first build,
not later.

Company moves were modelled as *within-day relocations plus consecutive days sharing
no location*. That is wrong when the calendar has a gap: shoot at the park Monday,
nothing Tuesday, the studio Wednesday, and the model sees no overnight move because
Tuesday's location set is empty — while the board plainly contains one. Every hard
constraint was satisfied, the solver reported `OPTIMAL`, and the objective was
minimising a cost the board did not have.

Nothing about the board looked wrong. What caught it was a cross-check that measures
moves and holding days off the finished assignments and refuses to return a board when
that disagrees with what the model optimised. The fix was to carry the unit's base
forward across gap days. The lesson is the one this codebase keeps relearning: the
check that finds these has to be a second, independent reading, because the first
reading is exactly the thing that is wrong.

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
