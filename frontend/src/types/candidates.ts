export type CandidateEvidence = {
  id: string;
  candidate_id: string;
  episode_id: string;
  excerpt: string | null;
  confidence: number | null;
  source_type: string | null;
  source_ref: string | null;
  source_description: string | null;
  body_hash: string | null;
  actor: string | null;
  created_at: string;
};

export type Candidate = {
  id: string;
  candidate_type: string;
  target_entity_id: string | null;
  payload: Record<string, unknown>;
  evidence: CandidateEvidence[];
  confidence: number;
  sensitivity: string;
  suggested_action: string | null;
  status: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  resolved_by: string | null;
  resolution_note: string | null;
  canonical_record_ref: string | null;
  supersedes_candidate_id: string | null;
  supersedes_record_ref: string | null;
};

export type CandidateFilters = {
  status: string;
  candidate_type: string;
  sensitivity: string;
};
