"use client";

import { useEffect, useMemo, useState } from "react";

type CastMember = {
    id: string;
    production_id: string;
    cast_id: string;
    performer: string;
    character: string;
    is_minor: boolean;
};

type LocationRow = {
    id: string;
    production_id: string;
    location_id: string;
    name: string;
    city: string;
    state: string;
    latitude: number | null;
    longitude: number | null;
    timezone: string;
    aliases: string[];
};

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
    proposal_scene: Record<string, unknown> | null;
    confidence: number | null;
    status: string;
    accepted: boolean;
    rejected: boolean;
    schedulable: boolean;
    resolution_errors: string[];
    number_synthesized: boolean;
};

type BreakdownRun = {
    id: string;
    production_id: string;
    screenplay_asset_id: string;
    status: string;
    agent_mode: string;
    error: string;
    unresolved_locations: string[];
    unresolved_cast: string[];
    candidates: Candidate[];
};

type CandidateBatchAcceptResponse = {
    accepted: string[];
    skipped: Record<string, string[]>;
    candidates: Candidate[];
};

type ScheduleRun = {
    id: string;
    status: string;
    board_id: string | null;
    error: string;
};

type Job = {
    id: string;
    production_id: string | null;
    job_type: string;
    target_id: string;
    status: string;
    attempts: number;
    error: string;
    result: Record<string, unknown>;
};

type GroundingEvidence = {
    id: string;
    production_id: string;
    location_id: string;
    fact_kind: string;
    target_date: string;
    status: string;
    error: string;
    evidence: {
        covering_urls?: string[];
        source_urls?: string[];
    };
};

type ConstraintRow = {
    id: string;
    production_id: string;
    constraint_id: string;
    family: string;
    policy: string;
    active: boolean;
    constraint: Record<string, unknown>;
    provenance: Record<string, unknown>;
};

type BoardStrip = {
    work_id: string;
    location_id: string;
    shoot_day: string;
    sequence: number;
    planned_call_time: string;
    planned_wrap_time: string;
    scene_id: string;
    kind: string;
    duration_minutes: number | null;
    day_night: string;
    flags: Record<string, boolean>;
    requires_daylight: boolean | null;
    location: { id: string; name: string; place: string };
    cast: Array<{ id: string; character: string; performer: string }>;
    cast_ids: string[];
};

type ExplanationTrace = {
    constraint_id: string;
    family: string;
    policy: string;
    satisfied: boolean;
    detail: string;
    source: string;
};

type Board = {
    id: string;
    solver_status: string;
    stripboard: string;
    result: {
        strips?: BoardStrip[];
        explanation_traces?: ExplanationTrace[];
        days?: Array<{
            date: string;
            call_time: string | null;
            wrap_time: string | null;
            company_moves: number;
            assignments: Array<{
                work_id: string;
                location_id: string;
                shoot_day: string;
                sequence: number;
            }>;
            strips?: BoardStrip[];
        }>;
    };
};

type Production = {
    id: string;
    title: string;
    cast_count: number;
    location_count: number;
    shoot_day_count: number;
};

type ScreenplayAsset = {
    id: string;
    filename: string;
    normalized_text_uri: string | null;
    extraction_error: string;
};

type CandidateFilter = "all" | "ready" | "blocked" | "accepted" | "rejected";
type AgentMode = "gemini" | "fixture";

type CandidatePatch = {
    scene_number?: string;
    slugline?: string;
    int_ext?: string;
    day_night?: string;
    location_ref?: string;
    page_eighths?: number;
    cast_ids?: string[];
    flags?: Record<string, boolean>;
};

const STORAGE_KEY = "coverset.production_id";

function textExcerpt(text: string): string {
    return text
        .replace(/<[^>]*>/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 240);
}

function errorMessage(payload: unknown, fallback: string): string {
    if (payload && typeof payload === "object") {
        const shaped = payload as { detail?: unknown; error?: unknown };
        if (typeof shaped.detail === "string") return shaped.detail;
        if (typeof shaped.error === "string") return shaped.error;
    }
    return fallback;
}

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
    const response = await fetch(url, {
        ...init,
        headers:
            init?.body instanceof FormData
                ? init.headers
                : {
                      "content-type": "application/json",
                      ...(init?.headers ?? {}),
                  },
    });
    const text = await response.text();
    const fallback = `${response.status} ${response.statusText}`;
    if (!text) {
        if (!response.ok) throw new Error(fallback);
        return {} as T;
    }

    const contentType = response.headers.get("content-type") ?? "";
    if (!contentType.includes("application/json")) {
        const excerpt = textExcerpt(text);
        throw new Error(excerpt ? `${fallback}: ${excerpt}` : fallback);
    }

    let payload: unknown;
    try {
        payload = JSON.parse(text);
    } catch {
        throw new Error(`${fallback}: invalid JSON response`);
    }
    if (!response.ok) {
        throw new Error(errorMessage(payload, fallback));
    }
    return payload as T;
}

function flagText(flags: Record<string, boolean>): string {
    return (
        Object.entries(flags)
            .filter(([, value]) => value)
            .map(([key]) => key)
            .join(", ") || "none"
    );
}

