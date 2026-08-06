from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    AgentProfile,
    ExternalAgentConnection,
    ExternalAgentCredential,
    ExternalAgentDiscoveredAsset,
    ExternalAgentNetworkPolicy,
    ExternalAgentTask,
    MarketplaceAIService,
    MarketplaceAIServiceVersion,
    OrganizationMember,
    TransactionExecutionNodeRun,
    TransactionExecutionRun,
    TransactionOrder,
    TransactionOrderMilestone,
    TransactionRequirement,
    TransactionRequirementVersion,
    User,
    utc_now,
)
from app.execution.schemas import ExecutionStartRequest
from app.execution.service import start_execution
from app.external_agents.schemas import (
    ExternalTaskClaimRequest,
    ExternalTaskResultRequest,
)
from app.external_agents.security import ExternalAgentPrincipal
from app.external_agents.service import claim_external_task, submit_external_task_result
from app.transaction.matching import evaluate_service_candidate


def _engine() -> object:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def test_real_match_rejects_unrelated_service_and_offline_external_runtime() -> None:
    engine = _engine()
    now = utc_now()
    with Session(engine) as db:
        requirement = TransactionRequirement(
            tenant_id="tenant_match",
            code="REQ-MATCH-1",
            buyer_organization_id="org_buyer",
            created_by_user_id="buyer",
            title="融资路演 PPT 设计",
            category="演示文稿设计",
            status="matching",
            budget_min_amount=Decimal("500"),
            budget_max_amount=Decimal("3000"),
            desired_delivery_at=now + timedelta(days=7),
        )
        requirement_version = TransactionRequirementVersion(
            tenant_id="tenant_match",
            requirement_id=requirement.id,
            version=1,
            status="published",
            description="根据商业计划书设计约 20 页融资路演 PPT。",
            deliverables_json=[{"name": "融资路演演示文稿", "format": ".pptx"}],
            acceptance_criteria_json=["逻辑完整并可编辑", "视觉风格专业统一"],
            snapshot_digest="req-digest",
            created_by_user_id="buyer",
        )
        unrelated = MarketplaceAIService(
            id="service_legal",
            tenant_id="tenant_match",
            provider_id="provider_legal",
            slug="legal-review",
            name="合同审查专员",
            category="企业法务",
            description="审查合同条款和法律风险。",
            status="published",
            visibility="public",
            verified=True,
            online=True,
        )
        unrelated_version = MarketplaceAIServiceVersion(
            id="version_legal",
            tenant_id="tenant_match",
            service_id=unrelated.id,
            version="v1",
            status="published",
            price_amount=Decimal("500"),
            average_minutes=60,
            snapshot_json={
                "service_scope": ["合同条款审查", "法律风险提示"],
                "deliverables": [{"name": "合同审查报告"}],
            },
        )
        unrelated.current_version_id = unrelated_version.id

        agent = AgentProfile(
            id="agent_ppt",
            tenant_id="tenant_match",
            name="路演 PPT 设计师",
            status="active",
        )
        connection = ExternalAgentConnection(
            id="connection_ppt",
            tenant_id="tenant_match",
            organization_id="org_provider",
            agent_profile_id=agent.id,
            provider="codex",
            runtime_type="local",
            external_agent_ref="ppt-agent",
            status="available",
            health_status="online",
            last_heartbeat_at=now,
            created_by_user_id="provider",
        )
        capability = ExternalAgentDiscoveredAsset(
            id="asset_ppt",
            tenant_id="tenant_match",
            organization_id="org_provider",
            manifest_id="manifest_ppt",
            connection_id=connection.id,
            external_id="pitch-deck-design",
            kind="skill",
            name="融资路演 PPT 设计",
            description="根据商业计划书生成可编辑的演示文稿",
            callable=True,
            selected=True,
            verification_status="verified",
            output_schema_json={
                "type": "object",
                "properties": {"pptx_file": {"type": "string"}},
            },
        )
        external = MarketplaceAIService(
            id="service_ppt",
            tenant_id="tenant_match",
            provider_id="provider_ppt",
            agent_profile_id=agent.id,
            slug="pitch-deck",
            name="融资路演 PPT 设计师",
            category="演示文稿设计",
            description="完成融资路演内容梳理与视觉设计。",
            status="published",
            visibility="public",
            verified=True,
            online=True,
        )
        external_version = MarketplaceAIServiceVersion(
            id="version_ppt",
            tenant_id="tenant_match",
            service_id=external.id,
            version="v1",
            status="published",
            price_amount=Decimal("1800"),
            average_minutes=240,
            snapshot_json={
                "service_scope": ["融资故事线梳理", "PPT 视觉设计"],
                "deliverables": [{"name": "可编辑融资路演 PPT", "format": ".pptx"}],
                "external_agent_bridge": {
                    "connection_id": connection.id,
                    "capabilities": [{"asset_id": capability.id, "callable": True}],
                },
            },
        )
        external.current_version_id = external_version.id
        db.add_all(
            [
                requirement,
                requirement_version,
                unrelated,
                unrelated_version,
                agent,
                connection,
                capability,
                external,
                external_version,
                ExternalAgentNetworkPolicy(
                    tenant_id="tenant_match",
                    organization_id="org_provider",
                    connection_id=connection.id,
                    heartbeat_interval_seconds=30,
                ),
            ]
        )
        db.commit()

        unrelated_decision = evaluate_service_candidate(
            db, requirement, requirement_version, unrelated
        )
        external_decision = evaluate_service_candidate(
            db, requirement, requirement_version, external
        )
        assert unrelated_decision.eligible is True
        assert unrelated_decision.semantic_ready is False
        assert external_decision.eligible is True
        assert external_decision.semantic_ready is True
        assert external_decision.profile.capability_asset_ids == (capability.id,)

        external.online = False
        db.add(external)
        db.commit()
        offline_service_decision = evaluate_service_candidate(
            db, requirement, requirement_version, external
        )
        assert offline_service_decision.eligible is False
        assert offline_service_decision.profile.runtime_reason == "服务当前已下线"

        external.online = True
        connection.health_status = "offline"
        db.add_all([external, connection])
        db.commit()
        offline_decision = evaluate_service_candidate(
            db, requirement, requirement_version, external
        )
        assert offline_decision.eligible is False
        assert "不在线" in offline_decision.reasons[0]


