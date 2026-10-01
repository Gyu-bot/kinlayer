#!/usr/bin/env python3
"""Serve a disposable, real Kinlayer API with the supplied fictional UI fixtures.

No production URL, credentials, or database is read. The database lives only for
this process. Run with PYTHONPATH=backend/src and the project's Python runtime.
"""

import argparse
import json
import re
import tempfile
from pathlib import Path

import uvicorn
from fastapi.testclient import TestClient

from kinlayer_backend.config import Settings
from kinlayer_backend.database import create_db_engine
from kinlayer_backend.main import create_app
from kinlayer_backend.models import Base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8785)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    seed = json.loads((root / "backend/tests/fixtures/frontend-demo.json").read_text())
    with tempfile.TemporaryDirectory(prefix="kinlayer-ui-demo-") as directory:
        overrides = {
            "database_url": f"sqlite+pysqlite:///{directory}/demo.db",
            "api_token": None, "material_import_token": None,
            "reconciliation_token": None, "reconciliation_commitment_key": None,
            "embedding_provider": None, "embedding_api_key": None,
            "embedding_api_url": None, "embedding_model": None, "embedding_dim": None,
            "curation_mode": "disabled", "bootstrap_self": True, "self_name": "나",
        }
        engine = create_db_engine(Settings(_env_file=None, **overrides))
        Base.metadata.create_all(engine)
        app = create_app(overrides)
        with TestClient(app) as client:
            def post(path, payload):
                response = client.post(path, json=payload)
                response.raise_for_status()
                return response.json()

            people = {"self": client.get("/api/entities?system_role=self").json()["items"][0]["id"]}
            for person in seed["people"]:
                result = post("/api/entities", {"display_name": person["name"], "created_by": "user"})
                people[person["id"]] = result["id"]
                for alias in person["aliases"]:
                    post(f"/api/entities/{result['id']}/aliases", {"alias": alias})

            counter = 0

            def memory(kind, payload, source_key, **changes):
                nonlocal counter
                counter += 1
                source = seed["sources"][source_key]
                y, m, d = map(int, re.findall(r"\d+", source["date"]))
                return post("/api/memories", {
                    "request_id": f"ui-demo-{counter}", "created_by": "user",
                    "source": {"source_type": "manual_entry", "actor": source["actor"],
                               "excerpt": source["excerpt"],
                               "occurred_at": f"{y:04}-{m:02}-{d:02}T12:00:00+09:00"},
                    "record": {"record_type": kind,
                               "payload": {"claim_basis": "reported", "confidence": 1, **payload}},
                    **changes,
                })

            for person in seed["people"]:
                for fact in person["facts"]:
                    memory("entity_facts", {"entity_id": people[person["id"]],
                           "fact_type": fact["type"], "content": fact["value"],
                           "value": {"text": fact["value"]}}, fact["source"])
                for context in person["contexts"]:
                    memory("observations", {"subject_entity_id": people[person["id"]],
                           "observation_type": context["type"], "content": context["text"],
                           "occurred_at": f"{context['date']}T12:00:00+09:00"}, context["source"])
            for edge in seed["edges"]:
                memory("entity_edges", {"from_entity_id": people[edge["a"]],
                       "to_entity_id": people[edge["b"]], "relation_type": edge["type"],
                       "claim_text": seed["sources"][edge["source"]]["excerpt"]}, edge["source"])

            # The old approval mock's uncertain future transfer is a saved observation,
            # never a silent replacement of Minji's current organization.
            memory("observations", {"subject_entity_id": people["minji"],
                   "observation_type": "recent_interaction",
                   "content": "다음 달 모노랩으로 옮긴다고 했던 것 같지만, 적용 시점은 다시 확인해야 한다."}, "review-minji")
            memory("entity_facts", {"entity_id": people["seoyeon"], "fact_type": "birthday",
                   "content": "--04-12", "value": {"year": None, "month": 4, "day": 12,
                   "precision": "day"}}, "seoyeon-context")
            old = memory("observations", {"subject_entity_id": people["seoyeon"],
                         "observation_type": "communication_preference",
                         "content": "연락 시간은 정해져 있지 않다.", "claim_basis": "unknown"}, "seoyeon-context")
            memory("observations", {"subject_entity_id": people["seoyeon"],
                   "observation_type": "communication_preference",
                   "content": "통화 전 메시지로 시간을 확인하는 편이 좋을 것 같다.",
                   "claim_basis": "inferred", "confidence": 0.7}, "review-seoyeon",
                   action="correct", old_record_ref=old["new_record_ref"],
                   reason="연락 방식에 관한 대화에서 추론한 맥락 추가")
            print(json.dumps({"fixture": "fictional frontend_v2", "people": people,
                              "api": f"http://127.0.0.1:{args.port}"}, ensure_ascii=False), flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