function candidateClass(candidate: Candidate): string {
    if (candidate.accepted) return "scene accepted";
    if (candidate.rejected) return "scene rejected";
    if (!candidate.schedulable) return "scene blocked";
    return "scene ready";
}

function splitList(value: string): string[] {
    return value
        .split(",")
        .map((entry) => entry.trim())
        .filter(Boolean);
}

function parsePositiveInteger(value: string, fallback: number): number {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function jobClass(job: Job): string {
    if (job.status === "complete") return "pill good";
    if (job.status === "failed") return "pill warn";
    return "pill";
}

function resultString(job: Job, key: string): string {
    const value = job.result[key];
    return typeof value === "string" ? value : "";
}

function timeLabel(value: string | null): string {
    if (!value) return "--";
    return new Date(value).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
    });
}

function expressionSummary(row: ConstraintRow): string {
    const expression = row.constraint["expression"];
    if (!expression || typeof expression !== "object") return "constraint";
    const shaped = expression as Record<string, unknown>;
    if (typeof shaped.type === "string") return shaped.type.replaceAll("_", " ");
    return "constraint";
}

function CandidateEditor({
    candidate,
    onSave,
    onReview,
}: {
    candidate: Candidate;
    onSave: (candidateId: string, patch: CandidatePatch) => Promise<void>;
    onReview: (
        candidateId: string,
        decision: "accept" | "reject",
    ) => Promise<void>;
}) {
    const [sceneNumber, setSceneNumber] = useState(candidate.scene_number);
    const [slugline, setSlugline] = useState(candidate.slugline);
    const [locationRef, setLocationRef] = useState(candidate.location_ref);
    const [castIds, setCastIds] = useState(candidate.cast_ids.join(", "));
    const [pageEighths, setPageEighths] = useState(
        String(candidate.page_eighths),
    );
    const [intExt, setIntExt] = useState(candidate.int_ext);
    const [dayNight, setDayNight] = useState(candidate.day_night);
    const [stunts, setStunts] = useState(Boolean(candidate.flags.stunts));
    const [minors, setMinors] = useState(Boolean(candidate.flags.minors));
    const [vfx, setVfx] = useState(Boolean(candidate.flags.vfx));

    async function save() {
        await onSave(candidate.id, {
            scene_number: sceneNumber,
            slugline,
            location_ref: locationRef,
            cast_ids: splitList(castIds),
            page_eighths: parsePositiveInteger(
                pageEighths,
                candidate.page_eighths,
            ),
            int_ext: intExt,
            day_night: dayNight,
            flags: { stunts, minors, vfx },
        });
    }

    return (
        <article className={candidateClass(candidate)}>
            <div className="sceneHeader">
                <strong>{candidate.scene_number}</strong>
                <span>{candidate.slugline}</span>
                <span className="pill">{candidate.status}</span>
                {candidate.schedulable ? (
                    <span className="pill good">schedulable</span>
                ) : (
                    <span className="pill warn">blocked</span>
                )}
            </div>
            <small>
                {candidate.int_ext}/{candidate.day_night} ·{" "}
                {candidate.location_ref} · cast:{" "}
                {candidate.cast_ids.join(", ") || "-"} · flags:{" "}
                {flagText(candidate.flags)}
                {candidate.source_page_range
                    ? ` · source: ${candidate.source_page_range}`
                    : ""}
                {candidate.number_synthesized ? " · synthesized number" : ""}
            </small>
            {candidate.resolution_errors.length > 0 && (
                <ul className="errorList">
                    {candidate.resolution_errors.map((message) => (
                        <li key={message}>{message}</li>
                    ))}
                </ul>
            )}
            <details>
                <summary>Edit candidate</summary>
                <div className="candidateForm">
                    <label>
                        Scene #
                        <input
                            value={sceneNumber}
                            onChange={(event) =>
                                setSceneNumber(event.target.value)
                            }
                        />
                    </label>
                    <label className="wide">
                        Slugline
                        <input
                            value={slugline}
                            onChange={(event) =>
                                setSlugline(event.target.value)
                            }
                        />
                    </label>
                    <label>
                        INT/EXT
                        <select
                            value={intExt}
                            onChange={(event) => setIntExt(event.target.value)}
                        >
                            <option value="int">int</option>
                            <option value="ext">ext</option>
                            <option value="int_ext">int/ext</option>
                            <option value="unknown">unknown</option>
                        </select>
                    </label>
                    <label>
                        Day/night
                        <select
                            value={dayNight}
                            onChange={(event) =>
                                setDayNight(event.target.value)
                            }
                        >
                            <option value="day">day</option>
                            <option value="night">night</option>
                            <option value="dawn">dawn</option>
                            <option value="dusk">dusk</option>
                            <option value="unknown">unknown</option>
                        </select>
                    </label>
                    <label>
                        Location ID
                        <input
                            value={locationRef}
                            onChange={(event) =>
                                setLocationRef(event.target.value)
                            }
                        />
                    </label>
                    <label>
                        Page eighths
                        <input
                            value={pageEighths}
                            onChange={(event) =>
                                setPageEighths(event.target.value)
                            }
                            inputMode="numeric"
                        />
                    </label>
                    <label className="wide">
                        Cast IDs, comma-separated
                        <input
                            value={castIds}
                            onChange={(event) => setCastIds(event.target.value)}
                        />
                    </label>
                    <div className="checks wide">
                        <label>
                            <input
                                type="checkbox"
                                checked={stunts}
                                onChange={(event) =>
                                    setStunts(event.target.checked)
                                }
                            />{" "}
                            Stunts
                        </label>
                        <label>
                            <input
                                type="checkbox"
                                checked={minors}
                                onChange={(event) =>
                                    setMinors(event.target.checked)
                                }
                            />{" "}
                            Minors
                        </label>
                        <label>
                            <input
                                type="checkbox"
                                checked={vfx}
                                onChange={(event) =>
                                    setVfx(event.target.checked)
                                }
                            />{" "}
                            VFX
                        </label>
                    </div>
                    <button type="button" onClick={save}>
                        Save edit
                    </button>
                </div>
            </details>
            <div className="actions">
                <button
                    type="button"
                    onClick={() => onReview(candidate.id, "accept")}
                    disabled={!candidate.schedulable || candidate.accepted}
                >
                    Accept
                </button>
                <button
                    type="button"
                    className="secondary"
                    onClick={() => onReview(candidate.id, "reject")}
                    disabled={candidate.rejected}
                >
                    Reject
                </button>
            </div>
        </article>
    );
}

