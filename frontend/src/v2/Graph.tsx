import {
  type KeyboardEvent,
  type PointerEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { EgoGraph, GraphEdge } from "../types/graph";
import { ErrorState, Loading, Modal, PersonPicker } from "./common";
import {
  basisLabels,
  dateTime,
  memoryUrl,
  query,
  useResource,
  type MemoryItem,
  type Ontology,
  type Page,
  type Person,
} from "./data";
import { Icon } from "./Icons";
import { relationLabel } from "./People";

type Point = [number, number];
const presets: Point[] = [
  [238, 136],
  [553, 126],
  [658, 263],
  [577, 426],
  [398, 456],
  [217, 425],
  [148, 266],
  [376, 103],
];
function positionNodes(graph: EgoGraph): Record<string, Point> {
  const result: Record<string, Point> = { [graph.focal_entity_id]: [410, 288] };
  const neighbors = graph.nodes.filter(
    (node) => node.entity_id !== graph.focal_entity_id,
  );
  neighbors.forEach((node, index) => {
    if (neighbors.length > 5 && neighbors.length <= 8)
      result[node.entity_id] = presets[index];
    else if (neighbors.length <= 5)
      result[node.entity_id] = [
        410 +
          224 *
            Math.cos(-Math.PI / 2 + (index * 2 * Math.PI) / neighbors.length),
        285 +
          177 *
            Math.sin(-Math.PI / 2 + (index * 2 * Math.PI) / neighbors.length),
      ];
    else {
      const ring = Math.floor(index / 12),
        start = ring * 12,
        count = Math.min(12, neighbors.length - start);
      const angle =
        -Math.PI / 2 + ((index - start) * 2 * Math.PI) / count + ring * 0.2;
      result[node.entity_id] = [
        410 + (285 + ring * 190) * Math.cos(angle),
        288 + (210 + ring * 150) * Math.sin(angle),
      ];
    }
  });
  return result;
}
function edgeGeometry(
  edge: GraphEdge,
  graph: EgoGraph,
  positions: Record<string, Point>,
) {
  const a = positions[edge.from_entity_id],
    b = positions[edge.to_entity_id];
  const parallels = graph.edges.filter(
    (other) =>
      (other.from_entity_id === edge.from_entity_id &&
        other.to_entity_id === edge.to_entity_id) ||
      (other.from_entity_id === edge.to_entity_id &&
        other.to_entity_id === edge.from_entity_id),
  );
  // Use a consistent orientation for offsets even if the directed endpoints reverse.
  const orientation = edge.from_entity_id < edge.to_entity_id ? 1 : -1;
  const offset =
    (parallels.indexOf(edge) - (parallels.length - 1) / 2) * 88 * orientation;
  const dx = b[0] - a[0],
    dy = b[1] - a[1],
    length = Math.hypot(dx, dy) || 1;
  const control: Point = [
    (a[0] + b[0]) / 2 - (dy / length) * offset,
    (a[1] + b[1]) / 2 + (dx / length) * offset,
  ];
  const trim = (point: Point, radius: number): Point => {
    const vx = control[0] - point[0],
      vy = control[1] - point[1],
      len = Math.hypot(vx, vy) || 1;
    return [point[0] + (vx / len) * radius, point[1] + (vy / len) * radius];
  };
  const start = trim(
    a,
    edge.from_entity_id === graph.focal_entity_id ? 40 : 31,
  );
  const end = trim(b, edge.to_entity_id === graph.focal_entity_id ? 44 : 35);
  return {
    path: `M${start[0]},${start[1]}Q${control[0]},${control[1]} ${end[0]},${end[1]}`,
    middle: [
      a[0] * 0.25 + control[0] * 0.5 + b[0] * 0.25,
      a[1] * 0.25 + control[1] * 0.5 + b[1] * 0.25,
    ],
  };
}

export function Graph({ onNavigate }: { onNavigate: (path: string) => void }) {
  const routeFocal =
    new URLSearchParams(window.location.search).get("focal") || "";
  const self = useResource<Page<Person>>(
    "/api/entities?entity_type=person&system_role=self&limit=1",
  );
  const ontology = useResource<Ontology>("/api/ontology");
  const [focal, setFocal] = useState(routeFocal);
  const [relation, setRelation] = useState("");
  const [selectedNode, setSelectedNode] = useState("");
  const [selectedEdge, setSelectedEdge] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<Point>([0, 0]);
  const [picking, setPicking] = useState(false);
  const [draftFocal, setDraftFocal] = useState("");
  const [dragging, setDragging] = useState(false);
  const drag = useRef<{ x: number; y: number; pan: Point } | null>(null);
  const selfId = self.data?.items[0]?.id || "";
  useEffect(() => {
    setFocal((current) => routeFocal || current || selfId);
  }, [routeFocal, selfId]);
  useEffect(() => {
    setSelectedNode(focal);
    setSelectedEdge(null);
    setZoom(1);
    setPan([0, 0]);
  }, [focal]);
  const graph = useResource<EgoGraph>(
    focal
      ? `/api/graph/ego/${encodeURIComponent(focal)}?${query({ depth: 1, relation_type: relation || undefined })}`
      : null,
  );
  const detail = useResource<MemoryItem>(
    selectedEdge
      ? `/api/memories/entity_edges/${encodeURIComponent(selectedEdge)}`
      : null,
  );
  useEffect(() => {
    setSelectedEdge(null);
    setSelectedNode(focal);
  }, [relation, focal]);
  const positions = useMemo(
    () => (graph.data ? positionNodes(graph.data) : {}),
    [graph.data],
  );
  // The API may resolve a merged URL ID to its canonical person. Keep the
  // requested ID for reads, but anchor all displayed relationships to the result.
  const renderedFocal = graph.data?.focal_entity_id || focal;
  const renderedSelection = graph.data?.nodes.some(
    (item) => item.entity_id === selectedNode,
  )
    ? selectedNode
    : renderedFocal;
  const node = graph.data?.nodes.find(
    (item) => item.entity_id === renderedSelection,
  );
  const edge = graph.data?.edges.find((item) => item.edge_id === selectedEdge);
  const focalNode = graph.data?.nodes.find(
    (item) => item.entity_id === renderedFocal,
  );
  const rings = Math.max(
    0,
    Math.ceil(((graph.data?.nodes.length || 1) - 1) / 12) - 1,
  );
  const worldWidth = 820 + rings * 380,
    worldHeight = 600 + rings * 300;
  const viewBox = `${410 - worldWidth / 2} ${300 - worldHeight / 2} ${worldWidth} ${worldHeight}`;
  const nodeName = (id: string) =>
    graph.data?.nodes.find((item) => item.entity_id === id)?.display_name ||
    "연결된 인물";
  function selectEdge(item: GraphEdge) {
    setSelectedEdge(item.edge_id);
    setSelectedNode(
      item.from_entity_id === renderedFocal
        ? item.to_entity_id
        : item.from_entity_id,
    );
  }
  function reset() {
    setFocal(selfId || focal);
    setRelation("");
    setSelectedEdge(null);
    setSelectedNode(selfId || renderedFocal);
    setZoom(1);
    setPan([0, 0]);
  }
  function keyboard(event: KeyboardEvent<SVGGElement>, action: () => void) {
    if (["Enter", " "].includes(event.key)) {
      event.preventDefault();
      action();
    }
  }
  function pointerDown(event: PointerEvent<SVGSVGElement>) {
    if (
      event.button !== 0 ||
      (event.target as Element).closest('[role="button"]')
    )
      return;
    drag.current = { x: event.clientX, y: event.clientY, pan };
    event.currentTarget.setPointerCapture(event.pointerId);
    setDragging(true);
  }
  function pointerMove(event: PointerEvent<SVGSVGElement>) {
    if (!drag.current) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    const scale = Math.max(
      worldWidth / bounds.width,
      worldHeight / bounds.height,
    );
    setPan([
      drag.current.pan[0] + (event.clientX - drag.current.x) * scale,
      drag.current.pan[1] + (event.clientY - drag.current.y) * scale,
    ]);
  }
  function endDrag() {
    drag.current = null;
    setDragging(false);
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <h1>관계 그래프</h1>
          <p>한 사람을 중심으로, 연결된 관계와 그 맥락을 살펴보세요.</p>
        </div>
        <button className="button ghost" onClick={() => onNavigate("/people")}>
          <Icon name="list" />
          목록으로 보기
        </button>
      </div>
      <div className="graph-toolbar">
        <div className="field-inline">
          <span>중심 인물</span>
          <button
            className="button graph-focal-button"
            onClick={() => {
              setDraftFocal(renderedFocal);
              setPicking(true);
            }}
          >
            {focalNode?.display_name ||
              (self.loading ? "불러오는 중…" : "인물 선택")}
            <Icon name="down" />
          </button>
        </div>
        <label className="field-inline">
          관계 유형
          <select
            className="select"
            value={relation}
            onChange={(event) => setRelation(event.target.value)}
            disabled={!ontology.data}
          >
            <option value="">모든 관계</option>
            {ontology.data?.edge_types
              .filter((item) => item.active !== false)
              .map((item) => (
                <option key={item.relation_type} value={item.relation_type}>
                  {relationLabel(item.relation_type, ontology.data)}
                  {item.directed_default ? " (방향 있음)" : ""}
                </option>
              ))}
          </select>
        </label>
        <button className="button ghost" onClick={reset}>
          <Icon name="reset" />
          보기 초기화
        </button>
      </div>
      {ontology.error ? (
        <ErrorState error={ontology.error} retry={ontology.reload} />
      ) : null}
      {self.error && !focal ? (
        <ErrorState error={self.error} retry={self.reload} />
      ) : null}
      {(self.loading && !focal) || graph.loading ? (
        <Loading />
      ) : graph.error ? (
        <ErrorState error={graph.error} retry={graph.reload} />
      ) : !focal && !self.error ? (
        <div className="panel empty-state">
          <h2>기준 인물이 아직 없어요</h2>
          <p>중심 인물에서 사람을 선택하거나 연결 설정을 확인해 주세요.</p>
          <button className="text-link" onClick={self.reload}>
            다시 확인
          </button>
        </div>
      ) : graph.data ? (
        <div className="graph-layout">
          <section aria-label="관계 그래프와 목록">
            <div className="graph-board">
              <div className="graph-caption">
                <h2>{focalNode?.display_name || "선택한 인물"}의 관계</h2>
                <p>
                  직접 연결된 {Math.max(0, graph.data.nodes.length - 1)}명 ·
                  1단계 관계
                </p>
              </div>
              <svg
                className={`graph-svg ${dragging ? "dragging" : ""}`}
                viewBox={viewBox}
                aria-label={`${focalNode?.display_name || "선택한 인물"}의 직접 관계 그래프`}
                onPointerDown={pointerDown}
                onPointerMove={pointerMove}
                onPointerUp={endDrag}
                onPointerCancel={endDrag}
                onLostPointerCapture={endDrag}
              >
                <defs>
                  <marker
                    id="graph-direction-arrow"
                    viewBox="0 0 10 10"
                    refX="9"
                    refY="5"
                    markerWidth="7"
                    markerHeight="7"
                    orient="auto-start-reverse"
                  >
                    <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
                  </marker>
                </defs>
                <g
                  transform={`translate(${410 + pan[0]} ${300 + pan[1]}) scale(${zoom}) translate(-410 -300)`}
                >
                  {graph.data.edges.map((item) => {
                    const geometry = edgeGeometry(item, graph.data!, positions);
                    const name = `${nodeName(item.from_entity_id)} ${item.directed ? "→" : "↔"} ${nodeName(item.to_entity_id)} · ${relationLabel(item.relation_type, ontology.data)}`;
                    return (
                      <g
                        key={item.edge_id}
                        className={`edge-group ${item.edge_id === selectedEdge ? "selected" : ""}`}
                        tabIndex={0}
                        role="button"
                        aria-label={name}
                        aria-pressed={item.edge_id === selectedEdge}
                        onClick={() => selectEdge(item)}
                        onKeyDown={(event) =>
                          keyboard(event, () => selectEdge(item))
                        }
                      >
                        <title>{name}</title>
                        <path
                          className="graph-edge"
                          d={geometry.path}
                          markerEnd={
                            item.directed
                              ? "url(#graph-direction-arrow)"
                              : undefined
                          }
                        />
                        <path className="edge-hit" d={geometry.path} />
                        <text
                          className="edge-label"
                          x={geometry.middle[0]}
                          y={geometry.middle[1] - 9}
                          textAnchor="middle"
                        >
                          {relationLabel(item.relation_type, ontology.data)}
                        </text>
                      </g>
                    );
                  })}
                  {graph.data.nodes.map((item) => {
                    const isFocal = item.entity_id === renderedFocal;
                    return (
                      <g
                        key={item.entity_id}
                        className={`graph-node ${item.entity_id === renderedSelection ? "selected" : ""} ${isFocal ? "self" : ""}`}
                        transform={`translate(${positions[item.entity_id].join(",")})`}
                        tabIndex={0}
                        role="button"
                        aria-label={`${item.display_name} 선택${isFocal ? " · 중심 인물" : ""}`}
                        aria-pressed={item.entity_id === renderedSelection}
                        onClick={() => {
                          setSelectedNode(item.entity_id);
                          setSelectedEdge(null);
                        }}
                        onKeyDown={(event) =>
                          keyboard(event, () => {
                            setSelectedNode(item.entity_id);
                            setSelectedEdge(null);
                          })
                        }
                      >
                        <title>{item.display_name}</title>
                        <circle className="node-circle" r={isFocal ? 38 : 29} />
                        <text className="node-letter" textAnchor="middle" y="6">
                          {item.entity_id === selfId
                            ? "나"
                            : Array.from(item.display_name).slice(-2).join("")}
                        </text>
                        <text
                          className="node-name"
                          textAnchor="middle"
                          y={isFocal ? 61 : 51}
                        >
                          {item.display_name.length > 12
                            ? `${item.display_name.slice(0, 11)}…`
                            : item.display_name}
                        </text>
                        {isFocal && (
                          <text className="node-sub" textAnchor="middle" y="79">
                            관계의 중심
                          </text>
                        )}
                      </g>
                    );
                  })}
                </g>
              </svg>
              <div className="graph-controls">
                <button
                  className="icon-button"
                  aria-label="그래프 축소"
                  onClick={() =>
                    setZoom((value) =>
                      Math.max(0.6, Math.round((value - 0.2) * 10) / 10),
                    )
                  }
                >
                  <Icon name="minus" />
                </button>
                <span aria-live="polite">{Math.round(zoom * 100)}%</span>
                <button
                  className="icon-button"
                  aria-label="그래프 확대"
                  onClick={() =>
                    setZoom((value) =>
                      Math.min(2.4, Math.round((value + 0.2) * 10) / 10),
                    )
                  }
                >
                  <Icon name="plus" />
                </button>
                <button
                  className="icon-button"
                  aria-label="그래프 전체 맞춤"
                  onClick={() => {
                    setZoom(1);
                    setPan([0, 0]);
                  }}
                >
                  <Icon name="fit" />
                </button>
              </div>
              <span className="graph-hint">
                인물이나 연결선을 선택해 보세요
              </span>
            </div>
            {!graph.data.edges.length && (
              <p className="status-line">
                {relation
                  ? "선택한 유형으로 연결된 관계가 없어요."
                  : "아직 직접 연결된 관계가 없어요."}
              </p>
            )}
            <div className="graph-mobile-list" aria-label="연결된 관계 목록">
              {graph.data.edges.map((item) => (
                <button
                  key={item.edge_id}
                  aria-pressed={item.edge_id === selectedEdge}
                  onClick={() => selectEdge(item)}
                >
                  <span className="avatar" aria-hidden="true">
                    {nodeName(
                      item.from_entity_id === renderedFocal
                        ? item.to_entity_id
                        : item.from_entity_id,
                    ).slice(-2)}
                  </span>
                  <span>
                    {nodeName(
                      item.from_entity_id === renderedFocal
                        ? item.to_entity_id
                        : item.from_entity_id,
                    )}
                    <small>
                      {relationLabel(item.relation_type, ontology.data)}
                      {item.directed
                        ? ` · ${item.from_entity_id === renderedFocal ? "중심에서 상대에게" : "상대에서 중심에게"}`
                        : " · 양방향"}
                    </small>
                  </span>
                </button>
              ))}
            </div>
          </section>
          <aside className="graph-rail" aria-label="선택한 인물과 관계">
            {node && (
              <section className="panel preview-panel">
                <div className="panel-kicker">
                  <span>{edge ? "선택한 관계" : "선택한 인물"}</span>
                  <Icon name="graph" />
                </div>
                <div className="preview-body">
                  <span className="avatar large" aria-hidden="true">
                    {node.display_name.slice(-2)}
                  </span>
                  <div className="preview-name">
                    <h2>{node.display_name}</h2>
                  </div>
                  <p className="preview-subtitle">
                    {edge
                      ? relationLabel(edge.relation_type, ontology.data)
                      : node.entity_id === renderedFocal
                        ? "관계의 중심"
                        : "직접 연결된 인물"}
                  </p>
                  {edge && (
                    <div className="graph-evidence">
                      <p className="small muted">
                        {nodeName(edge.from_entity_id)}{" "}
                        {edge.directed ? "→" : "↔"}{" "}
                        {nodeName(edge.to_entity_id)}
                      </p>
                      {detail.loading ? (
                        <Loading />
                      ) : detail.error ? (
                        <ErrorState
                          error={detail.error}
                          retry={detail.reload}
                        />
                      ) : (
                        detail.data && (
                          <>
                            <div className="context-meta">
                              <span
                                className={`pill ${detail.data.claim_basis === "inferred" ? "warning" : ""}`}
                              >
                                {basisLabels[detail.data.claim_basis]}
                              </span>
                              <span>
                                {detail.data.is_current
                                  ? "현재 맥락"
                                  : detail.data.status === "active"
                                    ? "유효 기간 밖"
                                    : "이전 기록"}
                              </span>
                            </div>
                            <p className="graph-claim">{detail.data.content}</p>
                            {(detail.data.valid_from ||
                              detail.data.valid_to) && (
                              <p className="small muted">
                                유효 기간{" "}
                                {detail.data.valid_from
                                  ? dateTime(detail.data.valid_from)
                                  : "시작 미상"}{" "}
                                →{" "}
                                {detail.data.valid_to
                                  ? dateTime(detail.data.valid_to)
                                  : "종료 미상"}
                              </p>
                            )}
                            <div className="stack graph-sources">
                              {detail.data.sources.length ? (
                                detail.data.sources.map((source, index) => (
                                  <div
                                    key={`${source.episode_id}-${index}`}
                                    className="evidence-card"
                                  >
                                    {source.missing && (
                                      <p className="small muted">
                                        이전 출처가 연결되어 있지 않아요.
                                      </p>
                                    )}
                                    <>
                                      <span className="small muted">
                                        {source.actor || "작성자 미상"} ·{" "}
                                        {source.occurred_at
                                          ? dateTime(source.occurred_at)
                                          : "발언 시점 미상"}
                                      </span>
                                      <blockquote>
                                        {source.excerpt || "저장된 발췌 없음"}
                                      </blockquote>
                                      {!source.missing && source.episode_id && (
                                        <button
                                          className="text-link"
                                          onClick={() =>
                                            onNavigate(
                                              `/sources/${encodeURIComponent(source.episode_id!)}`,
                                            )
                                          }
                                        >
                                          <Icon name="source" />
                                          출처 보기
                                        </button>
                                      )}
                                    </>
                                  </div>
                                ))
                              ) : (
                                <p className="small muted">
                                  연결된 출처가 없어요.
                                </p>
                              )}
                            </div>
                            <button
                              className="text-link"
                              onClick={() =>
                                onNavigate(memoryUrl(detail.data!.record_ref))
                              }
                            >
                              기억 확인·정정
                              <Icon name="arrow" />
                            </button>
                          </>
                        )
                      )}
                    </div>
                  )}
                </div>
                <div className="preview-actions">
                  {node.entity_type === "person" && (
                    <button
                      className="button primary"
                      onClick={() =>
                        onNavigate(
                          `/people/${encodeURIComponent(node.entity_id)}`,
                        )
                      }
                    >
                      프로필 보기
                      <Icon name="arrow" />
                    </button>
                  )}
                  {node.entity_id !== renderedFocal && (
                    <button
                      className="button ghost"
                      onClick={() => setFocal(node.entity_id)}
                    >
                      이 사람을 중심으로
                    </button>
                  )}
                </div>
              </section>
            )}
          </aside>
        </div>
      ) : null}
      {picking && (
        <Modal title="중심 인물 변경" onClose={() => setPicking(false)}>
          <div className="modal-body">
            <PersonPicker
              title="중심 인물"
              value={draftFocal}
              initialName={focalNode?.display_name}
              onChange={setDraftFocal}
            />
          </div>
          <div className="modal-footer">
            <button className="button ghost" onClick={() => setPicking(false)}>
              취소
            </button>
            <button
              className="button primary"
              disabled={!draftFocal}
              onClick={() => {
                setFocal(draftFocal);
                setPicking(false);
              }}
            >
              이 인물을 중심으로
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
