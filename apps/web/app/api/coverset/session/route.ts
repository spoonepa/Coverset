import type { NextRequest } from "next/server";

import { actorClaimsFromHeaders } from "../../../../shared/auth-claims";

export const runtime = "nodejs";

export function GET(request: NextRequest): Response {
  return Response.json(actorClaimsFromHeaders(request.headers));
}
