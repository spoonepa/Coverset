"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  coversetFetch,
  exportPath,
  formatError,
  textExcerpt,
} from "../../shared/coverset-api";
import type {
  Actor,
  ActorRole,
  AuditEvent,
  Board,
  BoardStrip,
  BreakdownRun,
  CallSheet,
  ConstraintProposal,
  ConstraintRow,
  CostApproval,
  CoverageFinding,
  CoverageItem,
  GroundedValue,
  GroundingEvidence,
  Job,
  LockedDay,
  MonitorChangeEvent,
  MonitorFinding,
  MonitoredSource,
  PickupTask,
  Production,
  ReplanRequest,
  ScheduleDiff,
} from "../../shared/coverset-types";

type ScreenProps = {
  productionId: string;
  boardId?: string;
};

type BoardScreenProps = {
  productionId: string;
  boardId: string;
};

type ScreenData = {
  production: Production | null;
  board: Board | null;
  jobs: Job[];
  grounding: GroundingEvidence[];
  constraints: ConstraintRow[];
  locks: LockedDay[];
  monitoredSources: MonitoredSource[];
  monitorFindings: MonitorFinding[];
  replanRequests: ReplanRequest[];
  scheduleDiffs: ScheduleDiff[];
  callSheets: CallSheet[];
  audit: AuditEvent[];
};

const initialData: ScreenData = {
  production: null,
  board: null,
  jobs: [],
  grounding: [],
  constraints: [],
  locks: [],
  monitoredSources: [],
  monitorFindings: [],
  replanRequests: [],
  scheduleDiffs: [],
  callSheets: [],
  audit: [],
};

const roleNames: Record<ActorRole, string> = {
  first_ad: "First AD",
  second_ad: "Second AD",
  script_supervisor: "Script Supervisor",
  director: "Director",
  producer: "Producer",
  upm: "UPM",
  line_producer: "Line Producer",
};

const defaultNames: Record<ActorRole, string> = {
  first_ad: "R. Okonkwo",
  second_ad: "T. Nguyen",
  script_supervisor: "S. Patel",
  director: "A. Kowalczyk",
  producer: "M. Rivera",
  upm: "M. Chen",
  line_producer: "L. Brooks",
};

function asString(value: unknown, fallback = "—"): string {
  if (typeof value === "string" && value.length > 0) {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return fallback;
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => asString(item, "")).filter(Boolean);
}

function firstBoardStrip(board: Board | null): BoardStrip | null {
  return board?.result.strips?.[0] ?? null;
}

function firstBoardDate(board: Board | null): string {
  return board?.result.days?.[0]?.date ?? "2026-09-14";
}

function stripsForDay(board: Board, date: string): BoardStrip[] {
  return (board.result.strips ?? []).filter(
    (strip) => strip.shoot_day === date,
  );
}

function boardNav(productionId: string, boardId?: string): string {
  return boardId
    ? `/productions/${productionId}/board/${boardId}`
    : `/productions/${productionId}`;
}

function withBoard(path: string, boardId?: string): string {
  return boardId ? `${path}?boardId=${encodeURIComponent(boardId)}` : path;
}

function useActor(role: ActorRole): [Actor, (actor: Actor) => void] {
  return useState<Actor>({ name: defaultNames[role], role });
}

function useProductionData(productionId: string, boardId?: string) {
  const [data, setData] = useState<ScreenData>(initialData);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("Loading production data…");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [
        production,
        jobs,
        grounding,
        constraints,
        locks,
        monitoredSources,
        monitorFindings,
        replanRequests,
        scheduleDiffs,
        audit,
        board,
        callSheets,
      ] = await Promise.all([
        coversetFetch<Production>(`/productions/${productionId}`),
        coversetFetch<Job[]>(`/productions/${productionId}/jobs`),
        coversetFetch<GroundingEvidence[]>(
          `/productions/${productionId}/grounding`,
        ),
        coversetFetch<ConstraintRow[]>(
          `/productions/${productionId}/constraints`,
        ),
        coversetFetch<LockedDay[]>(`/productions/${productionId}/locks`),
        coversetFetch<MonitoredSource[]>(
          `/productions/${productionId}/monitored-sources`,
        ),
        coversetFetch<MonitorFinding[]>(
          `/productions/${productionId}/monitor/findings`,
        ),
        coversetFetch<ReplanRequest[]>(
          `/productions/${productionId}/replan-requests`,
        ),
        coversetFetch<ScheduleDiff[]>(
          `/productions/${productionId}/schedule-diffs`,
        ),
        coversetFetch<AuditEvent[]>(`/productions/${productionId}/audit`),
        boardId
          ? coversetFetch<Board>(`/boards/${boardId}`)
          : Promise.resolve(null),
        boardId
          ? coversetFetch<CallSheet[]>(`/boards/${boardId}/call-sheets`)
          : Promise.resolve([]),
      ]);
      setData({
        production,
        board,
        jobs,
        grounding,
        constraints,
        locks,
        monitoredSources,
        monitorFindings,
        replanRequests,
        scheduleDiffs,
        callSheets,
        audit,
      });
      setMessage("Production data loaded.");
    } catch (err) {
      setError(formatError(err));
      setMessage("Could not load production data.");
    } finally {
      setLoading(false);
    }
  }, [boardId, productionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    data,
    error,
    loading,
    message,
    refresh,
    setData,
    setError,
    setMessage,
  };
}

function ScreenShell({
  title,
  eyebrow,
  description,
  productionId,
  boardId,
  status,
  error,
  onRefresh,
  children,
}: {
  title: string;
  eyebrow: string;
  description: string;
  productionId: string;
  boardId?: string;
  status: string;
  error: string;
  onRefresh: () => void;
  children: React.ReactNode;
}) {
  const base = `/productions/${productionId}`;
  const query = boardId ? `?boardId=${encodeURIComponent(boardId)}` : "";
  const nav = [
    ["Overview", base],
    ["Board", boardNav(productionId, boardId)],
    ["Breakdown", `${base}/breakdown${query}`],
    ["Constraints", `${base}/constraints${query}`],
    ["Grounding", `${base}/grounding${query}`],
    ["Replans", `${base}/replans${query}`],
    ["Coverage", `${base}/coverage${query}`],
    ["Call sheets", `${base}/call-sheets${query}`],
    ["Audit", `${base}/audit${query}`],
    ["Infeasible", `${base}/infeasible${query}`],
    ["Costs", `${base}/costs${query}`],
  ];

  return (
    <main className="shell">
      <section className="hero routeHero">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </section>
      <nav className="screenNav" aria-label="Coverset workflow screens">
        {nav.map(([label, href]) => (
          <a key={href} href={href}>
            {label}
          </a>
        ))}
      </nav>
      <section className="panel status sectionHeader">
        <div>
          <strong>Status:</strong> {status}
          {error && <pre className="error">{error}</pre>}
        </div>
        <button className="secondary" type="button" onClick={onRefresh}>
          Refresh
        </button>
      </section>
      {children}
    </main>
  );
}

