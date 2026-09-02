import { expect, test, type Page, type Route } from "@playwright/test";

type Json = Record<string, unknown>;

const production = {
  id: "prod_1",
  title: "The Ferry Job",
  cast_count: 1,
  location_count: 1,
  shoot_day_count: 2,
};

const board = {
  id: "board_1",
  production_id: "prod_1",
  schedule_run_id: "sched_1",
  solver_status: "optimal",
  approval_state: "approved",
  stripboard: "STRIPBOARD\n1. W-BRK-001",
  result: {
    objective: {
      company_moves: 0,
      holding_days: 1,
      overtime_hours: 0,
    },
    explanation_traces: [
      {
        work_id: "W-BRK-001",
        constraint_id: "SYN-DAYLIGHT",
        reason: "algorithmic daylight bound",
      },
    ],
    days: [
      { date: "2026-09-14", kind: "night" },
      { date: "2026-09-15", kind: "day" },
    ],
    strips: [
      {
        work_id: "W-BRK-001",
        scene_id: "BRK-001",
        scene_number: "1",
        shoot_day: "2026-09-14",
        sequence: 0,
        location_id: "maya-s-apartment",
        zone: "Brooklyn",
        day_night: "night",
        cast_ids: ["cast-maya"],
        page_eighths: 8,
        minutes: 60,
        planned_call_time: "2026-09-14T07:00:00-04:00",
        planned_wrap_time: "2026-09-14T08:00:00-04:00",
        kind: "scene",
      },
    ],
  },
};

let breakdowns: Json[];
let constraintProposals: Json[];
let constraints: Json[];
let grounding: Json[];
let groundedValues: Json[];
let locks: Json[];
let monitoredSources: Json[];
let monitorFindings: Json[];
let replanRequests: Json[];
let scheduleDiffs: Json[];
let coverageItems: Json[];
let coverageFindings: Json[];
let pickupTasks: Json[];
let costApprovals: Json[];
let callSheets: Json[];
let audit: Json[];
let coverageItem: Json | null;
let coverageFinding: Json | null;
let pickupTask: Json | null;

function resetState() {
  breakdowns = [];
  constraintProposals = [];
  constraints = [];
  grounding = [];
  groundedValues = [];
  locks = [];
  monitoredSources = [];
  monitorFindings = [];
  replanRequests = [];
  scheduleDiffs = [];
  coverageItems = [];
  coverageFindings = [];
  pickupTasks = [];
  costApprovals = [];
  callSheets = [];
  audit = [
    {
      id: "audit_1",
      production_id: "prod_1",
      event_type: "board.solved",
      actor: "system",
      payload: { board_id: "board_1" },
      created_at: "2026-09-01T00:00:00Z",
    },
  ];
  coverageItem = null;
  coverageFinding = null;
  pickupTask = null;
}

function json(payload: unknown, status = 200) {
  return {
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  };
}

function mockCallSheet(role: string) {
  return {
    id: "cs_1",
    production_id: "prod_1",
    board_id: "board_1",
    schedule_run_id: "sched_1",
    shoot_date: "2026-09-14",
    generated_by_name: role === "second_ad" ? "T. Nguyen" : "Developer",
    generated_by_role: role,
    rendered_text: "CALL SHEET CS-20260914-board1\nRecipients read_only\n",
    payload: {
      shoot_date: "2026-09-14",
      scenes: [{ scene_id: "BRK-001", location_name: "Maya's Apartment" }],
      cast_calls: [{ cast_id: "cast-maya", performer: "A. Idowu" }],
      turnaround_notes: [{ display: "Crew", rest_hours: 12 }],
      recipients: [{ name: "Producer", authority: "read_only" }],
    },
  };
}

function mockDiff(replanRequestId: string | null) {
  return {
    id: "sdiff_1",
    production_id: "prod_1",
    base_board_id: "board_1",
    revised_board_id: "board_2",
    replan_request_id: replanRequestId,
    diff: {
      added_days: ["2026-09-15"],
      added_pickups: ["pickup-ptask_1"],
      moved_scenes: [],
      changed_call_times: [],
    },
    required_approvals: ["upm_or_line_producer_cost_approval"],
    cost_delta: 6500,
    rendered_text: "Added pickup pickup-ptask_1 on 2026-09-15.",
  };
}

