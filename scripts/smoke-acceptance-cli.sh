#!/usr/bin/env bash
set -euo pipefail

API_URL="${KINLAYER_API_URL:-http://127.0.0.1:8765}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

fixture_json="$TMP_DIR/fixtures.json"
person_json="$TMP_DIR/person.json"
candidate_json="$TMP_DIR/candidate.json"
invalid_candidate_json="$TMP_DIR/candidate-invalid-edge.json"
candidate_edit_json="$TMP_DIR/candidate-edit.json"
second_candidate_json="$TMP_DIR/candidate-second.json"
correction_json="$TMP_DIR/correction.json"
correction_result_json="$TMP_DIR/correction-result.json"

echo "== Load acceptance fixtures =="
python3 scripts/load-acceptance-fixtures.py --api-url "$API_URL" > "$fixture_json"

read_fixture() {
  python3 -c "import json,sys; data=json.load(open(sys.argv[1])); cur=data; [cur := cur[p] for p in sys.argv[2].split('.')]; print(cur)" "$fixture_json" "$1"
}

self_id="$(read_fixture self_id)"
minji_id="$(read_fixture people.minji)"
episode_id="$(read_fixture episodes.pending_candidate)"

echo "== CLI status and init =="
uv run kinlayer status --json > "$TMP_DIR/status.json"
uv run kinlayer init --self-name "Acceptance CLI Self" --json > "$TMP_DIR/init.json"

echo "== CLI people =="
uv run kinlayer person create \
  --name "Acceptance CLI Person $(date +%s)" \
  --alias "CLI Fixture" \
  --note "Created by CLI acceptance smoke." \
  --json > "$person_json"
cli_person_id="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['entity']['id'])" "$person_json")"
uv run kinlayer person list --query "Acceptance CLI" --json > "$TMP_DIR/person-list.json"
uv run kinlayer person show "$cli_person_id" --json > "$TMP_DIR/person-show.json"

echo "== CLI candidates =="
python3 - "$candidate_json" "$cli_person_id" "$self_id" "$episode_id" <<'PY'
import json
import sys

path, person_id, self_id, episode_id = sys.argv[1:5]
payload = {
    "candidate_type": "observation",
    "target_entity_id": person_id,
    "payload": {
        "subject_entity_id": person_id,
        "related_entity_ids": [self_id],
        "observation_type": "recent_interaction",
        "content": "CLI smoke accepted observation.",
        "claim_type": "fact",
        "ai_use_policy": "cautious_use",
        "sensitivity": "medium",
    },
    "evidence": [
        {"episode_id": episode_id, "excerpt": "CLI smoke accepted observation.", "confidence": 0.9}
    ],
    "confidence": 0.9,
    "sensitivity": "medium",
    "suggested_action": "review",
    "created_by": "ai_agent",
}
open(path, "w").write(json.dumps(payload))
PY
uv run kinlayer candidate submit "$candidate_json" --json > "$TMP_DIR/candidate-submit.json"
candidate_id="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['id'])" "$TMP_DIR/candidate-submit.json")"
uv run kinlayer candidate list --status pending --json > "$TMP_DIR/candidate-list.json"
uv run kinlayer candidate show "$candidate_id" --json > "$TMP_DIR/candidate-show.json"
uv run kinlayer candidate accept "$candidate_id" --json > "$TMP_DIR/candidate-accept.json"
accepted_ref="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['canonical_record_ref'])" "$TMP_DIR/candidate-accept.json")"

python3 - "$invalid_candidate_json" "$minji_id" "$self_id" <<'PY'
import json
import sys

path, person_id, self_id = sys.argv[1:4]
payload = {
    "candidate_type": "relationship_edge",
    "target_entity_id": person_id,
    "payload": {
        "from_entity_id": self_id,
        "to_entity_id": person_id,
        "relation_type": "reply_strategy",
        "claim_text": "CLI smoke invalid relationship edge.",
        "claim_type": "fact",
    },
    "confidence": 0.5,
    "sensitivity": "medium",
    "suggested_action": "review",
    "created_by": "ai_agent",
}
open(path, "w").write(json.dumps(payload))
PY
if uv run kinlayer candidate submit "$invalid_candidate_json" --json > "$TMP_DIR/candidate-invalid-edge.out" 2> "$TMP_DIR/candidate-invalid-edge.err"; then
  echo "Invalid relationship_edge candidate unexpectedly succeeded." >&2
  exit 1
fi

python3 - "$second_candidate_json" "$minji_id" "$self_id" "$episode_id" <<'PY'
import json
import sys

path, person_id, self_id, episode_id = sys.argv[1:5]
payload = {
    "candidate_type": "observation",
    "target_entity_id": person_id,
    "payload": {
        "subject_entity_id": person_id,
        "related_entity_ids": [self_id],
        "observation_type": "recent_interaction",
        "content": "CLI smoke edit-accept draft.",
        "claim_type": "fact",
        "ai_use_policy": "cautious_use",
        "sensitivity": "medium",
    },
    "evidence": [
        {"episode_id": episode_id, "excerpt": "CLI smoke edit-accept draft.", "confidence": 0.9}
    ],
    "confidence": 0.9,
    "sensitivity": "medium",
    "suggested_action": "review",
    "created_by": "ai_agent",
}
open(path, "w").write(json.dumps(payload))
PY
uv run kinlayer candidate submit "$second_candidate_json" --json > "$TMP_DIR/candidate-second-submit.json"
second_candidate_id="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['id'])" "$TMP_DIR/candidate-second-submit.json")"
python3 - "$candidate_edit_json" "$minji_id" "$self_id" <<'PY'
import json
import sys

