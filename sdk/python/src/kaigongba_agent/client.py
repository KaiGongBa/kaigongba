from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlparse
from uuid import uuid4

import httpx

JSONDict = dict[str, Any]
TaskHandler = Callable[[JSONDict, "TaskContext"], Mapping[str, Any] | None]


class AgentClientError(RuntimeError):
    """Base error raised by the connector."""


class AgentAPIError(AgentClientError):
    def __init__(self, status_code: int, detail: str, *, path: str) -> None:
        super().__init__(f"HTTP {status_code} {path}: {detail}")
        self.status_code = status_code
        self.detail = detail
        self.path = path


@dataclass(slots=True)
class AgentState:
    server: str
    connection_id: str
    credential: str
    external_agent_ref: str
    provider: str
    employee_name: str
    capability_count: int
    protocol_version: str = "1.0"

    @classmethod
    def load(cls, path: str | Path) -> AgentState:
        state_path = Path(path)
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AgentClientError(f"无法读取接入状态文件：{state_path}") from exc
        if not isinstance(payload, dict):
            raise AgentClientError("接入状态文件必须是 JSON object")
        return cls(**payload)

    def save(self, path: str | Path) -> Path:
        state_path = Path(path)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = state_path.with_suffix(f"{state_path.suffix}.tmp")
        temporary.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, state_path)
        state_path.chmod(0o600)
        return state_path


def validate_server(server: str) -> str:
    normalized = server.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgentClientError("平台地址必须是完整的 http(s) URL")
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https" and hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise AgentClientError("非本机平台必须使用 HTTPS")
    return normalized


def load_manifest(path: str | Path) -> JSONDict:
    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentClientError(f"无法读取 Manifest：{manifest_path}") from exc
    if not isinstance(payload, dict):
        raise AgentClientError("Manifest 必须是 JSON object")
    required = {"protocol_version", "agent", "capabilities", "execution", "disclosure"}
    missing = sorted(required - payload.keys())
    if missing:
        raise AgentClientError(f"Manifest 缺少字段：{', '.join(missing)}")
    if payload.get("protocol_version") != "1.0":
        raise AgentClientError("当前接入助手只支持 Manifest 1.0")
    disclosure = payload.get("disclosure")
    if not isinstance(disclosure, dict) or disclosure.get("confirmed_by_user") is not True:
        raise AgentClientError("提交前必须在 disclosure.confirmed_by_user 中明确确认扫描范围")
    return payload


