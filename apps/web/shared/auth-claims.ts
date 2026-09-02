import type { ActorRole } from "./coverset-types";

export type ActorClaims = {
  name: string;
  email: string;
  role: ActorRole | null;
  roles: ActorRole[];
  authenticated: boolean;
  source: string;
};

const ROLE_VALUES: ActorRole[] = [
  "first_ad",
  "second_ad",
  "script_supervisor",
  "director",
  "upm",
  "line_producer",
];

const DEV_ROLES: ActorRole[] = [
  "first_ad",
  "second_ad",
  "script_supervisor",
  "director",
  "upm",
  "line_producer",
];

function header(headers: Headers, name: string | undefined): string {
  return name ? (headers.get(name) ?? "") : "";
}

function cleanEmail(value: string): string {
  return value.replace(/^accounts\.google\.com:/, "").trim();
}

function emailFromAuthorization(headers: Headers): string {
  const headerValue = header(headers, "authorization");
  const match = /^Bearer\s+([^\s.]+\.[^\s.]+\.[^\s.]+)$/i.exec(headerValue);
  if (!match) {
    return "";
  }
  try {
    const payload = JSON.parse(
      Buffer.from(match[1].split(".")[1] ?? "", "base64url").toString(
        "utf8",
      ),
    ) as { email?: unknown };
    return typeof payload.email === "string" ? cleanEmail(payload.email) : "";
  } catch {
    return "";
  }
}

function isRole(value: string): value is ActorRole {
  return ROLE_VALUES.includes(value as ActorRole);
}

function parseRoles(value: string): ActorRole[] {
  const roles = value
    .split(/[\s,]+/)
    .map((role) => role.trim())
    .filter(isRole);
  return Array.from(new Set(roles));
}

function nameFromEmail(email: string): string {
  const local = email.split("@")[0] ?? "";
  if (!local) return "Authenticated user";
  return local
    .split(/[._-]+/)
    .filter(Boolean)
    .map((part) => `${part[0]?.toUpperCase() ?? ""}${part.slice(1)}`)
    .join(" ");
}

function rolesFromClaimMap(email: string): ActorRole[] {
  const raw = process.env.COVERSET_AUTH_ROLE_MAP ?? "";
  if (!email || !raw.trim()) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const domain = email.split("@")[1] ?? "";
    for (const key of [email, `@${domain}`, domain, "*"]) {
      const value = parsed[key];
      if (Array.isArray(value)) {
        return parseRoles(value.map(String).join(","));
      }
      if (typeof value === "string") {
        return parseRoles(value);
      }
    }
  } catch {
    return [];
  }
  return [];
}

export function actorClaimsFromHeaders(headers: Headers): ActorClaims {
  const envRoles = parseRoles(
    process.env.COVERSET_ACTOR_ROLES ?? process.env.COVERSET_ACTOR_ROLE ?? "",
  );
  const headerRoles = parseRoles(
    header(headers, process.env.COVERSET_AUTH_ROLES_HEADER),
  );
  const singleHeaderRole = parseRoles(
    header(headers, process.env.COVERSET_AUTH_ROLE_HEADER),
  );
  const envEmail = process.env.COVERSET_ACTOR_EMAIL;
  const headerEmail = header(
    headers,
    process.env.COVERSET_AUTH_EMAIL_HEADER ?? "x-goog-authenticated-user-email",
  );
  const email = cleanEmail(envEmail ?? (headerEmail || emailFromAuthorization(headers)));
  const mappedRoles = rolesFromClaimMap(email);
  let roles: ActorRole[] = [];
  if (envRoles.length > 0) {
    roles = envRoles;
  } else if (headerRoles.length > 0) {
    roles = headerRoles;
  } else if (singleHeaderRole.length > 0) {
    roles = singleHeaderRole;
  } else if (mappedRoles.length > 0) {
    roles = mappedRoles;
  } else if (process.env.NODE_ENV !== "production") {
    roles = DEV_ROLES;
  }

  const explicitName =
    process.env.COVERSET_ACTOR_NAME ??
    header(headers, process.env.COVERSET_AUTH_NAME_HEADER);
  const role = roles[0] ?? null;
  const hasIdentity = Boolean(
    email ||
      explicitName ||
      envRoles.length ||
      headerRoles.length ||
      singleHeaderRole.length,
  );
  const devFallback = process.env.NODE_ENV !== "production" && roles.length > 0;
  let name = "Unauthenticated user";
  if (explicitName) {
    name = explicitName;
  } else if (email) {
    name = nameFromEmail(email);
  } else if (devFallback) {
    name = "Developer";
  }

  let source = "missing-claim";
  if (hasIdentity) {
    source = "identity-claim";
  } else if (devFallback) {
    source = "development-fallback";
  }

  return {
    name,
    email,
    role,
    roles,
    authenticated: hasIdentity || devFallback,
    source,
  };
}

export function internalActorHeaders(claims: ActorClaims): Record<string, string> {
  return {
    "x-coverset-authenticated": claims.authenticated ? "true" : "false",
    "x-coverset-actor-name": claims.name,
    "x-coverset-actor-email": claims.email,
    "x-coverset-actor-role": claims.role ?? "",
    "x-coverset-actor-roles": claims.roles.join(","),
  };
}
