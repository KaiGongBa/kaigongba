from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.disputes import router as disputes_router
from app.api.external_agents import agent_router, enterprise_router
from app.api.transactions import router as transactions_router
from app.db import get_session
from app.db.models import (
    ExternalAgentCredential,
    ExternalAgentTask,
    Organization,
    OrganizationMember,
    Tenant,
    User,
    utc_now,
)
from app.external_agents.local_simulator import LocalExternalAgentSimulator
from app.security.auth import create_access_token


@pytest.fixture
def simulator_app() -> tuple[TestClient, object, User]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    owner = User(
        id="simulator_owner",
        tenant_id="tenant_simulator",
        username="simulator_owner",
        password_hash="test",
    )
    with Session(engine) as db:
        db.add(Tenant(id="tenant_simulator", name="External Agent Simulator"))
        db.add(owner)
        db.add(
            Organization(
                id="org_simulator",
                tenant_id="tenant_simulator",
                slug="external-agent-simulator",
                name="外接 Agent 模拟企业",
                owner_user_id=owner.id,
            )
        )
        db.add(
            OrganizationMember(
                id="simulator_owner_membership",
                tenant_id="tenant_simulator",
                organization_id="org_simulator",
                user_id=owner.id,
                role="owner",
                roles_json=["owner"],
            )
        )
        db.commit()
        db.refresh(owner)

    app = FastAPI()
    app.include_router(enterprise_router)
    app.include_router(agent_router)
    app.include_router(transactions_router)
    app.include_router(disputes_router)

    def override_session() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), engine, owner


