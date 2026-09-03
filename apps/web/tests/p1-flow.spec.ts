import { expect, test, type Page, type Route } from "@playwright/test";

type Candidate = {
  id: string;
  scene_id: string;
  scene_number: string;
  slugline: string;
  int_ext: string;
  day_night: string;
  location_ref: string;
  page_eighths: number;
  cast_ids: string[];
  flags: Record<string, boolean>;
  source_page_range: string;
  proposal_scene: Record<string, unknown>;
  confidence: number;
  status: string;
  accepted: boolean;
  rejected: boolean;
  schedulable: boolean;
  resolution_errors: string[];
  number_synthesized: boolean;
};

const production = {
  id: "prod_1",
  title: "The Ferry Job",
  cast_count: 0,
  location_count: 0,
  shoot_day_count: 0,
};

const actorClaims = {
  name: "Authenticated Operator",
  email: "operator@coverset.local",
  role: "first_ad",
  roles: [
    "first_ad",
    "second_ad",
    "script_supervisor",
    "director",
    "upm",
    "line_producer",
  ],
  authenticated: true,
  source: "test-claim",
};

let cast = [] as Array<Record<string, unknown>>;
let locations = [] as Array<Record<string, unknown>>;
let calendar = [] as string[];
let candidates: Candidate[] = [];
let jobs = [] as Array<Record<string, unknown>>;
let callSheets = [] as Array<Record<string, unknown>>;

const readyCandidate: Candidate = {
  id: "scene_ready",
  scene_id: "BRK-001",
  scene_number: "1",
  slugline: "INT. MAYA'S APARTMENT - NIGHT",
  int_ext: "int",
  day_night: "night",
  location_ref: "maya-s-apartment",
  page_eighths: 8,
  cast_ids: ["cast-maya"],
  flags: { stunts: false, minors: false, vfx: false },
  source_page_range: "p. 1",
  proposal_scene: { cast_ids: ["cast-maya"] },
  confidence: 0.95,
  status: "candidate",
  accepted: false,
  rejected: false,
  schedulable: false,
  resolution_errors: ["unresolved cast cue: DEV"],
  number_synthesized: false,
};

const blockedCandidate: Candidate = {
  id: "scene_blocked",
  scene_id: "BRK-002",
  scene_number: "2",
  slugline: "EXT. UNKNOWN PIER - DAY",
  int_ext: "ext",
  day_night: "day",
  location_ref: "UNKNOWN PIER",
  page_eighths: 3,
  cast_ids: ["cast-maya"],
  flags: { stunts: true, minors: false, vfx: false },
  source_page_range: "p. 2",
  proposal_scene: { location_ref: "UNKNOWN PIER" },
  confidence: 0.81,
  status: "candidate",
  accepted: false,
  rejected: false,
  schedulable: false,
  resolution_errors: ["unresolved location: UNKNOWN PIER"],
  number_synthesized: false,
};

function json(payload: unknown, status = 200) {
  return {
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  };
}

