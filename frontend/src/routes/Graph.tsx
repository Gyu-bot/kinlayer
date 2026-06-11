import {useEffect, useMemo, useState} from "react";
import {Background, Controls, ReactFlow, type Edge, type Node} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import {formatApiError, getEgoGraph, listPeople} from "../api/client";
import type {Entity} from "../types/entities";
import type {EgoGraph, GraphEdge, GraphFilters, GraphNode} from "../types/graph";

const graphStatuses = ["active", "deleted", "deprecated", "disputed", "superseded"];
const graphSensitivities = ["all", "low", "medium", "high"];

export function Graph() {
  const [people, setPeople] = useState<Entity[]>([]);
  const [focalId, setFocalId] = useState("");
  const [filters, setFilters] = useState<GraphFilters>({
    relation_type: "",
    status: "active",
    sensitivity: "all",
  });
  const [graph, setGraph] = useState<EgoGraph | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<GraphEdge | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listPeople("")
      .then((result) => {
        setPeople(result.items);
        setFocalId((current) => current || result.items[0]?.id || "");
        setError(null);
      })
      .catch((err: unknown) => setError(formatApiError(err)));
  }, []);

  useEffect(() => {
    if (!focalId) {
      return;
    }
    getEgoGraph(focalId, filters)
      .then((result) => {
        setGraph(result);
        setSelectedNode(result.nodes.find((node) => node.is_focal) ?? result.nodes[0] ?? null);
        setSelectedEdge(null);
        setError(null);
      })
      .catch((err: unknown) => setError(formatApiError(err)));
  }, [focalId, filters]);

  const flowNodes = useMemo<Node[]>(
    () =>
      (graph?.nodes ?? []).map((node, index) => ({
        id: node.entity_id,
        position: node.is_focal
          ? {x: 260, y: 140}
          : {
              x: 80 + (index % 3) * 210,
              y: 330 + Math.floor(index / 3) * 120,
            },
        data: {label: node.display_name},
        className: node.is_focal ? "flow-node focal" : "flow-node",
      })),
    [graph],
  );

  const flowEdges = useMemo<Edge[]>(
    () =>
      (graph?.edges ?? []).map((edge) => ({
        id: edge.edge_id,
        source: edge.from_entity_id,
        target: edge.to_entity_id,
        label: edge.relation_type,
        animated: edge.directed,
      })),
    [graph],
  );

  function updateFilter(key: keyof GraphFilters, value: string) {
    setFilters((current) => ({...current, [key]: value}));
  }

  function chooseNode(node: GraphNode) {
    setSelectedNode(node);
    setSelectedEdge(null);
  }

  function chooseEdge(edge: GraphEdge) {
    setSelectedEdge(edge);
    setSelectedNode(null);
  }

  return (
    <section className="page-section" aria-labelledby="graph-title">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Graph</p>
          <h1 id="graph-title">Ego Graph</h1>
        </div>
        <span className="status-chip">{graph?.nodes.length ?? 0} nodes</span>
      </div>

      <div className="filter-grid">
        <label>
          <span>Focal entity</span>
          <select value={focalId} onChange={(event) => setFocalId(event.target.value)}>
            {people.map((person) => (
              <option value={person.id} key={person.id}>
                {person.display_name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Relation type</span>
          <input
            value={filters.relation_type}
            onChange={(event) => updateFilter("relation_type", event.target.value)}
          />
        </label>
        <label>
          <span>Status</span>
          <select value={filters.status} onChange={(event) => updateFilter("status", event.target.value)}>
            {graphStatuses.map((status) => (
              <option value={status} key={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Sensitivity</span>
          <select
            value={filters.sensitivity}
            onChange={(event) => updateFilter("sensitivity", event.target.value)}
          >
            {graphSensitivities.map((sensitivity) => (
              <option value={sensitivity} key={sensitivity}>
                {sensitivity}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error ? <p className="error">{error}</p> : null}

      <div className="graph-layout">
        <div className="graph-canvas">
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            fitView
            onNodeClick={(_event, node) => {
              const graphNode = graph?.nodes.find((item) => item.entity_id === node.id);
              if (graphNode) {
                chooseNode(graphNode);
              }
            }}
            onEdgeClick={(_event, edge) => {
              const graphEdge = graph?.edges.find((item) => item.edge_id === edge.id);
              if (graphEdge) {
                chooseEdge(graphEdge);
              }
            }}
          >
            <Background />
            <Controls />
          </ReactFlow>
        </div>

        <section className="panel" aria-labelledby="graph-detail-title">
          <h2 id="graph-detail-title">Graph detail</h2>
          <div className="debug-stack">
            <section>
              <h3>Nodes</h3>
              <div className="pill-row">
                {(graph?.nodes ?? []).map((node) => (
                  <button
                    className="secondary"
                    key={node.entity_id}
                    type="button"
                    onClick={() => chooseNode(node)}
                  >
                    Node {node.display_name}
                  </button>
                ))}
              </div>
            </section>
            <section>
              <h3>Edges</h3>
              <div className="pill-row">
                {(graph?.edges ?? []).map((edge) => (
                  <button
                    className="secondary"
                    key={edge.edge_id}
                    type="button"
                    onClick={() => chooseEdge(edge)}
                  >
                    Edge {edge.relation_type}
                  </button>
                ))}
              </div>
            </section>
            {selectedNode ? <NodeDetail node={selectedNode} /> : null}
            {selectedEdge ? <EdgeDetail edge={selectedEdge} /> : null}
          </div>
        </section>
      </div>
    </section>
  );
}

function NodeDetail({node}: {node: GraphNode}) {
  return (
    <dl className="definition-list compact">
      <div>
        <dt>Entity</dt>
        <dd>{node.display_name}</dd>
      </div>
      <div>
        <dt>ID</dt>
        <dd>{node.entity_id}</dd>
      </div>
      <div>
        <dt>Status</dt>
        <dd>{node.status}</dd>
      </div>
      <div>
        <dt>Sensitivity</dt>
        <dd>{node.sensitivity}</dd>
      </div>
    </dl>
  );
}

function EdgeDetail({edge}: {edge: GraphEdge}) {
  return (
    <dl className="definition-list compact">
      <div>
        <dt>Edge</dt>
        <dd>{edge.edge_id}</dd>
      </div>
      <div>
        <dt>Type</dt>
        <dd>{edge.relation_type}</dd>
      </div>
      <div>
        <dt>Endpoints</dt>
        <dd>
          {edge.from_entity_id} {"->"} {edge.to_entity_id}
        </dd>
      </div>
      <div>
        <dt>Confidence</dt>
        <dd>{edge.confidence}</dd>
      </div>
    </dl>
  );
}