async function mockApi(page: Page) {
  resetState();
  await page.route("**/api/coverset/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/coverset", "");
    const method = request.method();

    if (path === "/productions/prod_1" && method === "GET")
      return route.fulfill(json(production));
    if (path === "/productions/prod_1/jobs" && method === "GET")
      return route.fulfill(json([]));
    if (path === "/productions/prod_1/breakdowns" && method === "GET")
      return route.fulfill(json(breakdowns));
    if (path === "/productions/prod_1/grounding" && method === "GET")
      return route.fulfill(json(grounding));
    if (path === "/productions/prod_1/grounded-values" && method === "GET")
      return route.fulfill(json(groundedValues));
    if (path === "/productions/prod_1/constraint-proposals" && method === "GET")
      return route.fulfill(json(constraintProposals));
    if (path === "/productions/prod_1/constraints" && method === "GET")
      return route.fulfill(json(constraints));
    if (path === "/productions/prod_1/locks" && method === "GET")
      return route.fulfill(json(locks));
    if (path === "/productions/prod_1/monitored-sources" && method === "GET")
      return route.fulfill(json(monitoredSources));
    if (path === "/productions/prod_1/monitor/findings" && method === "GET")
      return route.fulfill(json(monitorFindings));
    if (path === "/productions/prod_1/replan-requests" && method === "GET")
      return route.fulfill(json(replanRequests));
    if (path === "/productions/prod_1/schedule-diffs" && method === "GET")
      return route.fulfill(json(scheduleDiffs));
    if (path === "/productions/prod_1/coverage-items" && method === "GET")
      return route.fulfill(json(coverageItems));
    if (path === "/productions/prod_1/coverage-findings" && method === "GET")
      return route.fulfill(json(coverageFindings));
    if (path === "/productions/prod_1/pickup-tasks" && method === "GET")
      return route.fulfill(json(pickupTasks));
    if (path === "/productions/prod_1/cost-approvals" && method === "GET")
      return route.fulfill(json(costApprovals));
    if (path === "/productions/prod_1/audit" && method === "GET")
      return route.fulfill(json(audit));
    if (path === "/boards/board_1" && method === "GET")
      return route.fulfill(json(board));
    if (path === "/boards/board_2" && method === "GET") {
      const approved = costApprovals.some(
        (approval) =>
          approval.board_id === "board_2" && approval.decision === "approved",
      );
      return route.fulfill(
        json({
          ...board,
          id: "board_2",
          approval_state: approved ? "approved" : "pending_cost_approval",
          result: {
            ...board.result,
            approval_state: approved ? "approved" : "pending_cost_approval",
            required_approvals: ["upm_or_line_producer_cost_approval"],
            cost_delta: 6500,
          },
        }),
      );
    }
    if (path === "/boards/board_1/call-sheets" && method === "GET")
      return route.fulfill(json(callSheets));
    if (path === "/boards/board_2/cost-approvals" && method === "GET")
      return route.fulfill(
        json(
          costApprovals.filter((approval) => approval.board_id === "board_2"),
        ),
      );
    if (path === "/grounding/evidence_1/values" && method === "GET")
      return route.fulfill(json(groundedValues));

    if (
      path === "/productions/prod_1/constraints/translate" &&
      method === "POST"
    ) {
      constraintProposals = [
        {
          id: "proposal_1",
          production_id: "prod_1",
          source_text: "Maximum daily hours 11",
          status: "needs_review",
          confidence: 0.92,
          payload: { expression_type: "maximum_daily_hours", hours: 11 },
          validation_errors: [],
          created_by_name: "R. Okonkwo",
          accepted_by_name: null,
          accepted_by_role: null,
          accepted_constraint_id: null,
        },
      ];
      return route.fulfill(json(constraintProposals));
    }
    if (
      path === "/constraint-proposals/proposal_1/accept" &&
      method === "POST"
    ) {
      const row = {
        id: "constraint_1",
        production_id: "prod_1",
        constraint_id: "MAX-HOURS-11",
        family: "turnaround",
        policy: "hard",
        active: false,
        constraint: { expression: { type: "maximum_daily_hours", hours: 11 } },
        provenance: { type: "human", accepted_by: { role: "first_ad" } },
      };
      constraints = [row];
      constraintProposals = constraintProposals.map((proposal) =>
        proposal.id === "proposal_1"
          ? {
              ...proposal,
              status: "accepted",
              accepted_by_name: "R. Okonkwo",
              accepted_by_role: "first_ad",
              accepted_constraint_id: row.id,
            }
          : proposal,
      );
      return route.fulfill(json(row));
    }
    if (path === "/constraints/constraint_1/activation" && method === "PATCH") {
      constraints = [{ ...constraints[0], active: true }];
      return route.fulfill(json(constraints[0]));
    }

    if (path === "/productions/prod_1/grounding" && method === "POST") {
      const row = {
        id: "evidence_1",
        production_id: "prod_1",
        location_id: "maya-s-apartment",
        fact_kind: "weather",
        target_date: "2026-03-17",
        status: "accepted",
        error: "",
        evidence: {
          source_url: "https://weather.example/source",
          quote: "Rain risk for 2026-03-17 is high",
          source_span: "paragraph 2",
          query: "weather risk",
        },
      };
      grounding = [row];
      return route.fulfill(json(row));
    }
    if (path === "/grounding/evidence_1/values" && method === "POST") {
      const value = {
        id: "gval_1",
        production_id: "prod_1",
        evidence_id: "evidence_1",
        fact_kind: "weather",
        location_id: "maya-s-apartment",
        target_date: "2026-03-17",
        normalized_value: { quote: "Rain risk for 2026-03-17 is high" },
        units: "risk",
        source_url: "https://weather.example/source",
        source_quote: "Rain risk for 2026-03-17 is high",
        source_span: "paragraph 2",
        query: "weather risk",
        provider_response_id: "resp_1",
        content_hash: "hash",
        derived_from: "excerpt",
        validator_result: { passed: true },
        covering_date: true,
        context_source_urls: ["https://weather.example/source"],
      };
      groundedValues = [value];
      return route.fulfill(json(value));
    }

    if (path === "/productions/prod_1/monitored-sources" && method === "POST") {
      const source = {
        id: "msrc_1",
        production_id: "prod_1",
        board_id: "board_1",
        source_url: "https://film.example.gov/permits",
        fact_kind: "permit",
        location_id: "maya-s-apartment",
        query: "film permit hours",
        provider: "ui",
        external_monitor_id: "ui-monitor",
        status: "active",
        last_fingerprint: "old",
      };
      monitoredSources = [source];
      return route.fulfill(json(source));
    }
    if (path === "/productions/prod_1/monitor/events" && method === "POST") {
      const requestRow = {
        id: "replan_1",
        production_id: "prod_1",
        finding_id: null,
        current_board_id: "board_1",
        requester_component: "monitor",
        source_kind: "monitor",
        source_id: "msrc_1",
        reason: "UI material monitor change",
        status: "requested",
        affected_work_ids: ["W-BRK-001"],
        locked_days: [],
      };
      replanRequests = [requestRow];
      return route.fulfill(
        json({
          id: "mevent_1",
          production_id: "prod_1",
          monitored_source_id: "msrc_1",
          board_id: "board_1",
          status: "material",
          material: true,
          old_fingerprint: "old",
          new_fingerprint: "new",
          payload: {},
          finding_id: null,
          replan_request_id: "replan_1",
        }),
      );
    }
    if (path === "/replan-requests/replan_1/options" && method === "POST") {
      scheduleDiffs = [mockDiff("replan_1")];
      return route.fulfill(json(scheduleDiffs));
    }
    if (path === "/boards/board_2/selection" && method === "POST") {
      const payload = request.postDataJSON() as { actor_role: string };
      if (payload.actor_role !== "first_ad")
        return route.fulfill(
          json({ detail: "only first_ad may select boards" }, 403),
        );
      const approved = costApprovals.some(
        (approval) =>
          approval.board_id === "board_2" && approval.decision === "approved",
      );
      if (!approved)
        return route.fulfill(
          json({ detail: "cost approval is required before board selection" }, 409),
        );
      return route.fulfill(
        json({
          id: "sel_1",
          production_id: "prod_1",
          selected_board_id: "board_2",
        }),
      );
    }

    if (path === "/boards/board_1/locks" && method === "POST") {
      const row = {
        id: "lock_1",
        production_id: "prod_1",
        board_id: "board_1",
        schedule_run_id: "sched_1",
        shoot_date: "2026-09-14",
        locked_assignments: [{ work_id: "W-BRK-001" }],
        locations: ["maya-s-apartment"],
        cast: ["cast-maya"],
        call_sheet_version: "ui-lock-2026-09-14",
        recorded_by_name: "S. Patel",
        recorded_by_role: "script_supervisor",
      };
      locks = [row];
      return route.fulfill(json(row));
    }
    if (path === "/productions/prod_1/coverage-items" && method === "POST") {
      coverageItem = {
        id: "cov_1",
        production_id: "prod_1",
        scene_id: "BRK-001",
        coverage_key: "ui-insert",
        coverage_type: "insert",
        planned: {},
        shot: {},
        status: "planned",
      };
      coverageItems = [coverageItem];
      return route.fulfill(json(coverageItem));
    }
    if (path === "/coverage-items/cov_1/shot" && method === "POST") {
      coverageItem = {
        ...coverageItem,
        shot: { take: "A3", usable: false },
        status: "shot",
      };
      coverageItems = coverageItems.map((item) =>
        item.id === "cov_1" ? coverageItem! : item,
      );
      return route.fulfill(json(coverageItem));
    }
    if (path === "/coverage-items/cov_1/findings" && method === "POST") {
      coverageFinding = {
        id: "finding_1",
        production_id: "prod_1",
        coverage_item_id: "cov_1",
        board_id: "board_1",
        status: "open",
        severity: "medium",
        message: "insert is unusable",
        raised_by_name: "S. Patel",
        raised_by_role: "script_supervisor",
        human_raised: true,
      };
      coverageFindings = [coverageFinding];
      return route.fulfill(json(coverageFinding));
    }
    if (path === "/coverage-findings/finding_1/pickup" && method === "POST") {
      pickupTask = {
        id: "ptask_1",
        production_id: "prod_1",
        finding_id: "finding_1",
        coverage_item_id: "cov_1",
        board_id: "board_1",
        status: "requested",
        scene_id: "BRK-001",
        pickup_spec: {},
        decision: {},
        requested_by_name: "A. Kowalczyk",
        requested_by_role: "director",
        confirmed_by_name: null,
        confirmed_by_role: null,
      };
      coverageFindings = coverageFindings.map((item) =>
        item.id === "finding_1"
          ? { ...item, status: "pickup_requested" }
          : item,
      );
      pickupTasks = [pickupTask];
      return route.fulfill(json(pickupTask));
    }
    if (path === "/pickup-tasks/ptask_1/confirm" && method === "POST") {
      pickupTask = {
        ...pickupTask,
        status: "schedulable",
        pickup_spec: { scene_id: "BRK-001" },
        confirmed_by_name: "R. Okonkwo",
        confirmed_by_role: "first_ad",
      };
      pickupTasks = pickupTasks.map((item) =>
        item.id === "ptask_1" ? pickupTask! : item,
      );
      return route.fulfill(json(pickupTask));
    }
    if (path === "/pickup-tasks/ptask_1/replan" && method === "POST") {
      const requestRow = {
        id: "replan_pickup",
        production_id: "prod_1",
        finding_id: "finding_1",
        current_board_id: "board_1",
        requester_component: "pickup",
        source_kind: "pickup",
        source_id: "ptask_1",
        reason: "pickup",
        status: "requested",
        affected_work_ids: ["pickup-ptask_1"],
        locked_days: ["2026-09-14"],
      };
      replanRequests = [requestRow, ...replanRequests];
      return route.fulfill(json(requestRow));
    }

    if (path === "/boards/board_1/call-sheets" && method === "POST") {
      const payload = request.postDataJSON() as { actor_role: string };
      if (payload.actor_role !== "second_ad")
        return route.fulfill(
          json({ detail: "may not generate call sheet" }, 403),
        );
      const sheet = mockCallSheet(payload.actor_role);
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

    if (path === "/boards/board_2/cost-approvals" && method === "POST") {
      const payload = request.postDataJSON() as {
        actor_role: string;
        decision: string;
      };
      if (payload.actor_role === "first_ad")
        return route.fulfill(
          json({ detail: "only upm or line_producer may approve cost" }, 403),
        );
      const approval = {
        id: "cost_1",
        production_id: "prod_1",
        board_id: "board_2",
        approver_name: "M. Chen",
        approver_role: payload.actor_role,
        cost_delta: 6500,
        added_shoot_days: ["2026-09-15"],
        decision: payload.decision,
      };
      costApprovals = [approval];
      return route.fulfill(json(approval));
    }

    return route.fulfill(
      json({ detail: `Unhandled mock ${method} ${path}` }, 500),
    );
  });
}