function ActorRoleControl({
  actor,
  onActorChange,
  roles = Object.keys(roleNames) as ActorRole[],
}: {
  actor: Actor;
  onActorChange: (actor: Actor) => void;
  roles?: ActorRole[];
}) {
  return (
    <div className="actorControl">
      <label>
        Actor
        <input
          value={actor.name}
          onChange={(event) =>
            onActorChange({ ...actor, name: event.target.value })
          }
        />
      </label>
      <label>
        Role
        <select
          value={actor.role}
          onChange={(event) => {
            const role = event.target.value as ActorRole;
            onActorChange({ name: defaultNames[role], role });
          }}
        >
          {roles.map((role) => (
            <option key={role} value={role}>
              {roleNames[role]}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function Pill({
  children,
  tone = "",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return <span className={`pill ${tone}`.trim()}>{children}</span>;
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return <p className="muted emptyState">{children}</p>;
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="jsonBlock">{JSON.stringify(value, null, 2)}</pre>;
}

function MetricGrid({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <div className="metricGrid">
      {items.map(([label, value]) => (
        <div key={label} className="metricCard">
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </div>
  );
}

function BoardMini({ board }: { board: Board | null }) {
  if (!board) {
    return (
      <EmptyState>
        No board id is attached to this route yet. Start from the root demo or
        pass `?boardId=...`.
      </EmptyState>
    );
  }
  return (
    <div className="miniBoard">
      {(board.result.days ?? []).map((day) => (
        <div className="dayCard" key={day.date}>
          <div className="sectionHeader compactHeader">
            <h3>{day.date}</h3>
            <Pill tone={day.kind === "night" ? "warn" : "good"}>
              {asString(day.kind, "shoot")}
            </Pill>
          </div>
          {stripsForDay(board, day.date).map((strip) => (
            <div className="stripRow" key={strip.work_id}>
              <strong>{strip.scene_number}</strong>
              <span>{strip.location_id}</span>
              <span>{strip.day_night}</span>
              <small>
                {strip.planned_call_time ?? "call ?"} →{" "}
                {strip.planned_wrap_time ?? "wrap ?"}
              </small>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function DiffCard({
  diff,
  baseBoardId,
}: {
  diff: ScheduleDiff;
  baseBoardId?: string;
}) {
  const addedDays = asStringList(diff.diff.added_days);
  const addedPickups = asStringList(diff.diff.added_pickups);
  return (
    <article className="scene diffCard">
      <div className="sectionHeader compactHeader">
        <div>
          <strong>{diff.id}</strong>
          <p className="muted">
            {diff.base_board_id} → {diff.revised_board_id}
          </p>
        </div>
        <div className="actions">
          <Pill tone={diff.cost_delta > 0 ? "warn" : "good"}>
            ${diff.cost_delta.toLocaleString()}
          </Pill>
          {diff.required_approvals.map((approval) => (
            <Pill key={approval}>{approval}</Pill>
          ))}
        </div>
      </div>
      <MetricGrid
        items={[
          ["Added days", addedDays.length ? addedDays.join(", ") : "none"],
          [
            "Added pickups",
            addedPickups.length ? addedPickups.join(", ") : "none",
          ],
          ["Required approvals", diff.required_approvals.length || "none"],
        ]}
      />
      {diff.rendered_text && <pre>{diff.rendered_text}</pre>}
      <div className="actions">
        <a
          className="buttonLink secondary"
          href={`/productions/${diff.production_id}/board/${diff.revised_board_id}`}
        >
          Open revised board
        </a>
        <a
          className="buttonLink secondary"
          href={withBoard(
            `/productions/${diff.production_id}/costs`,
            diff.revised_board_id,
          )}
        >
          Cost approval
        </a>
        {baseBoardId && (
          <a
            className="buttonLink secondary"
            href={`/productions/${diff.production_id}/board/${baseBoardId}`}
          >
            Base board
          </a>
        )}
      </div>
    </article>
  );
}

export function ProductionOverviewScreen({
  productionId,
  boardId,
}: ScreenProps) {
  const { data, error, message, refresh } = useProductionData(
    productionId,
    boardId,
  );
  return (
    <ScreenShell
      title="Production operations cockpit"
      eyebrow="Coverset UI"
      description="Route-based access to the full operational screen set backed by the merged API workflows."
      productionId={productionId}
      boardId={boardId}
      status={message}
      error={error}
      onRefresh={refresh}
    >
      <section className="panel grid">
        <div>
          <h2>{data.production?.title ?? "Production"}</h2>
          <MetricGrid
            items={[
              ["Cast", data.production?.cast_count ?? "—"],
              ["Locations", data.production?.location_count ?? "—"],
              ["Shoot days", data.production?.shoot_day_count ?? "—"],
            ]}
          />
          <p className="muted">
            Use the navigation row to open the implemented screen routes. If no
            board link is available, run the root demo first.
          </p>
        </div>
        <div>
          <h2>Operational state</h2>
          <MetricGrid
            items={[
              ["Jobs", data.jobs.length],
              ["Constraints", data.constraints.length],
              ["Replans", data.replanRequests.length],
              ["Schedule diffs", data.scheduleDiffs.length],
            ]}
          />
        </div>
      </section>
    </ScreenShell>
  );
}

export function BoardDashboardScreen({
  productionId,
  boardId,
}: BoardScreenProps) {
  const { data, error, message, refresh, setError, setMessage } =
    useProductionData(productionId, boardId);
  const board = data.board;
  const lockDay = async () => {
    if (!board) return;
    const shootDate = firstBoardDate(board);
    setError("");
    try {
      await coversetFetch<LockedDay>(`/boards/${board.id}/locks`, {
        method: "POST",
        body: JSON.stringify({
          shoot_date: shootDate,
          call_sheet_version: `ui-lock-${shootDate}`,
          actor_name: defaultNames.script_supervisor,
          actor_role: "script_supervisor",
        }),
      });
      setMessage(`Locked ${shootDate}.`);
      await refresh();
    } catch (err) {
      setError(formatError(err));
    }
  };

  return (
    <ScreenShell
      title="Stripboard dashboard"
      eyebrow="First AD board view"
      description="Solved days, strips, objective signals, board approval state, locks, and route links for downstream decisions."
      productionId={productionId}
      boardId={boardId}
      status={message}
      error={error}
      onRefresh={refresh}
    >
      <section className="panel">
        <div className="sectionHeader">
          <div>
            <h2>Board: {board?.solver_status ?? "loading"}</h2>
            <p className="muted">
              Schedule run {board?.schedule_run_id ?? "—"}
            </p>
          </div>
          <div className="actions">
            <Pill tone={board?.approval_state === "approved" ? "good" : "warn"}>
              {board?.approval_state ?? "unknown"}
            </Pill>
            <button type="button" onClick={lockDay} disabled={!board}>
              Lock first shoot day
            </button>
          </div>
        </div>
        {board && (
          <MetricGrid
            items={[
              ["Days", board.result.days?.length ?? 0],
              ["Work strips", board.result.strips?.length ?? 0],
              ["Locks", data.locks.length],
              ["Call sheets", data.callSheets.length],
            ]}
          />
        )}
        <BoardMini board={board} />
      </section>
      <section className="panel grid three">
        <div>
          <h3>Objective</h3>
          <JsonBlock value={board?.result.objective ?? {}} />
        </div>
        <div>
          <h3>Constraint traces</h3>
          {(board?.result.explanation_traces ?? []).slice(0, 8).map((trace) => (
            <p
              className="muted"
              key={`${trace.work_id}-${trace.constraint_id ?? trace.reason}`}
            >
              <strong>{trace.work_id}</strong> ·{" "}
              {trace.constraint_id ?? "reason"} · {trace.reason}
            </p>
          ))}
          {!(board?.result.explanation_traces ?? []).length && (
            <EmptyState>No explanation traces reported.</EmptyState>
          )}
        </div>
        <div>
          <h3>Next actions</h3>
          <div className="routeCards compact">
            <a
              href={withBoard(
                `/productions/${productionId}/call-sheets`,
                boardId,
              )}
            >
              Generate call sheet
            </a>
            <a
              href={withBoard(`/productions/${productionId}/coverage`, boardId)}
            >
              Record actuals / pickup
            </a>
            <a
              href={withBoard(`/productions/${productionId}/replans`, boardId)}
            >
              Compare replans
            </a>
            <a href={withBoard(`/productions/${productionId}/costs`, boardId)}>
              Approve costs
            </a>
          </div>
        </div>
      </section>
    </ScreenShell>
  );
}

export function BreakdownReviewScreen({ productionId, boardId }: ScreenProps) {
  const { error, message, refresh, setData, setError, setMessage } =
    useProductionData(productionId, boardId);
  const [file, setFile] = useState<File | null>(null);
  const [breakdown, setBreakdown] = useState<BreakdownRun | null>(null);
  const [agentMode, setAgentMode] = useState("fixture");

  const uploadAndBreakDown = async () => {
    if (!file) {
      setError("Choose a screenplay file before running breakdown.");
      return;
    }
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const asset = await fetch(
        `/api/coverset/productions/${productionId}/screenplays`,
        {
          method: "POST",
          body: form,
        },
      ).then(async (response) => {
        const payload = (await response.json()) as
          | { id: string }
          | { detail: string };
        if (!response.ok || !("id" in payload)) {
          throw new Error(
            "detail" in payload ? payload.detail : "screenplay upload failed",
          );
        }
        return payload;
      });
      const run = await coversetFetch<BreakdownRun>(
        `/productions/${productionId}/breakdowns`,
        {
          method: "POST",
          body: JSON.stringify({
            screenplay_asset_id: asset.id,
            agent_mode: agentMode,
          }),
        },
      );
      setBreakdown(run);
      setMessage(`Breakdown ${run.status}.`);
    } catch (err) {
      setError(formatError(err));
    }
  };

  const review = async (candidateId: string, decision: "accept" | "reject") => {
    setError("");
    try {
      await coversetFetch(`/scene-candidates/${candidateId}/review`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
      if (breakdown) {
        const refreshed = await coversetFetch<BreakdownRun>(
          `/breakdowns/${breakdown.id}`,
        );
        setBreakdown(refreshed);
      }
      setMessage(`Candidate ${decision}ed.`);
    } catch (err) {
      setError(formatError(err));
    }
  };

  const solve = async () => {
    setError("");
    try {
      const schedule = await coversetFetch<{
        board_id: string | null;
        status: string;
        error: string;
      }>(`/productions/${productionId}/boards/solve`, {
        method: "POST",
        body: JSON.stringify({ accepted_only: true }),
      });
      setMessage(
        schedule.board_id
          ? `Solved board ${schedule.board_id}.`
          : schedule.error || schedule.status,
      );
      if (schedule.board_id) {
        const board = await coversetFetch<Board>(
          `/boards/${schedule.board_id}`,
        );
        setData((current) => ({ ...current, board }));
      }
      await refresh();
    } catch (err) {
      setError(formatError(err));
    }
  };

  return (
    <ScreenShell
      title="Scene breakdown / review"
      eyebrow="Gemini advisory, human acceptance"
      description="Upload screenplay text, inspect candidate records, and keep candidates inert until explicitly accepted."
      productionId={productionId}
      boardId={boardId}
      status={message}
      error={error}
      onRefresh={refresh}
    >
      <section className="panel grid">
        <div>
          <h2>Screenplay intake</h2>
          <label>
            Agent mode
            <select
              value={agentMode}
              onChange={(event) => setAgentMode(event.target.value)}
            >
              <option value="fixture">Fixture</option>
              <option value="gemini">Gemini advisory</option>
            </select>
          </label>
          <label>
            Screenplay file
            <input
              type="file"
              accept=".txt,.fountain,.fdx"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <button type="button" onClick={uploadAndBreakDown}>
            Upload and break down
          </button>
          <button className="secondary" type="button" onClick={solve}>
            Solve accepted scenes
          </button>
        </div>
        <div>
          <h2>Review summary</h2>
          <MetricGrid
            items={[
              ["Candidates", breakdown?.candidates.length ?? 0],
              [
                "Accepted",
                breakdown?.candidates.filter((candidate) => candidate.accepted)
                  .length ?? 0,
              ],
              [
                "Blocked",
                breakdown?.candidates.filter(
                  (candidate) => candidate.resolution_errors.length > 0,
                ).length ?? 0,
              ],
            ]}
          />
          <p className="muted">
            Candidates remain advisory until a human review decision is posted.
          </p>
        </div>
      </section>
      <section className="panel">
        <h2>Candidate review</h2>
        <div className="sceneList">
          {(breakdown?.candidates ?? []).map((candidate) => (
            <article
              className={`scene ${candidate.accepted ? "accepted" : candidate.rejected ? "rejected" : candidate.schedulable ? "ready" : "blocked"}`}
              key={candidate.id}
            >
              <div className="sectionHeader compactHeader">
                <div>
                  <strong>
                    {candidate.scene_number} · {candidate.slugline}
                  </strong>
                  <p className="muted">
                    {candidate.location_ref} · {candidate.day_night} · cast{" "}
                    {candidate.cast_ids.join(", ") || "—"}
                  </p>
                </div>
                <div className="actions">
                  <Pill>{candidate.status}</Pill>
                  <button
                    type="button"
                    onClick={() => review(candidate.id, "accept")}
                  >
                    Accept
                  </button>
                  <button
                    className="secondary"
                    type="button"
                    onClick={() => review(candidate.id, "reject")}
                  >
                    Reject
                  </button>
                </div>
              </div>
              {candidate.resolution_errors.length > 0 && (
                <ul className="errorList">
                  {candidate.resolution_errors.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
            </article>
          ))}
          {!breakdown && (
            <EmptyState>
              No breakdown has been run in this browser session. Upload a
              screenplay or use the root fixture demo.
            </EmptyState>
          )}
        </div>
      </section>
    </ScreenShell>
  );
}

export function ConstraintEntryScreen({ productionId, boardId }: ScreenProps) {
  const { data, error, message, refresh, setError, setMessage } =
    useProductionData(productionId, boardId);
  const [text, setText] = useState("Maximum daily hours 11");
  const [proposals, setProposals] = useState<ConstraintProposal[]>([]);
  const [actor, setActor] = useActor("first_ad");

  const translate = async () => {
    setError("");
    try {
      const rows = await coversetFetch<ConstraintProposal[]>(
        `/productions/${productionId}/constraints/translate`,
        {
          method: "POST",
          body: JSON.stringify({ text, actor_name: actor.name }),
        },
      );
      setProposals(rows);
      setMessage(`${rows.length} inactive proposal(s) created.`);
      await refresh();
    } catch (err) {
      setError(formatError(err));
    }
  };

  const decide = async (
    proposal: ConstraintProposal,
    decision: "accept" | "reject",
  ) => {
    setError("");
    try {
      await coversetFetch(`/constraint-proposals/${proposal.id}/${decision}`, {
        method: "POST",
        body: JSON.stringify({
          decision,
          actor_name: actor.name,
          actor_role: actor.role,
        }),
      });
      setMessage(
        `${decision === "accept" ? "Accepted" : "Rejected"} proposal ${proposal.id}.`,
      );
      await refresh();
    } catch (err) {
      setError(formatError(err));
    }
  };

  const toggle = async (row: ConstraintRow) => {
    setError("");
    try {
      await coversetFetch(`/constraints/${row.id}/activation`, {
        method: "PATCH",
        body: JSON.stringify({
          active: !row.active,
          actor_name: actor.name,
          actor_role: actor.role,
        }),
      });
      setMessage(
        `${row.constraint_id} is now ${row.active ? "inactive" : "active"}.`,
      );
      await refresh();
    } catch (err) {
      setError(formatError(err));
    }
  };

  return (
    <ScreenShell
      title="Plain-English constraint entry"
      eyebrow="Candidate constraints fail closed"
      description="Production prose becomes inactive typed proposals; activation remains a separate human act."
      productionId={productionId}
      boardId={boardId}
      status={message}
      error={error}
      onRefresh={refresh}
    >
      <section className="panel grid">
        <div>
          <h2>Translate instruction</h2>
          <ActorRoleControl
            actor={actor}
            onActorChange={setActor}
            roles={["first_ad", "producer", "script_supervisor"]}
          />
          <label>
            Plain English
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
            />
          </label>
          <button type="button" onClick={translate}>
            Translate into inactive proposals
          </button>
        </div>
        <div>
          <h2>Why this fails closed</h2>
          <p className="muted">
            A proposal is inert until accepted, and an accepted constraint still
            needs explicit activation before the solver may consider it.
          </p>
          <MetricGrid
            items={[
              ["Live constraints", data.constraints.length],
              ["Active", data.constraints.filter((row) => row.active).length],
              ["New proposals", proposals.length],
            ]}
          />
        </div>
      </section>
      <section className="panel grid">
        <div>
          <h2>Latest proposals</h2>
          {(proposals.length ? proposals : []).map((proposal) => (
            <article className="scene" key={proposal.id}>
              <div className="sectionHeader compactHeader">
                <strong>{proposal.id}</strong>
                <Pill tone="warn">{proposal.status}</Pill>
              </div>
              <p>{proposal.source_text}</p>
              <JsonBlock value={proposal.payload} />
              {proposal.validation_errors.length > 0 && (
                <ul className="errorList">
                  {proposal.validation_errors.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
              <div className="actions">
                <button
                  type="button"
                  onClick={() => decide(proposal, "accept")}
                >
                  Accept as human
                </button>
                <button
                  className="secondary"
                  type="button"
                  onClick={() => decide(proposal, "reject")}
                >
                  Reject
                </button>
              </div>
            </article>
          ))}
          {!proposals.length && (
            <EmptyState>
              No browser-session proposals yet. Translate text above.
            </EmptyState>
          )}
        </div>
        <div>
          <h2>Constraints</h2>
          {data.constraints.map((row) => (
            <article className="scene" key={row.id}>
              <div className="sectionHeader compactHeader">
                <strong>{row.constraint_id}</strong>
                <Pill tone={row.active ? "good" : "warn"}>
                  {row.active ? "active" : "inactive"}
                </Pill>
              </div>
              <p className="muted">
                {row.family} · {row.policy}
              </p>
              <JsonBlock value={row.provenance} />
              <button type="button" onClick={() => toggle(row)}>
                {row.active ? "Deactivate" : "Activate"}
              </button>
            </article>
          ))}
          {!data.constraints.length && (
            <EmptyState>
              No constraints have been created for this production.
            </EmptyState>
          )}
        </div>
      </section>
    </ScreenShell>
  );
}

export function GroundedFactsScreen({ productionId, boardId }: ScreenProps) {
  const { data, error, message, refresh, setData, setError, setMessage } =
    useProductionData(productionId, boardId);
  const [kind, setKind] = useState("weather");
  const [locationId, setLocationId] = useState("");
  const [targetDate, setTargetDate] = useState("2026-03-17");
  const [groundedValues, setGroundedValues] = useState<GroundedValue[]>([]);

  const runGrounding = async () => {
    const location =
      locationId || firstBoardStrip(data.board)?.location_id || "LOC-001";
    setError("");
    try {
      const evidence = await coversetFetch<GroundingEvidence>(
        `/productions/${productionId}/grounding`,
        {
          method: "POST",
          body: JSON.stringify({
            kind,
            location_id: location,
            target_date: targetDate,
          }),
        },
      );
      setData((current) => ({
        ...current,
        grounding: [evidence, ...current.grounding],
      }));
      setMessage(`Grounded ${evidence.fact_kind} evidence ${evidence.id}.`);
      await refresh();
    } catch (err) {
      setError(formatError(err));
    }
  };

  const recordValue = async (evidence: GroundingEvidence) => {
    const sourceUrl = asString(
      evidence.evidence.source_url,
      "https://example.invalid/source",
    );
    const quote = asString(
      evidence.evidence.quote,
      "source span extracted and normalized",
    );
    setError("");
    try {
      const value = await coversetFetch<GroundedValue>(
        `/grounding/${evidence.id}/values`,
        {
          method: "POST",
          body: JSON.stringify({
            normalized_value: {
              value: "ui-reviewed",
              fact_kind: evidence.fact_kind,
            },
            units: evidence.fact_kind === "weather" ? "risk" : "rule",
            source_url: sourceUrl,
            source_quote: quote,
            source_span: asString(evidence.evidence.source_span, "source text"),
            query: asString(
              evidence.evidence.query,
              "ui grounded value extraction",
            ),
            validator_family: evidence.fact_kind,
            validator_reason:
              "UI operator reviewed source span before activation.",
          }),
        },
      );
      setGroundedValues((current) => [value, ...current]);
      setMessage(`Recorded grounded value ${value.id}.`);
    } catch (err) {
      setError(formatError(err));
    }
  };

  return (
    <ScreenShell
      title="Grounded facts / source provenance"
      eyebrow="Parallel evidence remains advisory"
      description="Inspect source spans, extraction mode, validators, conflicts, and value-level provenance before constraints are activated."
      productionId={productionId}
      boardId={boardId}
      status={message}
      error={error}
      onRefresh={refresh}
    >
      <section className="panel grid">
        <div>
          <h2>Ground a value</h2>
          <label>
            Fact kind
            <select
              value={kind}
              onChange={(event) => setKind(event.target.value)}
            >
              <option value="weather">Weather</option>
              <option value="permit">Permit</option>
            </select>
          </label>
          <label>
            Location id
            <input
              value={locationId}
              placeholder={
                firstBoardStrip(data.board)?.location_id ?? "LOC-001"
              }
              onChange={(event) => setLocationId(event.target.value)}
            />
          </label>
          <label>
            Target date
            <input
              type="date"
              value={targetDate}
              onChange={(event) => setTargetDate(event.target.value)}
            />
          </label>
          <button type="button" onClick={runGrounding}>
            Run grounding now
          </button>
        </div>
        <div>
          <h2>Provenance summary</h2>
          <MetricGrid
            items={[
              ["Evidence rows", data.grounding.length],
              ["Browser recorded values", groundedValues.length],
              ["Constraints", data.constraints.length],
            ]}
          />
          <p className="muted">
            Daylight remains algorithm-derived; URL evidence is only valid for
            families that accept retrieved facts.
          </p>
        </div>
      </section>
      <section className="panel grid">
        {data.grounding.map((evidence) => (
          <article className="scene" key={evidence.id}>
            <div className="sectionHeader compactHeader">
              <strong>
                {evidence.id} · {evidence.fact_kind} · {evidence.location_id}
              </strong>
              <Pill
                tone={
                  evidence.status === "accepted" || evidence.status === "ok"
                    ? "good"
                    : "warn"
                }
              >
                {evidence.status}
              </Pill>
            </div>
            <p className="muted">{evidence.target_date}</p>
            <JsonBlock value={evidence.evidence} />
            <button type="button" onClick={() => recordValue(evidence)}>
              Record reviewed grounded value
            </button>
          </article>
        ))}
        {!data.grounding.length && (
          <EmptyState>
            No grounding evidence yet. Run grounding or enqueue a grounding job
            from the root app.
          </EmptyState>
        )}
      </section>
      {groundedValues.length > 0 && (
        <section className="panel">
          <h2>Recorded values in this browser session</h2>
          {groundedValues.map((value) => (
            <article className="scene" key={value.id}>
              <strong>{value.id}</strong>
              <p className="muted">
                {value.units} · {value.derived_from} · covers date:{" "}
                {String(value.covering_date)}
              </p>
              <JsonBlock value={value.validator_result} />
            </article>
          ))}
        </section>
      )}
    </ScreenShell>
  );
}

export function ReplanOptionsScreen({ productionId, boardId }: ScreenProps) {
  const { data, error, message, refresh, setError, setMessage } =
    useProductionData(productionId, boardId);
  const [actor, setActor] = useActor("first_ad");
  const board = data.board;

  const createMaterialMonitorReplan = async () => {
    const strip = firstBoardStrip(board);
    if (!board || !strip) {
      setError(
        "Open this screen with a board id before creating a material monitor replan.",
      );
      return;
    }
    setError("");
    try {
      const source = await coversetFetch<MonitoredSource>(
        `/productions/${productionId}/monitored-sources`,
        {
          method: "POST",
          body: JSON.stringify({
            board_id: board.id,
            source_url: "https://film.example.gov/permits",
            fact_kind: "permit",
            location_id: strip.location_id,
            query: "film permit hours",
            external_monitor_id: `ui-monitor-${Date.now()}`,
          }),
        },
      );
      const event = await coversetFetch<MonitorChangeEvent>(
        `/productions/${productionId}/monitor/events`,
        {
          method: "POST",
          body: JSON.stringify({
            monitored_source_id: source.id,
            board_id: board.id,
            source_url: source.source_url,
            fact_kind: source.fact_kind,
            old_fingerprint: "old",
            new_fingerprint: `new-${Date.now()}`,
            affected_work_ids: [strip.work_id],
            material: true,
            message: "UI material monitor change",
          }),
        },
      );
      setMessage(
        event.replan_request_id
          ? `Material change created replan ${event.replan_request_id}.`
          : "Material event recorded.",
      );
      await refresh();
    } catch (err) {
      setError(formatError(err));
    }
  };

  const generateOptions = async (request: ReplanRequest) => {
    setError("");
    try {
      await coversetFetch<ScheduleDiff[]>(
        `/replan-requests/${request.id}/options`,
        {
          method: "POST",
          body: JSON.stringify({ max_options: 2 }),
        },
      );
      setMessage(`Generated options for ${request.id}.`);
      await refresh();
    } catch (err) {
      setError(formatError(err));
    }
  };

  const selectBoard = async (diff: ScheduleDiff) => {
    setError("");
    try {
      await coversetFetch(`/boards/${diff.revised_board_id}/selection`, {
        method: "POST",
        body: JSON.stringify({
          prior_board_id: diff.base_board_id,
          actor_name: actor.name,
          actor_role: actor.role,
        }),
      });
      await refresh();
      setMessage(`Selected board ${diff.revised_board_id}.`);
    } catch (err) {
      setError(formatError(err));
    }
  };

  return (
    <ScreenShell
      title="Replan option comparison"
      eyebrow="Monitor requests, First AD selection"
      description="Generate deterministic options from replan requests and keep board selection separate from monitor automation."
      productionId={productionId}
      boardId={boardId}
      status={message}
      error={error}
      onRefresh={refresh}
    >
      <section className="panel grid">
        <div>
          <h2>Replan requests</h2>
          <button
            type="button"
            onClick={createMaterialMonitorReplan}
            disabled={!board}
          >
            Create material monitor replan
          </button>
          {data.replanRequests.map((request) => (
            <article className="scene" key={request.id}>
              <div className="sectionHeader compactHeader">
                <strong>{request.id}</strong>
                <Pill>{request.status}</Pill>
              </div>
              <p>{request.reason || request.requester_component}</p>
              <p className="muted">
                Source: {request.source_kind} · affected{" "}
                {request.affected_work_ids.join(", ") || "—"}
              </p>
              <button type="button" onClick={() => generateOptions(request)}>
                Generate options
              </button>
            </article>
          ))}
          {!data.replanRequests.length && (
            <EmptyState>
              No replan requests yet. Create a material monitor replan to
              exercise the flow.
            </EmptyState>
          )}
        </div>
        <div>
          <h2>Selection authority</h2>
          <ActorRoleControl
            actor={actor}
            onActorChange={setActor}
            roles={["first_ad", "director", "producer"]}
          />
          <p className="muted">
            The UI can propose options, but only the API-enforced First AD
            decision can select a board.
          </p>
        </div>
      </section>
      <section className="panel">
        <h2>Schedule diffs</h2>
        <div className="sceneList">
          {data.scheduleDiffs.map((diff) => (
            <div key={diff.id}>
              <DiffCard diff={diff} baseBoardId={boardId} />
              <button type="button" onClick={() => selectBoard(diff)}>
                Select revised board as {roleNames[actor.role]}
              </button>
            </div>
          ))}
          {!data.scheduleDiffs.length && (
            <EmptyState>
              No schedule diffs yet. Generate options from a replan request.
            </EmptyState>
          )}
        </div>
      </section>
    </ScreenShell>
  );
}

export function CoverageWorkflowScreen({ productionId, boardId }: ScreenProps) {
  const { data, error, message, refresh, setError, setMessage } =
    useProductionData(productionId, boardId);
  const [coverageItem, setCoverageItem] = useState<CoverageItem | null>(null);
  const [finding, setFinding] = useState<CoverageFinding | null>(null);
  const [pickup, setPickup] = useState<PickupTask | null>(null);
  const [pickupReplan, setPickupReplan] = useState<ReplanRequest | null>(null);
  const board = data.board;

  const createFinding = async () => {
    const strip = firstBoardStrip(board);
    if (!board || !strip) {
      setError(
        "Open this screen with a board id before creating coverage actuals.",
      );
      return;
    }
    setError("");
    try {
      const item = await coversetFetch<CoverageItem>(
        `/productions/${productionId}/coverage-items`,
        {
          method: "POST",
          body: JSON.stringify({
            scene_id: strip.scene_id,
            coverage_key: `ui-${strip.scene_id}-insert-${Date.now()}`,
            coverage_type: "insert",
            planned: { shot: "insert", source: "UI floor actual" },
          }),
        },
      );
      const shot = await coversetFetch<CoverageItem>(
        `/coverage-items/${item.id}/shot`,
        {
          method: "POST",
          body: JSON.stringify({ shot: { take: "A3", usable: false } }),
        },
      );
      const raised = await coversetFetch<CoverageFinding>(
        `/coverage-items/${item.id}/findings`,
        {
          method: "POST",
          body: JSON.stringify({
            board_id: board.id,
            message: "insert is unusable from camera shake",
            actor_name: defaultNames.script_supervisor,
            actor_role: "script_supervisor",
          }),
        },
      );
      setCoverageItem(shot);
      setFinding(raised);
      await refresh();
      setMessage(`Script Supervisor raised finding ${raised.id}.`);
    } catch (err) {
      setError(formatError(err));
    }
  };

  const requestPickup = async () => {
    if (!finding) return;
    setError("");
    try {
      const task = await coversetFetch<PickupTask>(
        `/coverage-findings/${finding.id}/pickup`,
        {
          method: "POST",
          body: JSON.stringify({
            actor_name: defaultNames.director,
            actor_role: "director",
          }),
        },
      );
      setPickup(task);
      setMessage(`Director requested pickup ${task.id}.`);
    } catch (err) {
      setError(formatError(err));
    }
  };

  const confirmPickup = async () => {
    const strip = firstBoardStrip(board);
    if (!pickup || !strip) return;
    setError("");
    try {
      const task = await coversetFetch<PickupTask>(
        `/pickup-tasks/${pickup.id}/confirm`,
        {
          method: "POST",
          body: JSON.stringify({
            actor_name: defaultNames.first_ad,
            actor_role: "first_ad",
            pickup_spec: {
              scene_id: strip.scene_id,
              coverage_type: "insert",
              location_id: strip.location_id,
              cast_ids: strip.cast_ids,
              duration_minutes: 15,
              priority: "must_have",
              day_night: strip.day_night,
            },
          }),
        },
      );
      setPickup(task);
      setMessage(`First AD confirmed pickup spec ${task.id}.`);
    } catch (err) {
      setError(formatError(err));
    }
  };

  const createPickupReplan = async () => {
    if (!pickup || !board) return;
    setError("");
    try {
      const request = await coversetFetch<ReplanRequest>(
        `/pickup-tasks/${pickup.id}/replan`,
        {
          method: "POST",
          body: JSON.stringify({
            current_board_id: board.id,
            cutoff_at: `${firstBoardDate(board)}T12:00:00-04:00`,
            lock_policy: "preserve_locked",
          }),
        },
      );
      setPickupReplan(request);
      await refresh();
      setMessage(`Pickup replan ${request.id} is ready for options.`);
    } catch (err) {
      setError(formatError(err));
    }
  };

  const lockDay = async () => {
    if (!board) return;
    const shootDate = firstBoardDate(board);
    setError("");
    try {
      await coversetFetch<LockedDay>(`/boards/${board.id}/locks`, {
        method: "POST",
        body: JSON.stringify({
          shoot_date: shootDate,
          call_sheet_version: `ui-lock-${shootDate}`,
          actor_name: defaultNames.script_supervisor,
          actor_role: "script_supervisor",
        }),
      });
      setMessage(`Locked ${shootDate} actuals.`);
      await refresh();
    } catch (err) {
      setError(formatError(err));
    }
  };

  return (
    <ScreenShell
      title="Coverage pickup and lock-day actuals"
      eyebrow="Production floor workflow"
      description="Script Supervisor records actuals and findings; Director/First AD decide whether pickup work becomes schedulable."
      productionId={productionId}
      boardId={boardId}
      status={message}
      error={error}
      onRefresh={refresh}
    >
      <section className="panel grid">
        <div>
          <h2>Actuals and findings</h2>
          <button type="button" onClick={lockDay} disabled={!board}>
            Lock first board day
          </button>
          <button type="button" onClick={createFinding} disabled={!board}>
            Record unusable insert finding
          </button>
          {coverageItem && <JsonBlock value={coverageItem} />}
          {finding && <JsonBlock value={finding} />}
        </div>
        <div>
          <h2>Pickup decision chain</h2>
          <div className="actions">
            <button type="button" onClick={requestPickup} disabled={!finding}>
              Director requests pickup
            </button>
            <button type="button" onClick={confirmPickup} disabled={!pickup}>
              First AD confirms spec
            </button>
            <button
              type="button"
              onClick={createPickupReplan}
              disabled={!pickup}
            >
              Create pickup replan
            </button>
          </div>
          {pickup && <JsonBlock value={pickup} />}
          {pickupReplan && <JsonBlock value={pickupReplan} />}
        </div>
      </section>
      <section className="panel grid">
        <div>
          <h2>Locked days</h2>
          {data.locks.map((lock) => (
            <article className="scene" key={lock.id}>
              <strong>{lock.shoot_date}</strong>
              <p className="muted">
                {lock.locked_assignments.length} assignments immutable ·{" "}
                {lock.recorded_by_role}
              </p>
            </article>
          ))}
          {!data.locks.length && <EmptyState>No locked days yet.</EmptyState>}
        </div>
        <div>
          <h2>Related schedule diffs</h2>
          {data.scheduleDiffs.slice(0, 3).map((diff) => (
            <DiffCard diff={diff} key={diff.id} baseBoardId={boardId} />
          ))}
          {!data.scheduleDiffs.length && (
            <EmptyState>
              Create a pickup replan, then open Replans to generate options.
            </EmptyState>
          )}
        </div>
      </section>
    </ScreenShell>
  );
}

export function CallSheetsScreen({ productionId, boardId }: ScreenProps) {
  const { data, error, message, refresh, setData, setError, setMessage } =
    useProductionData(productionId, boardId);
  const [actor, setActor] = useActor("second_ad");
  const [shootDate, setShootDate] = useState("2026-09-14");
  const [selected, setSelected] = useState<CallSheet | null>(null);
  const board = data.board;
  const dayOptions = useMemo(() => board?.result.days ?? [], [board]);

  useEffect(() => {
    if (dayOptions[0]?.date) {
      setShootDate(dayOptions[0].date);
    }
  }, [dayOptions]);

  const generate = async () => {
    if (!board) {
      setError("Open call sheets with a board id before generating.");
      return;
    }
    setError("");
    try {
      const sheet = await coversetFetch<CallSheet>(
        `/boards/${board.id}/call-sheets`,
        {
          method: "POST",
          body: JSON.stringify({
            shoot_date: shootDate,
            actor_name: actor.name,
            actor_role: actor.role,
          }),
        },
      );
      setSelected(sheet);
      setData((current) => ({
        ...current,
        callSheets: [
          sheet,
          ...current.callSheets.filter((item) => item.id !== sheet.id),
        ],
      }));
      setMessage(`Generated call sheet ${sheet.id}.`);
    } catch (err) {
      setError(formatError(err));
    }
  };

  return (
    <ScreenShell
      title="Call sheet preview"
      eyebrow="Second AD only"
      description="Generate persisted call sheets from solved board-day snapshots without re-running scheduling."
      productionId={productionId}
      boardId={boardId}
      status={message}
      error={error}
      onRefresh={refresh}
    >
      <section className="panel grid">
        <div>
          <h2>Generate</h2>
          <ActorRoleControl
            actor={actor}
            onActorChange={setActor}
            roles={["second_ad", "first_ad", "producer"]}
          />
          <label>
            Shoot date
            <select
              value={shootDate}
              onChange={(event) => setShootDate(event.target.value)}
            >
              {dayOptions.map((day) => (
                <option key={day.date} value={day.date}>
                  {day.date}
                </option>
              ))}
              {!dayOptions.length && (
                <option value={shootDate}>{shootDate}</option>
              )}
            </select>
          </label>
          <button type="button" onClick={generate} disabled={!board}>
            Generate call sheet
          </button>
          <p className="muted">
            Try First AD to see the API-enforced rejection; switch back to
            Second AD for success.
          </p>
        </div>
        <div>
          <h2>Existing sheets</h2>
          <div className="callSheetTabs">
            {data.callSheets.map((sheet) => (
              <button
                className="secondary"
                type="button"
                key={sheet.id}
                onClick={() => setSelected(sheet)}
              >
                {sheet.shoot_date}
              </button>
            ))}
          </div>
          {!data.callSheets.length && (
            <EmptyState>
              No call sheets have been generated for this board.
            </EmptyState>
          )}
        </div>
      </section>
      <section className="callSheetPanel">
        <div className="sectionHeader">
          <h2>Preview</h2>
          {selected && (
            <div className="actions">
              <a
                className="buttonLink secondary"
                href={exportPath(
                  `/call-sheets/${selected.id}/export?format=text`,
                )}
              >
                Export text
              </a>
              <a
                className="buttonLink secondary"
                href={exportPath(
                  `/call-sheets/${selected.id}/export?format=json`,
                )}
              >
                Export JSON
              </a>
            </div>
          )}
        </div>
        {selected ? (
          <div className="callSheetCard">
            <MetricGrid
              items={[
                ["Shoot date", selected.shoot_date],
                [
                  "Generated by",
                  `${selected.generated_by_name} (${selected.generated_by_role})`,
                ],
                ["Recipients", selected.payload.recipients?.length ?? 0],
              ]}
            />
            <div className="callSheetColumns">
              <div>
                <h4>Scenes</h4>
                <JsonBlock value={selected.payload.scenes ?? []} />
              </div>
              <div>
                <h4>Cast calls</h4>
                <JsonBlock value={selected.payload.cast_calls ?? []} />
              </div>
              <div>
                <h4>Turnaround</h4>
                <JsonBlock value={selected.payload.turnaround_notes ?? []} />
              </div>
              <div>
                <h4>Recipients</h4>
                <JsonBlock value={selected.payload.recipients ?? []} />
              </div>
            </div>
            <pre>{selected.rendered_text}</pre>
          </div>
        ) : (
          <EmptyState>Select or generate a call sheet.</EmptyState>
        )}
      </section>
    </ScreenShell>
  );
}

export function AuditLogScreen({ productionId, boardId }: ScreenProps) {
  const { data, error, message, refresh } = useProductionData(
    productionId,
    boardId,
  );
  return (
    <ScreenShell
      title="Audit log"
      eyebrow="Authority and provenance ledger"
      description="Review the chronological record of advisory events, human decisions, exports, locks, replans, and approvals."
      productionId={productionId}
      boardId={boardId}
      status={message}
      error={error}
      onRefresh={refresh}
    >
      <section className="panel sectionHeader">
        <div>
          <h2>Exports</h2>
          <p className="muted">Audit exports are read-only review artifacts.</p>
        </div>
        <div className="actions">
          <a
            className="buttonLink secondary"
            href={exportPath(
              `/productions/${productionId}/audit/export?format=json`,
            )}
          >
            Export JSON
          </a>
          <a
            className="buttonLink secondary"
            href={exportPath(
              `/productions/${productionId}/audit/export?format=csv`,
            )}
          >
            Export CSV
          </a>
        </div>
      </section>
      <section className="panel">
        <h2>Events</h2>
        <div className="timeline">
          {data.audit.map((event) => (
            <article className="timelineRow" key={event.id}>
              <Pill>{event.event_type}</Pill>
              <div>
                <strong>{event.actor}</strong>
                <p className="muted">
                  {new Date(event.created_at).toLocaleString()}
                </p>
                <JsonBlock value={event.payload} />
              </div>
            </article>
          ))}
          {!data.audit.length && (
            <EmptyState>No audit events loaded yet.</EmptyState>
          )}
        </div>
      </section>
    </ScreenShell>
  );
}

export function CostApprovalScreen({ productionId, boardId }: ScreenProps) {
  const { data, error, message, refresh, setError, setMessage } =
    useProductionData(productionId, boardId);
  const [actor, setActor] = useActor("upm");
  const [approvals, setApprovals] = useState<CostApproval[]>([]);

  const approve = async (
    diff: ScheduleDiff,
    decision: "approved" | "rejected",
  ) => {
    const addedDays = asStringList(diff.diff.added_days);
    const fallbackDay = data.board?.result.days?.at(-1)?.date;
    setError("");
    try {
      const approval = await coversetFetch<CostApproval>(
        `/boards/${diff.revised_board_id}/cost-approvals`,
        {
          method: "POST",
          body: JSON.stringify({
            cost_delta: diff.cost_delta,
            added_shoot_days: addedDays.length
              ? addedDays
              : fallbackDay
                ? [fallbackDay]
                : [],
            decision,
            actor_name: actor.name,
            actor_role: actor.role,
          }),
        },
      );
      setApprovals((current) => [approval, ...current]);
      await refresh();
      setMessage(`${decision} cost exposure for ${diff.revised_board_id}.`);
    } catch (err) {
      setError(formatError(err));
    }
  };

  return (
    <ScreenShell
      title="Cost approval"
      eyebrow="UPM / Line Producer gate"
      description="Review added-day exposure from schedule diffs and keep cost approval separate from board selection."
      productionId={productionId}
      boardId={boardId}
      status={message}
      error={error}
      onRefresh={refresh}
    >
      <section className="panel grid">
        <div>
          <h2>Approver</h2>
          <ActorRoleControl
            actor={actor}
            onActorChange={setActor}
            roles={["upm", "line_producer", "first_ad"]}
          />
          <p className="muted">
            Try First AD to confirm authority rejection; UPM or Line Producer
            can approve/reject.
          </p>
        </div>
        <div>
          <h2>Recorded in this session</h2>
          {approvals.map((approval) => (
            <JsonBlock key={approval.id} value={approval} />
          ))}
          {!approvals.length && (
            <EmptyState>No browser-session cost decisions yet.</EmptyState>
          )}
        </div>
      </section>
      <section className="panel">
        <h2>Cost-exposed schedule diffs</h2>
        <div className="sceneList">
          {data.scheduleDiffs.map((diff) => (
            <article className="scene" key={diff.id}>
              <DiffCard diff={diff} baseBoardId={boardId} />
              <div className="actions">
                <button type="button" onClick={() => approve(diff, "approved")}>
                  Approve as {roleNames[actor.role]}
                </button>
                <button
                  className="secondary"
                  type="button"
                  onClick={() => approve(diff, "rejected")}
                >
                  Reject
                </button>
              </div>
            </article>
          ))}
          {!data.scheduleDiffs.length && (
            <EmptyState>
              No schedule diffs yet. Create options from Replans or Coverage
              first.
            </EmptyState>
          )}
        </div>
      </section>
    </ScreenShell>
  );
}

export function InfeasibleConflictScreen({
  productionId,
  boardId,
}: ScreenProps) {
  const { data, error, message, refresh } = useProductionData(
    productionId,
    boardId,
  );
  const failedJobs = data.jobs.filter(
    (job) => job.status === "failed" || job.error,
  );
  return (
    <ScreenShell
      title="Infeasible board diagnostics"
      eyebrow="Truthful conflict surface"
      description="Show real solver failures and avoid hard-coded conflict math when the API has not exposed a minimal conflict subset."
      productionId={productionId}
      boardId={boardId}
      status={message}
      error={error}
      onRefresh={refresh}
    >
      <section className="panel grid">
        <div>
          <h2>Current solver status</h2>
          <MetricGrid
            items={[
              ["Board status", data.board?.solver_status ?? "no board"],
              ["Failed jobs", failedJobs.length],
              ["Constraints", data.constraints.length],
            ]}
          />
          <p className="muted">
            When a failed schedule includes conflict metadata, this route should
            render that subset. Until then it reports the available error and
            links operators back to constraints.
          </p>
        </div>
        <div>
          <h2>Next action</h2>
          <a
            className="buttonLink"
            href={withBoard(
              `/productions/${productionId}/constraints`,
              boardId,
            )}
          >
            Review constraints
          </a>
        </div>
      </section>
      <section className="panel">
        <h2>Failures</h2>
        {failedJobs.map((job) => (
          <article className="scene" key={job.id}>
            <strong>{job.job_type}</strong>
            <p className="errorText">{job.error || "failed"}</p>
            <JsonBlock value={job.result} />
          </article>
        ))}
        {!failedJobs.length && (
          <EmptyState>
            No infeasible or failed schedule run is available for this
            production.
          </EmptyState>
        )}
      </section>
    </ScreenShell>
  );
}