function mockCallSheet(shootDate: string): Record<string, unknown> {
  return {
    id: "cs_1",
    production_id: "prod_1",
    board_id: "board_1",
    schedule_run_id: "sched_1",
    shoot_date: shootDate,
    generated_by_name: "T. Nguyen",
    generated_by_role: "second_ad",
    created_at: "2026-09-01T00:00:00Z",
    rendered_text: "CALL SHEET CS-20260914-board1\nRecipients read_only\n",
    payload: {
      call_sheet_version: "CS-20260914-board1",
      shoot_date: shootDate,
      crew_call: "2026-09-14T07:00:00-04:00",
      wrap_estimate: "2026-09-14T08:00:00-04:00",
      scenes: [
        {
          scene_id: "BRK-001",
          location_name: "Maya's Apartment",
          planned_call_time: "2026-09-14T07:00:00-04:00",
          planned_wrap_time: "2026-09-14T08:00:00-04:00",
          cast: [{ character: "MAYA" }],
          flags: {},
        },
      ],
      cast_calls: [
        {
          cast_id: "cast-maya",
          performer: "A. Idowu",
          character: "MAYA",
          call_time: "2026-09-14T07:00:00-04:00",
          wrap_time: "2026-09-14T08:00:00-04:00",
          is_minor: false,
          work_hours: 1,
        },
      ],
      daylight_windows: [
        {
          location_name: "Maya's Apartment",
          sunrise: "2026-09-14T06:35:00-04:00",
          sunset: "2026-09-14T19:05:00-04:00",
          algorithm: "astral",
        },
      ],
      turnaround_notes: [
        {
          display: "Crew",
          rest_hours: 12,
          minimum_hours: 10,
          satisfied: true,
        },
      ],
      permit_notes: [],
      recipients: [
        {
          recipient_type: "crew",
          display_name: "Crew distribution",
          authority: "read_only",
        },
      ],
    },
  };
}

