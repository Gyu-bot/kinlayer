"""Disposable source/receipt fake and synthetic ontology. Not a backend or identity model."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import importlib
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
import identity_smoke_fixtures as smoke

STAMP = "2026-09-30T19:07:30+09:00"

RECORD_PATHS = {"entity_facts": "entity-facts", "entity_edges": "edges", "observations": "observations"}

FORBIDDEN = {"claim_type", "ai_use_policy", "confirmation_status", "sensitivity", "suggested_action"}

ROLES = ("subject", "related", "mentioned", "speaker", "target", "about", "experiencer")

AXIS_VALUES = {
    "closeness": ("recognize", "acquainted", "comfortable", "close", "very_close"),
    "importance": ("normal", "important", "very_important"),
    "interaction_frequency": ("frequent", "occasional", "rare", "none"),
    "connection_state": ("maintained", "distant", "disconnected"),
}

def ontology():
    """Subset of the real OntologyRead shape, including legacy registry rows."""
    def values(category, items):
        return [{"category": category, "value": value, "label": value,
                 "is_active": True, "support_level": "supported", "sort_order": index}
                for index, value in enumerate(items)]
    return {
        "version": "offline-relationship-version",
        "relationship_profile": {"version": "relationship-profile-v1", "axes": {
            axis: {"label": axis, "description": "Explicit user assessment", "values": [
                {"value": value, "label": value, "description": "Source stated " + value} for value in values]}
            for axis, values in AXIS_VALUES.items()}},
        "entity_types": values("entity_type", ["person"]),
        "fact_types": values("fact_type", ["legal_name", "job", "role", "organization", "email",
                                          "birth_date", "birthday", "memo", "important_context",
                                          "relationship_note", "contact_note"]),
        "claim_bases": values("claim_basis", ["reported", "inferred", "unknown"]),
        "participant_roles": values("participant_role", ROLES),
        "edge_types": [{"relation_type": value, "from_entity_type": "person", "to_entity_type": "person",
                        "directed_default": value == "reports_to", "active": True,
                        "support_level": "supported", "write_supported": True,
                        "created_at": STAMP, "updated_at": STAMP}
                       for value in ("friend", "coworker", "reports_to")],
        "observation_types": [{"observation_type": value, "active": True,
                               "created_at": STAMP, "updated_at": STAMP}
                              for value in ("stable_fact", "preference", "communication_preference",
                                            "relationship_pattern", "care_point", "caution",
                                            "recent_interaction", "user_feeling", "follow_up_context", "relationship_assessment")],
        "policies": {"candidate_types": [], "claim_types": [], "ai_use_policies": []},
    }

def observation(**overrides):
    return {"action": "create", "record_type": "observations", "subject": "Casey",
            "observation_type": "preference", "content": "Casey prefers concise replies.",
            "claim_basis": "reported", "confidence": 0.9,
            "source_quote": "Casey prefers concise replies.", **overrides}

def assessment(**overrides):
    return observation(**{"observation_type": "relationship_assessment", "perspective_subject": "self",
                          "relationship_axis": "importance", "relationship_value": "important",
                          "content": "Casey is important to me.", "source_quote": "Casey is important to me.", **overrides})

def fact(**overrides):
    return {"action": "create", "record_type": "entity_facts", "subject": "Casey",
            "fact_type": "job", "content": "Engineer", "value": {"text": "Engineer"},
            "claim_basis": "reported", "confidence": 0.9,
            "source_quote": "Casey works as an engineer.", **overrides}

def edge(**overrides):
    return {"action": "create", "record_type": "entity_edges", "subject": "Casey",
            "from_subject": "Casey", "to_subject": "Riley", "relation_type": "friend",
            "claim_text": "Casey and Riley are friends.", "claim_basis": "reported", "confidence": 0.9,
            "source_quote": "Casey and Riley are friends.", **overrides}

def http_error(code):
    return HTTPError("http://offline.invalid/api/memories", code, "synthetic failure", {},
                     io.BytesIO(json.dumps({"detail": {"code": f"test_{code}"}}).encode()))

class FakeMemoryTransport:
    """Atomic fake with real wire shapes, receipt replay, soft state and readback."""
    def __init__(self):
        self.calls = []
        self.contract = {"endpoint": "/api/memories", "contract_version": "2", "review_required": False}
        self.ontology = ontology()
        self.entities = {
            "Casey": {"id": "person-casey", "entity_type": "person", "display_name": "Casey", "status": "active"},
            "Riley": {"id": "person-riley", "entity_type": "person", "display_name": "Riley", "status": "active"},
            "self": {"id": "person-self", "entity_type": "person", "display_name": "Synthetic owner",
                     "status": "active", "system_role": "self", "is_system": True},
        }
        self.resolutions = {}
        self.records = {}
        self.requests = {}
        self.receipts = {}
        self.memory_failures = []
        self.commit_then_timeout = False
        self.create_person_then_timeout = False

    @property
    def memory_calls(self):
        return [payload for method, path, payload in self.calls if method == "POST" and path == "/api/memories"]

    @property
    def writes(self):
        return [(method, path, payload) for method, path, payload in self.calls if method != "GET"]

    def add_record(self, kind, identifier, **payload):
        row = {"id": identifier, "status": "active", "claim_basis": "reported", "confidence": 0.9,
               "created_at": STAMP, "updated_at": STAMP, **payload}
        self.records[f"{kind}:{identifier}"] = row
        return deepcopy(row)

    def card(self, entity_id):
        result = {"entity": next(row for row in self.entities.values() if row["id"] == entity_id),
                  "aliases": [], "profile_facts": [], "relationship_edges": [], "stable_context": [],
                  "recent_context": [], "communication_context": [], "cautions": [],
                  "provenance_summary": {"evidence": []}, "retrieval_hints": {"entity_id": entity_id},
                  "relationship_profile": self.profile(entity_id)}
        for ref, row in self.records.items():
            if row["status"] not in {"active", "disputed"}:
                continue
            kind = ref.split(":", 1)[0]
            if kind == "entity_facts" and row.get("entity_id") == entity_id:
                result["profile_facts"].append(row)
            elif kind == "entity_edges" and entity_id in (row.get("from_entity_id"), row.get("to_entity_id")):
                result["relationship_edges"].append(row)
            elif kind == "observations" and row.get("subject_entity_id") == entity_id:
                topic = row.get("observation_type")
                if topic == "relationship_assessment":
                    continue
                bucket = "cautions" if topic == "caution" else "communication_context" if topic == "communication_preference" else "recent_context" if topic in {"recent_interaction", "follow_up_context"} else "stable_context"
                result[bucket].append(row)
        for key, receipt in self.receipts.items():
            ref = receipt["new_record_ref"]
            if ref and ref in self.records and self.records[ref]["status"] in {"active", "disputed"}:
                kind, record_id = ref.split(":", 1)
                source = self.requests[key]["source"]
                result["provenance_summary"]["evidence"].append({
                    "record_type": {"entity_facts": "fact", "entity_edges": "edge", "observations": "observation"}[kind],
                    "record_id": record_id, "episode_id": receipt["source_episode_id"],
                    "actor": source["actor"], "excerpt": source["excerpt"]})
        return deepcopy(result)

    def memory_read(self, ref):
        row = self.records[ref]
        return {"record_ref": ref, "record_type": ref.split(":", 1)[0],
                **{key: row[key] for key in ("id", "status", "updated_at", "created_at")},
                "is_current": row["status"] in {"active", "disputed"}, "sources": [],
                "payload": {key: value for key, value in row.items() if key not in {"id", "status", "created_at", "updated_at"}}}

    def profile(self, entity_id):
        axes = {axis: {"value": None, "label": None, "record": None} for axis in AXIS_VALUES}
        for ref, row in self.records.items():
            if (row.get("observation_type") == "relationship_assessment" and row.get("subject_entity_id") == entity_id
                    and row.get("perspective_entity_id") == "person-self" and row["status"] in {"active", "disputed"}):
                value = row["relationship_value"]
                axes[row["relationship_axis"]] = {"value": value, "label": value, "record": self.memory_read(ref)}
        return {"version": "relationship-profile-v1", "entity_id": entity_id, "perspective_entity_id": "person-self", "axes": axes}

    def _write(self, payload):
        identifier = payload["request_id"]
        if identifier in self.requests:
            if self.requests[identifier] != payload:
                raise http_error(409)
            return deepcopy(self.receipts[identifier])
        old = payload.get("old_record_ref")
        if old and old not in self.records:
            raise http_error(404)
        if old and self.records[old]["status"] not in {"active", "disputed"}:
            raise http_error(409)
        count = len(self.requests) + 1
        new_ref = None
        if payload["action"] != "retract":
            record = payload["record"]
            proposed = record["payload"]
            if proposed.get("observation_type") == "relationship_assessment":
                for ref, row in self.records.items():
                    if (ref != old and row["status"] in {"active", "disputed"}
                            and row.get("observation_type") == "relationship_assessment"
                            and all(row.get(key) == proposed.get(key) for key in ("subject_entity_id", "perspective_entity_id", "relationship_axis"))):
                        raise http_error(409)
            new_ref = f"{record['record_type']}:new-{count}"
            self.add_record(record["record_type"], f"new-{count}", **record["payload"])
        if old:
            self.records[old]["status"] = "deleted" if payload["action"] == "retract" else "superseded"
        receipt = {"change_id": f"change-{count}", "action": payload["action"],
                   "old_record_ref": old, "new_record_ref": new_ref, "source_episode_id": f"episode-{count}"}
        self.requests[identifier] = deepcopy(payload)
        self.receipts[identifier] = receipt
        return deepcopy(receipt)

    def __call__(self, config, method, path, payload=None):
        self.calls.append((method, path, deepcopy(payload)))
        parsed = urlsplit(path)
        route = parsed.path
        if method == "GET" and route == "/api/system/config":
            return {"memory_write": deepcopy(self.contract), "embedding": {"enabled": False}}
        if method == "GET" and route == "/api/ontology":
            return deepcopy(self.ontology)
        if method == "POST" and route == "/api/entities/resolve":
            assert set(payload) == {"surface", "entity_type"}, payload
            assert payload["entity_type"] == "person", payload
            name = payload["surface"]
            if name in self.resolutions:
                return deepcopy(self.resolutions[name])
            entity = self.entities.get(name)
            return {"surface": name, "ambiguity": "single_strong_match" if entity else "no_match",
                    "matches": [{"entity_id": entity["id"], "display_name": name, "entity_type": "person",
                                 "score": 1.0, "match_reasons": ["exact_name"]}] if entity else []}
        if method == "POST" and route == "/api/entities":
            assert payload == {"entity_type": "person", "display_name": payload["display_name"], "created_by": "ai_agent"}, payload
            name = payload["display_name"]
            assert name not in self.entities, "Duplicate entity creation attempted"
            self.entities[name] = {"id": f"person-{len(self.entities) + 1}", "display_name": name,
                                   "entity_type": "person", "status": "active"}
            if self.create_person_then_timeout:
                self.create_person_then_timeout = False
                raise TimeoutError("entity committed but acknowledgement lost")
            return deepcopy(self.entities[name])
        if method == "GET" and route == "/api/entities":
            items = list(self.entities.values())
            query = parse_qs(parsed.query)
            if "system_role" in query:
                items = [row for row in items if row.get("system_role") == query["system_role"][0]]
            return {"items": deepcopy(items), "total": len(items)}
        if method == "GET" and route.startswith("/api/entities/"):
            entity_id = route.split("/")[3]
            if route.endswith("/relationship-profile"):
                return self.profile(entity_id)
            if route.endswith("/context-card"):
                return self.card(entity_id)
            matches = [row for row in self.entities.values() if row["id"] == entity_id]
            if len(matches) == 1:
                return deepcopy(matches[0])
            raise http_error(404)
        if method == "POST" and route == "/api/memories":
            if self.memory_failures:
                raise self.memory_failures.pop(0)
            receipt = self._write(payload)
            if self.commit_then_timeout:
                self.commit_then_timeout = False
                raise TimeoutError("memory committed but acknowledgement lost")
            return receipt
        if method == "GET" and route.startswith("/api/memories/observations/"):
            return self.memory_read("observations:" + route.rsplit("/", 1)[1])
        if method == "GET" and route.startswith("/api/memory-changes/"):
            receipt = next(r for r in self.receipts.values() if r["change_id"] == route.rsplit("/", 1)[1])
            body = next(b for key, b in self.requests.items() if self.receipts[key] == receipt)
            return {"id": receipt["change_id"], "request_id": body["request_id"], "change_kind": body["action"],
                    "old_record_ref": receipt["old_record_ref"], "new_record_ref": receipt["new_record_ref"],
                    "source_episode_id": receipt["source_episode_id"], "actor": body["created_by"]}
        if method == "GET" and route.startswith("/api/episodes/"):
            key = next(key for key, r in self.receipts.items() if r["source_episode_id"] == route.rsplit("/", 1)[1])
            source = self.requests[key]["source"]
            return {"id": route.rsplit("/", 1)[1], "body_excerpt": source["excerpt"], **source,
                    "source_type": source["source_type"] if self.requests[key]["action"] == "create" else "correction"}
        if method == "GET":
            for kind, fragment in RECORD_PATHS.items():
                if route.startswith(f"/api/{fragment}/"):
                    ref = f"{kind}:{route.rsplit('/', 1)[1]}"
                    if ref in self.records:
                        return deepcopy(self.records[ref])
                    raise http_error(404)
        raise AssertionError(f"Unexpected or legacy API operation: {method} {path}")

class SaveFirstMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Guard before importing the plugin, including any integration imports.
        for target, attribute in ((socket.socket, "connect"), (socket.socket, "connect_ex"),
                                  (socket, "create_connection")):
            guard = patch.object(target, attribute, side_effect=AssertionError("network forbidden"))
            guard.start()
            cls.addClassCleanup(guard.stop)
        smoke.load_plugin_module()
        prefix = smoke.PLUGIN_MODULE_NAME + ".router."
        cls.post = importlib.import_module(prefix + "post_turn")
        cls.policy = importlib.import_module(prefix + "policy")
        cls.config_module = importlib.import_module(prefix + "config")

    def setUp(self):
        self.home = tempfile.TemporaryDirectory(prefix="pcr-memory-offline-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.home.cleanup)
        env = patch.dict(os.environ, {"HERMES_HOME": self.home.name, "KINLAYER_API_TOKEN": ""})
        env.start()
        self.addCleanup(env.stop)
        self.config = self.config_module.RouterConfig(
            enabled=True, dry_run=False,
            kinlayer=self.config_module.KinlayerConfig(enabled=True, base_url="http://offline.invalid"))
        self.config.kinlayer.enrichment.protected_self_entity_id = "person-self"
        self.post._MEMORY_CAPABILITY_CACHE.clear()
        self.transport = FakeMemoryTransport()
        self.kwargs = {"session_id": "synthetic-session", "turn_id": "synthetic-turn"}
