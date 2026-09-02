"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";

import {
  coversetFetch,
  exportPath,
  formatError,
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
  breakdowns: BreakdownRun[];
  grounding: GroundingEvidence[];
  groundedValues: GroundedValue[];
  constraintProposals: ConstraintProposal[];
  constraints: ConstraintRow[];
  locks: LockedDay[];
  monitoredSources: MonitoredSource[];
  monitorFindings: MonitorFinding[];
  replanRequests: ReplanRequest[];
  scheduleDiffs: ScheduleDiff[];
  coverageItems: CoverageItem[];
  coverageFindings: CoverageFinding[];
  pickupTasks: PickupTask[];
  costApprovals: CostApproval[];
  callSheets: CallSheet[];
  audit: AuditEvent[];
};

const initialData: ScreenData = {
  production: null,
  board: null,
  jobs: [],
  breakdowns: [],
  grounding: [],
  groundedValues: [],
  constraintProposals: [],
  constraints: [],
  locks: [],
  monitoredSources: [],
  monitorFindings: [],
  replanRequests: [],
  scheduleDiffs: [],
  coverageItems: [],
  coverageFindings: [],
  pickupTasks: [],
  costApprovals: [],
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
  return board?.result.days?.[0]?.date ?? "";
}

function evidenceField(
  evidence: GroundingEvidence,
  key: string,
  fallback = "",
): string {
  return asString(evidence.evidence[key], fallback);
}

function evidenceSourceUrl(evidence: GroundingEvidence): string {
  const direct = evidenceField(evidence, "source_url");
  if (direct) return direct;
  const urls = asStringList(evidence.evidence.source_urls);
  if (urls[0]) return urls[0];
  const sources = evidence.evidence.sources;
  if (Array.isArray(sources)) {
    for (const item of sources) {
      if (item && typeof item === "object") {
        const url = asString((item as Record<string, unknown>).url, "");
        if (url) return url;
      }
    }
  }
  return "";
}

function evidenceQuote(evidence: GroundingEvidence): string {
  const direct = evidenceField(evidence, "quote");
  if (direct) return direct;
  const sources = evidence.evidence.sources;
  if (Array.isArray(sources)) {
    for (const item of sources) {
      if (!item || typeof item !== "object") continue;
      const excerpts = asStringList((item as Record<string, unknown>).excerpts);
      if (excerpts[0]) return excerpts[0];
    }
  }
  return "";
}

function coverageItemsForStrip(
  items: CoverageItem[],
  strip: BoardStrip,
): CoverageItem[] {
  return items.filter((item) => item.scene_id === strip.scene_id);
}

function coverageFindingForStrip(
  items: CoverageItem[],
  findings: CoverageFinding[],
  strip: BoardStrip,
): CoverageFinding | null {
  const itemIds = new Set(
    coverageItemsForStrip(items, strip).map((item) => item.id),
  );
  return (
    findings.find((finding) => itemIds.has(finding.coverage_item_id)) ?? null
  );
}

