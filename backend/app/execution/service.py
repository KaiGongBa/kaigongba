from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from app.db.models import (
    ExternalAgentConnection,
    ExternalAgentDiscoveredAsset,
    ExternalAgentNetworkPolicy,
    ExternalAgentTask,
    MarketplaceAIService,
    MarketplaceAuditLog,
    OrganizationMember,
    TransactionExecutionEvent,
    TransactionExecutionNodeRun,
    TransactionExecutionRun,
    TransactionOrder,
    TransactionOrderMilestone,
    TransactionOrderSOPSnapshot,
    TransactionOutboxEvent,
    TransactionSkillPackageVersion,
    TransactionSkillReview,
    User,
    new_id,
    utc_now,
)
from app.execution.package_security import scan_skill_package
from app.execution.schemas import (
    ExecutionCapabilitiesRead,
    ExecutionCommandRequest,
    ExecutionEventRead,
    ExecutionNodeRead,
    ExecutionRunRead,
    ExecutionStartRequest,
    InternalEventReceipt,
    InternalExecutionEventRequest,
    OrderExecutionRead,
    SkillPackageImportRequest,
    SkillPackageRead,
    SkillReviewRequest,
    SOPSnapshotRead,
)
from app.integrations.staffdeck import get_staffdeck_gateway
from app.integrations.staffdeck.schemas import SOPDefinitionRequest
from app.security.permissions import is_admin_user
from app.transaction.object_storage import (
    DownloadTarget,
    ObjectAlreadyExistsError,
    get_order_object_store,
)

MANAGER_ROLES = {
    "owner",
    "admin",
    "enterprise_owner",
    "service_admin",
    "seller_admin",
    "buyer_manager",
}
TERMINAL_RUN_STATES = {"succeeded", "failed", "cancelled"}
ACTIVE_RUN_STATES = {"queued", "running", "paused", "waiting_confirmation"}
SKILL_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,119}$")


