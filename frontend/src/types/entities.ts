export type Entity = {
  id: string;
  entity_type: string;
  display_name: string;
  canonical_name: string | null;
  properties: Record<string, unknown>;
  confirmation_status: string;
  status: string;
  sensitivity: string;
  ai_use_policy: string;
  created_by: string;
  system_role: string | null;
  is_system: boolean;
  first_seen_at: string | null;
  last_referenced_at: string | null;
  created_at: string;
  updated_at: string;
};

export type EntityAlias = {
  id: string;
  entity_id: string;
  alias: string;
  normalized_alias: string | null;
  status: string;
  confidence: number;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type EntityFact = {
  id: string;
  entity_id: string;
  fact_type: string;
  content: string;
  value: Record<string, unknown> | null;
  claim_type: string;
  confidence: number;
  sensitivity: string;
  ai_use_policy: string;
  status: string;
  valid_from: string | null;
  valid_to: string | null;
  source_candidate_id: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type EntityEdge = {
  id: string;
  from_entity_id: string;
  to_entity_id: string;
  relation_type: string;
  directed: boolean;
  claim_text: string;
  claim_type: string;
  properties: Record<string, unknown>;
  confidence: number;
  status: string;
  valid_from: string | null;
  valid_to: string | null;
  sensitivity: string;
  ai_use_policy: string;
  created_by: string;
  invalidated_by_edge_id: string | null;
  source_candidate_id: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
};

export type RelatedEntity = {
  id: string;
  observation_id: string;
  entity_id: string;
  role: string;
  confidence: number | null;
  created_at: string;
};

export type Observation = {
  id: string;
  subject_entity_id: string;
  related_entities: RelatedEntity[];
  observation_type: string;
  content: string;
  claim_type: string;
  confidence: number;
  sensitivity: string;
  ai_use_policy: string;
  status: string;
  valid_from: string | null;
  valid_to: string | null;
  occurred_at: string | null;
  recency_weight: number | null;
  created_by: string;
  source_candidate_id: string | null;
  embedding: string | null;
  embedding_status: string;
  embedding_error: string | null;
  embedding_model: string | null;
  embedding_dim: number | null;
  embedding_created_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ProvenanceItem = {
  record_type: string;
  record_id: string;
  episode_id: string | null;
  excerpt: string | null;
  confidence: number | null;
  created_at: string | null;
};

export type ProvenanceSummary = {
  fact_count: number;
  edge_count: number;
  observation_count: number;
  evidence_count: number;
  evidence: ProvenanceItem[];
};

export type ContextCard = {
  entity: Entity;
  aliases: EntityAlias[];
  profile_facts: EntityFact[];
  relationship_edges: EntityEdge[];
  stable_context: Observation[];
  recent_context: Observation[];
  communication_context: Observation[];
  cautions: Observation[];
  provenance_summary: ProvenanceSummary;
  retrieval_hints: {
    entity_id: string;
    canonical_name: string | null;
    aliases: string[];
    entity_type: string;
  };
};

export type ListResponse<T> = {
  items: T[];
  limit: number;
  offset: number;
  total: number;
};

export type ApiErrorShape = {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
  };
};

export type SystemHealth = {
  status: string;
  database: string;
  embedding: string;
};

export type EmbeddingConfig = {
  provider: string;
  model: string | null;
  dim: number | null;
  status: string;
  api_url_configured: boolean;
  api_key_configured: boolean;
};

export type SystemConfig = {
  bind_host: string;
  auth_token_configured: boolean;
  embedding: EmbeddingConfig;
};

export type EmbeddingStatus = EmbeddingConfig & {
  observations: {
    total: number;
    pending: number;
    ready: number;
    failed: number;
    stale: number;
  };
};

export type RegistryValue = {
  category?: string;
  value: string;
  label: string;
  description?: string | null;
  support_level?: string;
  is_active?: boolean;
  sort_order?: number;
};

export type EdgeType = {
  relation_type: string;
  from_entity_type?: string;
  to_entity_type?: string;
  directed_default?: boolean;
  inverse_relation_type?: string | null;
  description?: string | null;
  active?: boolean;
};

export type ObservationType = {
  observation_type: string;
  description?: string | null;
  active?: boolean;
};

export type Ontology = {
  entity_types: RegistryValue[];
  fact_types: RegistryValue[];
  edge_types: EdgeType[];
  observation_types: ObservationType[];
  policies: {
    sensitivity_levels: RegistryValue[];
    ai_use_policies: RegistryValue[];
    claim_types: RegistryValue[];
    candidate_types: RegistryValue[];
  };
};
