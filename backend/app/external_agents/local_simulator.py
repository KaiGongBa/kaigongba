from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import httpx


class HTTPClient(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any: ...


class SimulatorHTTPError(RuntimeError):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


@dataclass
class SimulatorState:
    connection_id: str
    credential: str
    external_agent_ref: str
    provider: str
    employee_name: str
    capability_count: int = 1

    @classmethod
    def load(cls, path: Path) -> SimulatorState:
        return cls(**json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)


class LocalExternalAgentSimulator:
    """A deterministic polling client for the public external-Agent protocol.

    It intentionally uses only HTTP endpoints available to a third-party Agent.
    Platform review, task creation, acceptance, payment, refunds, and settlements
    remain user/platform operations and are not exposed by this helper.
    """

    def __init__(
        self,
        client: HTTPClient,
        *,
        state: SimulatorState | None = None,
        lease_owner: str = "kaigongba-local-agent-simulator",
        artifact_ref: str = "object://external-agent-results/simulator-result.json",
        max_transport_attempts: int = 3,
        retry_delay_seconds: float = 0.05,
    ) -> None:
        self.client = client
        self.state = state
        self.lease_owner = lease_owner
        self.artifact_ref = artifact_ref
        self.max_transport_attempts = max(1, max_transport_attempts)
        self.retry_delay_seconds = max(0, retry_delay_seconds)

    def enroll(
        self,
        pairing_code: str,
        *,
        provider: str = "kaigongba-simulator",
        external_agent_ref: str = "local-e2e-agent",
        employee_name: str = "本地外接验收员工",
    ) -> dict[str, Any]:
        self._request_json(
            "POST",
            "/api/external-agent-enrollments/preflight",
            payload={"pairing_code": pairing_code},
            authenticated=False,
        )
        registration_key = self._key("simulator-register")
        registered = self._request_json(
            "POST",
            "/api/external-agent-enrollments/register",
            payload={
                "pairing_code": pairing_code,
                "registration_idempotency_key": registration_key,
                "provider": provider,
                "runtime_type": "local",
                "transport": "polling",
                "external_agent_ref": external_agent_ref,
                "protocol_version": "1.0",
                "metadata": {"connector_version": "kaigongba-simulator/1.0"},
            },
            authenticated=False,
        )
        if not registered:
            raise RuntimeError("外接 Agent 登记未返回数据")
        connection = registered["connection"]
        self.state = SimulatorState(
            connection_id=connection["id"],
            credential=registered["credential"],
            external_agent_ref=external_agent_ref,
            provider=provider,
            employee_name=employee_name,
        )
        digest = sha256(external_agent_ref.encode("utf-8")).hexdigest()
        manifest = self._request_json(
            "POST",
            f"/api/external-agents/{self.state.connection_id}/manifest",
            payload={
                "idempotency_key": self._key("simulator-manifest"),
                "manifest": {
                    "protocol_version": "1.0",
                    "agent": {
                        "external_id": external_agent_ref,
                        "name": employee_name,
                        "description": "可重放的本地外接 Agent 协议验收器",
                        "provider": provider,
                        "runtime": "local",
                        "runtime_version": "1.0",
                        "input_modes": ["text", "file"],
                        "output_modes": ["text", "file"],
                        "source_hash": f"sha256:{digest}",
                    },
                    "capabilities": [
                        {
                            "external_id": "document-delivery",
                            "kind": "skill",
                            "name": "受控文档交付",
                            "description": "生成结构化结果并回传平台对象引用",
                            "version": "1.0",
                            "input_schema": {"type": "object"},
                            "output_schema": {"type": "object"},
                            "permissions": ["filesystem:write:output"],
                            "risk_level": "low",
                            "portable": False,
                            "callable": True,
                            "source_type": "simulator",
                            "source_hash": f"sha256:{digest}",
                            "evidence": {"method": "deterministic", "confidence": 1.0},
                        }
                    ],
                    "execution": {
                        "mode": "external",
                        "transports": ["polling"],
                        "supports_streaming": True,
                        "supports_cancellation": True,
                        "supports_approval": True,
                        "max_concurrency": 1,
                    },
                    "disclosure": {
                        "source_uploaded": False,
                        "knowledge_content_uploaded": False,
                        "secrets_uploaded": False,
                        "confirmed_by_user": True,
                    },
                },
            },
        )
        return {"registration": registered, "manifest": manifest}

    def heartbeat(self, *, idempotency_key: str | None = None) -> dict[str, Any]:
        state = self._require_state()
        result = self._request_json(
            "POST",
            f"/api/external-agents/{state.connection_id}/heartbeat",
            payload={
                "idempotency_key": idempotency_key or self._key("simulator-heartbeat"),
                "status": "online",
                "protocol_version": "1.0",
                "runtime_version": "kaigongba-simulator/1.0",
                "running_task_count": 0,
                "queue_depth": 0,
                "latency_ms": 1,
                "diagnostics": {"connector_version": "kaigongba-simulator/1.0"},
            },
        )
        return result or {}

    def answer_connection_test_once(self) -> dict[str, Any] | None:
        state = self._require_state()
        claimed = self._request_json(
            "POST",
            f"/api/external-agents/{state.connection_id}/connection-tests/claim",
            payload={"lease_owner": self.lease_owner},
        )
        if not claimed:
            return None
        return self._request_json(
            "POST",
            f"/api/external-agent-connection-tests/{claimed['testId']}/result",
            payload={
                "challenge": claimed["challenge"],
                "employee_name": state.employee_name,
                "protocol_version": "1.0",
                "enabled_capability_count": state.capability_count,
            },
        )

    def claim_task(self, *, lease_seconds: int = 120) -> dict[str, Any] | None:
        state = self._require_state()
        claimed = self._request_json(
            "POST",
            f"/api/external-agents/{state.connection_id}/tasks/claim",
            payload={
                "lease_owner": self.lease_owner,
                "lease_seconds": lease_seconds,
            },
        )
        if not claimed or claimed.get("task") is None:
            return None
        return claimed

    def run_task_once(self, *, replay_result: bool = True) -> dict[str, Any] | None:
        claimed = self.claim_task()
        if claimed is None:
            return None
        task = claimed["task"]
        task_id = task["id"]
        lease_token = claimed["leaseToken"]
        common = {"lease_owner": self.lease_owner, "lease_token": lease_token}
        self._event(task_id, common, "task.accepted", "外接 Agent 已接收任务", {})
        self._event(task_id, common, "task.started", "外接 Agent 开始执行", {})
        self._event(
            task_id,
            common,
            "task.progress",
            "已完成核心处理",
            {"progress": 75},
        )
        artifact = {
            "ref": self.artifact_ref,
            "name": "simulator-result.json",
            "media_type": "application/json",
        }
        self._event(
            task_id,
            common,
            "task.artifact_created",
            "已生成阶段性交付物",
            {"artifact": artifact},
        )
        result_payload = {
            **common,
            "idempotency_key": self._key(f"simulator-result-{task_id}"),
            "outcome": "succeeded",
            "output": {"summary": "本地外接 Agent 模拟执行完成"},
            "artifact_refs": [artifact],
        }
        receipt = self._request_json(
            "POST", f"/api/external-agent-tasks/{task_id}/result", payload=result_payload
        )
        if replay_result:
            replayed = self._request_json(
                "POST", f"/api/external-agent-tasks/{task_id}/result", payload=result_payload
            )
            if replayed != receipt:
                raise RuntimeError("结果回执重放未返回同一幂等响应")
        return receipt

    def run_cycle(self) -> dict[str, Any]:
        heartbeat = self.heartbeat()
        connection_test = self.answer_connection_test_once()
        task_receipt = self.run_task_once()
        return {
            "heartbeat": heartbeat,
            "connectionTest": connection_test,
            "taskReceipt": task_receipt,
        }

    def _event(
        self,
        task_id: str,
        common: dict[str, str],
        event_type: str,
        summary: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        result = self._request_json(
            "POST",
            f"/api/external-agent-tasks/{task_id}/events",
            payload={
                **common,
                "idempotency_key": self._key(f"simulator-{event_type}-{task_id}"),
                "event_type": event_type,
                "summary": summary,
                "payload": payload,
            },
        )
        return result or {}

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any],
        authenticated: bool = True,
    ) -> dict[str, Any] | None:
        headers: dict[str, str] = {}
        if authenticated:
            headers["Authorization"] = f"Bearer {self._require_state().credential}"
        response: Any | None = None
        for attempt in range(1, self.max_transport_attempts + 1):
            try:
                response = self.client.request(method, path, json=payload, headers=headers)
                if response.status_code not in {502, 503, 504}:
                    break
            except httpx.TransportError:
                response = None
            if attempt < self.max_transport_attempts:
                time.sleep(self.retry_delay_seconds * (2 ** (attempt - 1)))
        if response is None:
            raise RuntimeError(f"连续 {self.max_transport_attempts} 次无法连接平台")
        if response.status_code == 204:
            return None
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            body = {}
        if response.status_code < 200 or response.status_code >= 300:
            detail = body.get("detail") if isinstance(body, dict) else str(body)
            raise SimulatorHTTPError(response.status_code, str(detail or "平台请求失败"))
        if not isinstance(body, dict):
            raise RuntimeError("平台返回了非 JSON object 响应")
        return body

    def _require_state(self) -> SimulatorState:
        if self.state is None:
            raise RuntimeError("请先完成外接 Agent 登记或加载状态文件")
        return self.state

    @staticmethod
    def _key(prefix: str) -> str:
        return f"{prefix}:{uuid4().hex}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="开工吧本地外接 Agent 协议模拟器")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("KAIGONGBA_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path(".data/external-agent-simulator.json"),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    enroll = subcommands.add_parser("enroll", help="使用平台配对码登记并提交 Manifest")
    enroll.add_argument("--pairing-code", required=True)
    enroll.add_argument("--provider", default="kaigongba-simulator")
    enroll.add_argument("--external-agent-ref", default="local-e2e-agent")
    enroll.add_argument("--employee-name", default="本地外接验收员工")
    subcommands.add_parser("run-once", help="上报心跳、回应连接测试并执行一个任务")
    run = subcommands.add_parser("run", help="持续轮询并执行任务")
    run.add_argument("--poll-seconds", type=float, default=5.0)
    run.add_argument("--max-cycles", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    with httpx.Client(base_url=args.base_url, timeout=15.0, trust_env=False) as client:
        if args.command == "enroll":
            simulator = LocalExternalAgentSimulator(client)
            enrolled = simulator.enroll(
                args.pairing_code,
                provider=args.provider,
                external_agent_ref=args.external_agent_ref,
                employee_name=args.employee_name,
            )
            simulator.state.save(args.state_file)
            output = {
                "connectionId": simulator.state.connection_id,
                "manifestId": enrolled["manifest"]["id"],
                "manifestStatus": enrolled["manifest"]["status"],
                "stateFile": str(args.state_file),
            }
            print(json.dumps(output, ensure_ascii=False))
            return 0
        simulator = LocalExternalAgentSimulator(
            client,
            state=SimulatorState.load(args.state_file),
        )
        if args.command == "run-once":
            print(json.dumps(simulator.run_cycle(), ensure_ascii=False, default=str))
            return 0
        cycles = 0
        while args.max_cycles <= 0 or cycles < args.max_cycles:
            result = simulator.run_cycle()
            print(json.dumps(result, ensure_ascii=False, default=str))
            cycles += 1
            if args.max_cycles <= 0 or cycles < args.max_cycles:
                time.sleep(max(0.1, args.poll_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
