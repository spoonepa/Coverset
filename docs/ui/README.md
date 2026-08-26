# UI — Stitch MCP attempt

One screen, generated through the Stitch **MCP server** against project
`13355501855075038394`.

This is **not** the UI baseline. The complete seven-screen set, generated through
`@google/stitch-sdk` across three iteration passes, is in `docs/ui-sling/` — see
`docs/ui-sling/validation.md` for the reference table. Use that for visual direction.

What is kept here is one screen and, more usefully, what the MCP route turned out to do.

## Files

| File | What it is |
|---|---|
| `01-stripboard-dashboard.html` / `.png` | Initial generation |
| `01-stripboard-dashboard.v2.html` / `.v2.png` | After five corrections — the better of the two |

The v2 corrections were: removing a stray text artifact; adding explicit `LOCKED`
(green, padlock) and `PLANNED` (blue) status pills, because colour-only spines made
locked and planned days indistinguishable; unwrapping scene ids; replacing a single
green tick with named `Cast · Permit · Daylight · Turnaround` badges; and rendering the
truncated advisory badge in full as `Gemini Advisory · Coverage Needs Review`.

Lock status mattered most. "What is locked?" is one of the four questions the design
direction says a tired AD must answer instantly, and immutability of shot days is the
spine of the whole replan story — if the board does not show it, the core claim is not
visible.

## What survived into the render

Worth noting because it is the part most likely to be lost:

- Daylight reads `Computed · NOAA solar algorithm` and shows **no source URL**, because
  it is arithmetic rather than a web fact.
- Weather carries `Grounded by Parallel` with `View Sources`; permits cite a source
  document. Retrieved facts look retrieved.
- Indigo is used only for the Gemini advisory badge, never for a decision.
- The audit strip states the hard-constraint count and the constraint snapshot hash.

## Behaviour of the MCP route

Recorded because someone will try it again.

**A timeout does not mean failure.** `generate_screen_from_text` timed out on every
call. The first one still appeared in `list_screens` about two minutes later. Do not
retry on timeout — poll.

**Consecutive submissions stopped producing anything.** After the first success, seven
further generations were fired in close succession and none ever landed, including one
sent without a `designSystem` parameter, which rules the design system out as the cause.
Most likely rate limiting. Space submissions out instead of batching them.

**`update_design_system` reported success without persisting.** It echoed the submitted
markdown back in its response, but the stored asset kept the original prose: two
corrections were silently discarded, and `labelFont` was changed from `JETBRAINS_MONO`
to `PUBLIC_SANS` unasked — which would undermine the tabular figures a scheduling board
depends on. Both update calls returned `sessions/...` resource names rather than the
asset name. Treat the design system as unreliable for carrying intent; put style
constraints inline in each screen prompt.

**`edit_screens` is reliable** and returns synchronously with the finished screen.
Iterating on an existing screen worked every time; generating a new one mostly did not.

**Edited screens can end up detached.** The v2 edit returned a complete screen with HTML
and a screenshot, but that screen never appeared in the project's `screenInstances` or
in `list_screens`. Download artifacts when you get them rather than assuming you can
list them later — the files here exist because of that.
