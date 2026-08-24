from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from kinlayer_backend.models import CurationDecision, CurationRun


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

    def count_decisions(self, run_id: str, status: str) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(CurationDecision)
                .where(CurationDecision.run_id == run_id, CurationDecision.status == status)
            )
            or 0
        )
