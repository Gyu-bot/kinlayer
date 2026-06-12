import {useEffect, useState} from "react";

import {exportAgentOperations, formatApiError, listAgentOperations} from "../api/client";
import type {AgentOperationFilters, AgentWriteOperation} from "../types/agentOperations";

const operationTypes = [
  "all",
  "candidate_submit",
  "candidate_accept",
  "candidate_edit_accept",
  "correction_apply",
];
const resultStatuses = ["all", "success", "rejected"];
const errorStates = ["all", "true", "false"];

const defaultFilters: AgentOperationFilters = {
  actor: "",
  source_path: "",
  operation_type: "all",
  result_status: "all",
  has_error: "all",
  created_from: "",
  created_to: "",
};

export function AgentOperations() {
  const [filters, setFilters] = useState<AgentOperationFilters>(defaultFilters);
  const [operations, setOperations] = useState<AgentWriteOperation[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    setLoading(true);
    listAgentOperations(filters)
      .then((result) => {
        setOperations(result.items);
        setTotal(result.total);
        setError(null);
      })
      .catch((err: unknown) => setError(formatApiError(err)))
      .finally(() => setLoading(false));
  }, [filters]);

  function updateFilter(key: keyof AgentOperationFilters, value: string) {
    setFilters((current) => ({...current, [key]: value}));
  }

  function downloadExport() {
    setExporting(true);
    exportAgentOperations(filters)
      .then((content) => {
        const blob = new Blob([content], {type: "application/x-ndjson"});
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = "kinlayer-agent-write-operations.jsonl";
        anchor.click();
        URL.revokeObjectURL(url);
        setError(null);
      })
      .catch((err: unknown) => setError(formatApiError(err)))
      .finally(() => setExporting(false));
  }

  return (
    <section className="page-section" aria-labelledby="agent-operations-title">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Audit</p>
          <h1 id="agent-operations-title">Agent Write Operations</h1>
        </div>
        <button type="button" onClick={downloadExport} disabled={exporting}>
          {exporting ? "Exporting..." : "Export"}
        </button>
      </div>

      <div className="filter-grid">
        <label>
          <span>Actor</span>
          <input
            value={filters.actor}
            placeholder="ai_agent"
            onChange={(event) => updateFilter("actor", event.target.value)}
          />
        </label>
        <label>
          <span>Source path</span>
          <input
            value={filters.source_path}
            placeholder="/api/candidates"
            onChange={(event) => updateFilter("source_path", event.target.value)}
          />
        </label>
        <label>
          <span>Operation</span>
          <select
            value={filters.operation_type}
            onChange={(event) => updateFilter("operation_type", event.target.value)}
          >
            {operationTypes.map((operationType) => (
              <option value={operationType} key={operationType}>
                {operationType}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Result</span>
          <select
            value={filters.result_status}
            onChange={(event) => updateFilter("result_status", event.target.value)}
          >
            {resultStatuses.map((status) => (
              <option value={status} key={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Error</span>
          <select
            value={filters.has_error}
            onChange={(event) => updateFilter("has_error", event.target.value)}
          >
            {errorStates.map((state) => (
              <option value={state} key={state}>
                {state}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Created from</span>
          <input
            value={filters.created_from}
            placeholder="2026-06-12T00:00:00Z"
            onChange={(event) => updateFilter("created_from", event.target.value)}
          />
        </label>
        <label>
          <span>Created to</span>
          <input
            value={filters.created_to}
            placeholder="2026-06-12T23:59:59Z"
            onChange={(event) => updateFilter("created_to", event.target.value)}
          />
        </label>
      </div>

      {error ? <p className="error">{error}</p> : null}
      {loading ? <p className="muted">Loading agent operations...</p> : null}

      <div className="table-wrap">
        <table>
          <caption>{total} agent write operations</caption>
          <thead>
            <tr>
              <th>Operation</th>
              <th>Result</th>
              <th>Actor</th>
              <th>Candidate</th>
              <th>Record</th>
              <th>Excerpt</th>
            </tr>
          </thead>
          <tbody>
            {operations.map((operation) => (
              <tr key={operation.id}>
                <td>{operation.operation_type}</td>
                <td>{operation.result_status}</td>
                <td>{operation.actor}</td>
                <td>{operation.candidate_id ?? "-"}</td>
                <td>{operation.canonical_record_ref ?? operation.api_error_code ?? "-"}</td>
                <td>{operation.bounded_excerpt ?? "-"}</td>
              </tr>
            ))}
            {operations.length === 0 && !loading ? (
              <tr>
                <td colSpan={6}>No agent write operations found.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}