async function mockApi(page: Page) {
  cast = [];
  locations = [];
  calendar = [];
  candidates = [];
  jobs = [];
  callSheets = [];
  await page.route("**/api/coverset/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/coverset", "");
    const method = request.method();

    if (path === "/productions" && method === "POST") {
      const payload = request.postDataJSON() as {
        title: string;
        seed_demo_data?: boolean;
      };
      expect(payload.title).toBe("Operator production");
      expect(payload.seed_demo_data).toBe(false);
      return route.fulfill(json({ ...production, title: payload.title }));
    }
    if (path === "/session" && method === "GET") {
      return route.fulfill(json(actorClaims));
    }
    if (path === "/productions/prod_1" && method === "GET") {
      return route.fulfill(
        json({
          ...production,
          cast_count: cast.length,
          location_count: locations.length,
          shoot_day_count: calendar.length,
        }),
      );
    }
    if (path === "/productions/prod_1/cast" && method === "GET") {
      return route.fulfill(json(cast));
    }
    if (path === "/productions/prod_1/cast" && method === "POST") {
      const payload = request.postDataJSON() as Record<string, unknown>;
      cast.push({
        id: `cast_${cast.length}`,
        production_id: "prod_1",
        ...payload,
      });
      return route.fulfill(json(cast[cast.length - 1]));
    }
    if (path === "/productions/prod_1/locations" && method === "GET") {
      return route.fulfill(json(locations));
    }
    if (path === "/productions/prod_1/locations" && method === "POST") {
      const payload = request.postDataJSON() as Record<string, unknown>;
      locations.push({
        id: `loc_${locations.length}`,
        production_id: "prod_1",
        ...payload,
      });
      return route.fulfill(json(locations[locations.length - 1]));
    }
    if (path === "/productions/prod_1/calendar" && method === "GET") {
      return route.fulfill(
        json({ production_id: "prod_1", shoot_dates: calendar }),
      );
    }
    if (path === "/productions/prod_1/calendar" && method === "PUT") {
      const payload = request.postDataJSON() as { shoot_dates: string[] };
      calendar = payload.shoot_dates;
      return route.fulfill(
        json({ production_id: "prod_1", shoot_dates: calendar }),
      );
    }
    if (path === "/productions/prod_1/jobs" && method === "GET") {
      return route.fulfill(json(jobs));
    }
    if (path === "/productions/prod_1/grounding" && method === "GET") {
      return route.fulfill(json([]));
    }
    if (path === "/productions/prod_1/grounded-values" && method === "GET") {
      return route.fulfill(json([]));
    }
    if (
      path === "/productions/prod_1/constraint-proposals" &&
      method === "GET"
    ) {
      return route.fulfill(json([]));
    }
    if (path === "/productions/prod_1/constraints" && method === "GET") {
      return route.fulfill(json([]));
    }
    if (path === "/productions/prod_1/locks" && method === "GET") {
      return route.fulfill(json([]));
    }
    if (path === "/productions/prod_1/monitored-sources" && method === "GET") {
      return route.fulfill(json([]));
    }
    if (path === "/productions/prod_1/monitor/findings" && method === "GET") {
      return route.fulfill(json([]));
    }
    if (path === "/productions/prod_1/replan-requests" && method === "GET") {
      return route.fulfill(json([]));
    }
    if (path === "/productions/prod_1/schedule-diffs" && method === "GET") {
      return route.fulfill(json([]));
    }
    if (path === "/productions/prod_1/schedule-runs" && method === "GET") {
      return route.fulfill(json([]));
    }
    if (path === "/productions/prod_1/coverage-items" && method === "GET") {
      return route.fulfill(json([]));
    }
    if (path === "/productions/prod_1/coverage-findings" && method === "GET") {
      return route.fulfill(json([]));
    }
    if (path === "/productions/prod_1/pickup-tasks" && method === "GET") {
      return route.fulfill(json([]));
    }
    if (path === "/productions/prod_1/cost-approvals" && method === "GET") {
      return route.fulfill(json([]));
    }
    if (path === "/productions/prod_1/audit" && method === "GET") {
      return route.fulfill(json([]));
    }
    if (path === "/productions/prod_1/screenplays" && method === "POST") {
      return route.fulfill(
        json({
          id: "asset_1",
          filename: "fixture.txt",
          normalized_text_uri: "file://normalized",
          extraction_error: "",
        }),
      );
    }
    if (path === "/productions/prod_1/breakdowns/jobs" && method === "POST") {
      candidates = [{ ...readyCandidate }, { ...blockedCandidate }];
      const job = {
        id: "job_breakdown",
        production_id: "prod_1",
        job_type: "breakdown",
        target_id: "asset_1",
        status: "queued",
        attempts: 0,
        error: "",
        result: {},
      };
      jobs = [job];
      return route.fulfill(json(job));
    }
    if (path === "/jobs/job_breakdown" && method === "GET") {
      const job = {
        ...jobs[0],
        status: "complete",
        attempts: 1,
        result: { breakdown_run_id: "brk_1", status: "complete" },
      };
      jobs = [job];
      return route.fulfill(json(job));
    }
    if (path === "/breakdowns/brk_1" && method === "GET") {
      return route.fulfill(
        json({
          id: "brk_1",
          production_id: "prod_1",
          screenplay_asset_id: "asset_1",
          status: "complete",
          agent_mode: "fixture",
          error: "",
          unresolved_locations: ["UNKNOWN PIER"],
          unresolved_cast: ["DEV"],
          candidates,
        }),
      );
    }
    if (path === "/scene-candidates/scene_ready" && method === "PATCH") {
      const payload = request.postDataJSON() as Partial<Candidate>;
      candidates = candidates.map((candidate) =>
        candidate.id === "scene_ready"
          ? {
              ...candidate,
              ...payload,
              cast_ids: payload.cast_ids ?? candidate.cast_ids,
              schedulable: true,
              resolution_errors: [],
            }
          : candidate,
      );
      return route.fulfill(json(candidates[0]));
    }
    if (path === "/scene-candidates/scene_ready/review" && method === "PATCH") {
      candidates = candidates.map((candidate) =>
        candidate.id === "scene_ready"
          ? { ...candidate, accepted: true, status: "active" }
          : candidate,
      );
      return route.fulfill(json(candidates[0]));
    }
    if (
      path === "/breakdowns/brk_1/candidates/batch-accept" &&
      method === "POST"
    ) {
      candidates = candidates.map((candidate) =>
        candidate.schedulable
          ? { ...candidate, accepted: true, status: "active" }
          : candidate,
      );
      return route.fulfill(
        json({
          accepted: ["scene_ready"],
          skipped: { scene_blocked: ["unresolved location: UNKNOWN PIER"] },
          candidates,
        }),
      );
    }
    if (path === "/productions/prod_1/boards/solve/jobs" && method === "POST") {
      const job = {
        id: "job_schedule",
        production_id: "prod_1",
        job_type: "schedule",
        target_id: "prod_1",
        status: "queued",
        attempts: 0,
        error: "",
        result: {},
      };
      jobs = [job, ...jobs];
      return route.fulfill(json(job));
    }
    if (path === "/jobs/job_schedule" && method === "GET") {
      const job = {
        ...jobs[0],
        status: "complete",
        attempts: 1,
        result: {
          schedule_run_id: "sched_1",
          board_id: "board_1",
          status: "optimal",
        },
      };
      jobs = [job, ...jobs.slice(1)];
      return route.fulfill(json(job));
    }
    if (path === "/schedule-runs/sched_1" && method === "GET") {
      return route.fulfill(
        json({
          id: "sched_1",
          production_id: "prod_1",
          status: "optimal",
          board_id: "board_1",
          error: "",
          diagnostics: [],
          input_hash: "hash",
          conflict: {},
        }),
      );
    }
    if (path === "/boards/board_1/call-sheets" && method === "GET") {
      return route.fulfill(json(callSheets));
    }
    if (path === "/boards/board_1/call-sheets" && method === "POST") {
      const payload = request.postDataJSON() as {
        shoot_date: string;
        actor_name: string;
        actor_role: string;
      };
      expect(payload.actor_name).toBe("Authenticated Operator");
      if (payload.actor_role !== "second_ad") {
        return route.fulfill(
          json({ detail: "may not generate call sheet" }, 403),
        );
      }
      const sheet = mockCallSheet(payload.shoot_date);
      callSheets = [sheet];
      return route.fulfill(json(sheet));
    }
    if (path === "/call-sheets/cs_1/export" && method === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "text/plain",
        body: "CALL SHEET CS-20260914-board1\n",
      });
    }
    if (path === "/boards/board_1" && method === "GET") {
      return route.fulfill(
        json({
          id: "board_1",
          solver_status: "optimal",
          stripboard: "STRIPBOARD\\n1. W-BRK-001",
          result: {
            explanation_traces: [
              {
                constraint_id: "SYN-DAYLIGHT",
                family: "daylight",
                policy: "hard",
                satisfied: true,
                detail: "",
                source: "algorithmic daylight bound",
              },
            ],
            strips: [
              {
                work_id: "W-BRK-001",
                location_id: "maya-s-apartment",
                shoot_day: "2026-09-14",
                sequence: 0,
                planned_call_time: "2026-09-14T07:00:00-04:00",
                planned_wrap_time: "2026-09-14T08:00:00-04:00",
                scene_id: "BRK-001",
                kind: "scene",
                duration_minutes: 60,
                day_night: "night",
                flags: { stunts: false, minors: false, vfx: false },
                requires_daylight: false,
                location: {
                  id: "maya-s-apartment",
                  name: "Maya's Apartment",
                  place: "Brooklyn, NY",
                },
                cast: [
                  {
                    id: "cast-maya",
                    character: "MAYA",
                    performer: "A. Idowu",
                  },
                ],
                cast_ids: ["cast-maya"],
              },
            ],
            days: [
              {
                date: "2026-09-14",
                call_time: "2026-09-14T07:00:00-04:00",
                wrap_time: "2026-09-14T08:00:00-04:00",
                company_moves: 0,
                assignments: [
                  {
                    work_id: "W-BRK-001",
                    location_id: "maya-s-apartment",
                    shoot_day: "2026-09-14",
                    sequence: 0,
                  },
                ],
                strips: [
                  {
                    work_id: "W-BRK-001",
                    location_id: "maya-s-apartment",
                    shoot_day: "2026-09-14",
                    sequence: 0,
                    planned_call_time: "2026-09-14T07:00:00-04:00",
                    planned_wrap_time: "2026-09-14T08:00:00-04:00",
                    scene_id: "BRK-001",
                    kind: "scene",
                    duration_minutes: 60,
                    day_night: "night",
                    flags: { stunts: false, minors: false, vfx: false },
                    requires_daylight: false,
                    location: {
                      id: "maya-s-apartment",
                      name: "Maya's Apartment",
                      place: "Brooklyn, NY",
                    },
                    cast: [
                      {
                        id: "cast-maya",
                        character: "MAYA",
                        performer: "A. Idowu",
                      },
                    ],
                    cast_ids: ["cast-maya"],
                  },
                ],
              },
            ],
          },
        }),
      );
    }

    return route.fulfill(
      json({ detail: `Unhandled mock ${method} ${path}` }, 500),
    );
  });
}