def test_local_simulator_full_protocol_replay_recovery_and_business_boundary(
    simulator_app: tuple[TestClient, object, User],
) -> None:
    client, engine, owner = simulator_app
    owner_headers = _user_auth(owner)
    enrollment = client.post(
        "/api/enterprise/external-agent-enrollments",
        json={
            "organization_id": "org_simulator",
            "idempotency_key": "simulator-enrollment-0001",
        },
        headers=owner_headers,
    )
    assert enrollment.status_code == 200, enrollment.text

    transport = _LostResponseClient(client)
    transport.lose_once("/api/external-agent-enrollments/register")
    simulator = LocalExternalAgentSimulator(
        transport,
        retry_delay_seconds=0,
        artifact_ref="object://external-agent-results/e2e-result.json",
    )
    enrolled = simulator.enroll(enrollment.json()["pairingCode"])
    assert transport.lost_responses == 1
    manifest = enrolled["manifest"]
    assert manifest["status"] == "pending_user_review"
    assert len(manifest["assets"]) == 1
    connection_id = simulator.state.connection_id

    review = client.post(
        f"/api/enterprise/external-agent-manifests/{manifest['id']}/review",
        json={
            "decision": "approved",
            "selected_asset_ids": [manifest["assets"][0]["id"]],
        },
        headers=owner_headers,
    )
    assert review.status_code == 200, review.text
    asset_id = review.json()["assets"][0]["id"]
    draft = client.post(
        f"/api/enterprise/external-agents/{connection_id}/import-draft",
        json={"idempotency_key": "simulator-draft-create-0001"},
        headers=owner_headers,
    )
    assert draft.status_code == 200, draft.text
    confirmed = client.post(
        f"/api/enterprise/external-agent-import-drafts/{draft.json()['id']}/confirm",
        json={"idempotency_key": "simulator-draft-confirm-0001"},
        headers=owner_headers,
    )
    assert confirmed.status_code == 200, confirmed.text
    connection_test = client.post(
        f"/api/enterprise/external-agents/{connection_id}/connection-tests",
        json={"idempotency_key": "simulator-connection-test-0001"},
        headers=owner_headers,
    )
    assert connection_test.status_code == 200, connection_test.text
    passed = simulator.answer_connection_test_once()
    assert passed is not None and passed["status"] == "passed"

    heartbeat_key = "simulator-heartbeat-replay-0001"
    heartbeat = simulator.heartbeat(idempotency_key=heartbeat_key)
    replayed_heartbeat = simulator.heartbeat(idempotency_key=heartbeat_key)
    assert replayed_heartbeat["heartbeatId"] == heartbeat["heartbeatId"]

    task = _create_task(
        client,
        owner_headers,
        connection_id,
        asset_id,
        idempotency_key="simulator-task-success-0001",
    )
    receipt = simulator.run_task_once(replay_result=True)
    assert receipt is not None
    assert receipt["status"] == "succeeded"
    completed = client.get(
        f"/api/enterprise/external-agent-tasks/{task['id']}", headers=owner_headers
    ).json()
    assert completed["artifactRefs"] == [
        {
            "ref": "object://external-agent-results/e2e-result.json",
            "name": "simulator-result.json",
            "media_type": "application/json",
        }
    ]
    result_events = [
        item for item in completed["events"] if item["eventType"] == "task.result_succeeded"
    ]
    assert len(result_events) == 1

    # A lost response after the server commits is retried with the same event
    # idempotency key and therefore cannot duplicate the progress/event stream.
    flaky_task = _create_task(
        client,
        owner_headers,
        connection_id,
        asset_id,
        idempotency_key="simulator-task-network-replay-0001",
    )
    transport.lose_once(f"/api/external-agent-tasks/{flaky_task['id']}/events")
    assert simulator.run_task_once() is not None
    assert transport.lost_responses == 2
    flaky_read = client.get(
        f"/api/enterprise/external-agent-tasks/{flaky_task['id']}", headers=owner_headers
    ).json()
    assert len([item for item in flaky_read["events"] if item["eventType"] == "task.accepted"]) == 1

    lease_task = _create_task(
        client,
        owner_headers,
        connection_id,
        asset_id,
        idempotency_key="simulator-task-lease-expiry-0001",
    )
    claimed = simulator.claim_task()
    assert claimed is not None and claimed["task"]["id"] == lease_task["id"]
    with Session(engine) as db:
        row = db.get(ExternalAgentTask, lease_task["id"])
        assert row is not None
        row.lease_expires_at = utc_now() - timedelta(seconds=1)
        db.add(row)
        db.commit()
    reconciled = client.get(
        f"/api/enterprise/external-agent-tasks/{lease_task['id']}", headers=owner_headers
    ).json()
    assert reconciled["status"] == "queued"
    assert any(item["eventType"] == "task.lease_expired" for item in reconciled["events"])
    with Session(engine) as db:
        row = db.get(ExternalAgentTask, lease_task["id"])
        assert row is not None
        row.next_retry_at = utc_now() - timedelta(seconds=1)
        db.add(row)
        db.commit()
    assert simulator.run_task_once()["status"] == "succeeded"

    timeout_task = _create_task(
        client,
        owner_headers,
        connection_id,
        asset_id,
        idempotency_key="simulator-task-timeout-0001",
    )
    with Session(engine) as db:
        row = db.get(ExternalAgentTask, timeout_task["id"])
        assert row is not None
        row.timeout_at = utc_now() - timedelta(seconds=1)
        db.add(row)
        db.commit()
    expired = client.get(
        f"/api/enterprise/external-agent-tasks/{timeout_task['id']}", headers=owner_headers
    ).json()
    assert expired["status"] == "expired"
    retried = client.post(
        f"/api/enterprise/external-agent-tasks/{timeout_task['id']}/retry",
        json={"idempotency_key": "simulator-timeout-manual-retry-0001"},
        headers=owner_headers,
    )
    assert retried.status_code == 200, retried.text
    assert simulator.run_task_once()["status"] == "succeeded"

    # Agent credentials are not user tokens and cannot invoke transaction or
    # dispute authority, including acceptance, payment, refund, or release paths.
    agent_headers = _agent_auth(simulator.state.credential)
    denied_requests = [
        client.post(
            "/api/transactions/deliverables/not-owned/acceptance",
            json={
                "organization_id": "org_simulator",
                "action": "accept",
                "comments": "外接 Agent 不能验收",
                "idempotency_key": "agent-forbidden-acceptance-0001",
            },
            headers=agent_headers,
        ),
        client.post(
            "/api/transactions/payment-orders/not-owned/demo-simulate",
            json={
                "organization_id": "org_simulator",
                "result": "success",
                "confirmation_code": "0000",
                "callback_id": "agent-forbidden-payment-0001",
                "acknowledged_demo": True,
            },
            headers=agent_headers,
        ),
        client.post(
            "/api/disputes/cases/not-owned/decisions",
            json={
                "outcome": "split",
                "refund_amount": "1",
                "release_amount": "1",
                "rationale": "外接 Agent 不能作出退款或放款裁决，该请求必须被拒绝。",
                "idempotency_key": "agent-forbidden-settlement-0001",
            },
            headers=agent_headers,
        ),
    ]
    assert [response.status_code for response in denied_requests] == [401, 401, 401]