def _digest(value: dict[str, Any]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _membership(db: Session, current_user: User, organization_id: str) -> OrganizationMember:
    row = db.exec(
        select(OrganizationMember).where(
            OrganizationMember.tenant_id == current_user.tenant_id,
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    ).first()
    if not row:
        raise HTTPException(status_code=403, detail="当前用户不是该企业成员")
    return row


def _is_manager(membership: OrganizationMember) -> bool:
    return bool(MANAGER_ROLES.intersection(membership.roles_json or [membership.role]))


def _require_order_party(
    db: Session,
    current_user: User,
    order_id: str,
    organization_id: str,
) -> tuple[TransactionOrder, str, OrganizationMember]:
    order = db.get(TransactionOrder, order_id)
    if not order or order.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="订单不存在")
    membership = _membership(db, current_user, organization_id)
    if organization_id == order.buyer_organization_id:
        return order, "buyer", membership
    if organization_id == order.provider_organization_id:
        return order, "provider", membership
    raise HTTPException(status_code=403, detail="当前企业不是订单参与方")


def _agent_for_order(db: Session, order: TransactionOrder) -> str | None:
    service_data = dict(order.snapshot_json.get("service") or {})
    agent_id = service_data.get("agent_profile_id")
    if agent_id:
        return str(agent_id)
    service = db.get(MarketplaceAIService, order.service_id)
    return service.agent_profile_id if service else None


def _external_bridge_for_order(order: TransactionOrder) -> dict[str, Any] | None:
    service_data = dict(order.snapshot_json.get("service") or {})
    service_snapshot = service_data.get("snapshot")
    if not isinstance(service_snapshot, dict):
        return None
    bridge = service_snapshot.get("external_agent_bridge")
    return dict(bridge) if isinstance(bridge, dict) else None


def _enqueue_external_node_task(
    db: Session,
    current_user: User,
    order: TransactionOrder,
    milestone: TransactionOrderMilestone,
    run: TransactionExecutionRun,
) -> ExternalAgentTask | None:
    bridge = _external_bridge_for_order(order)
    if not bridge or not run.current_node_key:
        return None
    node = db.exec(
        select(TransactionExecutionNodeRun)
        .where(
            TransactionExecutionNodeRun.execution_run_id == run.id,
            TransactionExecutionNodeRun.node_key == run.current_node_key,
        )
        .order_by(TransactionExecutionNodeRun.attempt.desc())
    ).first()
    if not node or node.execution_mode != "agent" or node.status != "running":
        return None

    bridge_capabilities = [
        item for item in bridge.get("capabilities") or [] if isinstance(item, dict)
    ]
    connection = db.get(
        ExternalAgentConnection,
        str(bridge.get("connection_id") or ""),
    )
    if not connection or connection.status != "available" or connection.health_status != "online":
        raise HTTPException(status_code=409, detail="成交服务的外接员工当前不可用")
    policy = db.exec(
        select(ExternalAgentNetworkPolicy).where(
            ExternalAgentNetworkPolicy.connection_id == connection.id
        )
    ).first()
    heartbeat_interval = policy.heartbeat_interval_seconds if policy else 60
    if (
        not connection.last_heartbeat_at
        or utc_now() - connection.last_heartbeat_at
        > timedelta(seconds=heartbeat_interval * 3)
    ):
        raise HTTPException(status_code=409, detail="成交服务的外接员工心跳已过期")
    asset_ids = [str(item.get("asset_id") or "") for item in bridge_capabilities]
    assets = [
        asset
        for asset_id in asset_ids
        if asset_id
        for asset in [db.get(ExternalAgentDiscoveredAsset, asset_id)]
        if asset
        and asset.connection_id == str(bridge.get("connection_id") or "")
        and asset.selected
        and asset.callable
    ]
    if not assets:
        raise HTTPException(status_code=409, detail="成交服务的外接能力快照当前不可调用")
    asset = max(assets, key=lambda item: _capability_affinity(node.name, item))
    service_data = dict(order.snapshot_json.get("service") or {})
    service_snapshot = dict(service_data.get("snapshot") or {})
    requirement = dict(order.snapshot_json.get("requirement") or {})
    quote = dict(order.snapshot_json.get("quote") or {})
    declared_permissions = set(asset.permissions_json or [])
    granted_permissions = sorted(
        declared_permissions.intersection(service_snapshot.get("data_permissions") or [])
    )
    attachment_refs = [
        str(item.get("file_id") or item.get("storage_key") or item.get("ref") or "")
        for item in requirement.get("attachments") or []
        if isinstance(item, dict)
    ]
    attachment_refs = [item for item in attachment_refs if item]

    from app.external_agents.schemas import ExternalTaskCreateRequest
    from app.external_agents.service import enqueue_execution_external_task

    task = enqueue_execution_external_task(
        db,
        current_user,
        ExternalTaskCreateRequest(
            connection_id=str(bridge.get("connection_id") or ""),
            capability_asset_id=asset.id,
            goal=(
                f"为订单「{order.title}」执行里程碑「{milestone.name}」的"
                f"节点「{node.name}」，严格遵守成交范围和验收标准。"
            ),
            input={
                "schema_version": "order-execution-v1",
                "order": {"id": order.id, "code": order.code, "title": order.title},
                "milestone": {
                    "id": milestone.id,
                    "name": milestone.name,
                    "description": milestone.description,
                    "input_materials": milestone.input_materials_json,
                    "deliverables": milestone.deliverables_json,
                    "acceptance_criteria": milestone.acceptance_criteria_json,
                },
                "execution": {
                    "run_id": run.id,
                    "node_key": node.node_key,
                    "node_name": node.name,
                    "attempt": node.attempt,
                },
                "requirement": requirement,
                "contracted_scope": quote.get("service_scope") or [],
                "contracted_exclusions": quote.get("exclusions") or [],
            },
            attachment_refs=attachment_refs,
            permission_grants=granted_permissions,
            output_schema=dict(asset.output_schema_json or {}),
            idempotency_key=f"execution:{run.id}:node:{node.node_key}:attempt:{node.attempt}",
            order_id=order.id,
            milestone_id=milestone.id,
            execution_run_id=run.id,
            timeout_seconds=max(1800, min(86400, milestone.duration_days * 86400)),
            max_attempts=3,
            requires_approval=asset.risk_level == "high",
        ),
    )
    _append_event(
        db,
        run,
        "external_agent.task_queued",
        f"外接员工已领取执行准备：{node.name}",
        node_run_id=node.id,
        event_id=f"external-task-queued:{task.id}",
        public_payload={"task_id": task.id, "node_key": node.node_key},
        internal_payload={
            "connection_id": task.connection_id,
            "capability_asset_id": task.capability_asset_id,
        },
        actor_type="platform",
        actor_user_id=current_user.id,
    )
    return task


def _capability_affinity(node_name: str, asset: ExternalAgentDiscoveredAsset) -> int:
    haystack = f"{asset.name} {asset.description} {asset.external_id}".lower()
    normalized = "".join(node_name.lower().split())
    if normalized and normalized in haystack:
        return 100
    pairs = {
        normalized[index : index + 2]
        for index in range(max(0, len(normalized) - 1))
    }
    return sum(pair in haystack for pair in pairs)


def _normalize_nodes(
    content: dict[str, Any], milestone: TransactionOrderMilestone
) -> list[dict[str, Any]]:
    rows = content.get("nodes") if isinstance(content.get("nodes"), list) else []
    nodes: list[dict[str, Any]] = []
    for index, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("node_id") or raw.get("id") or f"node_{index}")
        name = str(raw.get("label") or raw.get("name") or raw.get("title") or f"步骤 {index}")
        nodes.append(
            {
                "key": key,
                "sequence": index,
                "name": name,
                "public_description": str(
                    raw.get("public_description")
                    or raw.get("description")
                    or "正在按照已确认的服务流程执行"
                ),
                "execution_mode": "agent",
                "requires_confirmation": bool(raw.get("requires_confirmation", False)),
            }
        )
    if nodes:
        return nodes
    return [
        {
            "key": "validate_inputs",
            "sequence": 1,
            "name": "核验输入材料",
            "public_description": "核验里程碑所需材料是否齐全",
            "execution_mode": "agent",
            "requires_confirmation": False,
        },
        {
            "key": "execute_service",
            "sequence": 2,
            "name": f"执行「{milestone.name}」",
            "public_description": "AI 员工根据成交范围执行任务",
            "execution_mode": "agent",
            "requires_confirmation": False,
        },
        {
            "key": "provider_review",
            "sequence": 3,
            "name": "乙方内部审核",
            "public_description": "服务方检查结果与验收标准的一致性",
            "execution_mode": "human",
            "requires_confirmation": True,
        },
        {
            "key": "prepare_delivery",
            "sequence": 4,
            "name": "准备交付",
            "public_description": "整理交付物并准备提交",
            "execution_mode": "agent",
            "requires_confirmation": False,
        },
    ]


