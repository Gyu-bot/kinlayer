import type {
  Entity,
  EntityAlias,
  ContextCard,
  EntityEdge,
  EntityFact,
  EmbeddingStatus,
  ListResponse,
  Observation,
  Ontology,
  SystemConfig,
  SystemHealth,
} from "../types/entities";
import type {
  ContextPackRequest,
  ContextPackResponse,
  ContextRequest,
  ContextRetrieveResponse,
} from "../types/context";
import type {Candidate, CandidateFilters} from "../types/candidates";
import type {EgoGraph, GraphFilters} from "../types/graph";

const apiUrl = import.meta.env.VITE_KINLAYER_API_URL ?? "http://127.0.0.1:8765";
const envApiToken = import.meta.env.VITE_KINLAYER_API_TOKEN;
const localApiTokenKey = "kinlayer.apiToken";

type CreatePersonInput = {
  displayName: string;
  aliases: string[];
  sensitivity: string;
  aiUsePolicy: string;
  shortNote: string;
  factType: string;
  factContent: string;
  initialRelationshipType: string;
  initialRelationshipNote: string;
  initialObservationType: string;
  initialObservation: string;
};

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
  const result: Record<string, string> = {"Content-Type": "application/json"};
  const token = activeApiToken();
  if (token) {
    result.Authorization = `Bearer ${token}`;
  }
  return result;
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiUrl}${path}`, {
    ...init,
    headers: {...headers(), ...(init?.headers ?? {})},
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code = payload?.error?.code ?? "request_failed";
    const message = payload?.error?.message ?? `Request failed with ${response.status}`;
    const details = payload?.error?.details ?? {};
    throw new ApiError(response.status, code, message, details);
  }
  return payload as T;
}

export function formatApiError(error: unknown) {
  if (error instanceof ApiError) {
    return `${error.code}: ${error.message}`;
  }
  return error instanceof Error ? error.message : "Request failed.";
}

export async function listPeople(
  query: string,
  filters: {status?: string; sensitivity?: string} = {},
) {
  const params = new URLSearchParams({entity_type: "person", limit: "50"});
  if (query.trim()) {
    params.set("q", query.trim());
  }
  if (filters.status && filters.status !== "all") {
    params.set("status", filters.status);
  }
  if (filters.sensitivity && filters.sensitivity !== "all") {
    params.set("sensitivity", filters.sensitivity);
  }
  return request<ListResponse<Entity>>(`/api/entities?${params.toString()}`);
}

export async function getPerson(id: string) {
  return request<Entity>(`/api/entities/${id}`);
}

export async function updatePerson(id: string, input: Record<string, unknown>) {
  return request<Entity>(`/api/entities/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function getAliases(id: string) {
  return request<ListResponse<EntityAlias>>(`/api/entities/${id}/aliases`);
}