export default function Home() {
    const [title, setTitle] = useState("The Ferry Job");
    const [seedDemo, setSeedDemo] = useState(true);
    const [agentMode, setAgentMode] = useState<AgentMode>("gemini");
    const [file, setFile] = useState<File | null>(null);
    const [production, setProduction] = useState<Production | null>(null);
    const [castMembers, setCastMembers] = useState<CastMember[]>([]);
    const [locations, setLocations] = useState<LocationRow[]>([]);
    const [shootDates, setShootDates] = useState(
        "2026-09-14\n2026-09-15\n2026-09-16",
    );
    const [castForm, setCastForm] = useState({
        cast_id: "cast-maya",
        performer: "",
        character: "MAYA",
        is_minor: false,
    });
    const [locationForm, setLocationForm] = useState({
        location_id: "maya-s-apartment",
        name: "Maya's Apartment",
        city: "Brooklyn",
        state: "NY",
        latitude: "",
        longitude: "",
        timezone: "America/New_York",
        aliases: "",
    });
    const [asset, setAsset] = useState<ScreenplayAsset | null>(null);
    const [breakdown, setBreakdown] = useState<BreakdownRun | null>(null);
    const [filter, setFilter] = useState<CandidateFilter>("all");
    const [schedule, setSchedule] = useState<ScheduleRun | null>(null);
    const [board, setBoard] = useState<Board | null>(null);
    const [jobs, setJobs] = useState<Job[]>([]);
    const [grounding, setGrounding] = useState<GroundingEvidence[]>([]);
    const [constraints, setConstraints] = useState<ConstraintRow[]>([]);
    const [lockWorkId, setLockWorkId] = useState("W-BRK-001");
    const [lockDate, setLockDate] = useState("2026-09-14");
    const [groundingLocationId, setGroundingLocationId] = useState(
        "brooklyn-bridge-park",
    );
    const [groundingDate, setGroundingDate] = useState("2026-03-17");
    const [status, setStatus] = useState("Ready");
    const [error, setError] = useState("");

    useEffect(() => {
        const savedProduction = window.localStorage.getItem(STORAGE_KEY);
        if (savedProduction) {
            void refreshSetup(savedProduction);
        }
    }, []);

    const acceptedCount = useMemo(
        () =>
            breakdown?.candidates.filter((candidate) => candidate.accepted)
                .length ?? 0,
        [breakdown],
    );

    const readyCount = useMemo(
        () =>
            breakdown?.candidates.filter(
                (candidate) =>
                    candidate.schedulable &&
                    !candidate.accepted &&
                    !candidate.rejected,
            ).length ?? 0,
        [breakdown],
    );

    const visibleCandidates = useMemo(() => {
        const candidates = breakdown?.candidates ?? [];
        if (filter === "ready")
            return candidates.filter(
                (candidate) =>
                    candidate.schedulable &&
                    !candidate.accepted &&
                    !candidate.rejected,
            );
        if (filter === "blocked")
            return candidates.filter(
                (candidate) => !candidate.schedulable && !candidate.rejected,
            );
        if (filter === "accepted")
            return candidates.filter((candidate) => candidate.accepted);
        if (filter === "rejected")
            return candidates.filter((candidate) => candidate.rejected);
        return candidates;
    }, [breakdown, filter]);

    function replaceCandidate(updated: Candidate) {
        setBreakdown((current) =>
            current
                ? {
                      ...current,
                      candidates: current.candidates.map((candidate) =>
                          candidate.id === updated.id ? updated : candidate,
                      ),
                  }
                : current,
        );
    }

    function rememberJob(job: Job) {
        setJobs((current) => [
            job,
            ...current.filter((existing) => existing.id !== job.id),
        ]);
    }

    async function refreshJob(jobId: string): Promise<Job> {
        const job = await jsonFetch<Job>(`/api/coverset/jobs/${jobId}`);
        rememberJob(job);
        return job;
    }

    async function hydrateCompletedJob(job: Job) {
        const breakdownRunId = resultString(job, "breakdown_run_id");
        if (breakdownRunId) {
            setBreakdown(
                await jsonFetch<BreakdownRun>(
                    `/api/coverset/breakdowns/${breakdownRunId}`,
                ),
            );
        }

        const scheduleRunId = resultString(job, "schedule_run_id");
        if (scheduleRunId) {
            setSchedule(
                await jsonFetch<ScheduleRun>(
                    `/api/coverset/schedule-runs/${scheduleRunId}`,
                ),
            );
        }

        const boardId = resultString(job, "board_id");
        if (boardId) {
            setBoard(await jsonFetch<Board>(`/api/coverset/boards/${boardId}`));
        }

        if (resultString(job, "evidence_id") && job.production_id) {
            await refreshSetup(job.production_id);
        }
    }

    async function pollJob(job: Job): Promise<Job> {
        rememberJob(job);
        for (let attempt = 0; attempt < 90; attempt += 1) {
            const latest = await refreshJob(job.id);
            setStatus(
                `${latest.job_type} job ${latest.status} (${latest.attempts} attempt${latest.attempts === 1 ? "" : "s"}).`,
            );
            if (latest.status === "complete") {
                await hydrateCompletedJob(latest);
                return latest;
            }
            if (latest.status === "failed") {
                throw new Error(latest.error || `${latest.job_type} job failed`);
            }
            await sleep(2000);
        }
        throw new Error(`Timed out waiting for job ${job.id}`);
    }

    async function refreshSetup(productionId: string) {
        setError("");
        try {
            const [
                loadedProduction,
                loadedCast,
                loadedLocations,
                calendar,
                loadedJobs,
                loadedGrounding,
                loadedConstraints,
            ] = await Promise.all([
                jsonFetch<Production>(
                    `/api/coverset/productions/${productionId}`,
                ),
                jsonFetch<CastMember[]>(
                    `/api/coverset/productions/${productionId}/cast`,
                ),
                jsonFetch<LocationRow[]>(
                    `/api/coverset/productions/${productionId}/locations`,
                ),
                jsonFetch<{ shoot_dates: string[] }>(
                    `/api/coverset/productions/${productionId}/calendar`,
                ),
                jsonFetch<Job[]>(`/api/coverset/productions/${productionId}/jobs`),
                jsonFetch<GroundingEvidence[]>(
                    `/api/coverset/productions/${productionId}/grounding`,
                ),
                jsonFetch<ConstraintRow[]>(
                    `/api/coverset/productions/${productionId}/constraints`,
                ),
            ]);
            setProduction(loadedProduction);
            setTitle(loadedProduction.title);
            setCastMembers(loadedCast);
            setLocations(loadedLocations);
            setJobs(loadedJobs);
            setGrounding(loadedGrounding);
            setConstraints(loadedConstraints);
            if (loadedLocations.length > 0 && !groundingLocationId) {
                setGroundingLocationId(loadedLocations[0].location_id);
            }
            if (calendar.shoot_dates.length > 0) {
                setShootDates(calendar.shoot_dates.join("\n"));
            }
            window.localStorage.setItem(STORAGE_KEY, productionId);
            setStatus("Loaded saved production setup.");
        } catch (err) {
            window.localStorage.removeItem(STORAGE_KEY);
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Could not load saved production.");
        }
    }

    async function createProduction() {
        setError("");
        setBoard(null);
        setBreakdown(null);
        setAsset(null);
        setStatus(
            seedDemo
                ? "Creating production with demo setup..."
                : "Creating empty production...",
        );
        try {
            const createdProduction = await jsonFetch<Production>(
                "/api/coverset/productions",
                {
                    method: "POST",
                    body: JSON.stringify({ title, seed_demo_data: seedDemo }),
                },
            );
            window.localStorage.setItem(STORAGE_KEY, createdProduction.id);
            await refreshSetup(createdProduction.id);
            setStatus("Production setup ready.");
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Production creation failed.");
        }
    }

    async function addCastMember() {
        if (!production) return;
        setError("");
        try {
            await jsonFetch<CastMember>(
                `/api/coverset/productions/${production.id}/cast`,
                {
                    method: "POST",
                    body: JSON.stringify(castForm),
                },
            );
            await refreshSetup(production.id);
            setStatus("Cast member saved.");
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Cast save failed.");
        }
    }

    async function addLocation() {
        if (!production) return;
        setError("");
        const payload = {
            location_id: locationForm.location_id,
            name: locationForm.name,
            city: locationForm.city,
            state: locationForm.state,
            latitude: locationForm.latitude
                ? Number(locationForm.latitude)
                : null,
            longitude: locationForm.longitude
                ? Number(locationForm.longitude)
                : null,
            timezone: locationForm.timezone,
            aliases: splitList(locationForm.aliases),
        };
        try {
            await jsonFetch<LocationRow>(
                `/api/coverset/productions/${production.id}/locations`,
                {
                    method: "POST",
                    body: JSON.stringify(payload),
                },
            );
            await refreshSetup(production.id);
            setStatus("Location saved.");
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Location save failed.");
        }
    }

    async function saveCalendar() {
        if (!production) return;
        setError("");
        try {
            await jsonFetch(
                `/api/coverset/productions/${production.id}/calendar`,
                {
                    method: "PUT",
                    body: JSON.stringify({
                        shoot_dates: shootDates.split(/\s+/).filter(Boolean),
                    }),
                },
            );
            await refreshSetup(production.id);
            setStatus("Shooting calendar saved.");
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Calendar save failed.");
        }
    }

    async function runFixtureDemo() {
        setError("");
        setStatus("Running fixture demo through API, scheduler, and DB...");
        setBoard(null);
        try {
            const demoBoard = await jsonFetch<Board>("/api/coverset/demo/run", {
                method: "POST",
            });
            setBoard(demoBoard);
            setStatus("Fixture demo solved.");
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Demo failed.");
        }
    }

    async function uploadAndBreakDown() {
        if (!file) {
            setError("Choose a screenplay file first.");
            return;
        }
        let currentProduction = production;
        setError("");
        setBoard(null);
        setSchedule(null);
        try {
            if (!currentProduction) {
                setStatus("Creating production before upload...");
                currentProduction = await jsonFetch<Production>(
                    "/api/coverset/productions",
                    {
                        method: "POST",
                        body: JSON.stringify({
                            title,
                            seed_demo_data: seedDemo,
                        }),
                    },
                );
                window.localStorage.setItem(STORAGE_KEY, currentProduction.id);
                setProduction(currentProduction);
                await refreshSetup(currentProduction.id);
            }

            setStatus("Uploading screenplay...");
            const form = new FormData();
            form.append("file", file);
            const uploadedAsset = await jsonFetch<ScreenplayAsset>(
                `/api/coverset/productions/${currentProduction.id}/screenplays`,
                { method: "POST", body: form },
            );
            setAsset(uploadedAsset);
            if (uploadedAsset.extraction_error) {
                throw new Error(
                    `Screenplay extraction failed: ${uploadedAsset.extraction_error}`,
                );
            }

            setStatus(`Enqueuing ${agentMode} breakdown job...`);
            const job = await jsonFetch<Job>(
                `/api/coverset/productions/${currentProduction.id}/breakdowns/jobs`,
                {
                    method: "POST",
                    body: JSON.stringify({
                        screenplay_asset_id: uploadedAsset.id,
                        auto_accept_schedulable: false,
                        agent_mode: agentMode,
                    }),
                },
            );
            await pollJob(job);
            setStatus("Breakdown job complete. Review candidates before solving.");
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Upload or breakdown failed.");
        }
    }

    async function saveCandidate(candidateId: string, patch: CandidatePatch) {
        setError("");
        try {
            const updated = await jsonFetch<Candidate>(
                `/api/coverset/scene-candidates/${candidateId}`,
                {
                    method: "PATCH",
                    body: JSON.stringify(patch),
                },
            );
            replaceCandidate(updated);
            setStatus(
                updated.schedulable
                    ? "Candidate resolved."
                    : "Candidate saved with blockers.",
            );
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Candidate edit failed.");
        }
    }

    async function reviewCandidate(
        candidateId: string,
        decision: "accept" | "reject",
    ) {
        setError("");
        try {
            const updated = await jsonFetch<Candidate>(
                `/api/coverset/scene-candidates/${candidateId}/review`,
                { method: "PATCH", body: JSON.stringify({ decision }) },
            );
            replaceCandidate(updated);
            setStatus(
                decision === "accept"
                    ? "Candidate accepted."
                    : "Candidate rejected.",
            );
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Review decision failed.");
        }
    }

    async function batchAcceptReady() {
        if (!breakdown) return;
        setError("");
        try {
            const result = await jsonFetch<CandidateBatchAcceptResponse>(
                `/api/coverset/breakdowns/${breakdown.id}/candidates/batch-accept`,
                { method: "POST" },
            );
            setBreakdown({ ...breakdown, candidates: result.candidates });
            setStatus(
                `Accepted ${result.accepted.length}; skipped ${Object.keys(result.skipped).length}.`,
            );
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Batch accept failed.");
        }
    }

    async function solveAccepted() {
        if (!production) return;
        setError("");
        setBoard(null);
        try {
            setStatus("Enqueuing deterministic scheduler job...");
            const job = await jsonFetch<Job>(
                `/api/coverset/productions/${production.id}/boards/solve/jobs`,
                {
                    method: "POST",
                    body: JSON.stringify({ accepted_only: true }),
                },
            );
            await pollJob(job);
            setStatus("Accepted scenes solved by the worker.");
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Solve failed.");
        }
    }

    async function createLockConstraint() {
        if (!production) return;
        setError("");
        try {
            const locked = await jsonFetch<ConstraintRow>(
                `/api/coverset/productions/${production.id}/constraints`,
                {
                    method: "POST",
                    body: JSON.stringify({
                        constraint_id: `LOCK-${lockWorkId}-${lockDate}`,
                        family: "lock",
                        policy: "hard",
                        subject_kind: "work",
                        subject_ref: lockWorkId,
                        expression_type: "pinned_day",
                        day: lockDate,
                        statement: `First AD locked ${lockWorkId} to ${lockDate}.`,
                        active: true,
                    }),
                },
            );
            setConstraints((current) => [locked, ...current]);
            await refreshSetup(production.id);
            setStatus("Lock constraint saved. Re-solve to preserve it.");
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Lock save failed.");
        }
    }

    async function toggleConstraint(row: ConstraintRow, active: boolean) {
        setError("");
        try {
            const updated = await jsonFetch<ConstraintRow>(
                `/api/coverset/constraints/${row.id}/activation`,
                {
                    method: "PATCH",
                    body: JSON.stringify({ active }),
                },
            );
            setConstraints((current) =>
                current.map((entry) =>
                    entry.id === updated.id ? updated : entry,
                ),
            );
            setStatus(active ? "Constraint activated." : "Constraint deactivated.");
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Constraint update failed.");
        }
    }

    async function enqueueGrounding() {
        if (!production) return;
        setError("");
        try {
            const job = await jsonFetch<Job>(
                `/api/coverset/productions/${production.id}/grounding/jobs`,
                {
                    method: "POST",
                    body: JSON.stringify({
                        kind: "weather",
                        location_id: groundingLocationId,
                        target_date: groundingDate,
                    }),
                },
            );
            await pollJob(job);
            setStatus("Grounding job complete. Evidence is persisted for review.");
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Grounding failed.");
        }
    }

    return (
        <main className="shell">
            <section className="hero">
                <p className="eyebrow">Coverset implementation</p>
                <h1>Screenplay to reviewed, deterministic stripboard.</h1>
                <p>
                    Gemini proposes candidate scenes, production facts resolve
                    them, explicit review accepts them, and the deterministic
                    scheduler remains the deciding authority.
                </p>
            </section>

            <section className="panel status">
                <strong>Status:</strong> {status}
                {error && <pre className="error">{error}</pre>}
            </section>

            <section className="panel grid">
                <div>
                    <h2>Fast smoke</h2>
                    <p>
                        Runs the authored fixture through the API, database, and
                        scheduler.
                    </p>
                    <button type="button" onClick={runFixtureDemo}>
                        Run fixture demo
                    </button>
                </div>
                <div>
                    <h2>Production</h2>
                    <label>
                        Title
                        <input
                            value={title}
                            onChange={(event) => setTitle(event.target.value)}
                        />
                    </label>
                    <label className="inline">
                        <input
                            type="checkbox"
                            checked={seedDemo}
                            onChange={(event) =>
                                setSeedDemo(event.target.checked)
                            }
                        />
                        Seed Ferry Job demo cast, locations, and dates
                    </label>
                    <button type="button" onClick={createProduction}>
                        Create / reset production
                    </button>
                    {production && (
                        <p className="muted">
                            Active: {production.title} · {production.cast_count}{" "}
                            cast · {production.location_count} locations ·{" "}
                            {production.shoot_day_count} shoot days
                        </p>
                    )}
                </div>
            </section>

            {production && (
                <section className="panel">
                    <h2>Production setup</h2>
                    <div className="grid three">
                        <div>
                            <h3>Cast</h3>
                            <label>
                                Cast ID
                                <input
                                    value={castForm.cast_id}
                                    onChange={(event) =>
                                        setCastForm({
                                            ...castForm,
                                            cast_id: event.target.value,
                                        })
                                    }
                                />
                            </label>
                            <label>
                                Performer
                                <input
                                    value={castForm.performer}
                                    onChange={(event) =>
                                        setCastForm({
                                            ...castForm,
                                            performer: event.target.value,
                                        })
                                    }
                                />
                            </label>
                            <label>
                                Character
                                <input
                                    value={castForm.character}
                                    onChange={(event) =>
                                        setCastForm({
                                            ...castForm,
                                            character: event.target.value,
                                        })
                                    }
                                />
                            </label>
                            <label className="inline">
                                <input
                                    type="checkbox"
                                    checked={castForm.is_minor}
                                    onChange={(event) =>
                                        setCastForm({
                                            ...castForm,
                                            is_minor: event.target.checked,
                                        })
                                    }
                                />{" "}
                                Minor performer
                            </label>
                            <button type="button" onClick={addCastMember}>
                                Add cast
                            </button>
                            <ul className="compactList">
                                {castMembers.map((member) => (
                                    <li key={member.id}>
                                        {member.cast_id} — {member.character}
                                    </li>
                                ))}
                            </ul>
                        </div>
                        <div>
                            <h3>Locations</h3>
                            <label>
                                Location ID
                                <input
                                    value={locationForm.location_id}
                                    onChange={(event) =>
                                        setLocationForm({
                                            ...locationForm,
                                            location_id: event.target.value,
                                        })
                                    }
                                />
                            </label>
                            <label>
                                Name
                                <input
                                    value={locationForm.name}
                                    onChange={(event) =>
                                        setLocationForm({
                                            ...locationForm,
                                            name: event.target.value,
                                        })
                                    }
                                />
                            </label>
                            <label>
                                City
                                <input
                                    value={locationForm.city}
                                    onChange={(event) =>
                                        setLocationForm({
                                            ...locationForm,
                                            city: event.target.value,
                                        })
                                    }
                                />
                            </label>
                            <label>
                                State
                                <input
                                    value={locationForm.state}
                                    onChange={(event) =>
                                        setLocationForm({
                                            ...locationForm,
                                            state: event.target.value,
                                        })
                                    }
                                />
                            </label>
                            <label>
                                Latitude
                                <input
                                    value={locationForm.latitude}
                                    onChange={(event) =>
                                        setLocationForm({
                                            ...locationForm,
                                            latitude: event.target.value,
                                        })
                                    }
                                />
                            </label>
                            <label>
                                Longitude
                                <input
                                    value={locationForm.longitude}
                                    onChange={(event) =>
                                        setLocationForm({
                                            ...locationForm,
                                            longitude: event.target.value,
                                        })
                                    }
                                />
                            </label>
                            <label>
                                Timezone
                                <input
                                    value={locationForm.timezone}
                                    onChange={(event) =>
                                        setLocationForm({
                                            ...locationForm,
                                            timezone: event.target.value,
                                        })
                                    }
                                />
                            </label>
                            <label>
                                Aliases
                                <input
                                    value={locationForm.aliases}
                                    onChange={(event) =>
                                        setLocationForm({
                                            ...locationForm,
                                            aliases: event.target.value,
                                        })
                                    }
                                    placeholder="FERRY TERMINAL / RIVER DOCK"
                                />
                            </label>
                            <button type="button" onClick={addLocation}>
                                Add location
                            </button>
                            <ul className="compactList">
                                {locations.map((location) => (
                                    <li key={location.id}>
                                        {location.location_id} — {location.name}
                                    </li>
                                ))}
                            </ul>
                        </div>
                        <div>
                            <h3>Shoot dates</h3>
                            <label>
                                One ISO date per line
                                <textarea
                                    value={shootDates}
                                    onChange={(event) =>
                                        setShootDates(event.target.value)
                                    }
                                    rows={8}
                                />
                            </label>
                            <button type="button" onClick={saveCalendar}>
                                Save calendar
                            </button>
                        </div>
                    </div>
                </section>
            )}

            {production && (
                <section className="panel grid three">
                    <div>
                        <h2>Locks</h2>
                        <p>
                            Persist locked production reality as hard solver
                            constraints before a re-solve.
                        </p>
                        <label>
                            Work ID
                            <input
                                value={lockWorkId}
                                onChange={(event) =>
                                    setLockWorkId(event.target.value)
                                }
                            />
                        </label>
                        <label>
                            Locked date
                            <input
                                type="date"
                                value={lockDate}
                                onChange={(event) =>
                                    setLockDate(event.target.value)
                                }
                            />
                        </label>
                        <button type="button" onClick={createLockConstraint}>
                            Save active lock
                        </button>
                    </div>
                    <div>
                        <h2>Grounding</h2>
                        <p>
                            Queue Parallel evidence retrieval; evidence stays
                            inert until a human activates a typed constraint.
                        </p>
                        <label>
                            Location
                            <select
                                value={groundingLocationId}
                                onChange={(event) =>
                                    setGroundingLocationId(event.target.value)
                                }
                            >
                                {locations.map((location) => (
                                    <option
                                        key={location.location_id}
                                        value={location.location_id}
                                    >
                                        {location.location_id}
                                    </option>
                                ))}
                            </select>
                        </label>
                        <label>
                            Target date
                            <input
                                type="date"
                                value={groundingDate}
                                onChange={(event) =>
                                    setGroundingDate(event.target.value)
                                }
                            />
                        </label>
                        <button type="button" onClick={enqueueGrounding}>
                            Enqueue weather grounding
                        </button>
                        <ul className="compactList">
                            {grounding.map((row) => (
                                <li key={row.id}>
                                    {row.fact_kind} · {row.location_id} ·{" "}
                                    {row.target_date} · {row.status} ·{" "}
                                    {row.evidence.covering_urls?.length ?? 0}
                                    {" covering source(s)"}
                                </li>
                            ))}
                        </ul>
                    </div>
                    <div>
                        <h2>Constraints & jobs</h2>
                        <ul className="compactList">
                            {constraints.map((row) => (
                                <li key={row.id}>
                                    <button
                                        type="button"
                                        className="tiny"
                                        onClick={() =>
                                            void toggleConstraint(row, !row.active)
                                        }
                                    >
                                        {row.active ? "Deactivate" : "Activate"}
                                    </button>{" "}
                                    <strong>{row.constraint_id}</strong> ·{" "}
                                    {row.family}/{row.policy} ·{" "}
                                    {expressionSummary(row)}
                                </li>
                            ))}
                        </ul>
                        <h3>Job history</h3>
                        <ul className="compactList">
                            {jobs.map((job) => (
                                <li key={job.id}>
                                    <button
                                        type="button"
                                        className="tiny"
                                        onClick={() => void refreshJob(job.id)}
                                    >
                                        Refresh
                                    </button>{" "}
                                    <span className={jobClass(job)}>{job.status}</span>{" "}
                                    {job.job_type} · attempts {job.attempts}
                                    {job.error ? ` · ${job.error}` : ""}
                                </li>
                            ))}
                        </ul>
                    </div>
                </section>
            )}

            <section className="panel grid">
                <div>
                    <h2>Screenplay intake</h2>
                    <label>
                        Breakdown mode
                        <select
                            value={agentMode}
                            onChange={(event) =>
                                setAgentMode(event.target.value as AgentMode)
                            }
                        >
                            <option value="gemini">Gemini live</option>
                            <option value="fixture">Fixture smoke</option>
                        </select>
                    </label>
                    <label>
                        PDF or text screenplay
                        <input
                            type="file"
                            accept=".pdf,.txt,.fountain,text/plain,application/pdf"
                            onChange={(event) =>
                                setFile(event.target.files?.[0] ?? null)
                            }
                        />
                    </label>
                    <button type="button" onClick={uploadAndBreakDown}>
                        Upload and break down
                    </button>
                </div>
                <div>
                    <h2>Review summary</h2>
                    {asset && (
                        <p>
                            Asset: {asset.filename}{" "}
                            {asset.normalized_text_uri
                                ? "· normalized text stored"
                                : ""}
                        </p>
                    )}
                    {breakdown ? (
                        <div className="meta">
                            <span>
                                {breakdown.candidates.length} candidates
                            </span>
                            <span>{acceptedCount} accepted</span>
                            <span>{readyCount} ready</span>
                            <span>
                                {breakdown.unresolved_locations.length}{" "}
                                unresolved locations
                            </span>
                            <span>
                                {breakdown.unresolved_cast.length} unresolved
                                cast cues
                            </span>
                        </div>
                    ) : (
                        <p className="muted">No breakdown yet.</p>
                    )}
                </div>
            </section>

            {breakdown && (
                <section className="panel">
                    <div className="sectionHeader">
                        <h2>Candidate review</h2>
                        <div className="actions">
                            <select
                                value={filter}
                                onChange={(event) =>
                                    setFilter(
                                        event.target.value as CandidateFilter,
                                    )
                                }
                            >
                                <option value="all">All</option>
                                <option value="ready">Ready</option>
                                <option value="blocked">Blocked</option>
                                <option value="accepted">Accepted</option>
                                <option value="rejected">Rejected</option>
                            </select>
                            <button type="button" onClick={batchAcceptReady}>
                                Batch accept ready
                            </button>
                            <button
                                type="button"
                                onClick={solveAccepted}
                                disabled={acceptedCount === 0}
                            >
                                Solve accepted
                            </button>
                        </div>
                    </div>
                    <div className="sceneList">
                        {visibleCandidates.map((candidate) => (
                            <CandidateEditor
                                key={candidate.id}
                                candidate={candidate}
                                onSave={saveCandidate}
                                onReview={reviewCandidate}
                            />
                        ))}
                    </div>
                </section>
            )}

            {schedule && (
                <section className="panel meta">
                    <span>Schedule run: {schedule.status}</span>
                </section>
            )}

            {board && (
                <section className="panel board">
                    <h2>Board: {board.solver_status}</h2>
                    {board.result.days && (
                        <div className="boardGrid">
                            {board.result.days.map((day) => (
                                <div className="dayCard" key={day.date}>
                                    <h3>{day.date}</h3>
                                    <p className="muted">
                                        {timeLabel(day.call_time)}–{timeLabel(day.wrap_time)} ·{" "}
                                        {day.company_moves} company move(s)
                                    </p>
                                    {(day.strips ?? []).map((strip) => (
                                        <article
                                            className="stripCard"
                                            key={`${day.date}-${strip.sequence}`}
                                        >
                                            <div className="sceneHeader">
                                                <strong>{strip.scene_id}</strong>
                                                <span>{strip.location.name}</span>
                                                <span className="pill">
                                                    {strip.day_night}
                                                </span>
                                            </div>
                                            <small>
                                                {strip.work_id} · {strip.kind} ·{" "}
                                                {strip.duration_minutes ?? 0} min ·{" "}
                                                {timeLabel(strip.planned_call_time)}–
                                                {timeLabel(strip.planned_wrap_time)}
                                            </small>
                                            <div className="badges">
                                                {strip.cast.map((member) => (
                                                    <span
                                                        className="pill"
                                                        key={`${strip.work_id}-${member.id}`}
                                                    >
                                                        {member.character}
                                                    </span>
                                                ))}
                                                {Object.entries(strip.flags)
                                                    .filter(([, value]) => value)
                                                    .map(([flag]) => (
                                                        <span
                                                            className="pill warn"
                                                            key={`${strip.work_id}-${flag}`}
                                                        >
                                                            {flag}
                                                        </span>
                                                    ))}
                                                {strip.requires_daylight && (
                                                    <span className="pill good">
                                                        daylight
                                                    </span>
                                                )}
                                            </div>
                                        </article>
                                    ))}
                                </div>
                            ))}
                        </div>
                    )}
                    {board.result.explanation_traces && (
                        <details className="explanations">
                            <summary>Constraint explanation traces</summary>
                            <ul className="compactList">
                                {board.result.explanation_traces.map((trace) => (
                                    <li key={trace.constraint_id}>
                                        <span
                                            className={
                                                trace.satisfied
                                                    ? "pill good"
                                                    : "pill warn"
                                            }
                                        >
                                            {trace.satisfied ? "ok" : "blocked"}
                                        </span>{" "}
                                        <strong>{trace.constraint_id}</strong> ·{" "}
                                        {trace.family}/{trace.policy}
                                        {trace.detail ? ` · ${trace.detail}` : ""}
                                        {trace.source ? ` · ${trace.source}` : ""}
                                    </li>
                                ))}
                            </ul>
                        </details>
                    )}
                    <details>
                        <summary>Text stripboard export</summary>
                        <pre>{board.stripboard}</pre>
                    </details>
                </section>
            )}
        </main>
    );
}