def _freeze_sop(
    db: Session,
    current_user: User,
    order: TransactionOrder,
    milestone: TransactionOrderMilestone,
) -> TransactionOrderSOPSnapshot:
    existing = db.exec(
        select(TransactionOrderSOPSnapshot).where(
            TransactionOrderSOPSnapshot.order_id == order.id,
            TransactionOrderSOPSnapshot.milestone_id == milestone.id,
        )
    ).first()
    if existing:
        return existing

    agent_id = _agent_for_order(db, order)
    resolved_sop = None
    if agent_id:
        requested_version = (
            dict(order.snapshot_json.get("service") or {})
            .get("snapshot", {})
            .get("sop_version")
        )
        resolved_sop = get_staffdeck_gateway(db).resolve_sop_definition(
            SOPDefinitionRequest(
                tenant_id=order.tenant_id,
                agent_id=agent_id,
                requested_version=str(requested_version) if requested_version else None,
            )
        )

    content = (
        {
            "name": resolved_sop.name,
            "nodes": resolved_sop.nodes,
            "edges": resolved_sop.edges,
        }
        if resolved_sop
        else {}
    )
    nodes = _normalize_nodes(content, milestone)
    definition = {
        "schema_version": "order-sop-v1",
        "order_id": order.id,
        "milestone_id": milestone.id,
        "source": "staffdeck_skill" if resolved_sop else "contract_fallback",
        "source_skill_id": resolved_sop.source_skill_id if resolved_sop else None,
        "source_skill_version": (
            resolved_sop.source_skill_version if resolved_sop else "order-v1"
        ),
        "nodes": nodes,
        "edges": content.get("edges", []),
    }
    summary = {
        "name": str(content.get("name") or f"{milestone.name} 执行流程"),
        "version": definition["source_skill_version"],
        "node_count": len(nodes),
        "nodes": [
            {
                "key": node["key"],
                "sequence": node["sequence"],
                "name": node["name"],
                "description": node["public_description"],
            }
            for node in nodes
        ],
        "privacy_notice": "甲方仅可查看执行进度摘要，不可查看提示词、知识库、密钥和内部成本",
    }
    snapshot = TransactionOrderSOPSnapshot(
        tenant_id=order.tenant_id,
        order_id=order.id,
        milestone_id=milestone.id,
        agent_profile_id=agent_id,
        source_skill_id=resolved_sop.source_skill_id if resolved_sop else None,
        source_skill_version=str(definition["source_skill_version"]),
        definition_digest=_digest(definition),
        definition_json=definition,
        public_summary_json=summary,
        frozen_by_user_id=current_user.id,
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _next_sequence(db: Session, run_id: str) -> int:
    value = db.exec(
        select(func.max(TransactionExecutionEvent.sequence)).where(
            TransactionExecutionEvent.execution_run_id == run_id
        )
    ).one()
    return int(value or 0) + 1


def _append_event(
    db: Session,
    run: TransactionExecutionRun,
    event_type: str,
    summary: str,
    *,
    node_run_id: str | None = None,
    command_id: str | None = None,
    event_id: str | None = None,
    source_sequence: int | None = None,
    public_payload: dict[str, Any] | None = None,
    internal_payload: dict[str, Any] | None = None,
    actor_type: str = "user",
    actor_user_id: str | None = None,
) -> TransactionExecutionEvent:
    row = TransactionExecutionEvent(
        tenant_id=run.tenant_id,
        execution_run_id=run.id,
        node_run_id=node_run_id,
        event_id=event_id or new_id("execution_event"),
        command_id=command_id,
        sequence=_next_sequence(db, run.id),
        source_sequence=source_sequence,
        event_type=event_type,
        public_summary=summary,
        public_payload_json=public_payload or {},
        internal_payload_json=internal_payload or {},
        actor_type=actor_type,
        actor_user_id=actor_user_id,
    )
    db.add(row)
    db.flush()
    return row


def _append_outbox(
    db: Session,
    run: TransactionExecutionRun,
    event_type: str,
    idempotency_key: str,
    payload: dict[str, Any],
) -> None:
    existing = db.exec(
        select(TransactionOutboxEvent).where(
            TransactionOutboxEvent.idempotency_key == idempotency_key
        )
    ).first()
    if existing:
        return
    db.add(
        TransactionOutboxEvent(
            tenant_id=run.tenant_id,
            aggregate_type="execution_run",
            aggregate_id=run.id,
            event_type=event_type,
            idempotency_key=idempotency_key,
            payload_json=payload,
        )
    )


def start_execution(
    db: Session,
    current_user: User,
    order_id: str,
    request: ExecutionStartRequest,
) -> ExecutionRunRead:
    order, perspective, membership = _require_order_party(
        db, current_user, order_id, request.organization_id
    )
    if perspective != "provider" or not _is_manager(membership):
        raise HTTPException(status_code=403, detail="仅乙方负责人可以启动 SOP")
    if order.status not in {"paid", "in_progress"}:
        raise HTTPException(status_code=409, detail="当前订单状态不能启动 SOP")
    milestone = db.get(TransactionOrderMilestone, request.milestone_id)
    if not milestone or milestone.order_id != order.id:
        raise HTTPException(status_code=404, detail="里程碑不存在")

    existing = db.exec(
        select(TransactionExecutionRun).where(
            TransactionExecutionRun.tenant_id == current_user.tenant_id,
            TransactionExecutionRun.start_command_id == request.command_id,
        )
    ).first()
    if existing:
        return _run_read(db, current_user, existing, perspective, membership)

    active = db.exec(
        select(TransactionExecutionRun).where(
            TransactionExecutionRun.order_id == order.id,
            TransactionExecutionRun.milestone_id == milestone.id,
            TransactionExecutionRun.status.in_(ACTIVE_RUN_STATES),
        )
    ).first()
    if active:
        return _run_read(db, current_user, active, perspective, membership)

    package = None
    if request.skill_package_version_id:
        package = db.get(TransactionSkillPackageVersion, request.skill_package_version_id)
        if not package or package.tenant_id != order.tenant_id:
            raise HTTPException(status_code=404, detail="Skill 固定版本不存在")
        if package.status != "approved":
            raise HTTPException(status_code=409, detail="只能运行已通过平台审核的 Skill 版本")
        if package.execution_policy == "hosted":
            from app.config import get_settings

            if not get_settings().hosted_skill_execution_enabled:
                raise HTTPException(status_code=503, detail="平台托管第三方 Skill 执行尚未启用")

    snapshot = _freeze_sop(db, current_user, order, milestone)
    nodes = list(snapshot.definition_json.get("nodes") or [])
    if not nodes:
        raise HTTPException(status_code=409, detail="SOP 快照不包含可执行节点")
    first = nodes[0]
    now = utc_now()
    run = TransactionExecutionRun(
        tenant_id=order.tenant_id,
        order_id=order.id,
        milestone_id=milestone.id,
        sop_snapshot_id=snapshot.id,
        skill_package_version_id=package.id if package else None,
        agent_profile_id=snapshot.agent_profile_id,
        status="running",
        start_command_id=request.command_id,
        current_node_key=str(first["key"]),
        progress_percent=0,
        started_by_user_id=current_user.id,
        started_at=now,
    )
    db.add(run)
    db.flush()
    for item in nodes:
        db.add(
            TransactionExecutionNodeRun(
                tenant_id=order.tenant_id,
                execution_run_id=run.id,
                node_key=str(item["key"]),
                sequence=int(item["sequence"]),
                name=str(item["name"]),
                status="running" if item is first else "pending",
                execution_mode=str(item.get("execution_mode") or "agent"),
                public_summary=(
                    "正在执行"
                    if item is first
                    else str(item.get("public_description") or "等待执行")
                ),
                started_at=now if item is first else None,
            )
        )
    _append_event(
        db,
        run,
        "run.started",
        "SOP 已启动，开始执行第一个节点",
        command_id=request.command_id,
        public_payload={"sop_digest": snapshot.definition_digest},
        actor_user_id=current_user.id,
    )
    _append_outbox(
        db,
        run,
        "execution.start.requested",
        f"execution-start:{request.command_id}",
        {
            "execution_run_id": run.id,
            "order_id": order.id,
            "milestone_id": milestone.id,
            "sop_snapshot_id": snapshot.id,
            "sop_digest": snapshot.definition_digest,
            "skill_package_version_id": package.id if package else None,
            "skill_package_digest": package.digest if package else None,
        },
    )
    _enqueue_external_node_task(db, current_user, order, milestone, run)
    if milestone.status == "pending":
        milestone.status = "in_progress"
        milestone.updated_at = now
        db.add(milestone)
    if order.status == "paid":
        order.status = "in_progress"
        order.updated_at = now
        db.add(order)
    db.commit()
    db.refresh(run)
    return _run_read(db, current_user, run, perspective, membership)


def command_execution(
    db: Session,
    current_user: User,
    run_id: str,
    request: ExecutionCommandRequest,
) -> ExecutionRunRead:
    run = db.get(TransactionExecutionRun, run_id)
    if not run or run.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    _, perspective, membership = _require_order_party(
        db, current_user, run.order_id, request.organization_id
    )
    if perspective != "provider" or not _is_manager(membership):
        raise HTTPException(status_code=403, detail="仅乙方负责人可以控制执行")
    duplicate = db.exec(
        select(TransactionExecutionEvent).where(
            TransactionExecutionEvent.command_id == request.command_id
        )
    ).first()
    if duplicate:
        return _run_read(db, current_user, run, perspective, membership)

    now = utc_now()
    node = _command_node(db, run, request.node_run_id)
    summary = request.summary.strip()
    if request.action == "pause":
        if run.status != "running":
            raise HTTPException(status_code=409, detail="只有执行中的任务可以暂停")
        run.status = "paused"
        run.paused_at = now
        summary = summary or "乙方已暂停 SOP 执行"
    elif request.action == "resume":
        if run.status != "paused":
            raise HTTPException(status_code=409, detail="只有已暂停的任务可以恢复")
        run.status = "running"
        run.paused_at = None
        summary = summary or "乙方已恢复 SOP 执行"
    elif request.action == "cancel":
        if run.status in TERMINAL_RUN_STATES:
            raise HTTPException(status_code=409, detail="终态任务不能取消")
        run.status = "cancelled"
        run.completed_at = now
        if node and node.status not in {"succeeded", "cancelled"}:
            node.status = "cancelled"
            node.completed_at = now
            db.add(node)
        summary = summary or "乙方已取消 SOP 执行"
    elif request.action == "takeover":
        if not node or node.status not in {"running", "failed", "waiting_confirmation"}:
            raise HTTPException(status_code=409, detail="当前节点不能人工接管")
        node.execution_mode = "human"
        node.claimed_by_user_id = current_user.id
        node.status = "running"
        node.public_summary = summary or "乙方交付人员已接管该节点"
        node.updated_at = now
        run.status = "running"
        summary = node.public_summary
        db.add(node)
    elif request.action == "retry_node":
        if not node or node.status != "failed":
            raise HTTPException(status_code=409, detail="只能重试失败节点")
        latest_attempt = db.exec(
            select(func.max(TransactionExecutionNodeRun.attempt)).where(
                TransactionExecutionNodeRun.execution_run_id == run.id,
                TransactionExecutionNodeRun.node_key == node.node_key,
            )
        ).one()
        retry = TransactionExecutionNodeRun(
            tenant_id=run.tenant_id,
            execution_run_id=run.id,
            node_key=node.node_key,
            sequence=node.sequence,
            attempt=int(latest_attempt or 1) + 1,
            name=node.name,
            status="running",
            execution_mode=node.execution_mode,
            public_summary=summary or "正在重试该节点",
            started_at=now,
        )
        db.add(retry)
        db.flush()
        node = retry
        run.status = "running"
        run.current_node_key = retry.node_key
        run.retry_count += 1
        summary = retry.public_summary
    elif request.action == "complete_node":
        if not node or node.status not in {"running", "waiting_confirmation"}:
            raise HTTPException(status_code=409, detail="当前节点不能完成")
        node.status = "succeeded"
        node.public_summary = summary or "该节点已完成"
        node.result_json = request.result
        node.completed_at = now
        node.updated_at = now
        db.add(node)
        _advance_run(db, run, node, now)
        summary = node.public_summary
    else:  # pragma: no cover - Literal protects this branch
        raise HTTPException(status_code=422, detail="未知执行命令")

    if request.action in {"retry_node", "complete_node"} and run.status == "running":
        order = db.get(TransactionOrder, run.order_id)
        milestone = db.get(TransactionOrderMilestone, run.milestone_id)
        if order and milestone:
            _enqueue_external_node_task(db, current_user, order, milestone, run)
    run.updated_at = now
    db.add(run)
    _append_event(
        db,
        run,
        f"command.{request.action}",
        summary,
        node_run_id=node.id if node else None,
        command_id=request.command_id,
        public_payload={"result": request.result} if request.result else {},
        actor_user_id=current_user.id,
    )
    _append_outbox(
        db,
        run,
        f"execution.{request.action}.requested",
        f"execution-command:{request.command_id}",
        {
            "execution_run_id": run.id,
            "action": request.action,
            "node_run_id": node.id if node else None,
        },
    )
    db.commit()
    db.refresh(run)
    return _run_read(db, current_user, run, perspective, membership)


def _command_node(
    db: Session, run: TransactionExecutionRun, node_run_id: str | None
) -> TransactionExecutionNodeRun | None:
    if node_run_id:
        node = db.get(TransactionExecutionNodeRun, node_run_id)
        if not node or node.execution_run_id != run.id:
            raise HTTPException(status_code=404, detail="执行节点不存在")
        return node
    if not run.current_node_key:
        return None
    return db.exec(
        select(TransactionExecutionNodeRun)
        .where(
            TransactionExecutionNodeRun.execution_run_id == run.id,
            TransactionExecutionNodeRun.node_key == run.current_node_key,
        )
        .order_by(TransactionExecutionNodeRun.attempt.desc())
    ).first()


def _advance_run(
    db: Session,
    run: TransactionExecutionRun,
    completed_node: TransactionExecutionNodeRun,
    now: datetime,
) -> None:
    next_node = db.exec(
        select(TransactionExecutionNodeRun)
        .where(
            TransactionExecutionNodeRun.execution_run_id == run.id,
            TransactionExecutionNodeRun.sequence > completed_node.sequence,
            TransactionExecutionNodeRun.attempt == 1,
        )
        .order_by(TransactionExecutionNodeRun.sequence)
    ).first()
    total = db.exec(
        select(func.count(TransactionExecutionNodeRun.id)).where(
            TransactionExecutionNodeRun.execution_run_id == run.id,
            TransactionExecutionNodeRun.attempt == 1,
        )
    ).one()
    if next_node:
        waiting_for_provider = next_node.execution_mode == "human"
        next_node.status = "waiting_confirmation" if waiting_for_provider else "running"
        next_node.started_at = now
        next_node.public_summary = "等待乙方人工复核" if waiting_for_provider else "正在执行"
        next_node.updated_at = now
        db.add(next_node)
        run.current_node_key = next_node.node_key
        run.status = "waiting_confirmation" if waiting_for_provider else "running"
        run.progress_percent = int(completed_node.sequence / max(int(total), 1) * 100)
    else:
        run.current_node_key = None
        run.status = "succeeded"
        run.progress_percent = 100
        run.completed_at = now
        run.result_summary_json = {"summary": "SOP 执行已完成，等待乙方提交交付物"}


def apply_external_task_result(db: Session, task: ExternalAgentTask) -> None:
    """Project a terminal external-Agent result onto the frozen order SOP."""

    if not task.execution_run_id or task.status not in {"succeeded", "failed", "cancelled"}:
        return
    run = db.get(TransactionExecutionRun, task.execution_run_id)
    if not run or run.order_id != task.order_id or run.milestone_id != task.milestone_id:
        raise HTTPException(status_code=409, detail="外接任务与订单执行批次关联不一致")
    event_id = f"external-task-result:{task.id}:{task.result_idempotency_key or task.status}"
    duplicate = db.exec(
        select(TransactionExecutionEvent).where(TransactionExecutionEvent.event_id == event_id)
    ).first()
    if duplicate:
        return
    execution_input = task.input_json.get("execution")
    node_key = (
        str(execution_input.get("node_key") or "")
        if isinstance(execution_input, dict)
        else ""
    )
    node = db.exec(
        select(TransactionExecutionNodeRun)
        .where(
            TransactionExecutionNodeRun.execution_run_id == run.id,
            TransactionExecutionNodeRun.node_key == node_key,
        )
        .order_by(TransactionExecutionNodeRun.attempt.desc())
    ).first()
    if not node:
        raise HTTPException(status_code=409, detail="外接任务对应的 SOP 节点不存在")
    now = utc_now()
    public_result = {
        "output": task.output_json,
        "artifacts": task.artifact_refs_json,
        "receipt_id": task.result_receipt_id,
    }
    if task.status == "succeeded":
        node.status = "succeeded"
        node.public_summary = "外接员工已完成该执行节点"
        node.result_json = public_result
        node.internal_detail_json = {
            "external_task_id": task.id,
            "connection_id": task.connection_id,
            "capability_external_id": task.capability_external_id,
        }
        node.completed_at = now
        node.updated_at = now
        db.add(node)
        _advance_run(db, run, node, now)
        if run.status == "succeeded":
            run.result_summary_json = public_result
        elif run.status == "running":
            order = db.get(TransactionOrder, run.order_id)
            milestone = db.get(TransactionOrderMilestone, run.milestone_id)
            actor = db.get(User, task.created_by_user_id)
            if order and milestone and actor:
                try:
                    _enqueue_external_node_task(db, actor, order, milestone, run)
                except HTTPException as exc:
                    run.status = "failed"
                    run.internal_error_json = {
                        "code": "external_agent_next_node_unavailable",
                        "detail": exc.detail,
                    }
    else:
        node.status = task.status
        node.public_summary = (
            "外接员工执行失败，等待乙方处理"
            if task.status == "failed"
            else "外接员工任务已取消"
        )
        node.result_json = public_result
        node.internal_detail_json = {
            "external_task_id": task.id,
            "error": task.error_json,
        }
        node.completed_at = now
        node.updated_at = now
        run.status = task.status
        run.internal_error_json = task.error_json
        run.completed_at = now
        db.add(node)
    run.updated_at = now
    db.add(run)
    _append_event(
        db,
        run,
        f"external_agent.task_{task.status}",
        node.public_summary,
        node_run_id=node.id,
        event_id=event_id,
        public_payload=public_result,
        internal_payload={
            "external_task_id": task.id,
            "connection_id": task.connection_id,
            "error": task.error_json,
        },
        actor_type="external_agent",
    )


def receive_internal_event(
    db: Session, request: InternalExecutionEventRequest
) -> InternalEventReceipt:
    run = db.get(TransactionExecutionRun, request.execution_run_id)
    if not run or run.tenant_id != request.tenant_id:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    duplicate = db.exec(
        select(TransactionExecutionEvent).where(
            TransactionExecutionEvent.event_id == request.event_id
        )
    ).first()
    if duplicate:
        return InternalEventReceipt(
            accepted=True,
            duplicate=True,
            stale=False,
            execution_run_id=run.id,
            last_source_sequence=run.last_source_sequence,
        )
    stale = request.source_sequence <= run.last_source_sequence
    node = None
    if request.node_key:
        node = db.exec(
            select(TransactionExecutionNodeRun)
            .where(
                TransactionExecutionNodeRun.execution_run_id == run.id,
                TransactionExecutionNodeRun.node_key == request.node_key,
            )
            .order_by(TransactionExecutionNodeRun.attempt.desc())
        ).first()
    _append_event(
        db,
        run,
        request.event_type,
        request.public_summary,
        node_run_id=node.id if node else None,
        event_id=request.event_id,
        source_sequence=request.source_sequence,
        public_payload=request.public_payload,
        internal_payload={**request.internal_payload, "stale": stale},
        actor_type="staffdeck",
    )
    if not stale:
        _apply_internal_projection(db, run, node, request)
        run.last_source_sequence = request.source_sequence
        run.updated_at = utc_now()
        db.add(run)
    db.commit()
    return InternalEventReceipt(
        accepted=True,
        duplicate=False,
        stale=stale,
        execution_run_id=run.id,
        last_source_sequence=run.last_source_sequence,
    )


def _apply_internal_projection(
    db: Session,
    run: TransactionExecutionRun,
    node: TransactionExecutionNodeRun | None,
    request: InternalExecutionEventRequest,
) -> None:
    now = utc_now()
    run_state = {
        "run.started": "running",
        "run.paused": "paused",
        "run.resumed": "running",
        "run.succeeded": "succeeded",
        "run.failed": "failed",
        "run.cancelled": "cancelled",
    }.get(request.event_type)
    if run_state:
        run.status = run_state
        if run_state in TERMINAL_RUN_STATES:
            run.completed_at = now
        if run_state == "succeeded":
            run.progress_percent = 100
            run.current_node_key = None
            run.result_summary_json = request.public_payload
        if run_state == "failed":
            run.internal_error_json = request.internal_payload
    if request.event_type == "progress.updated":
        progress = request.public_payload.get("progress_percent")
        if isinstance(progress, int):
            run.progress_percent = min(max(progress, 0), 100)
    node_state = {
        "node.started": "running",
        "node.waiting_confirmation": "waiting_confirmation",
        "node.succeeded": "succeeded",
        "node.failed": "failed",
    }.get(request.event_type)
    if node and node_state:
        node.status = node_state
        node.public_summary = request.public_summary
        node.result_json = request.public_payload
        node.internal_detail_json = request.internal_payload
        if node_state == "running" and not node.started_at:
            node.started_at = now
        if node_state in {"succeeded", "failed"}:
            node.completed_at = now
        node.updated_at = now
        run.current_node_key = node.node_key
        db.add(node)


def get_order_execution(
    db: Session,
    current_user: User,
    order_id: str,
    organization_id: str,
) -> OrderExecutionRead:
    order, perspective, membership = _require_order_party(
        db, current_user, order_id, organization_id
    )
    rows = db.exec(
        select(TransactionExecutionRun)
        .where(TransactionExecutionRun.order_id == order.id)
        .order_by(TransactionExecutionRun.started_at.desc())
    ).all()
    reads = [_run_read(db, current_user, row, perspective, membership) for row in rows]
    current = next((item for item in reads if item.status in ACTIVE_RUN_STATES), None)
    can_start = bool(
        perspective == "provider"
        and _is_manager(membership)
        and order.status in {"paid", "in_progress"}
        and current is None
    )
    return OrderExecutionRead(
        perspective=perspective,
        current=current or (reads[0] if reads else None),
        history=reads,
        can_start=can_start,
    )


def _run_read(
    db: Session,
    current_user: User,
    run: TransactionExecutionRun,
    perspective: str,
    membership: OrganizationMember,
) -> ExecutionRunRead:
    snapshot = db.get(TransactionOrderSOPSnapshot, run.sop_snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=500, detail="执行记录缺少 SOP 快照")
    package = (
        db.get(TransactionSkillPackageVersion, run.skill_package_version_id)
        if run.skill_package_version_id
        else None
    )
    nodes = db.exec(
        select(TransactionExecutionNodeRun)
        .where(TransactionExecutionNodeRun.execution_run_id == run.id)
        .order_by(
            TransactionExecutionNodeRun.sequence,
            TransactionExecutionNodeRun.attempt,
        )
    ).all()
    events = db.exec(
        select(TransactionExecutionEvent)
        .where(TransactionExecutionEvent.execution_run_id == run.id)
        .order_by(TransactionExecutionEvent.sequence.desc())
    ).all()
    provider_manager = perspective == "provider" and _is_manager(membership)
    return ExecutionRunRead(
        id=run.id,
        order_id=run.order_id,
        milestone_id=run.milestone_id,
        status=run.status,
        progress_percent=run.progress_percent,
        current_node_key=run.current_node_key,
        agent_profile_id=run.agent_profile_id,
        skill_package_version_id=run.skill_package_version_id,
        skill_package_digest=package.digest if package else None,
        sop_snapshot=SOPSnapshotRead(
            id=snapshot.id,
            source_skill_id=snapshot.source_skill_id if provider_manager else None,
            source_skill_version=snapshot.source_skill_version,
            definition_digest=snapshot.definition_digest,
            summary=snapshot.public_summary_json,
            frozen_at=snapshot.frozen_at,
        ),
        nodes=[
            ExecutionNodeRead(
                id=node.id,
                node_key=node.node_key,
                sequence=node.sequence,
                attempt=node.attempt,
                name=node.name,
                status=node.status,
                execution_mode=node.execution_mode,
                public_summary=node.public_summary,
                result=node.result_json,
                internal_detail=node.internal_detail_json if provider_manager else None,
                claimed_by=_user_name(db.get(User, node.claimed_by_user_id))
                if node.claimed_by_user_id
                else None,
                started_at=node.started_at,
                completed_at=node.completed_at,
            )
            for node in nodes
        ],
        events=[
            ExecutionEventRead(
                event_id=event.event_id,
                sequence=event.sequence,
                event_type=event.event_type,
                public_summary=event.public_summary,
                payload=event.public_payload_json,
                actor_type=event.actor_type,
                created_at=event.created_at,
            )
            for event in events
        ],
        capabilities=ExecutionCapabilitiesRead(
            can_start=False,
            can_pause=provider_manager and run.status == "running",
            can_resume=provider_manager and run.status == "paused",
            can_cancel=provider_manager and run.status not in TERMINAL_RUN_STATES,
            can_retry=provider_manager and any(node.status == "failed" for node in nodes),
            can_takeover=provider_manager
            and any(
                node.node_key == run.current_node_key
                and node.status in {"running", "failed", "waiting_confirmation"}
                for node in nodes
            ),
            can_complete_node=provider_manager
            and any(
                node.node_key == run.current_node_key
                and node.status in {"running", "waiting_confirmation"}
                for node in nodes
            ),
        ),
        started_at=run.started_at,
        paused_at=run.paused_at,
        completed_at=run.completed_at,
    )


def import_skill_package(
    db: Session, current_user: User, request: SkillPackageImportRequest
) -> SkillPackageRead:
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="仅平台管理员可导入第三方 Skill")
    immutable = {
        "slug": request.slug,
        "version": request.version,
        "runtime": request.runtime,
        "entrypoint": request.entrypoint,
        "manifest": request.manifest,
        "permissions": request.permissions,
        "package": request.package_snapshot,
    }
    digest = _digest(immutable)
    existing = db.exec(
        select(TransactionSkillPackageVersion).where(
            TransactionSkillPackageVersion.tenant_id == current_user.tenant_id,
            TransactionSkillPackageVersion.digest == digest,
        )
    ).first()
    if existing:
        return _package_read(existing)
    same_version = db.exec(
        select(TransactionSkillPackageVersion).where(
            TransactionSkillPackageVersion.tenant_id == current_user.tenant_id,
            TransactionSkillPackageVersion.slug == request.slug,
            TransactionSkillPackageVersion.version == request.version,
        )
    ).first()
    if same_version:
        raise HTTPException(status_code=409, detail="该 Skill 版本已存在且内容 digest 不同")
    package = TransactionSkillPackageVersion(
        tenant_id=current_user.tenant_id,
        provider_organization_id=request.organization_id,
        slug=request.slug,
        name=request.name,
        version=request.version,
        digest=digest,
        source_uri=request.source_uri,
        runtime=request.runtime,
        entrypoint=request.entrypoint,
        manifest_json=request.manifest,
        permissions_json=request.permissions,
        package_snapshot_json=request.package_snapshot,
        imported_by_user_id=current_user.id,
    )
    db.add(package)
    db.commit()
    db.refresh(package)
    return _package_read(package)


