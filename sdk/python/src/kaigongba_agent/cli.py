from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .client import AgentClientError, AgentState, ExternalAgentClient, TaskHandler, load_manifest

DEFAULT_STATE_FILE = Path(".kaigongba/agent-state.json")
DEFAULT_SERVER = "https://app.kaigongba.net"


def default_manifest() -> dict[str, Any]:
    return {
        "protocol_version": "1.0",
        "agent": {
            "external_id": "replace-with-stable-agent-id",
            "name": "我的外接 AI 员工",
            "description": "请描述该 Agent 的真实能力边界",
            "provider": "self-hosted",
            "runtime": "python",
            "runtime_version": "",
            "input_modes": ["text", "file"],
            "output_modes": ["text", "file"],
            "source_hash": "",
        },
        "capabilities": [
            {
                "external_id": "replace-with-stable-capability-id",
                "kind": "skill",
                "name": "示例能力（请修改）",
                "description": "声明可验收的真实能力，不要上传源码、密钥或知识正文",
                "version": "1.0",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "permissions": [],
                "risk_level": "low",
                "portable": False,
                "callable": True,
                "source_type": "declared",
                "source_hash": "",
                "evidence": {"method": "owner_declared"},
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
            "confirmed_by_user": False,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="开工吧外接 Agent 接入助手")
    parser.add_argument(
        "--server",
        default=os.environ.get("KAIGONGBA_SERVER_URL"),
        help="开工吧平台地址；connect 默认使用 app.kaigongba.net，后续默认读取状态文件",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path(os.environ.get("KAIGONGBA_AGENT_STATE", str(DEFAULT_STATE_FILE))),
        help="本地凭据状态文件（自动设置为 0600）",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init-manifest", help="生成 Manifest 1.0 模板")
    init.add_argument("--output", type=Path, default=Path("kaigongba-agent-manifest.json"))

    connect = commands.add_parser("connect", help="配对、登记并提交 Manifest")
    connect.add_argument("--pairing-code", required=True)
    connect.add_argument("--manifest", type=Path, required=True)
    connect.add_argument("--provider", default="self-hosted")
    connect.add_argument("--external-agent-ref", required=True)
    connect.add_argument(
        "--runtime-type",
        choices=["local", "cloud", "private_cloud", "self_hosted"],
        default="local",
    )
    connect.add_argument(
        "--transport", choices=["polling", "webhook", "a2a", "manual"], default="polling"
    )
    connect.add_argument("--endpoint", default="")

    status = commands.add_parser("status", help="验证本地凭据和平台连接")
    status.set_defaults(command="status")

    once = commands.add_parser("run-once", help="上报心跳、回应连接测试并领取一个任务")
    once.add_argument("--handler", default="kaigongba_agent.example:handle")

    run = commands.add_parser("run", help="持续上报心跳并轮询任务")
    run.add_argument("--handler", default="kaigongba_agent.example:handle")
    run.add_argument("--poll-seconds", type=float, default=5.0)
    run.add_argument("--max-cycles", type=int, default=0)
    return parser


def load_handler(reference: str) -> TaskHandler:
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise AgentClientError("--handler 必须使用 package.module:function 格式")
    try:
        handler = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise AgentClientError(f"无法加载任务处理器：{reference}") from exc
    if not callable(handler):
        raise AgentClientError(f"任务处理器不可调用：{reference}")
    return handler


def _write_manifest(path: Path) -> None:
    if path.exists():
        raise AgentClientError(f"文件已存在，拒绝覆盖：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(default_manifest(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _safe_output(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, default=str))


def _run(args: argparse.Namespace) -> int:
    if args.command == "init-manifest":
        _write_manifest(args.output)
        _safe_output(
            {
                "manifestFile": str(args.output),
                "next": "确认扫描范围后将 confirmed_by_user 改为 true",
            }
        )
        return 0

    if args.command == "connect":
        manifest = load_manifest(args.manifest)
        with ExternalAgentClient(args.server or DEFAULT_SERVER) as client:
            state, _registered, submitted = client.connect(
                args.pairing_code,
                manifest,
                provider=args.provider,
                external_agent_ref=args.external_agent_ref,
                runtime_type=args.runtime_type,
                transport=args.transport,
                endpoint=args.endpoint,
            )
            state.save(args.state_file)
        _safe_output(
            {
                "connectionId": state.connection_id,
                "manifestId": submitted.get("id"),
                "manifestStatus": submitted.get("status"),
                "stateFile": str(args.state_file),
            }
        )
        return 0

    state = AgentState.load(args.state_file)
    with ExternalAgentClient(args.server or state.server, state=state) as client:
        if args.command == "status":
            info = client.self_info()
            _safe_output(
                {
                    "connectionId": info.get("connectionId"),
                    "status": info.get("status"),
                    "scopes": info.get("scopes", []),
                }
            )
            return 0
        handler = load_handler(args.handler)
        if args.command == "run-once":
            _safe_output(client.run_once(handler))
            return 0
        cycles = 0
        while args.max_cycles <= 0 or cycles < args.max_cycles:
            _safe_output(client.run_once(handler))
            cycles += 1
            if args.max_cycles <= 0 or cycles < args.max_cycles:
                time.sleep(max(0.5, args.poll_seconds))
        return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(build_parser().parse_args(argv))
    except AgentClientError as exc:
        print(f"接入失败：{exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已停止外接 Agent 接入助手", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
