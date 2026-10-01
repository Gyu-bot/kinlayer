import type { AgentOperationFilters } from "../types/agentOperations";

type LocationLike = Pick<Location, "protocol" | "hostname">;

export function resolveApiUrl(
  configuredUrl?: string,
  locationLike?: LocationLike,
) {
  const trimmed = configuredUrl?.trim();
  if (trimmed) {
    return trimmed.replace(/\/$/, "");
  }

  const currentLocation =
    locationLike ??
    (typeof window === "undefined" ? undefined : window.location);
  if (!currentLocation?.hostname) {
    return "http://127.0.0.1:8765";
  }

  const protocol = currentLocation.protocol === "https:" ? "https:" : "http:";
  const hostname = currentLocation.hostname;
  const host =
    hostname.includes(":") && !hostname.startsWith("[")
      ? `[${hostname}]`
      : hostname;
  return `${protocol}//${host}:8765`;
}

const apiUrl = resolveApiUrl(import.meta.env.VITE_KINLAYER_API_URL);
const envApiToken = import.meta.env.VITE_KINLAYER_API_TOKEN;
const localApiTokenKey = "kinlayer.apiToken";

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function getStoredToken() {
  if (typeof window === "undefined") {
    return "";
  }
  return window.localStorage.getItem(localApiTokenKey)?.trim() ?? "";
}

export function setLocalApiToken(token: string) {
  const trimmed = token.trim();
  if (!trimmed) {
    clearLocalApiToken();
    return;
  }
  window.localStorage.setItem(localApiTokenKey, trimmed);
}

export function clearLocalApiToken() {
  window.localStorage.removeItem(localApiTokenKey);
}

export function isLocalApiTokenConfigured() {
  return Boolean(getStoredToken());
}

function activeApiToken() {
  return getStoredToken() || envApiToken || "";
}

function headers() {
  const result: Record<string, string> = { "Content-Type": "application/json" };
  const token = activeApiToken();
  if (token) {
    result.Authorization = `Bearer ${token}`;
  }
  return result;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: { ...headers(), ...(init?.headers ?? {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = payload?.error?.code ?? "request_failed";
    const message =
      payload?.error?.message ?? `Request failed with ${response.status}`;
    const details = payload?.error?.details ?? {};
    throw new ApiError(response.status, code, message, details);
  }
  return payload as T;
}

async function requestText(path: string, init?: RequestInit): Promise<string> {
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: { ...headers(), ...(init?.headers ?? {}) },
  });
  const text = await response.text();
  if (!response.ok) {
    throw new ApiError(
      response.status,
      "request_failed",
      text || `Request failed with ${response.status}`,
    );
  }
  return text;
}

function agentOperationParams(filters: AgentOperationFilters, limit: string) {
  const params = new URLSearchParams({ limit });
  if (filters.actor.trim()) {
    params.set("actor", filters.actor.trim());
  }
  if (filters.source_path.trim()) {
    params.set("source_path", filters.source_path.trim());
  }
  if (filters.operation_type && filters.operation_type !== "all") {
    params.set("operation_type", filters.operation_type);
  }
  if (filters.result_status && filters.result_status !== "all") {
    params.set("result_status", filters.result_status);
  }
  if (filters.has_error && filters.has_error !== "all") {
    params.set("has_error", filters.has_error);
  }
  if (filters.created_from.trim()) {
    params.set("created_from", filters.created_from.trim());
  }
  if (filters.created_to.trim()) {
    params.set("created_to", filters.created_to.trim());
  }
  return params;
}

export async function exportAgentOperations(filters: AgentOperationFilters) {
  const params = agentOperationParams(filters, "200");
  return requestText(`/api/agent-operations/export?${params.toString()}`);
}

export { apiUrl };
