from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import TransactionOutboxEvent
from app.transaction import outbox_worker


class _SuccessfulGateway:
    def __init__(self) -> None:
        self.requests = []

    def bind_marketplace_installation(self, request):
        self.requests.append(request)


class _FailingGateway:
    def bind_marketplace_installation(self, request):
        raise RuntimeError("StaffDeck unavailable")


def test_staffdeck_outbox_publishes_and_keeps_failures_pending(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    event = _event("outbox_success")
    failed = _event("outbox_failure")
    with Session(engine) as db:
        db.add(event)
        db.add(failed)
        db.commit()

        gateway = _SuccessfulGateway()
        monkeypatch.setattr(outbox_worker, "get_staffdeck_gateway", lambda _db: gateway)
        assert outbox_worker.publish_staffdeck_outbox_once(db, limit=1) == 1
        db.refresh(event)
        assert event.status == "published"
        assert event.published_at is not None
        assert gateway.requests[0].installation_id == "installation_outbox_success"

        monkeypatch.setattr(
            outbox_worker,
            "get_staffdeck_gateway",
            lambda _db: _FailingGateway(),
        )
        assert outbox_worker.publish_staffdeck_outbox_once(db) == 0
        db.refresh(failed)
        assert failed.status == "pending"
        assert failed.published_at is None


def _event(suffix: str) -> TransactionOutboxEvent:
    return TransactionOutboxEvent(
        id=f"txevent_{suffix}",
        tenant_id="tenant_outbox",
        aggregate_type="marketplace_skill_installation",
        aggregate_id=f"installation_{suffix}",
        event_type=outbox_worker.STAFFDECK_BIND_EVENT,
        idempotency_key=f"staffdeck:{suffix}",
        payload_json={
            "tenant_id": "tenant_outbox",
            "organization_id": "org_outbox",
            "agent_id": "agent_outbox",
            "installation_id": f"installation_{suffix}",
            "marketplace_skill_id": "skill_outbox",
            "marketplace_skill_version_id": "skill_version_outbox",
        },
    )