test("full UI routes expose operational workflows", async ({ page }) => {
  await mockApi(page);

  await page.goto("/productions/prod_1/board/board_1");
  await expect(
    page.getByRole("heading", { name: "The Ferry Job" }),
  ).toBeVisible();
  await expect(page.getByText("Stripboard dashboard").first()).toBeVisible();
  await expect(page.locator(".sideRail")).toBeVisible();
  await expect(page.locator(".stripboardBoard")).toBeVisible();
  await expect(page.getByText("W-BRK-001").first()).toBeVisible();

  await page.goto("/productions/prod_1/constraints?boardId=board_1");
  await expect(page.locator(".constraintWorkbench")).toBeVisible();
  await page.getByLabel("Plain English").fill("Maximum daily hours 11");
  await page
    .getByRole("button", { name: "Translate into inactive proposals" })
    .click();
  await expect(page.getByText("proposal_1")).toBeVisible();
  await page.getByRole("button", { name: "Accept as human" }).click();
  await expect(page.getByText("MAX-HOURS-11")).toBeVisible();
  await page.getByRole("button", { name: "Activate" }).click();
  await expect(page.getByText("active").first()).toBeVisible();

  await page.goto("/productions/prod_1/grounding?boardId=board_1");
  await expect(page.locator(".groundingLedger")).toBeVisible();
  await page.getByRole("button", { name: "Run grounding now" }).click();
  await expect(
    page.getByText("evidence_1 · weather · maya-s-apartment", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Record reviewed grounded value" })
    .click();
  await expect(page.getByText("gval_1", { exact: true })).toBeVisible();

  await page.goto("/productions/prod_1/replans?boardId=board_1");
  await expect(page.locator(".replanBoard")).toBeVisible();
  await page.getByLabel("Source URL").fill("https://film.example.gov/permits");
  await page.getByLabel("Monitor query").fill("film permit hours");
  await page
    .getByRole("button", { name: "Create material monitor replan" })
    .click();
  await expect(page.getByText("replan_1")).toBeVisible();
  await page.getByRole("button", { name: "Generate options" }).click();
  await expect(page.getByText("sdiff_1")).toBeVisible();
  await expect(page.getByText("approval required")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Select revised board as First AD" }),
  ).toBeDisabled();

  await page.goto("/productions/prod_1/coverage?boardId=board_1");
  await expect(page.locator(".coverageWorkbench")).toBeVisible();
  await page.getByRole("button", { name: "Lock first board day" }).click();
  await expect(page.getByText("2026-09-14").first()).toBeVisible();
  await page
    .getByLabel("Finding message")
    .fill("insert is unusable from camera shake");
  await page.getByRole("button", { name: "Record coverage finding" }).click();
  await expect(
    page.getByText("Script Supervisor raised finding finding_1."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Director requests pickup" }).click();
  await expect(
    page.getByText("Director requested pickup ptask_1."),
  ).toBeVisible();
  await page.getByRole("button", { name: "First AD confirms spec" }).click();
  await expect(
    page.getByText("First AD confirmed pickup spec ptask_1."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Create pickup replan" }).click();
  await expect(
    page.getByText("Pickup replan replan_pickup is ready for options."),
  ).toBeVisible();

  await page.goto("/productions/prod_1/call-sheets?boardId=board_1");
  await expect(page.locator(".callSheetWorkbench")).toBeVisible();
  await page.getByRole("button", { name: "Generate call sheet" }).click();
  await expect(page.getByText("CALL SHEET CS-20260914-board1")).toBeVisible();
  await expect(page.getByText("Recipients read_only")).toBeVisible();

  await page.goto("/productions/prod_1/costs?boardId=board_1");
  await expect(page.locator(".costWorkbench")).toBeVisible();
  await expect(page.getByText("sdiff_1")).toBeVisible();
  await page.getByRole("button", { name: "Approve as UPM" }).click();
  await expect(
    page.getByText("approved cost exposure for board_2."),
  ).toBeVisible();

  await page.goto("/productions/prod_1/replans?boardId=board_1");
  await expect(page.getByText("selectable")).toBeVisible();
  await page
    .getByRole("button", { name: "Select revised board as First AD" })
    .click();
  await expect(page.getByText("Selected board board_2.")).toBeVisible();

  await page.goto("/productions/prod_1/audit?boardId=board_1");
  await expect(page.locator(".auditLedger")).toBeVisible();
  await expect(page.getByText("Audit log").first()).toBeVisible();
  await expect(page.getByText("board.solved")).toBeVisible();

  await page.goto("/productions/prod_1/infeasible?boardId=board_1");
  await expect(page.locator(".infeasibleWorkbench")).toBeVisible();
  await expect(
    page.getByText("No infeasible or failed schedule run is available"),
  ).toBeVisible();
});
