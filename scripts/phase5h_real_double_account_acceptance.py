#!/usr/bin/env python3
"""Run the Phase 5H real two-account + external Worker acceptance flow.

The script deliberately uses the running HTTP API for all business commands.
Direct database access is limited to preparing controlled acceptance identities,
locating durable outbox evidence, and verifying the final immutable records.
Secrets, pairing codes, credentials, leases, and model prompts are never printed.
"""

# ruff: noqa: I001

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlmodel import Session, select


ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.db.database import engine
from app.db.models import (
    AIModelInvocationAudit,
    ExternalAgentTask,
    MarketplaceAIService,
    OrganizationMember,
    TransactionExecutionNodeRun,
    TransactionExecutionRun,
    TransactionOutboxEvent,
    TransactionQuote,
    User,
)
from app.security.auth import create_access_token, hash_password
from app.transaction import service as transaction_service


BUYER_USERNAME = "qa_phase5h_buyer"
PROVIDER_USERNAME = "qa_phase5h_provider"
REVIEWER_USERNAME = "qa_phase5h_reviewer"
BUYER_ORG = "org_demo_buyer"
PROVIDER_ORG = "org_cloud_ops"
TENANT = "tenant_demo"
CAPABILITY_EXTERNAL_ID = "goal-prompt-builder"


class AcceptanceFailure(RuntimeError):
    pass


def _step(message: str) -> None:
    print(json.dumps({"step": message}, ensure_ascii=False), flush=True)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _upsert_identity(
    db: Session,
    *,
    username: str,
    password: str,
    role: str,
    organization_id: str | None,
    organization_role: str = "owner",
) -> User:
    user = db.exec(
        select(User).where(User.tenant_id == TENANT, User.username == username)
    ).first()
    if user is None:
        user = User(
            tenant_id=TENANT,
            username=username,
            display_name=username,
            role=role,
            source="acceptance",
            password_hash=hash_password(password),
        )
    else:
        user.password_hash = hash_password(password)
        user.role = role
        user.source = "acceptance"
    db.add(user)
    db.flush()
    if organization_id:
        member = db.exec(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user.id,
            )
        ).first()
        if member is None:
            member = OrganizationMember(
                tenant_id=TENANT,
                organization_id=organization_id,
                user_id=user.id,
                role=organization_role,
                roles_json=[
                    organization_role,
                    "buyer_owner" if organization_id == BUYER_ORG else "seller_admin",
                ],
                data_scope_json={"mode": "all_orders"},
                status="active",
            )
        else:
            member.role = organization_role
            member.roles_json = [
                organization_role,
                "buyer_owner" if organization_id == BUYER_ORG else "seller_admin",
            ]
            member.data_scope_json = {"mode": "all_orders"}
            member.status = "active"
        db.add(member)
    return user


class API:
    def __init__(self, base_url: str) -> None:
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(240.0, connect=10.0),
            trust_env=False,
        )

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        expected: int | tuple[int, ...] = 200,
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        headers = dict(kwargs.pop("headers", {}))
        if token:
            headers.update(self.headers(token))
        response = self.client.request(method, path, headers=headers, **kwargs)
        statuses = (expected,) if isinstance(expected, int) else expected
        if response.status_code not in statuses:
            detail = response.text[:1200]
            raise AcceptanceFailure(
                f"{method} {path} expected {statuses}, got {response.status_code}: {detail}"
            )
        if response.status_code == 204 or not response.content:
            return {}
        payload = response.json()
        _require(isinstance(payload, (dict, list)), f"{path} returned invalid JSON")
        return payload

    def login(self, username: str, password: str) -> str:
        payload = self.request(
            "POST",
            "/api/auth/login",
            json={"tenant_id": TENANT, "username": username, "password": password},
        )
        _require(
            isinstance(payload, dict) and isinstance(payload.get("token"), str),
            "login failed",
        )
        return str(payload["token"])