def test_order_sop_dispatches_external_task_and_projects_real_result() -> None:
    engine = _engine()
    now = utc_now()
    with Session(engine) as db:
        provider = User(
            id="provider_user",
            tenant_id="tenant_exec",
            username="provider_user",
            password_hash="test",
        )
        agent = AgentProfile(
            id="agent_external",
            tenant_id="tenant_exec",
            name="外接交付员工",
            status="active",
        )
        connection = ExternalAgentConnection(
            id="connection_external",
            tenant_id="tenant_exec",
            organization_id="org_provider",
            agent_profile_id=agent.id,
            provider="codex",
            runtime_type="local",
            external_agent_ref="external-delivery-agent",
            status="available",
            health_status="online",
            last_heartbeat_at=now,
            created_by_user_id=provider.id,
        )
        capability = ExternalAgentDiscoveredAsset(
            id="asset_delivery",
            tenant_id="tenant_exec",
            organization_id="org_provider",
            manifest_id="manifest_delivery",
            connection_id=connection.id,
            external_id="document-delivery",
            kind="skill",
            name="文档分析与交付",
            description="核验输入、执行分析并生成文件",
            callable=True,
            selected=True,
            verification_status="verified",
            permissions_json=["filesystem:read:selected"],
            output_schema_json={
                "type": "object",
                "properties": {"summary": {"type": "string"}},
            },
        )
        credential = ExternalAgentCredential(
            id="credential_external",
            tenant_id="tenant_exec",
            connection_id=connection.id,
            token_digest="not-used-in-direct-principal",
            encrypted_token="encrypted",
            token_hint="direct",
            scopes_json=["tasks:claim", "events:write", "artifacts:write"],
            issuance_idempotency_key="credential-exec-test",
        )
        order = TransactionOrder(
            id="order_external",
            tenant_id="tenant_exec",
            code="ORDER-EXT-1",
            agreement_id="agreement_external",
            payment_order_id="payment_external",
            requirement_id="requirement_external",
            selected_quote_id="quote_external",
            buyer_organization_id="org_buyer",
            provider_organization_id="org_provider",
            service_id="service_external",
            title="完成一份真实分析报告",
            service_name="外接交付员工",
            status="paid",
            payment_status="paid",
            total_amount=Decimal("1000"),
            held_amount=Decimal("1000"),
            snapshot_json={
                "requirement": {
                    "title": "完成一份真实分析报告",
                    "description": "分析输入材料并生成可复核的报告。",
                    "attachments": [],
                },
                "quote": {
                    "service_scope": ["材料核验", "分析报告生成"],
                    "exclusions": [],
                },
                "service": {
                    "agent_profile_id": agent.id,
                    "snapshot": {
                        "data_permissions": ["filesystem:read:selected"],
                        "external_agent_bridge": {
                            "connection_id": connection.id,
                            "capabilities": [{"asset_id": capability.id, "callable": True}],
                        },
                    },
                },
            },
            snapshot_digest="order-external-digest",
            paid_at=now,
        )
        milestone = TransactionOrderMilestone(
            id="milestone_external",
            tenant_id="tenant_exec",
            order_id=order.id,
            sequence=1,
            name="分析与交付",
            description="核验材料并生成分析结果",
            amount=Decimal("1000"),
            duration_days=2,
            input_materials_json=["原始材料"],
            deliverables_json=["分析报告"],
            acceptance_criteria_json=["结论可追溯"],
        )
        db.add_all(
            [
                provider,
                agent,
                connection,
                capability,
                credential,
                order,
                milestone,
                OrganizationMember(
                    tenant_id="tenant_exec",
                    organization_id="org_provider",
                    user_id=provider.id,
                    role="owner",
                    roles_json=["owner"],
                    status="active",
                ),
                ExternalAgentNetworkPolicy(
                    tenant_id="tenant_exec",
                    organization_id="org_provider",
                    connection_id=connection.id,
                    heartbeat_interval_seconds=30,
                ),
            ]
        )
        db.commit()

        started = start_execution(
            db,
            provider,
            order.id,
            ExecutionStartRequest(
                organization_id="org_provider",
                milestone_id=milestone.id,
                command_id="start-external-order-0001",
            ),
        )
        first_task = db.exec(
            select(ExternalAgentTask).where(
                ExternalAgentTask.execution_run_id == started.id,
                ExternalAgentTask.status == "queued",
            )
        ).first()
        assert first_task is not None
        assert first_task.order_id == order.id
        assert first_task.milestone_id == milestone.id
        assert first_task.input_json["requirement"]["title"] == order.title
        assert first_task.permission_grants_json == ["filesystem:read:selected"]

        principal = ExternalAgentPrincipal(connection=connection, credential=credential)
        claimed = claim_external_task(
            db,
            principal,
            ExternalTaskClaimRequest(
                lease_owner="connector-worker",
                lease_seconds=120,
            ),
        )
        assert claimed.task is not None and claimed.lease_token
        receipt = submit_external_task_result(
            db,
            principal,
            claimed.task.id,
            ExternalTaskResultRequest(
                lease_owner="connector-worker",
                lease_token=claimed.lease_token,
                idempotency_key="external-result-success-0001",
                outcome="succeeded",
                output={"summary": "输入材料已核验"},
                artifact_refs=[
                    {
                        "ref": "orders/order_external/artifacts/input-check.json",
                        "name": "材料核验结果.json",
                        "media_type": "application/json",
                    }
                ],
            ),
        )
        assert receipt.status == "succeeded"

        run = db.get(TransactionExecutionRun, started.id)
        first_node = db.exec(
            select(TransactionExecutionNodeRun)
            .where(TransactionExecutionNodeRun.execution_run_id == started.id)
            .order_by(TransactionExecutionNodeRun.sequence)
        ).first()
        next_task = db.exec(
            select(ExternalAgentTask).where(
                ExternalAgentTask.execution_run_id == started.id,
                ExternalAgentTask.status == "queued",
            )
        ).first()
        assert run is not None and run.status == "running"
        assert first_node is not None and first_node.status == "succeeded"
        assert first_node.result_json["output"]["summary"] == "输入材料已核验"
        assert next_task is not None and next_task.id != first_task.id