test("production setup, candidate edit, accept, and solve flow", async ({
  page,
}) => {
  await mockApi(page);
  await page.goto("/");

  await expect(page.getByLabel("Title")).toHaveValue("");
  await expect(
    page.getByRole("button", { name: "Create / reset production" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Run fixture demo" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Seed demo cast, locations, and dates"),
  ).toHaveCount(0);

  await page.getByLabel("Title").fill("Operator production");
  await page.getByRole("button", { name: "Create / reset production" }).click();
  await expect(page.getByText("Production setup ready.")).toBeVisible();

  await page.getByRole("textbox", { name: "Cast ID" }).fill("cast-maya");
  await page.getByRole("textbox", { name: "Character" }).fill("MAYA");
  await page.getByRole("textbox", { name: "Performer" }).fill("A. Idowu");
  await page.getByRole("button", { name: "Add cast" }).click();
  await expect(page.getByText("cast-maya — MAYA")).toBeVisible();

  await page.getByRole("button", { name: "Save calendar" }).click();
  await expect(page.getByText("Shooting calendar saved.")).toBeVisible();

  await page.getByLabel("PDF or text screenplay").setInputFiles({
    name: "fixture.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("INT. MAYA'S APARTMENT - NIGHT"),
  });
  await page.getByRole("button", { name: "Upload and break down" }).click();
  await expect(
    page.getByText("Breakdown job complete. Review candidates before solving."),
  ).toBeVisible();
  await expect(page.getByText("unresolved cast cue: DEV")).toBeVisible();
  await expect(
    page.getByText("unresolved location: UNKNOWN PIER"),
  ).toBeVisible();

  const readyCard = page
    .getByRole("article")
    .filter({ hasText: "INT. MAYA'S APARTMENT" });
  await readyCard.getByText("Edit candidate").click();
  await readyCard
    .getByLabel("Cast IDs, comma-separated")
    .fill("cast-maya, cast-dev");
  await readyCard.getByRole("button", { name: "Save edit" }).click();
  await expect(page.getByText("Candidate resolved.")).toBeVisible();

  await readyCard.getByRole("button", { name: "Accept" }).click();
  await expect(page.getByText("Candidate accepted.")).toBeVisible();

  await page.getByRole("button", { name: "Batch accept ready" }).click();
  await expect(page.getByText("Accepted 1; skipped 1.")).toBeVisible();

  await page.getByRole("button", { name: "Solve accepted" }).click();
  await expect(
    page.getByText("Accepted scenes solved by the worker."),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Board: optimal" }),
  ).toBeVisible();
  await expect(
    page.getByText("Maya's Apartment", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Constraint explanation traces")).toBeVisible();

  await page.getByRole("button", { name: "Generate call sheet" }).click();
  await expect(
    page.getByText("Call sheet generated for read-only distribution."),
  ).toBeVisible();
  await expect(
    page.locator("strong", { hasText: "CS-20260914-board1" }),
  ).toBeVisible();
  await expect(page.getByText("Cast calls")).toBeVisible();
  await expect(page.getByRole("link", { name: "Text export" })).toHaveAttribute(
    "href",
    "/api/coverset/call-sheets/cs_1/export?format=text",
  );
});