def _run_connector(
    connector_python: Path,
    args: list[str],
    *,
    stdin_value: str | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    completed = subprocess.run(
        [str(connector_python), "-m", "kaigongba_agent", *args],
        cwd=ROOT,
        input=(stdin_value + "\n") if stdin_value is not None else None,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        safe_error = completed.stderr.strip() or completed.stdout.strip()
        raise AcceptanceFailure(
            f"connector command failed ({args[:3]}): {safe_error[:1200]}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AcceptanceFailure("connector returned invalid JSON") from exc
    _require(isinstance(payload, dict), "connector response must be an object")
    return payload


def _confirmation_receipt(
    connector_python: Path,
    directory: Path,
    *,
    action: str,
    intent: str,
    ordinal: str,
) -> Path:
    ticket = directory / f"{ordinal}-{action}-ticket.json"
    receipt = directory / f"{ordinal}-{action}-receipt.json"
    _run_connector(
        connector_python,
        [
            "assist",
            "card",
            "--intent",
            intent,
            "--action",
            action,
            "--output",
            str(ticket),
        ],
    )
    digest = json.loads(ticket.read_text(encoding="utf-8"))["confirmationDigest"]
    _run_connector(
        connector_python,
        [
            "assist",
            "acknowledge",
            "--ticket",
            str(ticket),
            "--digest",
            str(digest),
            "--output",
            str(receipt),
        ],
    )
    return receipt


def _latest_service_for_agent(agent_profile_id: str) -> MarketplaceAIService:
    with Session(engine) as db:
        service = db.exec(
            select(MarketplaceAIService)
            .where(MarketplaceAIService.agent_profile_id == agent_profile_id)
            .order_by(MarketplaceAIService.created_at.desc())
        ).first()
        if service is None:
            raise AcceptanceFailure(
                "external employee marketplace service draft was not created"
            )
        return service


def _retire_stale_acceptance_services(current_service_id: str) -> None:
    """Keep repeated local acceptance runs from competing with the active fixture."""

    with Session(engine) as db:
        current = db.get(MarketplaceAIService, current_service_id)
        _require(current is not None, "current acceptance service is missing")
        rows = db.exec(
            select(MarketplaceAIService).where(
                MarketplaceAIService.provider_id == current.provider_id,
                MarketplaceAIService.name == "Codex Goal 规划专家",
                MarketplaceAIService.id != current_service_id,
            )
        ).all()
        for row in rows:
            row.online = False
            row.updated_at = datetime.now(UTC).replace(tzinfo=None)
            db.add(row)
        db.commit()


def _process_quote_event(requirement_id: str) -> tuple[str, int]:
    with Session(engine) as db:
        before = len(
            db.exec(
                select(AIModelInvocationAudit).where(
                    AIModelInvocationAudit.capability == "quote_draft"
                )
            ).all()
        )
        events = db.exec(
            select(TransactionOutboxEvent).where(
                TransactionOutboxEvent.event_type
                == transaction_service.QUOTE_DRAFT_REQUESTED_EVENT
            )
        ).all()
        event = next(
            (
                row
                for row in reversed(events)
                if str((row.payload_json or {}).get("requirement_id") or "")
                == requirement_id
            ),
            None,
        )
        if event is None:
            raise AcceptanceFailure("quote draft outbox event was not created")
        transaction_service.process_quote_draft_outbox_event(db, event)
        quote_id = str((event.payload_json or {}).get("quote_id") or "")
    with Session(engine) as db:
        after = len(
            db.exec(
                select(AIModelInvocationAudit).where(
                    AIModelInvocationAudit.capability == "quote_draft"
                )
            ).all()
        )
    return quote_id, after - before


def _verification_snapshot(
    *,
    requirement_id: str,
    quote_id: str,
    order_id: str,
    execution_id: str,
    connection_id: str,
) -> dict[str, Any]:
    with Session(engine) as db:
        quote = db.get(TransactionQuote, quote_id)
        run = db.get(TransactionExecutionRun, execution_id)
        nodes = db.exec(
            select(TransactionExecutionNodeRun)
            .where(TransactionExecutionNodeRun.execution_run_id == execution_id)
            .order_by(TransactionExecutionNodeRun.sequence)
        ).all()
        tasks = db.exec(
            select(ExternalAgentTask)
            .where(
                ExternalAgentTask.connection_id == connection_id,
                ExternalAgentTask.order_id == order_id,
            )
            .order_by(ExternalAgentTask.created_at)
        ).all()
        audits = db.exec(
            select(AIModelInvocationAudit)
            .where(AIModelInvocationAudit.capability.in_(["matching", "quote_draft"]))
            .order_by(AIModelInvocationAudit.created_at.desc())
        ).all()
        matching = [
            row
            for row in audits
            if requirement_id in json.dumps(row.metadata_json or {})
        ]
        _require(
            quote is not None and quote.status == "selected", "quote was not selected"
        )
        _require(run is not None, "execution run missing")
        _require(bool(tasks), "external task missing")
        first_task = tasks[0]
        _require(
            first_task.status == "succeeded",
            f"external task status is {first_task.status}",
        )
        result = dict(first_task.output_json or {})
        _require(bool(result), "external Worker returned an empty result")
        succeeded_nodes = [node for node in nodes if node.status == "succeeded"]
        _require(
            bool(succeeded_nodes), "execution result was not projected to the SOP node"
        )
        digest = hashlib.sha256(
            json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        model_audits = [row for row in audits if row.capability == "quote_draft"]
        return {
            "requirementId": requirement_id,
            "quoteId": quote_id,
            "orderId": order_id,
            "executionRunId": execution_id,
            "connectionId": connection_id,
            "externalTaskId": first_task.id,
            "externalTaskStatus": first_task.status,
            "externalTaskAttempt": first_task.attempt_count,
            "resultDigest": f"sha256:{digest}",
            "resultKeys": sorted(result),
            "artifactCount": len(first_task.artifact_refs_json or []),
            "executionStatus": run.status,
            "succeededNodeCount": len(succeeded_nodes),
            "queuedFollowupTaskCount": sum(
                task.status == "queued" for task in tasks[1:]
            ),
            "quoteAIInvocationCount": len(model_audits),
            "matchingEvidenceCount": len(matching),
            "modelDeployments": sorted(
                {
                    str(row.deployment_id)
                    for row in audits
                    if getattr(row, "deployment_id", None)
                }
            ),
        }


def run(args: argparse.Namespace) -> dict[str, Any]:
    run_key = datetime.now(UTC).strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
    password_buyer = secrets.token_urlsafe(24)
    password_provider = secrets.token_urlsafe(24)
    password_reviewer = secrets.token_urlsafe(24)
    state_dir = args.resume_state_dir or Path(
        tempfile.mkdtemp(prefix="kaigongba-phase5h-state-")
    )
    confirmation_dir = Path(tempfile.mkdtemp(prefix="kaigongba-phase5h-confirm-"))
    profile = f"phase5h-{run_key}"

    _step("准备独立甲方、乙方与平台复核账号")
    with Session(engine) as db:
        buyer = _upsert_identity(
            db,
            username=BUYER_USERNAME,
            password=password_buyer,
            role="member",
            organization_id=BUYER_ORG,
        )
        provider = _upsert_identity(
            db,
            username=PROVIDER_USERNAME,
            password=password_provider,
            role="member",
            organization_id=PROVIDER_ORG,
        )
        reviewer = _upsert_identity(
            db,
            username=REVIEWER_USERNAME,
            password=password_reviewer,
            role="admin",
            organization_id=None,
        )
        db.commit()
        db.refresh(buyer)
        db.refresh(provider)
        db.refresh(reviewer)
        reviewer_token = create_access_token(reviewer)

    api = API(args.base_url)
    try:
        buyer_token = api.login(BUYER_USERNAME, password_buyer)
        provider_token = api.login(PROVIDER_USERNAME, password_provider)
        reviewer_login_token = api.login(REVIEWER_USERNAME, password_reviewer)
        _require(
            reviewer_login_token == reviewer_token, "reviewer login token mismatch"
        )

        _step("创建本地外接 Agent 配对并提交已确认 Manifest")
        manifest_envelope = json.loads(args.manifest.read_text(encoding="utf-8"))
        external_agent_ref = str(
            manifest_envelope.get("manifest", {}).get("agent", {}).get("external_id")
            or ""
        )
        _require(
            bool(external_agent_ref), "confirmed Manifest has no external Agent ID"
        )
        if args.resume_state_dir:
            state_files = [
                item for item in state_dir.glob("*.json") if ".worker-" not in item.name
            ]
            _require(len(state_files) == 1, "resume state directory is ambiguous")
            saved_state = json.loads(state_files[0].read_text(encoding="utf-8"))
            profile = str(saved_state.get("profile") or "")
            connection_id = str(saved_state.get("connection_id") or "")
            _require(bool(profile and connection_id), "resume state is incomplete")
        else:
            enrollment = api.request(
                "POST",
                "/api/enterprise/external-agent-enrollments",
                token=provider_token,
                json={
                    "organization_id": PROVIDER_ORG,
                    "idempotency_key": f"phase5h-enroll-{run_key}",
                },
            )
            _require(isinstance(enrollment, dict), "enrollment response invalid")
            pairing_code = str(enrollment["pairingCode"])
            _run_connector(
                args.connector_python,
                [
                    "register",
                    "preflight",
                    "--base-url",
                    args.base_url,
                    "--allow-localhost",
                ],
                stdin_value=pairing_code,
            )
            registered = _run_connector(
                args.connector_python,
                [
                    "register",
                    "enroll",
                    "--base-url",
                    args.base_url,
                    "--allow-localhost",
                    "--profile",
                    profile,
                    "--state-dir",
                    str(state_dir),
                    "--provider",
                    "codex",
                    "--runtime-type",
                    "local",
                    "--transport",
                    "polling",
                    "--external-agent-ref",
                    external_agent_ref,
                    "--employee-name",
                    "Codex Goal 规划专家",
                    "--confirm-store-credential",
                ],
                stdin_value=pairing_code,
            )
            connection = registered.get("connection") or {}
            evidence = registered.get("evidence") or {}
            connection_id = str(
                connection.get("connectionId")
                or connection.get("id")
                or evidence.get("connectionId")
                or registered.get("connectionId")
                or ""
            )
            _require(
                bool(connection_id), "connector registration returned no connection id"
            )
        manifest_digest = str(manifest_envelope["previewDigest"])
        _run_connector(
            args.connector_python,
            [
                "register",
                "manifest",
                "--profile",
                profile,
                "--state-dir",
                str(state_dir),
                "--manifest",
                str(args.manifest),
                "--confirm-submit-digest",
                manifest_digest,
            ],
        )

        manifest = api.request(
            "GET",
            f"/api/enterprise/external-agents/{connection_id}/manifest",
            token=provider_token,
        )
        _require(isinstance(manifest, dict), "manifest response invalid")
        capability = next(
            (
                item
                for item in manifest.get("assets", [])
                if item.get("externalId") == CAPABILITY_EXTERNAL_ID
            ),
            None,
        )
        _require(capability is not None, "goal-prompt-builder capability not found")
        reviewed = api.request(
            "POST",
            f"/api/enterprise/external-agent-manifests/{manifest['id']}/review",
            token=provider_token,
            json={"decision": "approved", "selected_asset_ids": [capability["id"]]},
        )
        _require(
            isinstance(reviewed, dict) and reviewed.get("status") == "approved",
            "manifest approval failed",
        )

        _step("创建外接员工并发布匹配服务")
        draft = api.request(
            "POST",
            f"/api/enterprise/external-agents/{connection_id}/import-draft",
            token=provider_token,
            json={"idempotency_key": f"phase5h-import-{run_key}"},
        )
        _require(isinstance(draft, dict), "import draft response invalid")
        if draft.get("status") == "confirmed" and draft.get("agentProfileId"):
            confirmed = draft
        else:
            api.request(
                "PUT",
                f"/api/enterprise/external-agent-import-drafts/{draft['id']}",
                token=provider_token,
                json={
                    "agent_name": "Codex Goal 规划专家",
                    "role_name": "AI 自动化方案顾问",
                    "job_description": "根据目标、范围、约束和验收标准生成可执行、可审计的 Codex /goal 命令。",
                    "service_scope": [
                        "需求澄清",
                        "Goal 结构设计",
                        "验收门禁设计",
                        "完整命令交付",
                    ],
                    "restrictions": [
                        "不执行客户业务系统变更",
                        "不接触未授权文件或密钥",
                    ],
                    "sync_policy": "notify",
                },
            )
            confirmed = api.request(
                "POST",
                f"/api/enterprise/external-agent-import-drafts/{draft['id']}/confirm",
                token=provider_token,
                json={"idempotency_key": f"phase5h-confirm-import-{run_key}"},
            )
        _require(isinstance(confirmed, dict), "employee confirmation response invalid")
        agent_profile_id = str(confirmed.get("agentProfileId") or "")
        _require(bool(agent_profile_id), "external employee profile was not created")

        configure_receipt = _confirmation_receipt(
            args.connector_python,
            confirmation_dir,
            action="configure_worker",
            intent="connect",
            ordinal="01",
        )
        _run_connector(
            args.connector_python,
            [
                "worker",
                "configure",
                "--profile",
                profile,
                "--state-dir",
                str(state_dir),
                "--manifest",
                str(args.manifest),
                "--workspace",
                str(args.workspace),
                "--runner",
                str(args.runner),
                "--sandbox",
                "read-only",
                "--lease-seconds",
                "180",
                "--heartbeat-seconds",
                "15",
                "--poll-seconds",
                "2",
                "--handler-timeout-seconds",
                "240",
                "--confirmation",
                str(configure_receipt),
            ],
        )
        connection_test = api.request(
            "POST",
            f"/api/enterprise/external-agents/{connection_id}/connection-tests",
            token=provider_token,
            json={"idempotency_key": f"phase5h-connection-test-{run_key}"},
        )
        _require(isinstance(connection_test, dict), "connection test response invalid")
        first_worker_receipt = _confirmation_receipt(
            args.connector_python,
            confirmation_dir,
            action="start_worker_once",
            intent="execute",
            ordinal="02",
        )
        _run_connector(
            args.connector_python,
            [
                "worker",
                "once",
                "--profile",
                profile,
                "--state-dir",
                str(state_dir),
                "--confirmation",
                str(first_worker_receipt),
            ],
            timeout=300,
        )
        tested = api.request(
            "GET",
            f"/api/enterprise/external-agent-connection-tests/{connection_test['id']}",
            token=provider_token,
        )
        _require(
            isinstance(tested, dict) and tested.get("status") == "passed",
            "connection test did not pass",
        )
        current_connection = api.request(
            "GET",
            f"/api/enterprise/external-agents/{connection_id}",
            token=provider_token,
        )
        _require(
            isinstance(current_connection, dict)
            and current_connection.get("status") == "available"
            and current_connection.get("healthStatus") == "online",
            "external connection is not available and online",
        )

        service = _latest_service_for_agent(agent_profile_id)
        service_id = service.id
        api.request(
            "PUT",
            f"/api/marketplace/publishing/ai-services/{service_id}",
            token=provider_token,
            json={
                "organization_id": PROVIDER_ORG,
                "agent_profile_id": agent_profile_id,
                "name": "Codex Goal 规划专家",
                "category": "AI 自动化与开发工具",
                "description": "把自然语言目标整理为可持续执行的 Codex /goal 命令，并设计开发范围、禁止项、自动化测试、逐阶段验收证据、失败停止条件和使用说明。",
                "version": "v1.0.0",
                "visibility": "public",
                "price": 699,
                "price_unit": "次",
                "average_minutes": 30,
                "included_revisions": 2,
                "delivery_format": "文档",
                "service_scope": [
                    "目标澄清与五段式 Goal 结构设计",
                    "开发范围、禁止项与失败停止条件设计",
                    "自动化测试与逐阶段验收证据设计",
                    "Codex Goal 命令与可直接复制运行的使用说明交付",
                ],
                "exclusions": ["不代替客户执行生产变更", "不读取未授权资料"],
                "deliverables": [
                    {"name": "Codex Goal 命令与使用说明", "format": ".md"}
                ],
                "acceptance_criteria": [
                    "命令包含 Objective、Scope、Constraints、Done when、Stop if 五段式结构",
                    "包含自动化测试、逐阶段验收证据和失败停止条件",
                    "命令和使用说明可以直接复制运行",
                ],
                "cases": [],
                "sop_version": None,
                "data_permissions": [],
                "change_summary": "5H 真实双账号验收服务版本",
            },
        )
        review = api.request(
            "POST",
            f"/api/marketplace/publishing/ai-services/{service_id}/submit-review",
            token=provider_token,
            params={"organizationId": PROVIDER_ORG},
        )
        _require(isinstance(review, dict), "service review response invalid")
        approved_service = api.request(
            "POST",
            f"/api/marketplace/reviews/{review['id']}/decision",
            token=reviewer_token,
            json={
                "action": "approve",
                "comment": "外接能力、连接健康和交付边界验收通过",
            },
        )
        _require(
            isinstance(approved_service, dict)
            and approved_service.get("status") == "approved",
            "service review failed",
        )
        _retire_stale_acceptance_services(service_id)

        _step("甲方发布真实需求并由平台执行真实匹配与 AI 报价")
        desired_at = (datetime.now(UTC) + timedelta(days=14)).isoformat()
        requirement = api.request(
            "POST",
            "/api/transactions/requirements",
            token=buyer_token,
            json={
                "organization_id": BUYER_ORG,
                "title": "为开工吧后续多阶段开发编写可执行 Codex Goal 命令",
                "category": "AI 自动化与开发工具",
                "description": "需要把后续功能开发目标整理为一条可持续执行的 Codex /goal 命令，必须明确范围、禁止项、逐阶段验收证据、失败停止条件和最终交付标准。",
                "budget_min_amount": "600.00",
                "budget_max_amount": "1200.00",
                "desired_delivery_at": desired_at,
                "visibility": "invited_providers",
                "confidentiality_level": "standard",
                "invite_limit": 3,
                "deliverables": [
                    {
                        "name": "Codex Goal 命令与使用说明",
                        "format": ".md",
                        "required": True,
                    }
                ],
                "acceptance_criteria": [
                    "命令包含五段式结构",
                    "包含自动化测试、证据和停止条件",
                    "可直接复制运行",
                ],
                "attachments": [],
            },
        )
        _require(isinstance(requirement, dict), "requirement response invalid")
        requirement_id = str(requirement["id"])
        published = api.request(
            "POST",
            f"/api/transactions/requirements/{requirement_id}/publish",
            token=buyer_token,
            params={"organizationId": BUYER_ORG},
        )
        _require(
            isinstance(published, dict)
            and published.get("status") == "matching"
            and int(published.get("invitationCount") or 0) >= 1,
            "requirement did not match an eligible provider",
        )
        quote_id, new_quote_ai_invocations = _process_quote_event(requirement_id)
        _require(
            new_quote_ai_invocations >= 1,
            "AI quote generation did not record a real model invocation",
        )
        with Session(engine) as db:
            matched_quote = db.get(TransactionQuote, quote_id)
            _require(
                matched_quote is not None and matched_quote.service_id == service_id,
                "matching selected a stale service instead of the active external employee",
            )

        workbench = api.request(
            "GET",
            "/api/transactions/provider/workbench",
            token=provider_token,
            params={"organizationId": PROVIDER_ORG},
        )
        _require(isinstance(workbench, dict), "provider workbench response invalid")
        provider_quote = next(
            (
                item
                for item in workbench.get("quoteDrafts", [])
                if item.get("id") == quote_id
            ),
            None,
        )
        _require(
            provider_quote is not None and provider_quote.get("status") == "ai_draft",
            "provider did not receive an AI quote draft",
        )
        _require(
            provider_quote.get("canConfirm") is True,
            "AI quote is not awaiting provider confirmation",
        )
        sent_quote = api.request(
            "POST",
            f"/api/transactions/quotes/{quote_id}/confirm-send",
            token=provider_token,
            params={"organizationId": PROVIDER_ORG},
        )
        _require(
            isinstance(sent_quote, dict) and sent_quote.get("status") == "sent",
            "provider quote confirmation failed",
        )

        _step("甲方选标、双方确认协议并生成演示支付订单")
        agreement = api.request(
            "POST",
            f"/api/transactions/requirements/{requirement_id}/select-quote",
            token=buyer_token,
            json={
                "organization_id": BUYER_ORG,
                "quote_id": quote_id,
                "buyer_note": "确认采用外接 Codex 员工的 AI 报价",
            },
        )
        _require(isinstance(agreement, dict), "agreement response invalid")
        agreement_id = str(agreement["id"])
        api.request(
            "POST",
            f"/api/transactions/agreements/{agreement_id}/confirm",
            token=buyer_token,
            json={
                "organization_id": BUYER_ORG,
                "confirmation_statement": "甲方确认冻结需求、报价和验收标准。",
            },
        )
        active_agreement = api.request(
            "POST",
            f"/api/transactions/agreements/{agreement_id}/confirm",
            token=provider_token,
            json={
                "organization_id": PROVIDER_ORG,
                "confirmation_statement": "乙方确认按冻结范围由外接员工完成交付。",
            },
        )
        _require(
            isinstance(active_agreement, dict)
            and active_agreement.get("status") == "active",
            "agreement did not become active",
        )
        payment = api.request(
            "POST",
            f"/api/transactions/agreements/{agreement_id}/payment-orders",
            token=buyer_token,
            json={"organization_id": BUYER_ORG},
        )
        _require(isinstance(payment, dict), "payment response invalid")
        paid = api.request(
            "POST",
            f"/api/transactions/payment-orders/{payment['id']}/demo-simulate",
            token=reviewer_token,
            json={
                "organization_id": BUYER_ORG,
                "result": "success",
                "confirmation_code": "DEMO-PAY",
                "callback_id": f"phase5h-demo-payment-{run_key}",
                "acknowledged_demo": True,
            },
        )
        _require(
            isinstance(paid, dict) and bool(paid.get("orderId")),
            "order was not generated",
        )
        order_id = str(paid["orderId"])

        _step("乙方启动订单 SOP，本机 Worker 领取并真实执行任务")
        provider_workspace = api.request(
            "GET",
            f"/api/transactions/orders/{order_id}/workspace",
            token=provider_token,
            params={"organizationId": PROVIDER_ORG},
        )
        _require(
            isinstance(provider_workspace, dict), "provider order workspace invalid"
        )
        milestones = provider_workspace.get("order", {}).get("milestones", [])
        _require(bool(milestones), "order has no milestone")
        execution = api.request(
            "POST",
            f"/api/executions/orders/{order_id}/runs",
            token=provider_token,
            json={
                "organization_id": PROVIDER_ORG,
                "milestone_id": milestones[0]["id"],
                "command_id": f"phase5h-start-{run_key}",
            },
        )
        _require(
            isinstance(execution, dict) and execution.get("status") == "running",
            "SOP did not start",
        )
        execution_id = str(execution["id"])
        second_worker_receipt = _confirmation_receipt(
            args.connector_python,
            confirmation_dir,
            action="start_worker_once",
            intent="execute",
            ordinal="03",
        )
        worker_result = _run_connector(
            args.connector_python,
            [
                "worker",
                "once",
                "--profile",
                profile,
                "--state-dir",
                str(state_dir),
                "--confirmation",
                str(second_worker_receipt),
            ],
            timeout=420,
        )
        _require(
            worker_result.get("status") in {"task_completed", "cycle_complete", "idle"}
            or worker_result.get("action") in {"worker_cycle", "task_result_submitted"},
            f"unexpected Worker result status: {worker_result.get('status')}",
        )
        time.sleep(0.5)
        evidence = _verification_snapshot(
            requirement_id=requirement_id,
            quote_id=quote_id,
            order_id=order_id,
            execution_id=execution_id,
            connection_id=connection_id,
        )
        evidence.update(
            {
                "status": "passed",
                "buyerAccount": BUYER_USERNAME,
                "providerAccount": PROVIDER_USERNAME,
                "providerOrganizationId": PROVIDER_ORG,
                "serviceId": service_id,
                "agentProfileId": agent_profile_id,
                "manifestId": str(manifest["id"]),
                "connectionTestId": str(connection_test["id"]),
                "paymentMode": "demo",
                "quoteAIInvocationDelta": new_quote_ai_invocations,
            }
        )
        return evidence
    finally:
        api.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5190")
    parser.add_argument("--resume-state-dir", type=Path)
    parser.add_argument(
        "--connector-python",
        type=Path,
        default=Path(
            "/Users/albert/Library/Application Support/Kaigongba Agent Connector/venv/bin/python"
        ),
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(
            "/Users/albert/Library/Application Support/Kaigongba Agent Connector/manifest-confirmed.json"
        ),
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path(
            "/Users/albert/Library/Application Support/Kaigongba Agent Connector/workspace"
        ),
    )
    parser.add_argument(
        "--runner",
        type=Path,
        default=Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in (args.connector_python, args.manifest, args.workspace, args.runner):
        if not path.exists():
            raise SystemExit(f"required acceptance dependency is missing: {path}")
    try:
        result = run(args)
    except Exception as exc:
        print(
            json.dumps(
                {"status": "failed", "error": type(exc).__name__, "detail": str(exc)},
                ensure_ascii=False,
            ),
            flush=True,
        )
        raise
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
