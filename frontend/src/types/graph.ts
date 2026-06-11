export type GraphNode = {
  entity_id: string;
  display_name: string;
  entity_type: string;
  status: string;
  sensitivity: string;
  is_focal: boolean;
};

export type GraphEdge = {
  edge_id: string;
  from_entity_id: string;
  to_entity_id: string;
  relation_type: string;
  directed: boolean;
  status: string;
  confidence: number;
  sensitivity: string;
};

export type EgoGraph = {
  focal_entity_id: string;
  depth: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  filters_applied: Record<string, string | number>;
};

export type GraphFilters = {
  relation_type: string;
  status: string;
  sensitivity: string;
};