export async function createAlias(id: string, input: Record<string, unknown>) {
  return request<EntityAlias>(`/api/entities/${id}/aliases`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateAlias(aliasId: string, input: Record<string, unknown>) {
  return request<EntityAlias>(`/api/aliases/${aliasId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function deleteAlias(aliasId: string) {
  return request<EntityAlias>(`/api/aliases/${aliasId}`, {method: "DELETE"});
}

export async function getFacts(id: string) {
  const params = new URLSearchParams({entity_id: id, status: "active", limit: "100"});
  return request<ListResponse<EntityFact>>(`/api/entity-facts?${params.toString()}`);
}

export async function createFact(input: Record<string, unknown>) {
  return request<EntityFact>("/api/entity-facts", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateFact(factId: string, input: Record<string, unknown>) {
  return request<EntityFact>(`/api/entity-facts/${factId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function deleteFact(factId: string) {
  return request<EntityFact>(`/api/entity-facts/${factId}`, {method: "DELETE"});
}

export async function createPerson(input: CreatePersonInput) {
  const entity = await request<Entity>("/api/entities", {
    method: "POST",
    body: JSON.stringify({
      entity_type: "person",
      display_name: input.displayName,
      properties: input.shortNote ? {short_note: input.shortNote} : {},
      confirmation_status: "confirmed",
      sensitivity: input.sensitivity,
      ai_use_policy: input.aiUsePolicy,
      created_by: "user",
    }),
  });

  await Promise.all(
    input.aliases.map((alias) =>
      request<EntityAlias>(`/api/entities/${entity.id}/aliases`, {
        method: "POST",
        body: JSON.stringify({alias, created_by: "user"}),
      }),
    ),
  );

  if (input.factContent.trim()) {
    await request<EntityFact>("/api/entity-facts", {
      method: "POST",
      body: JSON.stringify({
        entity_id: entity.id,
        fact_type: input.factType,
        content: input.factContent,
        claim_type: "fact",
        confidence: 1,
        sensitivity: input.sensitivity,
        ai_use_policy: input.aiUsePolicy,
        created_by: "user",
      }),
    });
  }

  const needsSelf = input.initialRelationshipNote.trim() || input.initialObservation.trim();
  const self = needsSelf ? await getProtectedSelf() : null;
  if (needsSelf && !self) {
    throw new Error("Protected self entity is required for initial relationship context.");
  }

  if (self && input.initialRelationshipNote.trim()) {
    await createEdge({
      from_entity_id: self.id,
      to_entity_id: entity.id,
      relation_type: input.initialRelationshipType,
      claim_text: input.initialRelationshipNote.trim(),
      claim_type: "fact",
      confidence: 1,
      sensitivity: input.sensitivity,
      ai_use_policy: input.aiUsePolicy,
      created_by: "user",
    });
  }

  if (input.initialObservation.trim()) {
    await createObservation({
      subject_entity_id: entity.id,
      related_entities: self ? [{entity_id: self.id, role: "related"}] : [],
      observation_type: input.initialObservationType,
      content: input.initialObservation.trim(),
      claim_type: "fact",
      confidence: 1,
      sensitivity: input.sensitivity,
      ai_use_policy: input.aiUsePolicy,
      recency_weight: 1,
      created_by: "user",
    });
  }

  return entity;
}

export async function getProtectedSelf() {
  const params = new URLSearchParams({
    entity_type: "person",
    system_role: "self",
    limit: "1",
  });
  const result = await request<ListResponse<Entity>>(`/api/entities?${params.toString()}`);
  return result.items[0] ?? null;
}

export async function createEdge(input: Record<string, unknown>) {
  return request<EntityEdge>("/api/edges", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateEdge(edgeId: string, input: Record<string, unknown>) {
  return request<EntityEdge>(`/api/edges/${edgeId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function deleteEdge(edgeId: string) {
  return request<EntityEdge>(`/api/edges/${edgeId}`, {method: "DELETE"});
}

export async function createObservation(input: Record<string, unknown>) {
  return request<Observation>("/api/observations", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function deleteObservation(observationId: string) {
  return request<Observation>(`/api/observations/${observationId}`, {method: "DELETE"});
}

export async function getContextCard(id: string) {
  return request<ContextCard>(`/api/entities/${id}/context-card`);
}

export async function listCandidates(filters: CandidateFilters) {
  const params = new URLSearchParams();
  if (filters.status && filters.status !== "all") {
    params.set("status", filters.status);
  }
  params.set("limit", "50");
  if (filters.candidate_type && filters.candidate_type !== "all") {
    params.set("candidate_type", filters.candidate_type);
  }
  if (filters.sensitivity && filters.sensitivity !== "all") {
    params.set("sensitivity", filters.sensitivity);
  }
  return request<ListResponse<Candidate>>(`/api/candidates?${params.toString()}`);
}

export async function runCandidateAction(candidateId: string, action: string) {
  return request<Candidate>(`/api/candidates/${candidateId}/${action}`, {
    method: "POST",
    body: JSON.stringify({resolved_by: "user"}),
  });
}

export async function editAcceptCandidate(candidateId: string, payload: Record<string, unknown>) {
  return request<Candidate>(`/api/candidates/${candidateId}/edit-accept`, {
    method: "POST",
    body: JSON.stringify({payload, resolved_by: "user"}),
  });
}

export async function getEgoGraph(entityId: string, filters: GraphFilters) {
  const params = new URLSearchParams({depth: "1"});
  if (filters.relation_type.trim()) {
    params.set("relation_type", filters.relation_type.trim());
  }
  if (filters.status && filters.status !== "active") {
    params.set("status", filters.status);
  }
  if (filters.sensitivity && filters.sensitivity !== "all") {
    params.set("sensitivity", filters.sensitivity);
  }
  return request<EgoGraph>(`/api/graph/ego/${entityId}?${params.toString()}`);
}

export async function getSystemHealth() {
  return request<SystemHealth>("/api/system/health");
}

export async function getSystemConfig() {
  return request<SystemConfig>("/api/system/config");
}

export async function getEmbeddingStatus() {
  return request<EmbeddingStatus>("/api/embeddings/status");
}

export async function getOntology() {
  return request<Ontology>("/api/ontology");
}

export async function retrieveContext(input: ContextRequest) {
  return request<ContextRetrieveResponse>("/api/context/retrieve", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function packContext(input: ContextPackRequest) {
  return request<ContextPackResponse>("/api/context/pack", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export {apiUrl};
