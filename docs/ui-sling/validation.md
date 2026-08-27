# Coverset UI reference — validation

`docs/ui-sling` is the implementation-reference UI baseline. `SPEC.md` remains product
truth for data models, scheduling semantics and authority boundaries. The Stitch HTML is
prototype/reference code, not production frontend architecture.

The current baseline is **v4**: a dark, dense production-operations cockpit, using
`docs/ui` as visual inspiration while carrying the product semantics from `SPEC.md`.

API credentials were supplied via environment for generation and are not stored here.

## Screens

| Screen | Final HTML | Purpose |
|---|---|---|
| Stripboard dashboard | `01-stripboard-dashboard.v4.html` | Main First AD board view |
| Scene breakdown / review | `02-scene-breakdown-review.v4.html` | Gemini candidate records and activation |
| Replan options | `03-replan-options.v4.html` | Weather-triggered replan comparison |
| Grounded facts | `04-grounded-facts.v4.html` | Parallel source and value provenance |
| Coverage pickup | `05-coverage-pickup.v4.html` | Advisory finding → human ruling → pickup |
| Call sheet | `06-call-sheet.v4.html` | Second AD call sheet preview |
| Audit log | `07-audit-log.v4.html` | Authority and provenance ledger |

`manifest.json`, `iteration-*-manifest.json`, `*.prompt.md`, and the `*.v2`/`*.v3` HTML
are historical. Do not use them as a baseline.

Each screen's `*.v4.final.hires.png` is rendered from the local HTML at 2048 CSS px,
device scale 1. Every other `*.png` here is historical and shows uncorrected screens.

```sh
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --disable-gpu --hide-scrollbars --virtual-time-budget=10000 \
  --window-size=2048,1638 --force-device-scale-factor=1 \
  --screenshot=NAME.final.hires.png "file://$PWD/NAME.html"
```

Render at 2048 wide, not 1024 at 2× — these are fixed-viewport app shells that scroll
internally, and a narrower viewport collapses the strip columns into each other.
`04-grounded-facts` is rendered at 2048×2150 because it now carries six cards.

## How this is checked

`scripts/check_ui_reference.py` runs the checks a reader cannot eyeball, and is wired
into `scripts/check.sh` so it gates a commit:

- day/night tokens against the `DayNight` vocabulary;
- every daylight claim against `coverset.daylight` for the date it is labelled with;
- one scene number, one time of day, across every screen that names it — whether the
  screen renders it as a slugline, a strip pill or a `D/N` column;
- the provenance elements each screen is obliged to show, keyed to a requirement id;
- one schedule length across the whole set.

Each detector was confirmed to fail on an injected regression before being kept — a
check that cannot fail is worse than no check, which is what the previous version of
this file turned out to be.

```sh
uv run python scripts/check_ui_reference.py
```

The earlier version of this file was a prose checklist that tested for strings left
over from the previous iteration's bugs — no requirement ids, nothing tied to the
domain model. It reported fifteen passes while the stripboard showed a split day, two
screens showed a Savannah sunset 29 minutes off, and four requirements the archive
screens had satisfied were missing. Rows below cite the requirement they check.

## Requirement coverage

| ID | Requirement | Screen | Evidence |
|---|---|---|---|
| OUT-003 | Stripboard lists days, ordered work, scene ids, locations, day/night, cast, call/wrap | 01 | Day header carries `call → wrap (Nh)`; every strip carries its own window. |
| SOL-006 | A shoot day is a day shoot or a night shoot | 01 | Day 8 is all night work and says so; Day 9 is all day work. No day mixes the two. |
| SOL-005 | Company moves are counted and priced | 01 | Every move between two locations is banner'd and numbered `n of n`; header total matches. |
| DAY-001 | Daylight is computed, never retrieved | 01, 04, 06 | Values agree with `coverset.daylight`; the grounded-facts card states the family rejects URL provenance. |
| DAY-003 | Daylight bounds the prefix of a day | 01 | Day 9 leads with EXT/DAY work and states the last sun-bound wrap against sunset. |
| AUD-005 | Every active board records its constraint snapshot hash | 01, 03, 07 | Snapshot shown on the board, on each replan option, and on both validator entries. |
| SOL-004 | Locked days are immutable under replan | 03 | D1–D7 immutable; D8 shown as in progress, explicitly not yet locked. |
| AUD-006 | A schedule version records parent and new version | 03, 07 | Options carry `v4 → v5a`, `parent v4`; ledger records both versions on selection. |
| ACT-004 | Board selection requires First AD authority | 03 | Each viable option is gated `First AD Auth`. |
| ACT-005 / PIK-010 | Added-day cost stays pending until UPM approval | 03, 05, 07 | Weather waiver is not a cost approval; UPM gate stated on the pickup spec and recorded in the ledger. |
| GRD-003 | A dated value binds only with a source that states the date | 04 | Weather card quotes the source text containing the date; a second card refuses Day 17 outright. |
| GRD-004 | Date-independent families are exempt | 04 | Permit card records `EXEMPT · standing rule`. |
| GRD-006 | Weather excludes sources published before the horizon | 04 | Weather card records source publication time. |
| GRD-007 | Extract failure degrades to excerpt and is reported | 04 | Excerpt-fallback card records mode `excerpt`, never full content. |
| GRD-013 | Grounded values record query, timestamp, response id, hash, mode, units, validator | 04 | All present on the weather card; permit card carries span, id, hash, mode. |
| GRD-014 | Conflicting authoritative values cannot bind | 04 | Conflict card binds nothing and escalates. |
| SCN-001 | SceneRecord fields and vocabularies | 02 | Slugline, flags, page eighths, source span, confidence; time-of-day offers only `DayNight` members. |
| CON-004 | A candidate record cannot reach the solver | 02 | `Accept Scene Record` disabled while discrepancies stand; the scene under review is not on the board. |
| REV-001 / REV-003 | Findings are advisory; only a human decides | 05 | `Gemini can flag this; only a human can decide it.` above a separate Director panel. |
| PIK-002 / AUD-004 | Pickups trace to a named decision and finding | 05 | Authorisation trace names decision `RD-0142` and finding `GF-2291`. |
| PIK-008 | A pickup is schedulable only after a human completes the spec | 05 | Spec fields are blank and the copy states the gate. |
| OUT-004 | Call sheet content | 06 | Day, scenes, locations, cast calls, crew call, wrap, daylight, turnaround notes, permit notes, recipients, schedule version. |
| OUT-006 | Recipients are read-only | 06 | Recipients listed as `Viewers (Read-only)`. |
| SOL-007 | Objective is re-measured off the finished board | 07 | Validator entry records the two readings agreeing. |
| ACT-002 | An advisory agent is never a decider | 02, 05, 07 | Gemini rows are labelled advisory; every decision row names a human and a role. |

