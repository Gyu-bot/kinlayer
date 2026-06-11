from kinlayer_backend.schemas.common import APIModel


class GraphNode(APIModel):
    entity_id: str
    display_name: str
    entity_type: str
    status: str
    sensitivity: str
    is_focal: bool = False


class GraphEdge(APIModel):
    edge_id: str
    from_entity_id: str
    to_entity_id: str
    relation_type: str
    directed: bool
    status: str
    confidence: float
    sensitivity: str


class EgoGraph(APIModel):
    focal_entity_id: str
    depth: int
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    filters_applied: dict[str, str | int]