function pickupForFinding(
  tasks: PickupTask[],
  finding: CoverageFinding | null,
): PickupTask | null {
  if (!finding) return null;
  return tasks.find((task) => task.finding_id === finding.id) ?? null;
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
        breakdowns,
        grounding,
        groundedValues,
        constraintProposals,
        constraints,
        locks,
        monitoredSources,
        monitorFindings,
        replanRequests,
        scheduleDiffs,
        coverageItems,
        coverageFindings,
        pickupTasks,
        costApprovals,
        audit,
        board,
        callSheets,
      ] = await Promise.all([
        coversetFetch<Production>(`/productions/${productionId}`),
        coversetFetch<Job[]>(`/productions/${productionId}/jobs`),
        coversetFetch<BreakdownRun[]>(
          `/productions/${productionId}/breakdowns`,
        ),
        coversetFetch<GroundingEvidence[]>(
          `/productions/${productionId}/grounding`,
        ),
        coversetFetch<GroundedValue[]>(
          `/productions/${productionId}/grounded-values`,
        ),
        coversetFetch<ConstraintProposal[]>(
          `/productions/${productionId}/constraint-proposals`,
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
        coversetFetch<CoverageItem[]>(
          `/productions/${productionId}/coverage-items`,
        ),
        coversetFetch<CoverageFinding[]>(
          `/productions/${productionId}/coverage-findings`,
        ),
        coversetFetch<PickupTask[]>(
          `/productions/${productionId}/pickup-tasks`,
        ),
        coversetFetch<CostApproval[]>(
          `/productions/${productionId}/cost-approvals`,
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
        breakdowns,
        grounding,
        groundedValues,
        constraintProposals,
        constraints,
        locks,
        monitoredSources,
        monitorFindings,
        replanRequests,
        scheduleDiffs,
        coverageItems,
        coverageFindings,
        pickupTasks,
        costApprovals,
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
  const pathname = usePathname();
  const base = `/productions/${productionId}`;
  const query = boardId ? `?boardId=${encodeURIComponent(boardId)}` : "";
  const nav = [
    {
      label: "Dashboard",
      icon: "dashboard",
      href: boardNav(productionId, boardId),
    },
    { label: "Breakdown", icon: "list_alt", href: `${base}/breakdown${query}` },
    { label: "Constraints", icon: "rule", href: `${base}/constraints${query}` },
    { label: "Sources", icon: "source", href: `${base}/grounding${query}` },
    { label: "Replan", icon: "rebase_edit", href: `${base}/replans${query}` },
    {
      label: "Coverage",
      icon: "video_library",
      href: `${base}/coverage${query}`,
    },
    {
      label: "Call sheets",
      icon: "description",
      href: `${base}/call-sheets${query}`,
    },
    { label: "Audit", icon: "history", href: `${base}/audit${query}` },
    { label: "Costs", icon: "attach_money", href: `${base}/costs${query}` },
    { label: "Infeasible", icon: "block", href: `${base}/infeasible${query}` },
  ];

  return (
    <div className="appFrame">
      <aside className="sideRail" aria-label="Coverset workflow screens">
        <a className="railBrand" href={base} aria-label="Production overview">
          CS
        </a>
        <nav className="railNav">
          {nav.map((item) => {
            const itemPath = item.href.split("?")[0];
            const active = pathname === itemPath;
            return (
              <a
                key={item.href}
                aria-current={active ? "page" : undefined}
                className={active ? "active" : undefined}
                href={item.href}
                title={item.label}
              >
                <span
                  className="material-symbols-outlined railIcon"
                  aria-hidden="true"
                >
                  {item.icon}
                </span>
                <span className="railLabel">{item.label}</span>
              </a>
            );
          })}
        </nav>
        <div className="railFooter" title="Assistant director cockpit">
          AD
        </div>
      </aside>

      <main className="routeShell">
        <header className="routeTopbar">
          <div>
            <p className="eyebrow">{eyebrow}</p>
            <h1>{title}</h1>
            <p>{description}</p>
          </div>
          <div className="routeTopbarActions">
            <a className="buttonLink secondary" href={base}>
              Overview
            </a>
            <button className="secondary" type="button" onClick={onRefresh}>
              Refresh
            </button>
          </div>
        </header>

        <section className="panel status routeStatus">
          <strong>Status:</strong> {status}
          {error && <pre className="error">{error}</pre>}
        </section>
        {children}
      </main>
    </div>
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

function DataField({
  label,
  children,
  tone = "",
}: {
  label: string;
  children: React.ReactNode;
  tone?: string;
}) {
  return (
    <div className={`dataField ${tone}`.trim()}>
      <span>{label}</span>
      <strong>{children}</strong>
    </div>
  );
}

function formatTime(value: unknown): string {
  if (typeof value !== "string" || value.length === 0) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function stripLocation(strip: BoardStrip): string {
  const location = strip.location;
  if (location && typeof location === "object") {
    const record = location as Record<string, unknown>;
    return asString(record.name, strip.location_id);
  }
  return strip.location_id;
}

function stripDuration(strip: BoardStrip): string {
  const minutes = strip.duration_minutes ?? strip.minutes;
  if (typeof minutes !== "number") {
    return "—";
  }
  const hours = Math.floor(minutes / 60);
  const remaining = minutes % 60;
  return `${hours}:${String(remaining).padStart(2, "0")}`;
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
    <div className="stripboardBoard">
      {(board.result.days ?? []).map((day, index) => {
        const dayStrips = stripsForDay(board, day.date);
        const dayKind = asString(day.kind, dayStrips[0]?.day_night ?? "shoot");
        return (
          <section
            className={`stripDay ${index === 0 ? "active" : ""}`.trim()}
            key={day.date}
          >
            <header className="stripDayHeader">
              <div>
                <div className="dayTitle">DAY {index + 1}</div>
                <div className="dayMeta">{day.date}</div>
              </div>
              <div className="dayBadges">
                <Pill tone={dayKind === "night" ? "warn" : "good"}>
                  {dayKind} shoot
                </Pill>
                <span>{dayStrips.length} strips</span>
              </div>
            </header>
            <div className="dayRule">
              {dayKind === "night"
                ? "NIGHT WORK · DAYLIGHT BOUNDS DO NOT APPLY"
                : "DAY WORK · DAYLIGHT WINDOW ENFORCED"}
            </div>
            <div className="stripTable">
              {dayStrips.map((strip, stripIndex) => (
                <div className="stripRow" key={strip.work_id}>
                  <strong>{strip.scene_number || stripIndex + 1}</strong>
                  <span className="chip">{asString(strip.int_ext, "SCN")}</span>
                  <span className="chip mutedChip">{strip.day_night}</span>
                  <span className="stripSlug">
                    {asString(strip.slugline, strip.scene_id)}
                  </span>
                  <span className="stripLocation">{stripLocation(strip)}</span>
                  <span className="stripCast">
                    {strip.cast_ids.slice(0, 4).map((castId) => (
                      <span key={castId}>
                        {castId.replace(/^cast[-_]/, "")}
                      </span>
                    ))}
                    {!strip.cast_ids.length && <span>—</span>}
                  </span>
                  <small>
                    {formatTime(strip.planned_call_time)}–
                    {formatTime(strip.planned_wrap_time)}
                  </small>
                  <span className="stripDuration">{stripDuration(strip)}</span>
                </div>
              ))}
            </div>
          </section>
        );
      })}
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
          <div className="dataStack">
            <DataField label="Jobs">{data.jobs.length}</DataField>
            <DataField label="Constraints">{data.constraints.length}</DataField>
            <DataField label="Replans">{data.replanRequests.length}</DataField>
            <DataField label="Schedule diffs">
              {data.scheduleDiffs.length}
            </DataField>
          </div>
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
  const objective = board?.result.objective ?? {};
  const lockDay = async () => {
    const shootDate = firstBoardDate(board);
    if (!board || !shootDate) {
      setError("Load a board with at least one shoot day before locking.");
      return;
    }
    setError("");
    try {
      await coversetFetch<LockedDay>(`/boards/${board.id}/locks`, {
        method: "POST",
        body: JSON.stringify({
          shoot_date: shootDate,
          call_sheet_version: `actuals-${shootDate}`,
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
      <div className="workflowSplit boardWorkbench">
        <section className="workspacePanel stripboardWorkspace">
          <div className="commandBanner neutral">
            <div>
              <h2>Board: {board?.solver_status ?? "loading"}</h2>
              <p>
                Schedule run {board?.schedule_run_id ?? "—"} · CP-SAT solver ·
                validated against its recorded snapshot.
              </p>
            </div>
            <div className="commandMetrics">
              <DataField label="Days">
                {board?.result.days?.length ?? 0}
              </DataField>
              <DataField label="Work strips">
                {board?.result.strips?.length ?? 0}
              </DataField>
              <DataField label="Locks">{data.locks.length}</DataField>
            </div>
          </div>
          <BoardMini board={board} />
        </section>
        <aside className="inspectorPanel">
          <div className="inspectorHeader">
            <p className="eyebrow">Inspector</p>
            <h2>Board authority</h2>
            <Pill tone={board?.approval_state === "approved" ? "good" : "warn"}>
              {board?.approval_state ?? "unknown"}
            </Pill>
          </div>
          <button type="button" onClick={lockDay} disabled={!board}>
            Lock first shoot day
          </button>
          <div className="dataStack">
            <DataField label="Call sheets">{data.callSheets.length}</DataField>
            <DataField label="Company moves">
              {asString(objective.company_moves, "—")}
            </DataField>
            <DataField label="Holding days">
              {asString(objective.holding_days, "—")}
            </DataField>
            <DataField label="Overtime hours">
              {asString(objective.overtime_hours, "—")}
            </DataField>
          </div>
          <div className="inspectorSection">
            <h3>Constraint explanation traces</h3>
            {(board?.result.explanation_traces ?? [])
              .slice(0, 8)
              .map((trace) => (
                <p
                  className="traceLine"
                  key={`${trace.work_id}-${trace.constraint_id ?? trace.reason}`}
                >
                  <strong>{trace.work_id}</strong>
                  <span>{trace.constraint_id ?? "reason"}</span>
                  {trace.reason}
                </p>
              ))}
            {!(board?.result.explanation_traces ?? []).length && (
              <EmptyState>No explanation traces reported.</EmptyState>
            )}
          </div>
          <div className="inspectorSection routeCards compact">
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
        </aside>
      </div>
    </ScreenShell>
  );
}

export function BreakdownReviewScreen({ productionId, boardId }: ScreenProps) {
  const { data, error, message, refresh, setData, setError, setMessage } =
    useProductionData(productionId, boardId);
  const [file, setFile] = useState<File | null>(null);
  const [breakdown, setBreakdown] = useState<BreakdownRun | null>(null);
  const [agentMode, setAgentMode] = useState("fixture");
  const activeBreakdown = breakdown ?? data.breakdowns[0] ?? null;
  const candidates = activeBreakdown?.candidates ?? [];

  const uploadAndBreakDown = async () => {
    if (!file) {
      setError("Choose a screenplay file before running breakdown.");
      return;
    }
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(
        `/api/coverset/productions/${productionId}/screenplays`,
        {
          method: "POST",
          body: form,
        },
      );
      const asset = (await response.json()) as
        | { id: string }
        | { detail: string };
      if (!response.ok || !("id" in asset)) {
        throw new Error(
          "detail" in asset ? asset.detail : "screenplay upload failed",
        );
      }
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
      await refresh();
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
      if (activeBreakdown) {
        const refreshed = await coversetFetch<BreakdownRun>(
          `/breakdowns/${activeBreakdown.id}`,
        );
        setBreakdown(refreshed);
      }
      await refresh();
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
      <div className="workflowSplit breakdownWorkbench">
        <section className="workspacePanel candidateCanvas">
          <div className="canvasCommandBar">
            <div>
              <h2>Candidate scenes</h2>
              <p>
                Advisory records only — they become schedulable work after human
                acceptance.
              </p>
            </div>
            <div className="commandMetrics">
              <DataField label="Total">{candidates.length}</DataField>
              <DataField label="Needs review">
                {
                  candidates.filter(
                    (candidate) =>
                      !candidate.accepted &&
                      !candidate.rejected &&
                      candidate.resolution_errors.length > 0,
                  ).length
                }
              </DataField>
              <DataField label="Accepted">
                {candidates.filter((candidate) => candidate.accepted).length}
              </DataField>
            </div>
          </div>
          <div
            className="candidateTable"
            role="table"
            aria-label="Candidate review"
          >
            <div className="candidateHeader" role="row">
              <span>Scene</span>
              <span>Description</span>
              <span>Status</span>
              <span>Warning</span>
              <span>Confidence</span>
              <span>Pages</span>
            </div>
            {candidates.map((candidate) => (
              <article
                className={`candidateRow ${candidate.accepted ? "accepted" : candidate.rejected ? "rejected" : candidate.schedulable ? "ready" : "blocked"}`}
                key={candidate.id}
                role="row"
              >
                <span className="mono primaryText">
                  {candidate.scene_number || candidate.scene_id}
                </span>
                <span>
                  <strong>{candidate.slugline}</strong>
                  <small>
                    {candidate.location_ref} · {candidate.day_night} · cast{" "}
                    {candidate.cast_ids.join(", ") || "—"}
                  </small>
                </span>
                <Pill
                  tone={
                    candidate.accepted
                      ? "good"
                      : candidate.rejected
                        ? "error"
                        : candidate.schedulable
                          ? "good"
                          : "warn"
                  }
                >
                  {candidate.accepted
                    ? "active"
                    : candidate.rejected
                      ? "rejected"
                      : candidate.status}
                </Pill>
                <span className="warningCell">
                  {candidate.resolution_errors[0] ?? "—"}
                </span>
                <span className="mono right">
                  {candidate.confidence == null
                    ? "—"
                    : `${Math.round(candidate.confidence * 100)}%`}
                </span>
                <span className="mono right">{candidate.page_eighths}/8</span>
                <div className="rowActions">
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
              </article>
            ))}
            {!activeBreakdown && (
              <EmptyState>
                No breakdown runs loaded yet. Upload a screenplay or use the
                root fixture demo.
              </EmptyState>
            )}
          </div>
        </section>
        <aside className="inspectorPanel reviewInspector">
          <div className="inspectorHeader">
            <p className="eyebrow">Review inspector</p>
            <h2>Screenplay intake</h2>
            <p>
              Gemini may propose; explicit review is the production boundary.
            </p>
          </div>
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
          <div className="inspectorSection">
            <h3>Review summary</h3>
            <div className="dataStack">
              <DataField label="Candidates">{candidates.length}</DataField>
              <DataField label="Accepted">
                {candidates.filter((candidate) => candidate.accepted).length}
              </DataField>
              <DataField label="Blocked">
                {
                  candidates.filter(
                    (candidate) => candidate.resolution_errors.length > 0,
                  ).length
                }
              </DataField>
            </div>
          </div>
        </aside>
      </div>
    </ScreenShell>
  );
}

export function ConstraintEntryScreen({ productionId, boardId }: ScreenProps) {
  const { data, error, message, refresh, setError, setMessage } =
    useProductionData(productionId, boardId);
  const [text, setText] = useState("");
  const [actor, setActor] = useActor("first_ad");
  const proposals = data.constraintProposals;
  const activeCount = data.constraints.filter((row) => row.active).length;

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
      <div className="workflowTri constraintWorkbench">
        <aside className="inspectorPanel intakePanel">
          <div className="inspectorHeader">
            <p className="eyebrow">Say it plainly</p>
            <h2>Production instruction</h2>
            <p>
              Gemini interprets prose into typed candidates. It cannot activate,
              schedule, or silently resolve ambiguity.
            </p>
          </div>
          <ActorRoleControl
            actor={actor}
            onActorChange={setActor}
            roles={["first_ad", "producer", "script_supervisor"]}
          />
          <label>
            Plain English
            <textarea
              value={text}
              placeholder="Enter a production constraint"
              onChange={(event) => setText(event.target.value)}
            />
          </label>
          <button type="button" onClick={translate} disabled={!text.trim()}>
            Translate into inactive proposals
          </button>
          <div className="advisoryCard">
            <Pill tone="advisory">Gemini advisory</Pill>
            <p>
              Name resolution is visible. Near misses are refused, not guessed,
              because a silent fix can schedule the wrong person or location.
            </p>
          </div>
        </aside>
        <main className="workspacePanel constraintCanvas">
          <div className="canvasCommandBar">
            <div>
              <h2>Candidate constraints — {proposals.length}</h2>
              <p>
                A candidate is inert. Activation creates a new constraint
                snapshot for future boards.
              </p>
            </div>
            <div className="commandMetrics">
              <DataField label="Live">{data.constraints.length}</DataField>
              <DataField label="Active">{activeCount}</DataField>
              <DataField label="Typed">{proposals.length}</DataField>
            </div>
          </div>
          <div className="constraintCards">
            {proposals.map((proposal) => (
              <article className="constraintCard" key={proposal.id}>
                <header>
                  <div>
                    <span className="mono">{proposal.id}</span>
                    <Pill tone="warn">{proposal.status}</Pill>
                  </div>
                  <span className="caps">
                    confidence {Math.round(proposal.confidence * 100)}%
                  </span>
                </header>
                <p className="quote">“{proposal.source_text}”</p>
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
                No persisted proposals yet. Translate text from the left panel.
              </EmptyState>
            )}
            {data.constraints.map((row) => (
              <article className="constraintCard activeConstraint" key={row.id}>
                <header>
                  <div>
                    <span className="mono">{row.constraint_id}</span>
                    <Pill tone={row.active ? "good" : "warn"}>
                      {row.active ? "active" : "inactive"}
                    </Pill>
                  </div>
                  <span className="caps">
                    {row.family} · {row.policy}
                  </span>
                </header>
                <JsonBlock value={row.provenance} />
                <button type="button" onClick={() => toggle(row)}>
                  {row.active ? "Deactivate" : "Activate"}
                </button>
              </article>
            ))}
          </div>
        </main>
        <aside className="inspectorPanel activationPanel">
          <div className="inspectorHeader">
            <p className="eyebrow">Activation</p>
            <h2>What changes</h2>
            <p>Activation is a separate human commitment.</p>
          </div>
          <div className="dataStack">
            <DataField label="Acting as">
              {roleNames[actor.role]} · {actor.name}
            </DataField>
            <DataField label="Constraint snapshot">
              recomputed on activation
            </DataField>
            <DataField label="Current board">
              {activeCount > 0 ? "superseded on solve" : "unchanged"}
            </DataField>
          </div>
          <div className="inspectorSection dashed">
            <h3>Not offered here</h3>
            <p className="muted">
              There is no “activate all”. Each constraint is a separate
              production commitment with its own consequence.
            </p>
          </div>
        </aside>
      </div>
    </ScreenShell>
  );
}

export function GroundedFactsScreen({ productionId, boardId }: ScreenProps) {
  const { data, error, message, refresh, setError, setMessage } =
    useProductionData(productionId, boardId);
  const [kind, setKind] = useState("weather");
  const [locationId, setLocationId] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const groundedValues = data.groundedValues;
  const selectedEvidence = data.grounding[0] ?? null;

  useEffect(() => {
    const boardDate = firstBoardDate(data.board);
    if (boardDate && !targetDate) {
      setTargetDate(boardDate);
    }
  }, [data.board, targetDate]);

  const runGrounding = async () => {
    const location =
      locationId || firstBoardStrip(data.board)?.location_id || "";
    if (!location || !targetDate) {
      setError("Load a board date and location before grounding a value.");
      return;
    }
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
      setMessage(`Grounded ${evidence.fact_kind} evidence ${evidence.id}.`);
      await refresh();
    } catch (err) {
      setError(formatError(err));
    }
  };

  const recordValue = async (evidence: GroundingEvidence) => {
    const sourceUrl = evidenceSourceUrl(evidence);
    const quote = evidenceQuote(evidence);
    if (!sourceUrl || !quote) {
      setError(
        "Grounding evidence must include a source URL and quote before a value can be recorded.",
      );
      return;
    }
    setError("");
    try {
      const value = await coversetFetch<GroundedValue>(
        `/grounding/${evidence.id}/values`,
        {
          method: "POST",
          body: JSON.stringify({
            normalized_value: {
              fact_kind: evidence.fact_kind,
              quote,
              source_url: sourceUrl,
            },
            units: evidence.fact_kind === "weather" ? "risk" : "rule",
            source_url: sourceUrl,
            source_quote: quote,
            source_span: evidenceField(evidence, "source_span", "source text"),
            query: evidenceField(
              evidence,
              "query",
              "grounded value extraction",
            ),
            validator_family: evidence.fact_kind,
            validator_reason:
              "Operator reviewed source span before activation.",
          }),
        },
      );
      await refresh();
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
      <div className="workflowSplit groundingWorkbench">
        <section className="workspacePanel groundingLedger">
          <div className="canvasCommandBar">
            <div>
              <h2>Provenance ledger</h2>
              <p>
                Every bound value names the source span, extraction mode,
                validator, and date coverage.
              </p>
            </div>
            <div className="commandMetrics">
              <DataField label="Evidence">{data.grounding.length}</DataField>
              <DataField label="Values">{groundedValues.length}</DataField>
              <DataField label="Constraints">
                {data.constraints.length}
              </DataField>
            </div>
          </div>
          <div className="groundingCards">
            {data.grounding.map((evidence) => (
              <article
                className={`evidenceCard ${evidence.fact_kind}`}
                key={evidence.id}
              >
                <header>
                  <div>
                    <span className="material-symbols-outlined">
                      {evidence.fact_kind === "weather"
                        ? "cloud_sync"
                        : "verified"}
                    </span>
                    <h2>
                      {evidence.id} · {evidence.fact_kind} ·{" "}
                      {evidence.location_id}
                    </h2>
                  </div>
                  <Pill
                    tone={
                      evidence.status === "accepted" || evidence.status === "ok"
                        ? "good"
                        : "warn"
                    }
                  >
                    {evidence.status}
                  </Pill>
                </header>
                <div className="evidenceGrid">
                  <DataField label="Target date">
                    {evidence.target_date}
                  </DataField>
                  <DataField label="Source domain">
                    {evidenceSourceUrl(evidence) || "not recorded"}
                  </DataField>
                  <DataField label="Source span">
                    {evidenceField(evidence, "source_span", "source text")}
                  </DataField>
                  <DataField label="Query">
                    {evidenceField(evidence, "query", "grounding query")}
                  </DataField>
                </div>
                <blockquote>
                  {evidenceQuote(evidence) ||
                    "Source span will appear here after retrieval."}
                </blockquote>
                <button type="button" onClick={() => recordValue(evidence)}>
                  Record reviewed grounded value
                </button>
              </article>
            ))}
            {!data.grounding.length && (
              <EmptyState>
                No grounding evidence yet. Run grounding from the inspector.
              </EmptyState>
            )}
          </div>
        </section>
        <aside className="inspectorPanel sourceInspector">
          <div className="inspectorHeader">
            <p className="eyebrow">Ground a value</p>
            <h2>Source inspector</h2>
            <p>
              Retrieval is advisory until a human records the reviewed value.
            </p>
          </div>
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
                firstBoardStrip(data.board)?.location_id ?? "location id"
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
          <div className="inspectorSection">
            <h3>Selected evidence</h3>
            {selectedEvidence ? (
              <div className="dataStack">
                <DataField label="Provider response">
                  {asString(selectedEvidence.evidence.provider_response_id)}
                </DataField>
                <DataField label="Content hash">
                  {asString(selectedEvidence.evidence.content_hash)}
                </DataField>
                <DataField label="Extraction mode">
                  {asString(
                    selectedEvidence.evidence.extraction_mode,
                    "full content",
                  )}
                </DataField>
              </div>
            ) : (
              <EmptyState>No selected source yet.</EmptyState>
            )}
          </div>
          {groundedValues.length > 0 && (
            <div className="inspectorSection">
              <h3>Recorded values</h3>
              {groundedValues.map((value) => (
                <article className="miniRecord" key={value.id}>
                  <strong>{value.id}</strong>
                  <span>
                    {value.units} · {value.derived_from} · covers date:{" "}
                    {String(value.covering_date)}
                  </span>
                </article>
              ))}
            </div>
          )}
        </aside>
      </div>
    </ScreenShell>
  );
}

export function ReplanOptionsScreen({ productionId, boardId }: ScreenProps) {
  const { data, error, message, refresh, setError, setMessage } =
    useProductionData(productionId, boardId);
  const [actor, setActor] = useActor("first_ad");
  const [monitorKind, setMonitorKind] = useState("permit");
  const [monitorSourceUrl, setMonitorSourceUrl] = useState("");
  const [monitorQuery, setMonitorQuery] = useState("");
  const board = data.board;
  const lockedDates = new Set(data.locks.map((lock) => lock.shoot_date));

  const createMaterialMonitorReplan = async () => {
    const strip = firstBoardStrip(board);
    if (!board || !strip) {
      setError(
        "Open this screen with a board id before creating a material monitor replan.",
      );
      return;
    }
    const enteredSourceUrl = monitorSourceUrl.trim();
    const existingSource = data.monitoredSources.find(
      (source) =>
        source.board_id === board.id &&
        (!enteredSourceUrl || source.source_url === enteredSourceUrl),
    );
    const sourceUrl = enteredSourceUrl || existingSource?.source_url || "";
    if (!sourceUrl) {
      setError("Enter a monitored source URL before creating a replan.");
      return;
    }
    const query =
      monitorQuery.trim() || `${monitorKind} monitor for ${strip.location_id}`;
    setError("");
    try {
      const source =
        existingSource ??
        (await coversetFetch<MonitoredSource>(
          `/productions/${productionId}/monitored-sources`,
          {
            method: "POST",
            body: JSON.stringify({
              board_id: board.id,
              source_url: sourceUrl,
              fact_kind: monitorKind,
              location_id: strip.location_id,
              query,
              external_monitor_id: `operator-monitor-${Date.now()}`,
            }),
          },
        ));
      const event = await coversetFetch<MonitorChangeEvent>(
        `/productions/${productionId}/monitor/events`,
        {
          method: "POST",
          body: JSON.stringify({
            monitored_source_id: source.id,
            board_id: board.id,
            source_url: source.source_url,
            fact_kind: source.fact_kind,
            old_fingerprint: source.last_fingerprint || "unseen",
            new_fingerprint: `${source.last_fingerprint || "changed"}-${Date.now()}`,
            affected_work_ids: [strip.work_id],
            material: true,
            message: `Material ${source.fact_kind} change: ${query}`,
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
      <section className="commandBanner warning replanAlert">
        <div>
          <h2>Material fact change</h2>
          <p>
            Monitor changes can open requests, but cannot select a board.
            Options below preserve locked history and expose cost approval
            requirements.
          </p>
        </div>
        <div className="commandMetrics">
          <DataField label="Requests">{data.replanRequests.length}</DataField>
          <DataField label="Options">{data.scheduleDiffs.length}</DataField>
          <DataField label="Locked days">{data.locks.length}</DataField>
        </div>
      </section>
      <div className="replanBoard">
        <aside className="historyColumn">
          <header>
            <span>Shot days</span>
            <Pill>{data.locks.length ? "immutable" : "unlocked"}</Pill>
          </header>
          <div className="historyList">
            {(board?.result.days ?? []).map((day, index) => (
              <div
                className={lockedDates.has(day.date) ? "locked" : "current"}
                key={day.date}
              >
                <strong>Day {index + 1}</strong>
                <span>{day.date}</span>
                <small>
                  {lockedDates.has(day.date) ? "locked" : "available"}
                </small>
              </div>
            ))}
            {!board && <EmptyState>No board history yet.</EmptyState>}
          </div>
        </aside>
        <main className="optionDeck">
          {data.scheduleDiffs.map((diff, index) => (
            <article className="optionCard" key={diff.id}>
              <header>
                <div>
                  <span className="caps">
                    Option {String.fromCharCode(65 + index)}
                  </span>
                  <h3>{diff.id}</h3>
                  <p>
                    {diff.base_board_id} → {diff.revised_board_id} · validation
                    report expected before selection
                  </p>
                </div>
                <Pill tone={diff.cost_delta > 0 ? "warn" : "good"}>
                  {diff.required_approvals.length
                    ? "approval gate"
                    : "validated"}
                </Pill>
              </header>
              <MetricGrid
                items={[
                  ["Cost delta", `$${diff.cost_delta.toLocaleString()}`],
                  [
                    "Added days",
                    asStringList(diff.diff.added_days).length || 0,
                  ],
                  [
                    "Added pickups",
                    asStringList(diff.diff.added_pickups).join(", ") || "none",
                  ],
                  ["Approvals", diff.required_approvals.length || "none"],
                ]}
              />
              {diff.rendered_text && <pre>{diff.rendered_text}</pre>}
              <div className="actions optionActions">
                <button type="button" onClick={() => selectBoard(diff)}>
                  Select revised board as {roleNames[actor.role]}
                </button>
                <a
                  className="buttonLink secondary"
                  href={`/productions/${diff.production_id}/board/${diff.revised_board_id}`}
                >
                  Open board
                </a>
              </div>
            </article>
          ))}
          {!data.scheduleDiffs.length && (
            <EmptyState>
              No schedule diffs yet. Generate options from a replan request.
            </EmptyState>
          )}
        </main>
        <aside className="inspectorPanel replanInspector">
          <div className="inspectorHeader">
            <p className="eyebrow">First AD authority</p>
            <h2>Selection</h2>
            <p>
              The UI can propose options, but the API enforces board selection.
            </p>
          </div>
          <ActorRoleControl
            actor={actor}
            onActorChange={setActor}
            roles={["first_ad", "director", "producer"]}
          />
          <label>
            Fact kind
            <select
              value={monitorKind}
              onChange={(event) => setMonitorKind(event.target.value)}
            >
              <option value="permit">Permit</option>
              <option value="weather">Weather</option>
            </select>
          </label>
          <label>
            Source URL
            <input
              value={monitorSourceUrl}
              placeholder={
                data.monitoredSources[0]?.source_url ?? "https://..."
              }
              onChange={(event) => setMonitorSourceUrl(event.target.value)}
            />
          </label>
          <label>
            Monitor query
            <input
              value={monitorQuery}
              placeholder="What changed in the source?"
              onChange={(event) => setMonitorQuery(event.target.value)}
            />
          </label>
          <button
            type="button"
            onClick={createMaterialMonitorReplan}
            disabled={!board}
          >
            Create material monitor replan
          </button>
          <div className="inspectorSection">
            <h3>Replan requests</h3>
            {data.replanRequests.map((request) => (
              <article className="miniRecord" key={request.id}>
                <strong>{request.id}</strong>
                <span>{request.reason || request.requester_component}</span>
                <button type="button" onClick={() => generateOptions(request)}>
                  Generate options
                </button>
              </article>
            ))}
            {!data.replanRequests.length && (
              <EmptyState>No replan requests yet.</EmptyState>
            )}
          </div>
        </aside>
      </div>
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
  const [findingMessage, setFindingMessage] = useState("");
  const board = data.board;
  const strips = board?.result.strips ?? [];
  const primaryStrip = firstBoardStrip(board);
  const selectedFinding =
    finding ??
    (primaryStrip
      ? coverageFindingForStrip(
          data.coverageItems,
          data.coverageFindings,
          primaryStrip,
        )
      : (data.coverageFindings[0] ?? null));
  const selectedPickup =
    pickup ?? pickupForFinding(data.pickupTasks, selectedFinding) ?? null;
  const selectedCoverageItem =
    coverageItem ??
    data.coverageItems.find(
      (item) => item.id === selectedFinding?.coverage_item_id,
    ) ??
    (primaryStrip
      ? coverageItemsForStrip(data.coverageItems, primaryStrip)[0]
      : data.coverageItems[0]) ??
    null;
  const selectedPickupReplan =
    pickupReplan ??
    data.replanRequests.find(
      (request) =>
        request.source_kind === "pickup" &&
        request.source_id === selectedPickup?.id,
    ) ??
    null;

  const createFinding = async () => {
    const strip = firstBoardStrip(board);
    if (!board || !strip) {
      setError(
        "Open this screen with a board id before creating coverage actuals.",
      );
      return;
    }
    if (!findingMessage.trim()) {
      setError("Enter a coverage finding before recording actuals.");
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
            coverage_key: `operator-${strip.scene_id}-insert-${Date.now()}`,
            coverage_type: "insert",
            planned: { shot: "insert", source: "script supervisor actual" },
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
            message: findingMessage.trim(),
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
    if (!selectedFinding) return;
    setError("");
    try {
      const task = await coversetFetch<PickupTask>(
        `/coverage-findings/${selectedFinding.id}/pickup`,
        {
          method: "POST",
          body: JSON.stringify({
            actor_name: defaultNames.director,
            actor_role: "director",
          }),
        },
      );
      setPickup(task);
      await refresh();
      setMessage(`Director requested pickup ${task.id}.`);
    } catch (err) {
      setError(formatError(err));
    }
  };

  const confirmPickup = async () => {
    const strip = firstBoardStrip(board);
    if (!selectedPickup || !strip) return;
    setError("");
    try {
      const task = await coversetFetch<PickupTask>(
        `/pickup-tasks/${selectedPickup.id}/confirm`,
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
      await refresh();
      setMessage(`First AD confirmed pickup spec ${task.id}.`);
    } catch (err) {
      setError(formatError(err));
    }
  };

  const createPickupReplan = async () => {
    const shootDate = firstBoardDate(board);
    if (!selectedPickup || !board || !shootDate) return;
    setError("");
    try {
      const request = await coversetFetch<ReplanRequest>(
        `/pickup-tasks/${selectedPickup.id}/replan`,
        {
          method: "POST",
          body: JSON.stringify({
            current_board_id: board.id,
            cutoff_at: `${shootDate}T12:00:00-04:00`,
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
    const shootDate = firstBoardDate(board);
    if (!board || !shootDate) {
      setError("Load a board with at least one shoot day before locking.");
      return;
    }
    setError("");
    try {
      await coversetFetch<LockedDay>(`/boards/${board.id}/locks`, {
        method: "POST",
        body: JSON.stringify({
          shoot_date: shootDate,
          call_sheet_version: `actuals-${shootDate}`,
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
      <div className="workflowSplit coverageWorkbench">
        <section className="workspacePanel coverageCanvas">
          <div className="canvasCommandBar">
            <div>
              <h2>Completed coverage</h2>
              <p>
                Record actuals, expose advisory gaps, and route human decisions
                into pickup work.
              </p>
            </div>
            <div className="commandMetrics">
              <DataField label="Strips">{strips.length}</DataField>
              <DataField label="Locked days">{data.locks.length}</DataField>
              <DataField label="Findings">
                {data.coverageFindings.length}
              </DataField>
            </div>
          </div>
          <div className="coverageList">
            {strips.map((strip) => {
              const stripItems = coverageItemsForStrip(
                data.coverageItems,
                strip,
              );
              const stripFinding = coverageFindingForStrip(
                data.coverageItems,
                data.coverageFindings,
                strip,
              );
              const shotCount = stripItems.filter(
                (item) => item.status !== "planned",
              ).length;
              return (
                <article
                  className={`coverageCard ${stripFinding ? "needsReview" : "validated"}`}
                  key={strip.work_id}
                >
                  <header>
                    <div>
                      <span className="sceneNumber">{strip.scene_number}</span>
                      <h3>{asString(strip.slugline, strip.scene_id)}</h3>
                    </div>
                    <Pill tone={stripFinding ? "warn" : "good"}>
                      {stripFinding ? "needs review" : "validated"}
                    </Pill>
                  </header>
                  <div className="coverageMeta">
                    <DataField label="Cast">
                      {strip.cast_ids.join(", ") || "—"}
                    </DataField>
                    <DataField label="Location">
                      {stripLocation(strip)}
                    </DataField>
                    <DataField label="Coverage items">
                      {stripItems.length
                        ? `${shotCount} / ${stripItems.length}`
                        : "none"}
                    </DataField>
                  </div>
                  {stripFinding && (
                    <div className="advisoryCard">
                      <Pill tone="advisory">Advisory finding</Pill>
                      <p>{stripFinding.message}</p>
                    </div>
                  )}
                </article>
              );
            })}
            {!strips.length && <EmptyState>No board strips loaded.</EmptyState>}
          </div>
          <div className="lockActualsPanel">
            <h2>Before this day can lock</h2>
            <div className="checklist">
              <span>✓ Every strip has an outcome recorded</span>
              <span>✓ Actual call and wrap captured by Script Supervisor</span>
              <span>✓ Part-shot remainder converted to schedulable work</span>
              <span>✓ Recorded by {defaultNames.script_supervisor}</span>
            </div>
          </div>
          {data.locks.length > 0 && (
            <div className="lockList">
              {data.locks.map((lock) => (
                <article className="miniRecord" key={lock.id}>
                  <strong>{lock.shoot_date}</strong>
                  <span>
                    {lock.locked_assignments.length} assignments immutable ·{" "}
                    {lock.recorded_by_role}
                  </span>
                </article>
              ))}
            </div>
          )}
        </section>
        <aside className="inspectorPanel coverageInspector">
          <div className="inspectorHeader">
            <p className="eyebrow">Script Supervisor</p>
            <h2>{defaultNames.script_supervisor}</h2>
            <p>May record actuals and raise findings; may not select boards.</p>
          </div>
          <button type="button" onClick={lockDay} disabled={!board}>
            Lock first board day
          </button>
          <label>
            Finding message
            <textarea
              value={findingMessage}
              placeholder="Describe the unusable or missing coverage."
              onChange={(event) => setFindingMessage(event.target.value)}
            />
          </label>
          <button
            type="button"
            onClick={createFinding}
            disabled={!board || !findingMessage.trim()}
          >
            Record coverage finding
          </button>
          <div className="inspectorSection">
            <h3>Director decision</h3>
            <div className="stackedButtons">
              <button
                type="button"
                onClick={requestPickup}
                disabled={!selectedFinding}
              >
                Director requests pickup
              </button>
              <button
                type="button"
                onClick={confirmPickup}
                disabled={!selectedPickup}
              >
                First AD confirms spec
              </button>
              <button
                type="button"
                onClick={createPickupReplan}
                disabled={!selectedPickup}
              >
                Create pickup replan
              </button>
            </div>
          </div>
          {selectedCoverageItem && <JsonBlock value={selectedCoverageItem} />}
          {selectedFinding && <JsonBlock value={selectedFinding} />}
          {selectedPickup && <JsonBlock value={selectedPickup} />}
          {selectedPickupReplan && <JsonBlock value={selectedPickupReplan} />}
          <div className="inspectorSection">
            <h3>Related schedule diffs</h3>
            {data.scheduleDiffs.slice(0, 2).map((diff) => (
              <DiffCard diff={diff} key={diff.id} baseBoardId={boardId} />
            ))}
            {!data.scheduleDiffs.length && (
              <EmptyState>Open Replans after creating pickup work.</EmptyState>
            )}
          </div>
        </aside>
      </div>
    </ScreenShell>
  );
}

export function CallSheetsScreen({ productionId, boardId }: ScreenProps) {
  const { data, error, message, refresh, setData, setError, setMessage } =
    useProductionData(productionId, boardId);
  const [actor, setActor] = useActor("second_ad");
  const [shootDate, setShootDate] = useState("");
  const [selected, setSelected] = useState<CallSheet | null>(null);
  const board = data.board;
  const dayOptions = useMemo(() => board?.result.days ?? [], [board]);

  useEffect(() => {
    if (dayOptions[0]?.date && !shootDate) {
      setShootDate(dayOptions[0].date);
    }
  }, [dayOptions, shootDate]);

  useEffect(() => {
    if (!selected && data.callSheets[0]) {
      setSelected(data.callSheets[0]);
    }
  }, [data.callSheets, selected]);

  const generate = async () => {
    if (!board || !shootDate) {
      setError("Open call sheets with a board shoot date before generating.");
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
      await refresh();
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
      <div className="workflowSplit callSheetWorkbench">
        <main className="callSheetPaper workspacePanel">
          <div className="paperHeader">
            <div>
              <p className="eyebrow">Call sheet</p>
              <h2>
                {asString(
                  selected?.payload.call_sheet_version,
                  selected?.id ?? "Preview",
                )}
              </h2>
              <p>
                {selected?.shoot_date ?? shootDate} · board {board?.id ?? "—"}
              </p>
            </div>
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
            <div className="paperSections">
              <MetricGrid
                items={[
                  ["Crew call", asString(selected.payload.crew_call, "—")],
                  [
                    "Wrap estimate",
                    asString(
                      selected.payload.wrap_estimate,
                      asString(selected.payload.wrap, "—"),
                    ),
                  ],
                  ["Generated by", selected.generated_by_name],
                  ["Recipients", selected.payload.recipients?.length ?? 0],
                ]}
              />
              <div className="callSheetColumns">
                <div className="gridPanel">
                  <h4>Scenes</h4>
                  <JsonBlock value={selected.payload.scenes ?? []} />
                </div>
                <div className="gridPanel">
                  <h4>Cast calls</h4>
                  <JsonBlock value={selected.payload.cast_calls ?? []} />
                </div>
                <div className="gridPanel">
                  <h4>Turnaround notes</h4>
                  <JsonBlock value={selected.payload.turnaround_notes ?? []} />
                </div>
                <div className="gridPanel">
                  <h4>Permit notes</h4>
                  <JsonBlock value={selected.payload.permit_notes ?? []} />
                </div>
              </div>
              <pre>{selected.rendered_text}</pre>
            </div>
          ) : (
            <EmptyState>Select or generate a call sheet.</EmptyState>
          )}
        </main>
        <aside className="inspectorPanel callSheetInspector">
          <div className="inspectorHeader">
            <p className="eyebrow">Inspector</p>
            <h2>Generate</h2>
            <p>Only the Second AD endpoint may persist a call sheet.</p>
          </div>
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
          <button
            type="button"
            onClick={generate}
            disabled={!board || !shootDate}
          >
            Generate call sheet
          </button>
          <p className="muted">
            Try First AD to see the API-enforced rejection; switch back to
            Second AD for success.
          </p>
          <div className="inspectorSection">
            <h3>Existing sheets</h3>
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
        </aside>
      </div>
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
      <section className="auditHeader">
        <div>
          <h2>Production Provenance Ledger</h2>
          <p>
            Advisory events, solver decisions, human approvals, exports, locks,
            and replans are kept in chronological order.
          </p>
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
      <section className="auditLedger">
        <div className="auditLedgerHeader">
          <span>Timestamp</span>
          <span>Agent / type</span>
          <span>ICN</span>
          <span>Event description</span>
          <span>Data</span>
        </div>
        <div className="auditRows">
          {data.audit.map((event) => (
            <article className="auditRow" key={event.id}>
              <span className="mono">
                [{new Date(event.created_at).toLocaleTimeString()}]
              </span>
              <Pill>{event.event_type}</Pill>
              <span className="material-symbols-outlined">history</span>
              <div>
                <strong>{event.actor}</strong>
                <p>{new Date(event.created_at).toLocaleString()}</p>
                <JsonBlock value={event.payload} />
              </div>
              <span className="mono right">{event.id}</span>
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
  const approvals = data.costApprovals;
  const selectedDiff = data.scheduleDiffs[0] ?? null;

  const approve = async (
    diff: ScheduleDiff,
    decision: "approved" | "rejected",
  ) => {
    const addedDays = asStringList(diff.diff.added_days);
    const fallbackDay = data.board?.result.days?.at(-1)?.date;
    setError("");
    try {
      await coversetFetch<CostApproval>(
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
      <section className="commandBanner warning costGateBanner">
        <div>
          <h2>
            {selectedDiff
              ? `${selectedDiff.revised_board_id} cannot be selected yet`
              : "No cost-gated board selected"}
          </h2>
          <p>
            Added-day exposure stays pending until a UPM or Line Producer
            records a decision. The First AD may select boards, but may not
            spend.
          </p>
        </div>
        <div className="commandMetrics">
          <DataField label="Cost delta">
            ${selectedDiff?.cost_delta.toLocaleString() ?? "0"}
          </DataField>
          <DataField label="Diffs">{data.scheduleDiffs.length}</DataField>
          <DataField label="Decisions">{approvals.length}</DataField>
        </div>
      </section>
      <div className="workflowSplit costWorkbench">
        <main className="workspacePanel costCanvas">
          <h2>What changes, in production terms</h2>
          {selectedDiff ? (
            <div className="costTable">
              <div className="costHeader">
                <span>Measure</span>
                <span>Base</span>
                <span>Revised</span>
                <span>Delta</span>
              </div>
              {[
                [
                  "Shoot days",
                  "current",
                  "revised",
                  asStringList(selectedDiff.diff.added_days).length,
                ],
                [
                  "Pickups added",
                  "0",
                  "new work",
                  asStringList(selectedDiff.diff.added_pickups).length,
                ],
                [
                  "Call times changed",
                  "—",
                  "changed",
                  asStringList(selectedDiff.diff.changed_call_times).length,
                ],
                [
                  "Cost exposure",
                  "$0",
                  `$${selectedDiff.cost_delta.toLocaleString()}`,
                  `$${selectedDiff.cost_delta.toLocaleString()}`,
                ],
              ].map(([label, base, revised, delta]) => (
                <div className="costRow" key={label}>
                  <span>{label}</span>
                  <span>{base}</span>
                  <span>{revised}</span>
                  <span>{delta}</span>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState>
              No schedule diffs yet. Create options from Replans or Coverage
              first.
            </EmptyState>
          )}
          <div className="authorizationTrace">
            <Pill tone="advisory">finding · advisory</Pill>
            <span>→</span>
            <Pill>Director decision</Pill>
            <span>→</span>
            <Pill>First AD spec</Pill>
            <span>→</span>
            <Pill tone="warn">UPM / Line Producer</Pill>
          </div>
          <div className="optionDeck compactDeck">
            {data.scheduleDiffs.map((diff) => (
              <article className="optionCard" key={diff.id}>
                <DiffCard diff={diff} baseBoardId={boardId} />
                <div className="actions">
                  <button
                    type="button"
                    onClick={() => approve(diff, "approved")}
                  >
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
          </div>
        </main>
        <aside className="inspectorPanel costInspector">
          <div className="inspectorHeader">
            <p className="eyebrow">Record a decision</p>
            <h2>Approver</h2>
            <p>Authority is enforced by the API, not by presentation state.</p>
          </div>
          <ActorRoleControl
            actor={actor}
            onActorChange={setActor}
            roles={["upm", "line_producer", "first_ad"]}
          />
          <div className="dataStack">
            <DataField label="Approver">{actor.name}</DataField>
            <DataField label="Role">{roleNames[actor.role]}</DataField>
            <DataField label="Board">
              {selectedDiff?.revised_board_id ?? "pending"}
            </DataField>
          </div>
          <div className="inspectorSection">
            <h3>Recorded in this session</h3>
            {approvals.map((approval) => (
              <JsonBlock key={approval.id} value={approval} />
            ))}
            {!approvals.length && (
              <EmptyState>No persisted cost decisions yet.</EmptyState>
            )}
          </div>
        </aside>
      </div>
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
      <div className="workflowSplit infeasibleWorkbench">
        <main className="workspacePanel conflictCanvas">
          <section className="commandBanner errorBanner">
            <div>
              <h2>
                {failedJobs.length
                  ? "No valid board exists"
                  : "No conflict set yet"}
              </h2>
              <p>
                CP-SAT infeasible is different from a budget timeout. This page
                only renders failure facts the API actually returned.
              </p>
            </div>
            <div className="commandMetrics">
              <DataField label="Board status">
                {data.board?.solver_status ?? "no board"}
              </DataField>
              <DataField label="Failed jobs">{failedJobs.length}</DataField>
              <DataField label="Constraints">
                {data.constraints.length}
              </DataField>
            </div>
          </section>
          {failedJobs.length > 0 ? (
            <section className="conflictSet">
              <h2>Reported failures</h2>
              {failedJobs.map((job, index) => (
                <article className="conflictCard" key={job.id}>
                  <header>
                    <span className="mono">{index + 1}</span>
                    <strong>{job.job_type}</strong>
                    <Pill tone="error">{job.status}</Pill>
                  </header>
                  <p className="errorText">{job.error || "failed"}</p>
                  <JsonBlock value={job.result} />
                </article>
              ))}
            </section>
          ) : (
            <EmptyState>
              No infeasible or failed schedule run is available for this
              production.
            </EmptyState>
          )}
        </main>
        <aside className="inspectorPanel conflictInspector">
          <div className="inspectorHeader">
            <p className="eyebrow">What you can do</p>
            <h2>Production decision required</h2>
            <p>
              Coverset will not pick for you. Relaxing a constraint is a human
              decision with a recorded actor, reason, and new snapshot.
            </p>
          </div>
          <div className="inspectorSection routeCards compact">
            <a
              className="buttonLink"
              href={withBoard(
                `/productions/${productionId}/constraints`,
                boardId,
              )}
            >
              Review constraints
            </a>
            <a
              className="buttonLink secondary"
              href={withBoard(`/productions/${productionId}/replans`, boardId)}
            >
              Compare replans
            </a>
          </div>
          <div className="inspectorSection dashed">
            <h3>Not fabricated</h3>
            <p className="muted">
              The v4 reference shows a minimal conflict subset. This live route
              waits for backend conflict metadata before naming one.
            </p>
          </div>
        </aside>
      </div>
    </ScreenShell>
  );
}