class ExternalAgentClient:
    """HTTP client for the public 开工吧 external-Agent protocol.

    It never calls enterprise-only review, acceptance, payment, refund or settlement APIs.
    """

    def __init__(
        self,
        server: str,
        *,
        state: AgentState | None = None,
        credential: str | None = None,
        http_client: httpx.Client | None = None,
        timeout_seconds: float = 20.0,
        max_attempts: int = 3,
        retry_delay_seconds: float = 0.2,
        lease_owner: str = "kaigongba-python-agent",
    ) -> None:
        self.server = validate_server(server)
        if state and validate_server(state.server) != self.server:
            raise AgentClientError("状态文件的平台地址与当前 --server 不一致")
        self.state = state
        self.credential = credential or (state.credential if state else None)
        self.lease_owner = lease_owner
        self.max_attempts = max(1, max_attempts)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
        self._owns_client = http_client is None
        self.http = http_client or httpx.Client(
            base_url=self.server,
            timeout=timeout_seconds,
            trust_env=False,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self.http.close()

    def preflight(self, pairing_code: str) -> JSONDict:
        code = self._validate_pairing_code(pairing_code)
        return self._request(
            "POST",
            "/api/external-agent-enrollments/preflight",
            payload={"pairing_code": code},
            authenticated=False,
        )

    def register(
        self,
        pairing_code: str,
        *,
        provider: str,
        external_agent_ref: str,
        runtime_type: str = "local",
        transport: str = "polling",
        endpoint: str = "",
        metadata: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> JSONDict:
        code = self._validate_pairing_code(pairing_code)
        response = self._request(
            "POST",
            "/api/external-agent-enrollments/register",
            payload={
                "pairing_code": code,
                "registration_idempotency_key": idempotency_key or self.key("register"),
                "provider": provider,
                "runtime_type": runtime_type,
                "transport": transport,
                "external_agent_ref": external_agent_ref,
                "endpoint": endpoint,
                "protocol_version": "1.0",
                "metadata": dict(metadata or {}),
            },
            authenticated=False,
        )
        credential = response.get("credential")
        connection = response.get("connection")
        if not isinstance(credential, str) or not isinstance(connection, dict):
            raise AgentClientError("平台登记响应缺少 credential 或 connection")
        self.credential = credential
        return response

    def connect(
        self,
        pairing_code: str,
        manifest: Mapping[str, Any],
        *,
        provider: str,
        external_agent_ref: str,
        runtime_type: str = "local",
        transport: str = "polling",
        endpoint: str = "",
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[AgentState, JSONDict, JSONDict]:
        self.preflight(pairing_code)
        registered = self.register(
            pairing_code,
            provider=provider,
            external_agent_ref=external_agent_ref,
            runtime_type=runtime_type,
            transport=transport,
            endpoint=endpoint,
            metadata={"connector_version": "kaigongba-python/0.1.0", **dict(metadata or {})},
        )
        connection = registered["connection"]
        connection_id = str(connection["id"])
        agent = manifest.get("agent", {})
        capabilities = manifest.get("capabilities", [])
        state = AgentState(
            server=self.server,
            connection_id=connection_id,
            credential=str(registered["credential"]),
            external_agent_ref=external_agent_ref,
            provider=provider,
            employee_name=str(agent.get("name") or external_agent_ref),
            capability_count=len(capabilities) if isinstance(capabilities, list) else 0,
        )
        self.state = state
        submitted = self.submit_manifest(manifest)
        return state, registered, submitted

    def self_info(self) -> JSONDict:
        return self._request("GET", "/api/external-agents/me")

    def submit_manifest(
        self,
        manifest: Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> JSONDict:
        state = self._require_state()
        return self._request(
            "POST",
            f"/api/external-agents/{state.connection_id}/manifest",
            payload={
                "idempotency_key": idempotency_key or self.key("manifest"),
                "manifest": dict(manifest),
            },
        )

    def heartbeat(
        self,
        *,
        status: str = "online",
        running_task_count: int = 0,
        queue_depth: int = 0,
        latency_ms: int | None = None,
        capabilities_digest: str = "",
        diagnostics: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> JSONDict:
        state = self._require_state()
        return self._request(
            "POST",
            f"/api/external-agents/{state.connection_id}/heartbeat",
            payload={
                "idempotency_key": idempotency_key or self.key("heartbeat"),
                "status": status,
                "protocol_version": state.protocol_version,
                "runtime_version": "kaigongba-python/0.1.0",
                "running_task_count": running_task_count,
                "queue_depth": queue_depth,
                "latency_ms": latency_ms,
                "capabilities_digest": capabilities_digest,
                "diagnostics": dict(diagnostics or {}),
            },
        )

    def answer_connection_test(self) -> JSONDict | None:
        state = self._require_state()
        claimed = self._request(
            "POST",
            f"/api/external-agents/{state.connection_id}/connection-tests/claim",
            payload={"lease_owner": self.lease_owner},
            allow_empty=True,
        )
        if not claimed:
            return None
        expected = claimed.get("expected")
        expected = expected if isinstance(expected, dict) else {}
        return self._request(
            "POST",
            f"/api/external-agent-connection-tests/{claimed['testId']}/result",
            payload={
                "challenge": claimed["challenge"],
                "employee_name": str(expected.get("employee_name") or state.employee_name),
                "protocol_version": str(expected.get("protocol_version") or state.protocol_version),
                "enabled_capability_count": int(
                    expected.get("enabled_capability_count", state.capability_count)
                ),
            },
        )

    def claim_task(self, *, lease_seconds: int = 120) -> JSONDict | None:
        state = self._require_state()
        claimed = self._request(
            "POST",
            f"/api/external-agents/{state.connection_id}/tasks/claim",
            payload={
                "lease_owner": self.lease_owner,
                "max_tasks": 1,
                "lease_seconds": lease_seconds,
            },
        )
        return claimed if claimed.get("task") is not None else None

    def renew_lease(
        self,
        task_id: str,
        lease_token: str,
        *,
        lease_seconds: int = 120,
    ) -> JSONDict:
        return self._request(
            "POST",
            f"/api/external-agent-tasks/{task_id}/lease/renew",
            payload={
                "lease_owner": self.lease_owner,
                "lease_token": lease_token,
                "lease_seconds": lease_seconds,
            },
        )

    def send_event(
        self,
        task_id: str,
        lease_token: str,
        event_type: str,
        summary: str,
        *,
        payload: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> JSONDict:
        return self._request(
            "POST",
            f"/api/external-agent-tasks/{task_id}/events",
            payload={
                "lease_owner": self.lease_owner,
                "lease_token": lease_token,
                "idempotency_key": idempotency_key or self.key(f"event-{event_type}"),
                "event_type": event_type,
                "summary": summary,
                "payload": dict(payload or {}),
            },
        )

    def submit_result(
        self,
        task_id: str,
        lease_token: str,
        *,
        outcome: str,
        output: Mapping[str, Any] | None = None,
        error: Mapping[str, Any] | None = None,
        artifact_refs: list[Mapping[str, Any]] | None = None,
        idempotency_key: str | None = None,
    ) -> JSONDict:
        return self._request(
            "POST",
            f"/api/external-agent-tasks/{task_id}/result",
            payload={
                "lease_owner": self.lease_owner,
                "lease_token": lease_token,
                "idempotency_key": idempotency_key or self.key("result"),
                "outcome": outcome,
                "output": dict(output or {}),
                "error": dict(error or {}),
                "artifact_refs": [dict(item) for item in artifact_refs or []],
            },
        )

    def execute_claimed_task(self, claimed: JSONDict, handler: TaskHandler) -> JSONDict:
        task = claimed.get("task")
        lease_token = claimed.get("leaseToken")
        if not isinstance(task, dict) or not isinstance(lease_token, str):
            raise AgentClientError("任务领取响应缺少 task 或 leaseToken")
        task_id = str(task["id"])
        context = TaskContext(self, task_id, lease_token)
        context.event("task.accepted", "外接 Agent 已接收任务")
        context.event("task.started", "外接 Agent 开始执行")
        try:
            handled = handler(task, context)
            result = dict(handled or {})
            output = result.pop("output", result)
            artifact_refs = result.pop("artifact_refs", [])
        except Exception as exc:  # noqa: BLE001 - third-party handlers must become task failures
            return self.submit_result(
                task_id,
                lease_token,
                outcome="failed",
                error={"code": "handler_failed", "message": str(exc)[:1000]},
            )
        return self.submit_result(
            task_id,
            lease_token,
            outcome="succeeded",
            output=output if isinstance(output, Mapping) else {"value": output},
            artifact_refs=artifact_refs if isinstance(artifact_refs, list) else [],
        )

    def run_once(self, handler: TaskHandler) -> JSONDict:
        heartbeat = self.heartbeat()
        connection_test = self.answer_connection_test()
        claimed = self.claim_task()
        receipt = self.execute_claimed_task(claimed, handler) if claimed else None
        return {
            "heartbeat": heartbeat,
            "connectionTest": connection_test,
            "taskReceipt": receipt,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: Mapping[str, Any] | None = None,
        authenticated: bool = True,
        allow_empty: bool = False,
    ) -> JSONDict:
        headers: dict[str, str] = {"Accept": "application/json"}
        if authenticated:
            credential = self.credential
            if not credential:
                raise AgentClientError("该操作需要 Agent 凭据，请先执行 connect")
            headers["Authorization"] = f"Bearer {credential}"
        response: httpx.Response | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.http.request(
                    method, path, json=dict(payload) if payload else None, headers=headers
                )
                if response.status_code not in {502, 503, 504}:
                    break
            except httpx.TransportError:
                response = None
            if attempt < self.max_attempts:
                time.sleep(self.retry_delay_seconds * (2 ** (attempt - 1)))
        if response is None:
            raise AgentClientError(f"连续 {self.max_attempts} 次无法连接平台")
        if response.status_code == 204:
            return {}
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise AgentClientError(f"平台返回了非 JSON 响应：{path}") from exc
        if not 200 <= response.status_code < 300:
            detail = body.get("detail") if isinstance(body, dict) else body
            raise AgentAPIError(response.status_code, str(detail or "平台请求失败"), path=path)
        if not isinstance(body, dict):
            raise AgentClientError(f"平台返回了非 JSON object 响应：{path}")
        if not body and not allow_empty:
            return {}
        return body

    def _require_state(self) -> AgentState:
        if self.state is None:
            raise AgentClientError("请先执行 connect 或加载接入状态文件")
        return self.state

    @staticmethod
    def _validate_pairing_code(pairing_code: str) -> str:
        code = pairing_code.strip()
        if len(code) < 16:
            raise AgentClientError("配对码为空或格式不完整，请在平台重新复制")
        return code

    @staticmethod
    def key(prefix: str) -> str:
        return f"python-{prefix}:{uuid4().hex}"


class TaskContext:
    def __init__(self, client: ExternalAgentClient, task_id: str, lease_token: str) -> None:
        self.client = client
        self.task_id = task_id
        self.lease_token = lease_token

    def event(
        self,
        event_type: str,
        summary: str,
        payload: Mapping[str, Any] | None = None,
    ) -> JSONDict:
        return self.client.send_event(
            self.task_id,
            self.lease_token,
            event_type,
            summary,
            payload=payload,
        )

    def progress(self, percent: int, summary: str) -> JSONDict:
        return self.event("task.progress", summary, {"progress": max(0, min(100, percent))})

    def artifact(self, artifact: Mapping[str, Any], summary: str = "已生成交付物") -> JSONDict:
        return self.event("task.artifact_created", summary, {"artifact": dict(artifact)})

    def renew(self, *, lease_seconds: int = 120) -> JSONDict:
        return self.client.renew_lease(self.task_id, self.lease_token, lease_seconds=lease_seconds)
