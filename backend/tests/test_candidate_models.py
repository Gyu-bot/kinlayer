from kinlayer_backend.models import Candidate, CandidateEvidence, ReconciliationAction


def test_candidate_models_define_required_columns_and_defaults() -> None:
    candidate_columns = Candidate.__table__.columns
    evidence_columns = CandidateEvidence.__table__.columns

    for column in [
        "candidate_type",
        "target_entity_id",
        "payload",
        "confidence",
        "sensitivity",
        "suggested_action",
        "status",
        "created_by",
        "resolved_at",
        "resolved_by",
        "resolution_note",
        "canonical_record_ref",
        "supersedes_candidate_id",
        "supersedes_record_ref",
    ]:
        assert column in candidate_columns

    for column in ["candidate_id", "episode_id", "excerpt", "confidence", "created_at"]:
        assert column in evidence_columns

    candidate = Candidate(
        candidate_type="observation",
        payload={"content": "candidate only"},
        confidence=0.5,
        created_by="ai_agent",
    )

    assert candidate.status is None
    assert candidate_columns["status"].default.arg == "pending"
    assert evidence_columns["candidate_id"].foreign_keys
    assert evidence_columns["episode_id"].foreign_keys


def test_reconciliation_action_model_is_a_bounded_control_ledger() -> None:
    columns = ReconciliationAction.__table__.columns

    for column in [
        "resolution_id",
        "action_type",
        "status",
        "request_fingerprint",
        "candidate_ids",
        "expected_candidates",
        "expected_entities",
        "source_entity_id",
        "target_entity_id",
        "primary_entity_id",
        "derived_candidate_ids",
        "confirmation_episode_id",
        "outcome_canonical_refs",
        "readback_summary",
        "error_code",
        "committed_at",
        "verified_at",
    ]:
        assert column in columns

    constraints = {constraint.name for constraint in ReconciliationAction.__table__.constraints}
    assert "uq_reconciliation_actions_resolution_id" in constraints
    forbidden = {
        "discord_payload",
        "question_text",
        "reply_text",
        "session_content",
        "prompt",
        "model_output",
    }
    assert forbidden.isdisjoint(columns.keys())