def test_artifact_scope_is_required_for_events_and_results(
    simulator_app: tuple[TestClient, object, User],
) -> None:
    client, engine, owner = simulator_app
    simulator, asset_id = _ready_simulator(client, owner)
    owner_headers = _user_auth(owner)
    task = _create_task(
        client,
        owner_headers,
        simulator.state.connection_id,
        asset_id,
        idempotency_key="simulator-artifact-scope-task-0001",
    )
    claimed = simulator.claim_task()
    assert claimed is not None
    with Session(engine) as db:
        credential = db.exec(
            select(ExternalAgentCredential).where(
                ExternalAgentCredential.connection_id == simulator.state.connection_id,
                ExternalAgentCredential.status == "active",
            )
        ).one()
        credential.scopes_json = [scope for scope in credential.scopes_json if scope != "artifacts:write"]
        db.add(credential)
        db.commit()
    common = {
        "lease_owner": simulator.lease_owner,
        "lease_token": claimed["leaseToken"],
    }
    artifact = {
        "ref": "object://external-agent-results/forbidden.json",
        "name": "forbidden.json",
        "media_type": "application/json",
    }
    event = client.post(
        f"/api/external-agent-tasks/{task['id']}/events",
        json={
            **common,
            "idempotency_key": "artifact-scope-event-denied-0001",
            "event_type": "task.artifact_created",
            "summary": "尝试越权回传文件",
            "payload": {"artifact": artifact},
        },
        headers=_agent_auth(simulator.state.credential),
    )
    result = client.post(
        f"/api/external-agent-tasks/{task['id']}/result",
        json={
            **common,
            "idempotency_key": "artifact-scope-result-denied-0001",
            "outcome": "succeeded",
            "output": {"summary": "无文件权限"},
            "artifact_refs": [artifact],
        },
        headers=_agent_auth(simulator.state.credential),
    )
    assert event.status_code == 403
    assert result.status_code == 403
    assert event.json()["detail"] == "外部 Agent 凭据缺少权限：artifacts:write"
    assert result.json()["detail"] == event.json()["detail"]
    progress = client.post(
        f"/api/external-agent-tasks/{task['id']}/events",
        json={
            **common,
            "idempotency_key": "artifact-scope-progress-allowed-0001",
            "event_type": "task.progress",
            "summary": "无文件回传的普通进度事件",
            "payload": {"progress": 100},
        },
        headers=_agent_auth(simulator.state.credential),
    )
    plain_result = client.post(
        f"/api/external-agent-tasks/{task['id']}/result",
        json={
            **common,
            "idempotency_key": "artifact-scope-plain-result-allowed-0001",
            "outcome": "succeeded",
            "output": {"summary": "纯文本结果仍可回传"},
            "artifact_refs": [],
        },
        headers=_agent_auth(simulator.state.credential),
    )
    assert progress.status_code == 200, progress.text
    assert plain_result.status_code == 200, plain_result.text
    assert plain_result.json()["status"] == "succeeded"


def _ready_simulator(
    client: TestClient,
    owner: User,
) -> tuple[LocalExternalAgentSimulator, str]:
    owner_headers = _user_auth(owner)
    enrollment = client.post(
        "/api/enterprise/external-agent-enrollments",
        json={
            "organization_id": "org_simulator",
            "idempotency_key": "scope-enrollment-0001",
        },
        headers=owner_headers,
    ).json()
    simulator = LocalExternalAgentSimulator(client, retry_delay_seconds=0)
    enrolled = simulator.enroll(
        enrollment["pairingCode"], external_agent_ref="scope-test-agent"
    )
    manifest = enrolled["manifest"]
    approved = client.post(
        f"/api/enterprise/external-agent-manifests/{manifest['id']}/review",
        json={
            "decision": "approved",
            "selected_asset_ids": [manifest["assets"][0]["id"]],
        },
        headers=owner_headers,
    ).json()
    draft = client.post(
        f"/api/enterprise/external-agents/{simulator.state.connection_id}/import-draft",
        json={"idempotency_key": "scope-draft-create-0001"},
        headers=owner_headers,
    ).json()
    client.post(
        f"/api/enterprise/external-agent-import-drafts/{draft['id']}/confirm",
        json={"idempotency_key": "scope-draft-confirm-0001"},
        headers=owner_headers,
    )
    client.post(
        f"/api/enterprise/external-agents/{simulator.state.connection_id}/connection-tests",
        json={"idempotency_key": "scope-connection-test-0001"},
        headers=owner_headers,
    )
    assert simulator.answer_connection_test_once()["status"] == "passed"
    return simulator, approved["assets"][0]["id"]


def _create_task(
    client: TestClient,
    owner_headers: dict[str, str],
    connection_id: str,
    asset_id: str,
    *,
    idempotency_key: str,
) -> dict[str, object]:
    response = client.post(
        "/api/enterprise/external-agent-tasks",
        json={
            "connection_id": connection_id,
            "capability_asset_id": asset_id,
            "goal": "执行外接 Agent 端到端验收任务",
            "input": {"document": "acceptance-input"},
            "permission_grants": ["filesystem:write:output"],
            "idempotency_key": idempotency_key,
            "timeout_seconds": 300,
            "max_attempts": 2,
        },
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


class _LostResponseClient:
    def __init__(self, delegate: TestClient) -> None:
        self.delegate = delegate
        self._paths: set[str] = set()
        self.lost_responses = 0

    def lose_once(self, path: str) -> None:
        self._paths.add(path)

    def request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> object:
        response = self.delegate.request(method, url, json=json, headers=headers)
        if url in self._paths:
            self._paths.remove(url)
            self.lost_responses += 1
            raise httpx.ConnectError(
                "simulated connection loss after server commit",
                request=httpx.Request(method, f"http://testserver{url}"),
            )
        return response


def _user_auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def _agent_auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
