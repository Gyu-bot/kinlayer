export type AgentWriteOperation = {
  id: string;
  operation_type: string;
  source_path: string;
  actor: string;
  result_status: string;
  api_error_code: string | null;
  request_summary: Record<string, unknown>;
  diagnostics: Record<string, unknown>;
  related_refs: Record<string, unknown>;
  candidate_id: string | null;
  correction_id: string | null;
  episode_id: string | null;
  canonical_record_ref: string | null;
  bounded_excerpt: string | null;
  created_at: string;
  updated_at: string;
};

export type AgentOperationFilters = {
  actor: string;
  source_path: string;
  operation_type: string;
  result_status: string;
  has_error: string;
  created_from: string;
  created_to: string;
};
