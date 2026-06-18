import type {EntityFact} from "./entities";

export type ContextRequest = {
  query: string;
  entity_hints: string[];
  focal_entity_id?: string;
  include_debug: boolean;
  limit: number;
};

export type ContextPackRequest = ContextRequest & {
  situation?: string;
};

export type RetrievedObservation = {
  observation_id: string;
  content: string;
  score: number;
  match_reasons: string[];
  sensitivity: string;
  ai_use_policy: string;
  status: string;
  valid_from: string | null;
  valid_to: string | null;
  occurred_at: string | null;
  created_at: string | null;
};

export type MatchedEntity = {
  entity_id: string;
  display_name: string;
  entity_type: string;
  score: number;
  confidence_band: string;
  match_reasons: string[];
  score_breakdown: Record<string, number>;
  penalties: Record<string, number>;
  surface_bucket: string;
  sensitivity: string;
  ai_use_policy: string;
  confirmation_status: string;
  profile_facts: EntityFact[];
  observations: RetrievedObservation[];
};

export type ContextRetrieveResponse = {
  matched_entities: MatchedEntity[];
  observations: RetrievedObservation[];
  scores: Record<string, number>;
  match_reasons: Record<string, string[]>;
  score_breakdown: Record<string, Record<string, number>>;
  ambiguity_detected: boolean;
  debug: Record<string, unknown>;
};

export type ContextPack = {
  confidence: string;
  suggested_response_policy: string;
  ambiguity_detected: boolean;
  matched_entities: MatchedEntity[];
  buckets: Record<string, MatchedEntity[]>;
  recent_context: RetrievedObservation[];
  stable_context: RetrievedObservation[];
  cautions: RetrievedObservation[];
  provenance: unknown[];
};

export type ContextPackResponse = {
  context_pack: ContextPack;
  debug: Record<string, unknown>;
};
