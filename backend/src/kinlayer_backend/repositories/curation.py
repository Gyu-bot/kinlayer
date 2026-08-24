from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from kinlayer_backend.models import Candidate, CandidateEvidence, CurationDecision, CurationRun


class CurationRepository:
    def __init__(self, session):
        self.session = session

    def add_run(self, run_payload: dict, decision_payloads: list[dict]) -> CurationRun:
        run = CurationRun(**run_payload)
        self.session.add(run)
        self.session.flush()
        run.decisions = [CurationDecision(run_id=run.id, **item) for item in decision_payloads]
        self.session.flush()
        return run

    def get_run(self, run_id: str) -> CurationRun | None:
        return self.session.scalar(
            select(CurationRun)
            .options(selectinload(CurationRun.decisions))
            .where(CurationRun.id == run_id)
        )

    def list_runs(
        self,
        mode: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ):
        statement = select(CurationRun)
        if mode:
            statement = statement.where(CurationRun.mode == mode)
        if status:
            statement = statement.where(CurationRun.status == status)
        total = self.session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        items = self.session.scalars(
            statement.order_by(CurationRun.started_at.desc(), CurationRun.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return items, total

    def get_decision_by_idempotency_key(self, key: str) -> CurationDecision | None:
        return self.session.scalar(
            select(CurationDecision).where(CurationDecision.idempotency_key == key)
        )

    def get_decision(self, decision_id: str, *, for_update: bool = False) -> CurationDecision | None:
        statement = select(CurationDecision).where(CurationDecision.id == decision_id)
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def pending_candidates(
        self,
        *,
        as_of: datetime,
        created_after: datetime,
        cursor_at: datetime | None,
        cursor_id: str | None,
        upper_at: datetime | None,
        upper_id: str | None,
        limit: int,
    ) -> list[Candidate]:
        statement = (
            select(Candidate)
            .options(
                selectinload(Candidate.evidence).joinedload(CandidateEvidence.episode)
            )
            .where(
                Candidate.status == "pending",
                Candidate.created_at >= created_after,
                Candidate.created_at <= as_of,
            )
        )
        if cursor_at is not None and cursor_id is not None:
            statement = statement.where(
                or_(
                    Candidate.created_at > cursor_at,
                    and_(Candidate.created_at == cursor_at, Candidate.id > cursor_id),
                )
            )
        if upper_at is not None and upper_id is not None:
            statement = statement.where(
                or_(
                    Candidate.created_at < upper_at,
                    and_(Candidate.created_at == upper_at, Candidate.id <= upper_id),
                )
            )
        return self.session.scalars(
            statement.order_by(Candidate.created_at, Candidate.id).limit(limit)
        ).all()

    def candidates_by_ids(self, candidate_ids: list[str]) -> list[Candidate]:
        if not candidate_ids:
            return []
        return self.session.scalars(
            select(Candidate)
            .options(
                selectinload(Candidate.evidence).joinedload(CandidateEvidence.episode)
            )
            .where(Candidate.id.in_(candidate_ids))
        ).all()

    def lock_candidates(self, candidate_ids: list[str]) -> list[Candidate]:
        if not candidate_ids:
            return []
        return self.session.scalars(
            select(Candidate)
            .options(
                selectinload(Candidate.evidence).joinedload(CandidateEvidence.episode)
            )
            .where(Candidate.id.in_(candidate_ids))
            .order_by(Candidate.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()

    def count_decisions(self, run_id: str, status: str) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(CurationDecision)
                .where(CurationDecision.run_id == run_id, CurationDecision.status == status)
            )
            or 0
        )