path, person_id, self_id = sys.argv[1:4]
payload = {
    "subject_entity_id": person_id,
    "related_entity_ids": [self_id],
    "observation_type": "recent_interaction",
    "content": "CLI smoke edited accepted observation.",
    "claim_type": "fact",
    "ai_use_policy": "cautious_use",
    "sensitivity": "medium",
}
open(path, "w").write(json.dumps(payload))
PY
uv run kinlayer candidate edit-accept "$second_candidate_id" "$candidate_edit_json" --json > "$TMP_DIR/candidate-edit-accept.json"

echo "== CLI correction =="
python3 - "$correction_json" "$accepted_ref" "$cli_person_id" "$self_id" <<'PY'
import json
import sys

path, old_ref, person_id, self_id = sys.argv[1:5]
payload = {
    "old_record_ref": old_ref,
    "new_record": {
        "record_type": "observations",
        "payload": {
            "subject_entity_id": person_id,
            "related_entity_ids": [self_id],
            "observation_type": "communication_preference",
            "content": "CLI smoke corrected canonical observation.",
            "claim_type": "fact",
            "confidence": 1,
            "sensitivity": "medium",
            "ai_use_policy": "cautious_use",
            "recency_weight": 1,
        },
    },
    "correction_source": {
        "source_type": "agent_conversation",
        "user_explicit": True,
        "excerpt": "Correction from CLI smoke.",
        "source_ref": "cli-smoke-correction",
    },
    "created_by": "ai_agent",
}
open(path, "w").write(json.dumps(payload))
PY
uv run kinlayer correction apply "$correction_json" --json > "$correction_result_json"

echo "== CLI agent write operations =="
uv run kinlayer agent-operations list --json > "$TMP_DIR/agent-operations-list.json"
uv run kinlayer agent-operations export --limit 50 > "$TMP_DIR/agent-operations-export.jsonl"
uv run kinlayer ontology edge-diagnostics --json > "$TMP_DIR/edge-diagnostics.json"

echo "== CLI context, graph, and embeddings =="
uv run kinlayer retrieve "민지 한국어 요약 회의 확인" --entity-hint "$minji_id" --json > "$TMP_DIR/retrieve.json"
uv run kinlayer context pack "민지 한국어 요약 회의 확인" --focal-entity-id "$self_id" --debug --json > "$TMP_DIR/context-pack.json"
uv run kinlayer context-card "$minji_id" --json > "$TMP_DIR/context-card.json"
uv run kinlayer debug retrieval "민지 한국어 요약 회의 확인" --entity-hint "$minji_id" --json > "$TMP_DIR/debug-retrieval.json"
uv run kinlayer graph ego "$self_id" --json > "$TMP_DIR/graph.json"
uv run kinlayer embedding status --json > "$TMP_DIR/embedding-status.json"
uv run kinlayer embedding backfill --limit 10 --json > "$TMP_DIR/embedding-backfill.json"

python3 - "$TMP_DIR" "$minji_id" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
minji_id = sys.argv[2]

assert json.load(open(root / "status.json"))["api"] == "ok"
assert json.load(open(root / "person-show.json"))["entity"]["display_name"].startswith("Acceptance CLI Person")
assert json.load(open(root / "candidate-accept.json"))["canonical_record_ref"].startswith("observations:")
assert json.load(open(root / "candidate-edit-accept.json"))["status"] == "edited_accepted"
assert json.load(open(root / "correction-result.json"))["new_record_ref"].startswith("observations:")
assert json.load(open(root / "agent-operations-list.json"))["total"] >= 1
assert any(
    item["operation_type"] == "candidate_submit"
    and item["result_status"] == "rejected"
    and item["request_summary"].get("relation_type") == "reply_strategy"
    for item in json.load(open(root / "agent-operations-list.json"))["items"]
)
first_export_line = open(root / "agent-operations-export.jsonl").readline()
assert json.loads(first_export_line)["schema_version"] == "agent_write_operations.v1"
assert "relation_types" in json.load(open(root / "edge-diagnostics.json"))
assert any(item["entity_id"] == minji_id for item in json.load(open(root / "retrieve.json"))["matched_entities"])
assert "context_pack" in json.load(open(root / "context-pack.json"))
assert json.load(open(root / "context-card.json"))["entity"]["id"] == minji_id
assert "debug" in json.load(open(root / "debug-retrieval.json"))
assert len(json.load(open(root / "graph.json"))["nodes"]) >= 3
assert "status" in json.load(open(root / "embedding-status.json"))
assert "processed" in json.load(open(root / "embedding-backfill.json"))
PY

if [[ -n "${KINLAYER_API_TOKEN:-}" ]] && grep -R --fixed-strings "${KINLAYER_API_TOKEN}" "$TMP_DIR"; then
  echo "Token value leaked into CLI smoke output." >&2
  exit 1
fi

echo "Acceptance CLI smoke passed."
