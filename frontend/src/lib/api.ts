/** Typed client for the Tsunagi API. Mirrors backend/app/schemas.py. */

export type Scope = "device" | "user" | "admin";

export interface Identity {
  kind: string;
  scope: Scope;
  name: string | null;
  id: string | null;
}

export interface Device {
  id: string;
  name: string;
  /** Seen recently enough to count as online. Always false when disabled. */
  status: boolean;
  /** False when an admin has switched this device off. */
  enabled: boolean;
  last_seen: string | null;
  created_at: string;
  disabled_at: string | null;
}

export interface Message {
  id: string;
  device_id: string;
  sender: string;
  body: string;
  received_at: string;
  created_at: string;
}

export interface MessagePage {
  total: number;
  limit: number;
  offset: number;
  messages: Message[];
}

export interface ApiKey {
  id: string;
  name: string;
  scope: string;
  created_at: string;
  revoked_at: string | null;
}

export interface CreatedApiKey extends ApiKey {
  key: string;
}

export type EnrolmentStatus = "pending" | "used" | "expired" | "cancelled";

export interface Enrolment {
  id: string;
  label: string | null;
  status: EnrolmentStatus;
  created_at: string;
  expires_at: string;
  used_at: string | null;
  cancelled_at: string | null;
  used_by_device_id: string | null;
}

export interface CreatedEnrolment extends Enrolment {
  /** Shown once, at creation. */
  code: string;
}

export interface SystemEvent {
  timestamp: string;
  type: string;
  level: "info" | "warn" | "error";
  payload: Record<string, unknown>;
}

export interface Stats {
  messages_total: number;
  messages_today: number;
  active_devices: number;
  storage_bytes: number;
}

export interface VolumePoint {
  date: string;
  count: number;
}

export interface Volume {
  days: number;
  points: VolumePoint[];
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** The credential is missing, wrong, or revoked. */
  get isAuthFailure(): boolean {
    return this.status === 401 || this.status === 403;
  }
}

export interface Credentials {
  apiKey: string;
  /** Empty means same-origin, which is how the nginx deployment serves it. */
  serverUrl: string;
}

function joinUrl(serverUrl: string, path: string): string {
  if (!serverUrl) return path;
  return `${serverUrl.replace(/\/$/, "")}${path}`;
}

async function request<T>(
  credentials: Credentials,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(joinUrl(credentials.serverUrl, path), {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${credentials.apiKey}`,
        ...init.headers,
      },
    });
  } catch {
    // fetch only rejects for transport-level problems.
    throw new ApiError(0, "network_error", "Could not reach the server.");
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : null;

  if (!response.ok) {
    const envelope = payload as { error?: { code?: string; message?: string } } | null;
    throw new ApiError(
      response.status,
      envelope?.error?.code ?? "error",
      envelope?.error?.message ?? `Request failed with HTTP ${response.status}.`,
    );
  }

  return payload as T;
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : "";
}

export const api = {
  health: (c: Credentials) => request<{ status: string; version: string }>(c, "/health"),

  me: (c: Credentials) => request<Identity>(c, "/api/v1/me"),

  listMessages: (
    c: Credentials,
    params: {
      limit?: number;
      offset?: number;
      sender?: string;
      device_id?: string;
      after?: string;
      before?: string;
    } = {},
  ) => request<MessagePage>(c, `/api/v1/messages${query(params)}`),

  searchMessages: (
    c: Credentials,
    params: { query: string; sender?: string; limit?: number; offset?: number },
  ) => request<MessagePage>(c, `/api/v1/messages/search${query(params)}`),

  listDevices: (c: Credentials) =>
    request<{ devices: Device[] }>(c, "/api/v1/devices").then((r) => r.devices),

  setDeviceEnabled: (c: Credentials, id: string, enabled: boolean) =>
    request<Device>(c, `/api/v1/devices/${id}/enabled`, {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),

  revokeDevice: (c: Credentials, id: string) =>
    request<void>(c, `/api/v1/devices/${id}`, { method: "DELETE" }),

  createEnrolment: (c: Credentials, label?: string, ttlSeconds?: number) =>
    request<CreatedEnrolment>(c, "/api/v1/enrolments", {
      method: "POST",
      body: JSON.stringify({ label: label || null, ttl_seconds: ttlSeconds ?? null }),
    }),

  listEnrolments: (c: Credentials) =>
    request<{ enrolments: Enrolment[] }>(c, "/api/v1/enrolments").then((r) => r.enrolments),

  cancelEnrolment: (c: Credentials, id: string) =>
    request<void>(c, `/api/v1/enrolments/${id}`, { method: "DELETE" }),

  listKeys: (c: Credentials) =>
    request<{ keys: ApiKey[] }>(c, "/api/v1/keys").then((r) => r.keys),

  createKey: (c: Credentials, name: string, scope: string) =>
    request<CreatedApiKey>(c, "/api/v1/keys", {
      method: "POST",
      body: JSON.stringify({ name, scope }),
    }),

  revokeKey: (c: Credentials, id: string) =>
    request<void>(c, `/api/v1/keys/${id}`, { method: "DELETE" }),

  listEvents: (c: Credentials, params: { limit?: number; level?: string; type?: string } = {}) =>
    request<{ events: SystemEvent[] }>(c, `/api/v1/events${query(params)}`).then((r) => r.events),

  stats: (c: Credentials) => request<Stats>(c, "/api/v1/stats"),

  volume: (c: Credentials, days = 7) =>
    request<Volume>(c, `/api/v1/stats/volume${query({ days })}`),
};

/** WebSocket URL for /ws/messages, carrying the key as a query parameter
 * because browsers cannot set headers on a handshake. */
export function socketUrl(credentials: Credentials): string {
  const base = credentials.serverUrl || window.location.origin;
  const url = new URL("/ws/messages", base);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("token", credentials.apiKey);
  return url.toString();
}
