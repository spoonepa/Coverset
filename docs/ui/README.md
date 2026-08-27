# UI — Stitch MCP

Seven screens generated through the Stitch **MCP server**, project
`13355501855075038394`, from `../../STITCH_PROMPT.md`.

A second set exists in `docs/ui-sling/`, generated through `@google/stitch-sdk`.
**`docs/ui-sling` is the implementation-reference baseline** and its screens carry the
darker, denser style these ones established.

Read that as a statement about which directory is maintained, not about which one was
more correct. The v4 restyle dropped four provenance elements these screens had —
date-coverage proof and the refusal case, excerpt fallback, grounding conflict, and the
constraint snapshot hash — along with the call/wrap windows `OUT-003` requires. They
have since been restored there; see `docs/ui-sling/validation.md` for what changed and
`scripts/check_ui_reference.py` for what is now enforced. Where the two disagree on
product semantics, check against `SPEC.md` rather than assuming either is right.

## Screens

| File | Screen |
|---|---|
| `01-stripboard-dashboard.html` / `.png` | Stripboard, initial generation |
| `01-stripboard-dashboard.v2.html` / `.v2.png` | Stripboard after five corrections — use this one |
| `02-scene-breakdown` | Candidate scene records and the activation gate |
| `03-grounded-facts` | Parallel source and value provenance |
| `04-replan-options` | Weather-triggered replan comparison |
| `05-coverage-review` | Advisory finding → human ruling → authorised pickup |
| `06-call-sheet` | Day 15 call sheet for Second AD distribution |
| `07-audit-log` | Authority and provenance, inspectable |

## What survived into the renders

The distinctions most likely to be lost in generation all held:

- **Computed is not retrieved.** Daylight reads `Computed · NOAA solar algorithm` and
  shows no source URL, in the stripboard, grounded facts and call sheet. Weather and
  permits carry `Grounded by Parallel` with sources, retrieval mode and validator result.
- **Advisory is not decision.** Indigo appears only on Gemini findings. Coverage review
  states `Gemini cannot decide. Human ruling required.` beneath the finding, then a
  separate "Your ruling" panel attributed to Director · Maya Chen, then a green
  `Authorised by Director Maya Chen` banner on the resulting pickup. The visual order is
  the argument.
- **Proposal is not validated board.** Replan options distinguishes `Solver Proposed`
  from validated boards, and gates the option that adds a shoot day behind UPM approval.
- **Locked is legible.** `LOCKED` and `PLANNED` are explicit text pills, never colour
  alone.
- **Excerpt is not full content.** Grounded facts shows both `Extracted Full Content`
  and `Excerpt Fallback`, so a degraded retrieval is visible rather than silent.

The stripboard v2 corrections were: removing a stray text artifact; adding the status
pills, because colour-only spines made locked and planned days indistinguishable;
unwrapping scene ids; replacing a single tick with named
`Cast · Permit · Daylight · Turnaround` badges; and rendering the truncated advisory
badge in full.

## Behaviour of the MCP route

**Generation is slow, and a timeout tells you nothing.** Every
`generate_screen_from_text` call timed out at the MCP layer. The work continued
server-side regardless. The first screen appeared after about two minutes; the rest took
considerably longer — long enough that polling at two, five and ten minutes showed
nothing and looked like failure.

That misled the session badly. Seven screens were declared failed and three separate
causes were hypothesised — rate limiting, a bad design system asset, quota contention
with a concurrent session — before it turned out all seven had generated normally. The
only real problem was polling too early and treating absence as failure.

So: **do not retry on timeout, and do not conclude failure from an empty
`list_screens`.** Poll for considerably longer than feels reasonable. Retrying instead
produced three duplicate Scene Breakdown screens in this project.

**`update_design_system` reported success without persisting.** It echoed the submitted
markdown back, but the stored asset kept its original prose: two corrections were
silently discarded, and `labelFont` changed from `JETBRAINS_MONO` to `PUBLIC_SANS`
unasked, which would undermine the tabular figures a board depends on. Both update calls
returned `sessions/...` resource names rather than the asset name. Put style constraints
inline in each screen prompt rather than relying on the design system to carry them —
that is what these screens do, and it worked.

**`edit_screens` is reliable** and returns synchronously with the finished screen.
Iterating beats regenerating.
