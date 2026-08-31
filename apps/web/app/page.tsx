"use client";

import { useMemo, useState } from "react";

type Candidate = {
    id: string;
    scene_number: string;
    slugline: string;
    int_ext: string;
    day_night: string;
    location_ref: string;
    cast_ids: string[];
    flags: Record<string, boolean>;
    accepted: boolean;
    schedulable: boolean;
    resolution_errors: string[];
};

type BreakdownRun = {
    id: string;
    status: string;
    candidates: Candidate[];
};

type ScheduleRun = {
    id: string;
    status: string;
    board_id: string | null;
    error: string;
};

type Board = {
    id: string;
    solver_status: string;
    stripboard: string;
};

type Production = { id: string; title: string };
type ScreenplayAsset = { id: string; filename: string };

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
    const payload = text ? JSON.parse(text) : {};
    if (!response.ok) {
        throw new Error(payload.detail ?? payload.error ?? response.statusText);
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

export default function Home() {
    const [title, setTitle] = useState("The Ferry Job");
    const [file, setFile] = useState<File | null>(null);
    const [production, setProduction] = useState<Production | null>(null);
    const [asset, setAsset] = useState<ScreenplayAsset | null>(null);
    const [breakdown, setBreakdown] = useState<BreakdownRun | null>(null);
    const [schedule, setSchedule] = useState<ScheduleRun | null>(null);
    const [board, setBoard] = useState<Board | null>(null);
    const [status, setStatus] = useState("Ready");
    const [error, setError] = useState("");

    const acceptedCount = useMemo(
        () =>
            breakdown?.candidates.filter((candidate) => candidate.accepted)
                .length ?? 0,
        [breakdown],
    );

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

    async function runUploadedScreenplay() {
        if (!file) {
            setError("Choose a screenplay file first.");
            return;
        }
        setError("");
        setBoard(null);
        try {
            setStatus("Creating production...");
            const createdProduction = await jsonFetch<Production>(
                "/api/coverset/productions",
                {
                    method: "POST",
                    body: JSON.stringify({ title, seed_demo_data: true }),
                },
            );
            setProduction(createdProduction);

            setStatus("Uploading screenplay...");
            const form = new FormData();
            form.append("file", file);
            const uploadedAsset = await jsonFetch<ScreenplayAsset>(
                `/api/coverset/productions/${createdProduction.id}/screenplays`,
                { method: "POST", body: form },
            );
            setAsset(uploadedAsset);

            setStatus(
                "Running Gemini breakdown and auto-accepting schedulable candidates...",
            );
            const breakdownRun = await jsonFetch<BreakdownRun>(
                `/api/coverset/productions/${createdProduction.id}/breakdowns`,
                {
                    method: "POST",
                    body: JSON.stringify({
                        screenplay_asset_id: uploadedAsset.id,
                        auto_accept_schedulable: true,
                        agent_mode: "gemini",
                    }),
                },
            );
            setBreakdown(breakdownRun);
            if (breakdownRun.status !== "complete") {
                throw new Error(`Breakdown ${breakdownRun.status}`);
            }

            setStatus("Solving board with deterministic scheduler...");
            const scheduleRun = await jsonFetch<ScheduleRun>(
                `/api/coverset/productions/${createdProduction.id}/boards/solve`,
                {
                    method: "POST",
                    body: JSON.stringify({ accepted_only: true }),
                },
            );
            setSchedule(scheduleRun);
            if (!scheduleRun.board_id) {
                throw new Error(
                    scheduleRun.error || `Schedule ${scheduleRun.status}`,
                );
            }

            setStatus("Loading stripboard...");
            const solvedBoard = await jsonFetch<Board>(
                `/api/coverset/boards/${scheduleRun.board_id}`,
            );
            setBoard(solvedBoard);
            setStatus("Uploaded screenplay solved.");
        } catch (err) {
            setError(err instanceof Error ? err.message : String(err));
            setStatus("Upload flow failed.");
        }
    }

    return (
        <main className="shell">
            <section className="hero">
                <p className="eyebrow">Coverset dev MVP</p>
                <h1>
                    Screenplay to stripboard, with agents kept out of the
                    decision path.
                </h1>
                <p>
                    Gemini proposes candidate scenes, humans or dev auto-review
                    accept schedulable records, and the deterministic CP-SAT
                    scheduler produces the board.
                </p>
            </section>

            <section className="panel grid">
                <div>
                    <h2>Fast smoke</h2>
                    <p>
                        Runs the authored fixture through the deployed API, DB
                        layer, and scheduler.
                    </p>
                    <button type="button" onClick={runFixtureDemo}>
                        Run fixture demo
                    </button>
                </div>
                <div>
                    <h2>Live screenplay</h2>
                    <label>
                        Production title
                        <input
                            value={title}
                            onChange={(event) => setTitle(event.target.value)}
                        />
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
                    <button type="button" onClick={runUploadedScreenplay}>
                        Upload, break down, solve
                    </button>
                </div>
            </section>

            <section className="panel status">
                <strong>Status:</strong> {status}
                {error && <pre className="error">{error}</pre>}
            </section>

            {production && (
                <section className="panel meta">
                    <span>Production: {production.title}</span>
                    {asset && <span>Asset: {asset.filename}</span>}
                    {schedule && <span>Schedule run: {schedule.status}</span>}
                    {breakdown && (
                        <span>
                            Accepted scenes: {acceptedCount}/
                            {breakdown.candidates.length}
                        </span>
                    )}
                </section>
            )}

            {breakdown && (
                <section className="panel">
                    <h2>Candidate scenes</h2>
                    <div className="sceneList">
                        {breakdown.candidates.map((candidate) => (
                            <article
                                key={candidate.id}
                                className={
                                    candidate.accepted
                                        ? "scene accepted"
                                        : "scene"
                                }
                            >
                                <div>
                                    <strong>{candidate.scene_number}</strong>{" "}
                                    {candidate.slugline}
                                </div>
                                <small>
                                    {candidate.int_ext}/{candidate.day_night} ·{" "}
                                    {candidate.location_ref} · cast:{" "}
                                    {candidate.cast_ids.join(", ") || "-"} ·
                                    flags: {flagText(candidate.flags)}
                                </small>
                                {candidate.resolution_errors.length > 0 && (
                                    <small className="errorText">
                                        {candidate.resolution_errors.join("; ")}
                                    </small>
                                )}
                            </article>
                        ))}
                    </div>
                </section>
            )}

            {board && (
                <section className="panel board">
                    <h2>Board: {board.solver_status}</h2>
                    <pre>{board.stripboard}</pre>
                </section>
            )}
        </main>
    );
}