## Corrections applied to v4

Against the generated screens, keyed to what they violated:

- **01** — Day 8 mixed EXT/DAY with EXT/NIGHT and INT/NIGHT, which `solver.py` forbids;
  rebuilt as a night shoot. Added call/wrap windows (`OUT-003` had none). Added the
  second company move, which was invisible. Moved `Daylight OK` off night strips onto
  the day-bound ones. Corrected Day 14 daylight from `06:45/19:22` — no October date in
  Savannah has a 06:45 sunrise — to the computed `07:31/18:46`. Added the snapshot hash
  and a dark day, so the calendar visibly skips a day the index does not.
- **02** — `MORNING` removed as a scene time and as a selectable option. The record
  under review is now a scene the board has not placed. `Set Piece` replaced with
  slugline plus typed flags. Rejected candidate renumbered off a scheduled scene.
- **03** — Locked history claimed Day 8, which is being shot; split into D1–D7 immutable
  and D8 in progress. Scene ids normalised. Added version lineage and snapshot per option.
  Weather banner now names the date, not just the day index.
- **04** — Restored date-coverage proof, the refusal card, the excerpt-fallback card and
  the conflict card, all of which existed in `docs/ui` and were dropped. Added query,
  units, normalised value, source span, response id, hash, extraction mode and validator
  result to the weather record. Corrected daylight and labelled it with its date.
  Global status no longer reads `ALL SOURCES SYNCED` while a refusal and a conflict stand.
- **05** — Coverage moved onto scenes that have actually been shot (`REV-007`). `LATER`
  removed as a time of day. Added the authorisation trace and the note that night pickup
  work cannot land on a day shoot.
- **06** — Day counter reconciled to `Day 9 of 20`. Added turnaround notes and permit
  notes, both required by `OUT-004` and both absent. Cast call times now cover every
  performer working the day. Daylight corrected. Sun-bound work leads the day.
- **07** — Board proposal v5a now has its own validation entry; previously a proposal
  was generated with no report of its own. `Option B (Conservative)` corrected to
  `Option A` to match screen 03. Scene ids normalised. Legend says `Gemini Advisory`.
- **05, 06, 07** — `<style>` changed to `<style type="text/tailwindcss">`. The Tailwind
  Play CDN only processes `@apply` and `theme()` inside a marked block; with a plain
  `<style>` the browser discarded those rules as invalid CSS. The call sheet was
  rendering on a white background with unstyled, near-unreadable panels — in the
  published screenshots as well as locally. Nothing caught it because nothing rendered
  the files.

## Not covered by any screen

Four use cases have no screen at all. This is a gap in the reference set, not a
statement about the requirements:

| Use case | Missing | Requirements with no UI |
|---|---|---|
| UC-06 | Infeasibility view — the irreducible conflicting constraint subset | SOL-003, SOL-011 |
| UC-02 | Plain-English constraint entry → typed candidates → activation | CON-001, CON-002, CON-005 |
| UC-07 | Lock the day / record actuals | LCK-001…004, ACT-006 |
| UC-08 | UPM cost-approval view | ACT-008 |
| UC-09 | Script Supervisor raising a finding from the floor | REV-008 |

UC-06 is the most conspicuous: the conflict set is a headline capability and the words
"infeasible", "conflict" and "irreducible" appear nowhere in the screen set.

## Relationship to `docs/ui`

`docs/ui` is the earlier Stitch MCP set. Its **visual** language is the source of the v4
restyle. Its **provenance semantics were better than v4's** until the corrections above:
date-coverage proof, the refusal case, excerpt fallback, grounding conflict and the
constraint snapshot were all present there and absent here. Consult it before assuming
this directory is more complete.

## Remaining caveat

Sample scene, cast and location data is invented. Once MVP-0 fixture JSON is finalised,
normalise the screens against those fixtures and extend
`scripts/check_ui_reference.py` to assert against them rather than against a table
maintained by hand.
