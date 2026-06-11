from sqlalchemy import Select, func, select

from kinlayer_backend.models import Candidate, CandidateEvidence


def page(session, statement: Select, limit: int, offset: int):
    total = session.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = session.execute(statement.limit(limit).offset(offset)).scalars().unique().all()
    return items, total


class CandidateRepository:
    def __init__(self, session):
        self.session = session

    def add_candidate(self, payload: dict, evidence: list[dict]) -> Candidate:
        candidate = Candidate(**payload)
        self.session.add(candidate)
        self.session.flush()
        for item in evidence:
            self.session.add(CandidateEvidence(candidate_id=candidate.id, **item))
        self.session.commit()
        self.session.refresh(candidate)
        return candidate

    def get_candidate(self, candidate_id: str) -> Candidate | None:
        return self.session.get(Candidate, candidate_id)

    def list_candidates(
        self,
        status: str | None = None,
        candidate_type: str | None = None,
        target_entity_id: str | None = None,
        sensitivity: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        statement = select(Candidate)
        filters = []
        if status:
            filters.append(Candidate.status == status)
        if candidate_type:
            filters.append(Candidate.candidate_type == candidate_type)
        if target_entity_id:
            filters.append(Candidate.target_entity_id == target_entity_id)
        if sensitivity:
            filters.append(Candidate.sensitivity == sensitivity)
        if filters:
            statement = statement.where(*filters)
        return page(self.session, statement.order_by(Candidate.created_at.desc()), limit, offset)

    def commit_refresh(self, candidate: Candidate) -> Candidate:
        self.session.commit()
        self.session.refresh(candidate)
        return candidate
