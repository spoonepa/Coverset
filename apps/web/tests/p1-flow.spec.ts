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

let cast = [] as Array<Record<string, unknown>>;
let locations = [] as Array<Record<string, unknown>>;
let calendar = [] as string[];
let candidates: Candidate[] = [];

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

async function mockApi(page: Page) {
  cast = [];
  locations = [];
  calendar = [];
  candidates = [];
  await page.route("**/api/coverset/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/coverset", "");
    const method = request.method();

    if (path === "/productions" && method === "POST") {
      return route.fulfill(json(production));
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
    if (path === "/productions/prod_1/breakdowns" && method === "POST") {
      candidates = [{ ...readyCandidate }, { ...blockedCandidate }];
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
    if (path === "/productions/prod_1/boards/solve" && method === "POST") {
      return route.fulfill(
        json({
          id: "sched_1",
          status: "optimal",
          board_id: "board_1",
          error: "",
        }),
      );
    }
    if (path === "/boards/board_1" && method === "GET") {
      return route.fulfill(
        json({
          id: "board_1",
          solver_status: "optimal",
          stripboard: "STRIPBOARD\\n1. W-BRK-001",
          result: {
            days: [
              {
                date: "2026-09-14",
                assignments: [
                  {
                    work_id: "W-BRK-001",
                    location_id: "maya-s-apartment",
                    shoot_day: "2026-09-14",
                    sequence: 0,
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

  await page.getByRole("button", { name: "Create / reset production" }).click();
  await expect(page.getByText("Production setup ready.")).toBeVisible();

  await page.getByRole("textbox", { name: "Performer" }).fill("A. Idowu");
  await page.getByRole("button", { name: "Add cast" }).click();
  await expect(page.getByText("cast-maya — MAYA")).toBeVisible();

  await page.getByRole("button", { name: "Save calendar" }).click();
  await expect(page.getByText("Shooting calendar saved.")).toBeVisible();

  await page.getByLabel("Breakdown mode").selectOption("fixture");
  await page.getByLabel("PDF or text screenplay").setInputFiles({
    name: "fixture.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("INT. MAYA'S APARTMENT - NIGHT"),
  });
  await page.getByRole("button", { name: "Upload and break down" }).click();
  await expect(
    page.getByText("Breakdown complete. Review candidates before solving."),
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
  await expect(page.getByText("Accepted scenes solved.")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Board: optimal" }),
  ).toBeVisible();
  await expect(page.getByText("W-BRK-001 @ maya-s-apartment")).toBeVisible();
});
