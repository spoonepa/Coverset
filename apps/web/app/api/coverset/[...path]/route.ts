import { GoogleAuth } from "google-auth-library";
import type { NextRequest } from "next/server";

import {
  actorClaimsFromHeaders,
  internalActorHeaders,
} from "../../../../shared/auth-claims";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ path: string[] }> | { path: string[] };
};

const API_BASE = process.env.COVERSET_API_BASE_URL ?? "http://127.0.0.1:8080";
const API_AUDIENCE = process.env.COVERSET_API_AUDIENCE ?? "";

function upstreamUrlFor(path: string, search: string): URL | Response {
  try {
    const url = new URL(`${API_BASE.replace(/\/$/, "")}/${path}`);
    url.search = search;
    return url;
  } catch {
    return Response.json(
      { error: "Invalid COVERSET_API_BASE_URL" },
      { status: 500 },
    );
  }
}

function headersToRecord(
  headers: Headers | Record<string, unknown>,
): Record<string, string> {
  if (typeof (headers as Headers).entries === "function") {
    return Object.fromEntries((headers as Headers).entries());
  }
  const record: Record<string, string> = {};
  for (const [key, value] of Object.entries(headers)) {
    if (value !== undefined && value !== null) {
      record[key] = String(value);
    }
  }
  return record;
}

async function authHeaders(url: string): Promise<Record<string, string>> {
  if (!API_AUDIENCE) return {};
  const auth = new GoogleAuth();
  const client = await auth.getIdTokenClient(API_AUDIENCE);
  const headers = await client.getRequestHeaders(url);
  return headersToRecord(headers as Headers | Record<string, unknown>);
}

async function proxy(
  request: NextRequest,
  context: RouteContext,
): Promise<Response> {
  const params = await context.params;
  const upstreamPath = params.path.map(encodeURIComponent).join("/");
  const upstreamUrl = upstreamUrlFor(upstreamPath, request.nextUrl.search);
  if (upstreamUrl instanceof Response) {
    return upstreamUrl;
  }

  const headers = new Headers(request.headers);
  for (const name of [
    "host",
    "connection",
    "content-length",
    "authorization",
    "x-serverless-authorization",
    "proxy-authorization",
    "x-coverset-authenticated",
    "x-coverset-actor-name",
    "x-coverset-actor-email",
    "x-coverset-actor-role",
    "x-coverset-actor-roles",
  ]) {
    headers.delete(name);
  }
  const actorHeaders = internalActorHeaders(
    actorClaimsFromHeaders(request.headers),
  );
  for (const [key, value] of Object.entries(actorHeaders)) {
    headers.set(key, value);
  }
  const identityHeaders = await authHeaders(upstreamUrl.toString());
  for (const [key, value] of Object.entries(identityHeaders)) {
    headers.set(key, value);
  }

  const method = request.method.toUpperCase();
  const body =
    method === "GET" || method === "HEAD"
      ? undefined
      : await request.arrayBuffer();
  const upstream = await fetch(upstreamUrl, {
    method,
    headers,
    body,
    cache: "no-store",
  });

  const responseHeaders = new Headers(upstream.headers);
  responseHeaders.delete("content-encoding");
  responseHeaders.delete("content-length");
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