def upload_skill_package(
    db: Session,
    current_user: User,
    *,
    organization_id: str,
    slug: str,
    name: str,
    version: str,
    runtime: str,
    entrypoint: str,
    manifest: dict[str, Any],
    permissions: dict[str, Any],
    execution_policy: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> SkillPackageRead:
    if not SKILL_SLUG_PATTERN.fullmatch(slug):
        raise HTTPException(status_code=422, detail="Skill 标识只能包含小写字母、数字、点、下划线和短横线")
    if not is_admin_user(current_user):
        membership = _membership(db, current_user, organization_id)
        if not _is_manager(membership):
            raise HTTPException(status_code=403, detail="仅服务方负责人可上传 Skill 包")
    if runtime not in {"python", "node"}:
        raise HTTPException(status_code=422, detail="包上传仅支持 python 或 node；远程 API 请使用登记接口")
    if execution_policy not in {"external", "hosted"}:
        raise HTTPException(status_code=422, detail="包执行策略必须为 external 或 hosted")
    if not data:
        raise HTTPException(status_code=422, detail="Skill 包不能为空")

    digest = hashlib.sha256(data).hexdigest()
    same_version = db.exec(
        select(TransactionSkillPackageVersion).where(
            TransactionSkillPackageVersion.tenant_id == current_user.tenant_id,
            TransactionSkillPackageVersion.slug == slug,
            TransactionSkillPackageVersion.version == version,
        )
    ).first()
    if same_version:
        if same_version.digest == digest:
            return _package_read(same_version)
        raise HTTPException(status_code=409, detail="该 Skill 版本已冻结，不能用不同内容覆盖")

    scan = scan_skill_package(
        data,
        filename=filename,
        runtime=runtime,
        entrypoint=entrypoint,
        permissions=permissions,
    )
    safe_filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename.rsplit("/", 1)[-1]) or "skill.zip"
    storage_key = f"skill-packages/{current_user.tenant_id}/{slug}/{version}/{digest}/{safe_filename}"
    store = get_order_object_store()
    try:
        store.put(storage_key, data, content_type or "application/zip")
    except ObjectAlreadyExistsError:
        # 内容寻址键天然幂等；数据库事务可能在对象写入后重试。
        pass
    status = "scan_failed"
    if scan.passed:
        status = "pending_security_review" if scan.risk_level == "high" else "pending_review"
    package = TransactionSkillPackageVersion(
        tenant_id=current_user.tenant_id,
        provider_organization_id=organization_id,
        slug=slug,
        name=name,
        version=version,
        digest=digest,
        source_uri=f"object://{storage_key}",
        runtime=runtime,
        entrypoint=entrypoint,
        status=status,
        manifest_json=manifest,
        permissions_json=permissions,
        package_snapshot_json={
            "sha256": digest,
            "storage_key": storage_key,
            "files": scan.report.get("files", []),
        },
        storage_provider=store.provider_name,
        storage_key=storage_key,
        original_filename=safe_filename,
        content_type=content_type or "application/zip",
        size_bytes=len(data),
        scan_status="passed" if scan.passed else "failed",
        scan_report_json=scan.report,
        risk_level=scan.risk_level,
        execution_policy=execution_policy,
        imported_by_user_id=current_user.id,
    )
    db.add(package)
    db.flush()
    db.add(
        MarketplaceAuditLog(
            tenant_id=current_user.tenant_id,
            organization_id=organization_id,
            actor_user_id=current_user.id,
            action="skill_package.uploaded",
            target_type="skill_package_version",
            target_id=package.id,
            payload_json={
                "slug": slug,
                "version": version,
                "sha256": digest,
                "scan_status": package.scan_status,
                "risk_level": package.risk_level,
            },
        )
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        store.delete(storage_key)
        raise
    db.refresh(package)
    return _package_read(package)


def get_skill_package_download(
    db: Session,
    current_user: User,
    package_id: str,
    organization_id: str | None,
) -> tuple[TransactionSkillPackageVersion, DownloadTarget]:
    package = db.get(TransactionSkillPackageVersion, package_id)
    if not package or package.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Skill 固定版本不存在")
    if not package.storage_key:
        raise HTTPException(status_code=409, detail="该历史记录没有平台托管的包文件")
    if not is_admin_user(current_user):
        if not organization_id or organization_id != package.provider_organization_id:
            raise HTTPException(status_code=403, detail="无权下载该 Skill 包")
        _membership(db, current_user, organization_id)
    store = get_order_object_store(package.storage_provider)
    target = store.download_target(
        package.storage_key,
        package.original_filename or f"{package.slug}-{package.version}.zip",
        package.content_type,
    )
    return package, target


def review_skill_package(
    db: Session,
    current_user: User,
    package_id: str,
    request: SkillReviewRequest,
) -> SkillPackageRead:
    if not is_admin_user(current_user):
        raise HTTPException(status_code=403, detail="仅平台管理员可审核第三方 Skill")
    package = db.get(TransactionSkillPackageVersion, package_id)
    if not package or package.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Skill 固定版本不存在")
    if package.storage_key:
        if package.scan_status != "passed":
            raise HTTPException(status_code=409, detail="安全扫描未通过，不能进入审核")
        if package.imported_by_user_id == current_user.id:
            raise HTTPException(status_code=409, detail="上传人不能审核自己的 Skill 包")
        if request.review_stage == "security" and package.risk_level != "high":
            raise HTTPException(status_code=409, detail="低/中风险包不需要独立安全复核")
        if package.risk_level == "high" and request.review_stage == "platform":
            security_review = db.exec(
                select(TransactionSkillReview)
                .where(
                    TransactionSkillReview.skill_package_version_id == package.id,
                    TransactionSkillReview.review_stage == "security",
                    TransactionSkillReview.decision == "approved",
                )
                .order_by(TransactionSkillReview.created_at.desc())
            ).first()
            if not security_review:
                raise HTTPException(status_code=409, detail="高风险包必须先通过独立安全复核")
            if security_review.reviewed_by_user_id == current_user.id:
                raise HTTPException(status_code=409, detail="高风险包的平台审核必须由另一名管理员完成")
    if request.decision == "rejected":
        package.status = "rejected"
    elif request.review_stage == "security":
        package.status = "pending_review"
    else:
        package.status = "approved"
    package.reviewed_at = utc_now()
    package.updated_at = utc_now()
    db.add(package)
    db.add(
        TransactionSkillReview(
            tenant_id=current_user.tenant_id,
            skill_package_version_id=package.id,
            decision=request.decision,
            review_stage=request.review_stage,
            reviewer_comment=request.reviewer_comment,
            security_checks_json=request.security_checks,
            reviewed_by_user_id=current_user.id,
        )
    )
    db.add(
        MarketplaceAuditLog(
            tenant_id=current_user.tenant_id,
            organization_id=package.provider_organization_id,
            actor_user_id=current_user.id,
            action=f"skill_package.{request.review_stage}_{request.decision}",
            target_type="skill_package_version",
            target_id=package.id,
            payload_json={"comment": request.reviewer_comment, "risk_level": package.risk_level},
        )
    )
    db.commit()
    db.refresh(package)
    return _package_read(package)


def list_skill_packages(
    db: Session,
    current_user: User,
    organization_id: str | None,
) -> list[SkillPackageRead]:
    query = select(TransactionSkillPackageVersion).where(
        TransactionSkillPackageVersion.tenant_id == current_user.tenant_id
    )
    if not is_admin_user(current_user):
        if not organization_id:
            query = query.where(TransactionSkillPackageVersion.status == "approved")
        else:
            _membership(db, current_user, organization_id)
            query = query.where(
                (TransactionSkillPackageVersion.status == "approved")
                | (TransactionSkillPackageVersion.provider_organization_id == organization_id)
            )
    rows = db.exec(query.order_by(TransactionSkillPackageVersion.created_at.desc())).all()
    return [_package_read(row) for row in rows]


def _package_read(package: TransactionSkillPackageVersion) -> SkillPackageRead:
    return SkillPackageRead(
        id=package.id,
        provider_organization_id=package.provider_organization_id,
        slug=package.slug,
        name=package.name,
        version=package.version,
        digest=package.digest,
        source_uri=package.source_uri,
        runtime=package.runtime,
        entrypoint=package.entrypoint,
        status=package.status,
        manifest=package.manifest_json,
        permissions=package.permissions_json,
        storage_provider=package.storage_provider,
        original_filename=package.original_filename,
        size_bytes=package.size_bytes,
        scan_status=package.scan_status,
        scan_report=package.scan_report_json,
        risk_level=package.risk_level,
        execution_policy=package.execution_policy,
        immutable=True,
        reviewed_at=package.reviewed_at,
        created_at=package.created_at,
    )


def _user_name(user: User | None) -> str:
    if not user:
        return "未知成员"
    return user.display_name or user.username
