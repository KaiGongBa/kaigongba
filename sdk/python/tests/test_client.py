from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import httpx
import pytest

from kaigongba_agent import AgentClientError, AgentState, ExternalAgentClient
from kaigongba_agent.cli import main
from kaigongba_agent.client import load_manifest


def response(request: httpx.Request, body: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body, request=request)


def manifest() -> dict[str, Any]:
    return {
        "protocol_version": "1.0",
        "agent": {
            "external_id": "agent-001",
            "name": "测试外接员工",
            "provider": "test-provider",
            "runtime": "python",
        },
        "capabilities": [
            {
                "external_id": "writing",
                "kind": "skill",
                "name": "写作",
            }
        ],
        "execution": {"mode": "external", "transports": ["polling"]},
        "disclosure": {"confirmed_by_user": True},
    }


def test_connect_runs_preflight_register_manifest_and_saves_private_state(tmp_path: Path) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        payload = json.loads(request.content or b"{}")
        if request.url.path.endswith("/preflight"):
            assert payload["pairing_code"] == "KGB-1234567890123456"
            return response(request, {"protocolVersion": "1.0"})
        if request.url.path.endswith("/register"):
            assert payload["external_agent_ref"] == "agent-001"
            return response(
                request,
                {
                    "connection": {"id": "connection-001"},
                    "credential": "kgb_agent_secret",
                    "scopes": ["manifest:write"],
                },
            )
        assert request.headers["Authorization"] == "Bearer kgb_agent_secret"
        assert payload["manifest"]["agent"]["name"] == "测试外接员工"
        return response(request, {"id": "manifest-001", "status": "pending_review"})

    http = httpx.Client(base_url="http://127.0.0.1:8000", transport=httpx.MockTransport(handler))
    client = ExternalAgentClient("http://127.0.0.1:8000", http_client=http)
    state, _, submitted = client.connect(
        "KGB-1234567890123456",
        manifest(),
        provider="test-provider",
        external_agent_ref="agent-001",
    )
    state_path = state.save(tmp_path / "private" / "state.json")

    assert paths == [
        "/api/external-agent-enrollments/preflight",
        "/api/external-agent-enrollments/register",
        "/api/external-agents/connection-001/manifest",
    ]
    assert submitted["id"] == "manifest-001"
    assert AgentState.load(state_path).credential == "kgb_agent_secret"
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600


def test_run_once_wraps_connection_test_events_and_result() -> None:
    requests: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}")
        requests.append((request.url.path, payload))
        path = request.url.path
        if path.endswith("/heartbeat"):
            return response(request, {"heartbeatId": "hb-1"})
        if path.endswith("/connection-tests/claim"):
            return response(
                request,
                {
                    "testId": "test-1",
                    "challenge": "challenge-1234567890",
                    "expected": {
                        "employee_name": "平台确认后的员工名",
                        "protocol_version": "1.0",
                        "enabled_capability_count": 2,
                    },
                },
            )
        if path.endswith("/external-agent-connection-tests/test-1/result"):
            return response(request, {"id": "test-1", "status": "passed"})
        if path.endswith("/tasks/claim"):
            return response(
                request,
                {
                    "task": {"id": "task-1", "goal": "生成摘要", "input": {"text": "abc"}},
                    "leaseToken": "lease-token-123456",
                },
            )
        if path.endswith("/events"):
            return response(request, {"id": f"event-{len(requests)}"})
        if path.endswith("/result"):
            return response(
                request, {"taskId": "task-1", "status": "succeeded", "receiptId": "receipt-1"}
            )
        raise AssertionError(path)

    state = AgentState(
        server="http://127.0.0.1:8000",
        connection_id="connection-001",
        credential="kgb_agent_secret",
        external_agent_ref="agent-001",
        provider="test",
        employee_name="测试员工",
        capability_count=1,
    )
    http = httpx.Client(base_url=state.server, transport=httpx.MockTransport(handler))
    client = ExternalAgentClient(state.server, state=state, http_client=http)

    result = client.run_once(
        lambda task, context: (
            context.progress(70, "处理中"),
            {"output": {"summary": task["input"]["text"]}},
        )[1]
    )

    assert result["connectionTest"]["status"] == "passed"
    assert result["taskReceipt"]["receiptId"] == "receipt-1"
    test_payload = next(
        payload for path, payload in requests if path.endswith("connection-tests/test-1/result")
    )
    assert test_payload["employee_name"] == "平台确认后的员工名"
    assert test_payload["enabled_capability_count"] == 2
    event_types = [payload["event_type"] for path, payload in requests if path.endswith("/events")]
    assert event_types == ["task.accepted", "task.started", "task.progress"]
    result_payload = next(
        payload for path, payload in requests if path.endswith("/result") and "outcome" in payload
    )
    assert result_payload["outcome"] == "succeeded"
    assert result_payload["output"] == {"summary": "abc"}


def test_transport_retries_with_same_idempotency_payload() -> None:
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content or b"{}"))
        if len(payloads) == 1:
            return response(request, {"detail": "temporary"}, status=503)
        return response(request, {"heartbeatId": "hb-1"})

    state = AgentState("http://127.0.0.1:8000", "c1", "token", "a1", "p1", "A", 1)
    http = httpx.Client(base_url=state.server, transport=httpx.MockTransport(handler))
    client = ExternalAgentClient(
        state.server,
        state=state,
        http_client=http,
        retry_delay_seconds=0,
    )
    client.heartbeat()
    assert len(payloads) == 2
    assert payloads[0]["idempotency_key"] == payloads[1]["idempotency_key"]


def test_rejects_empty_pairing_code_before_network() -> None:
    client = ExternalAgentClient("http://127.0.0.1:8000", http_client=httpx.Client())
    with pytest.raises(AgentClientError, match="配对码为空"):
        client.preflight("  ")


def test_manifest_requires_explicit_disclosure_confirmation(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    payload = manifest()
    payload["disclosure"]["confirmed_by_user"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AgentClientError, match="明确确认扫描范围"):
        load_manifest(path)


def test_cli_empty_pairing_code_is_safe_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest()), encoding="utf-8")
    exit_code = main(
        [
            "--server",
            "http://127.0.0.1:8000",
            "connect",
            "--pairing-code",
            "",
            "--manifest",
            str(path),
            "--external-agent-ref",
            "agent-001",
        ]
    )
    assert exit_code == 2
    assert "配对码为空" in capsys.readouterr().err
