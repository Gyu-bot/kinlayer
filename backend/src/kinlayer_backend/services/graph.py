from kinlayer_backend.api.errors import api_error
from kinlayer_backend.repositories.graph import GraphRepository


class GraphService:
    def __init__(self, session):
        self.repository = GraphRepository(session)

    def ego_graph(
        self,
        entity_id: str,
        depth: int = 1,
        relation_type: str | None = None,
        status: str | None = None,
        sensitivity: str | None = None,
    ) -> dict:
        if depth != 1:
            raise api_error(422, "validation_error", "Only depth=1 is supported in MVP.")
        focal = self.repository.get_entity(entity_id)
        if not focal:
            raise api_error(404, "not_found", "Entity not found.")
        focal = self._redirect_merged_entity(focal)
        entity_id = focal.id
        edges = self.repository.ego_edges(
            entity_id,
            relation_type=relation_type,
            status=status,
            sensitivity=sensitivity,
        )
        entity_ids = {entity_id}
        for edge in edges:
            entity_ids.add(edge.from_entity_id)
            entity_ids.add(edge.to_entity_id)
        entities = {entity.id: entity for entity in self.repository.entities_by_id(entity_ids)}
        nodes = [
            {
                "entity_id": entity.id,
                "display_name": entity.display_name,
                "entity_type": entity.entity_type,
                "status": entity.status,
                "sensitivity": entity.sensitivity,
                "is_focal": entity.id == entity_id,
            }
            for entity in entities.values()
        ]
        nodes.sort(key=lambda node: (not node["is_focal"], node["display_name"]))
        filters_applied: dict[str, str | int] = {"depth": depth}
        if relation_type:
            filters_applied["relation_type"] = relation_type
        if status:
            filters_applied["status"] = status
        if sensitivity:
            filters_applied["sensitivity"] = sensitivity
        return {
            "focal_entity_id": entity_id,
            "depth": depth,
            "nodes": nodes,
            "edges": [
                {
                    "edge_id": edge.id,
                    "from_entity_id": edge.from_entity_id,
                    "to_entity_id": edge.to_entity_id,
                    "relation_type": edge.relation_type,
                    "directed": edge.directed,
                    "status": edge.status,
                    "confidence": float(edge.confidence),
                    "sensitivity": edge.sensitivity,
                }
                for edge in edges
            ],
            "filters_applied": filters_applied,
        }

    def _redirect_merged_entity(self, entity):
        if entity.status != "merged":
            return entity
        merged_ref = (entity.properties or {}).get("merged_entity_ref")
        if not merged_ref or not merged_ref.startswith("entities:"):
            return entity
        return self.repository.get_entity(merged_ref.split(":", 1)[1]) or entity
