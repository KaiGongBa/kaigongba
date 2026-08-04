from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlmodel import Session, select

from app.db import get_session
from app.db.models import AgentProfile, ChatSession, Message, User, new_id, utc_now
from app.integrations.transaction_core.gateway import TransactionCoreGateway
from app.integrations.transaction_core.guidance_schemas import TrustedGuidanceRequest
from app.integrations.transaction_core.schemas import (
    TrustedContextResolveRequest,
    TrustedContextScopeProjection,
)
from app.llm.platform_gateway import AIModelGateway
from app.platform_assistant.business_capabilities import (
    BusinessCapabilityRegistry,
    CapabilityRegistryError,
)
from app.platform_assistant.context import (
    ContextResolutionError,
    PageContext,
    RouteContextRegistry,
    TrustedResolutionScope,
    resolve_page_context,
)
from app.platform_assistant.feature_flags import (
    AssistantFeatureFlagService,
    FeatureFlagDecision,
)
from app.platform_assistant.governance import record_governance_event
from app.platform_assistant.protocol import BlockAnswerInput, PlatformAssistantProtocolError
from app.platform_assistant.guidance import (
    feature_stage_blocks,
    guidance_blocks,
    is_guidance_request,
)
from app.platform_assistant.orchestrator import (
    AIModelGatewayAdapter,
    RequirementWorkflowOrchestrator,
)
from app.platform_assistant.requirement_models import AssistantRequirementDraft
from app.platform_assistant.runtime import (
    PlatformAssistantRuntime,
    PlatformAssistantRuntimeError,
    RuntimeResult,
    RuntimeStateError,
)
from app.platform_assistant.safety import AssistantToolRiskPolicy, ToolPolicyDecision
from app.platform_assistant.usage import (
    AssistantUsageLinkError,
    AssistantUsageScope,
    AssistantUsageService,
)
from app.platform_assistant.repository import (
    BlockNotFound,
    BlockVersionConflict,
    IdempotencyKeyConflict,
    PlatformAssistantRepository,
    RunNotFound,
    RunScope,
    RunStateConflict,
)
from app.security.auth import get_current_user


router = APIRouter(prefix="/api/platform-assistant", tags=["platform-assistant"])
DatabaseSession = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContextRequest(StrictRequest):
    protocol_version: Literal["1.0", "2.0"]
    page_context: dict[str, Any]


class CreateRunRequest(ContextRequest):
    client_request_id: str = Field(min_length=8, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    capability_id: str = Field(min_length=1, max_length=160)


class TurnRequest(ContextRequest):
    client_request_id: str = Field(min_length=8, max_length=160)
    session_id: str | None = Field(default=None, max_length=160)
    message: str = Field(min_length=1, max_length=20_000)


class AnswerRunRequest(StrictRequest):
    protocol_version: Literal["1.0", "2.0"]
    session_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=160)
    block_id: str = Field(pattern=r"^block_")
    block_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=160)
    answers: list[BlockAnswerInput] = Field(min_length=1)


class RunControlRequest(StrictRequest):
    protocol_version: Literal["1.0", "2.0"]
    session_id: str = Field(min_length=1, max_length=160)


@router.get("/capabilities")
def list_capabilities(
    current_user: CurrentUser,
    route_id: str | None = None,
) -> dict[str, Any]:
    del current_user
    try:
        routes = RouteContextRegistry.from_contract()
        capabilities = BusinessCapabilityRegistry.from_contract(
            known_route_ids=routes.route_ids
        )
        entries = capabilities.for_route(route_id) if route_id else capabilities.all()
        return {
            "protocol_version": "1.0",
            "capabilities": [
                {
                    "capability_id": item.capability_id,
                    "version": item.version,
                    "display_name": item.display_name,
                    "risk_level": item.risk_level,
                    "supported_route_ids": list(item.supported_route_ids),
                    "target_route_id": item.target_route_id,
                    "fallback_strategy": item.fallback_strategy,
                }
                for item in entries
            ],
        }
    except (CapabilityRegistryError, ContextResolutionError) as exc:
        raise HTTPException(status_code=500, detail="平台副驾能力注册表不可用") from exc


@router.post("/context/resolve", response_model=None)
def resolve_context_endpoint(
    payload: ContextRequest,
    request: Request,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> dict[str, Any] | JSONResponse:
    try:
        return _resolve_context(db, current_user, payload.page_context).as_contract()
    except Exception as exc:  # mapped to the frozen error envelope below
        return _error_response(request, exc)


@router.post("/turns", response_model=None)
def create_turn(
    payload: TurnRequest,
    request: Request,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> dict[str, Any] | JSONResponse:
    """Run one server-owned platform-copilot turn.

    The client supplies only page state and natural language. Identity,
    organization membership, the platform-assistant employee, and the active
    workflow are resolved on the server.
    """

    try:
        projection = _transaction_projection(db, current_user, payload.page_context)
        context = _resolve_context(
            db,
            current_user,
            payload.page_context,
            projection=projection,
        )
        scope = _ensure_platform_assistant_scope(db, current_user, payload.session_id)
        feature = _feature_decision(db, current_user)
        repository = PlatformAssistantRepository(db)
        active = repository.get_latest_active_run(scope)
        initial_user_message = (
            _initial_user_message(db, scope, active.id) if active else None
        )
        user_message = _store_assistant_message(
            db,
            scope,
            role="user",
            content=payload.message.strip(),
            metadata={
                "platform_assistant": True,
                "client_request_id": payload.client_request_id,
            },
        )
        if not feature.assistant_enabled:
            _record_feature_blocked(
                db,
                current_user,
                scope,
                feature,
                request_id=payload.client_request_id,
                route_id=context.underlying_route_id,
            )
            return _feature_stage_turn_payload(
                db, scope, context, feature, payload.client_request_id, request
            )
        if is_guidance_request(payload.message):
            _authorize_action(
                db,
                current_user,
                scope,
                feature,
                capability_id="platform.guidance",
                action_id="business_summary.read",
                permissions={"authenticated", "resource.visible"},
                request_id=payload.client_request_id,
                route_id=context.underlying_route_id,
            )
            guidance = TransactionCoreGateway(db).resolve_guidance(
                TrustedGuidanceRequest(
                    tenant_id=current_user.tenant_id,
                    actor_user_id=current_user.id,
                    page_context=payload.page_context,
                )
            )
            return _guidance_turn_payload(
                db,
                scope,
                context,
                guidance.assistant_text,
                guidance_blocks(guidance, request_id=payload.client_request_id),
                request,
            )
        if not feature.requirement_draft_write_allowed:
            _record_feature_blocked(
                db,
                current_user,
                scope,
                feature,
                request_id=payload.client_request_id,
                route_id=context.underlying_route_id,
            )
            return _feature_stage_turn_payload(
                db, scope, context, feature, payload.client_request_id, request
            )
        _authorize_action(
            db,
            current_user,
            scope,
            feature,
            capability_id="requirement.create",
            action_id="assistant.requirement_draft.create",
            permissions={"requirement.create"},
            idempotency_key=payload.client_request_id,
            request_id=payload.client_request_id,
            route_id=context.underlying_route_id,
        )
        runtime = _runtime(
            db,
            current_user,
            scope,
            organization_id=context.organization_id,
        )
        result = runtime.handle_message(
            current_user=current_user,
            scope=scope,
            resolved_context=context,
            message=payload.message,
            client_request_id=payload.client_request_id,
            authorized_organization_ids=projection.organization_ids,
            initial_user_message=initial_user_message,
            protocol_version=payload.protocol_version,
        )
        _link_runtime_usage(db, current_user, scope, result)
        user_message.metadata_json = {
            **(user_message.metadata_json or {}),
            "assistant_run_id": result.snapshot.run.id,
        }
        db.add(user_message)
        db.commit()
        return _turn_payload(
            db,
            scope,
            context,
            result,
            request,
            protocol_version=payload.protocol_version,
        )
    except Exception as exc:
        return _error_response(request, exc)


@router.post("/runs", response_model=None)
def create_run(
    payload: CreateRunRequest,
    request: Request,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> dict[str, Any] | JSONResponse:
    try:
        scope = _run_scope(db, current_user, payload.session_id)
        feature = _feature_decision(db, current_user)
        context = _resolve_context(db, current_user, payload.page_context)
        routes = RouteContextRegistry.from_contract()
        capabilities = BusinessCapabilityRegistry.from_contract(
            known_route_ids=routes.route_ids
        )
        capability = capabilities.require(payload.capability_id)
        if context.route_id not in capability.supported_route_ids:
            raise ContextResolutionError(
                "CONTEXT_FORBIDDEN",
                "capability is unavailable on the current route",
                status_code=403,
            )
        _authorize_action(
            db,
            current_user,
            scope,
            feature,
            capability_id=capability.capability_id,
            action_id="assistant.requirement_draft.create",
            permissions={"requirement.create"},
            idempotency_key=payload.client_request_id,
            request_id=payload.client_request_id,
            route_id=context.underlying_route_id,
        )
        run = PlatformAssistantRepository(db).create_run(
            scope,
            capability_id=capability.capability_id,
            capability_version=capability.version,
            organization_id=context.organization_id,
            context_snapshot=context.as_contract(),
        )
        return _run_payload(PlatformAssistantRepository(db).get_run_snapshot(scope, run.id))
    except Exception as exc:
        return _error_response(request, exc)


@router.get("/runs/latest", response_model=None)
def get_latest_run(
    session_id: str,
    request: Request,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> dict[str, Any] | JSONResponse:
    try:
        scope = _run_scope(db, current_user, session_id)
        repository = PlatformAssistantRepository(db)
        run = repository.get_latest_active_run(scope)
        if run is None:
            raise RunNotFound("active platform assistant workflow was not found")
        return _run_payload(repository.get_run_snapshot(scope, run.id))
    except Exception as exc:
        return _error_response(request, exc)


@router.get("/runs/{run_id}", response_model=None)
def get_run(
    run_id: str,
    session_id: str,
    request: Request,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> dict[str, Any] | JSONResponse:
    try:
        scope = _run_scope(db, current_user, session_id)
        snapshot = PlatformAssistantRepository(db).get_run_snapshot(scope, run_id)
        return _run_payload(snapshot)
    except Exception as exc:
        return _error_response(request, exc)


@router.post("/runs/{run_id}/answers", response_model=None)
def submit_answers(
    run_id: str,
    payload: AnswerRunRequest,
    request: Request,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> dict[str, Any] | JSONResponse:
    try:
        if payload.run_id != run_id:
            raise PlatformAssistantProtocolError(
                "INVALID_REQUEST", "path run_id does not match request body"
            )
        scope = _run_scope(db, current_user, payload.session_id)
        feature = _feature_decision(db, current_user)
        _authorize_action(
            db,
            current_user,
            scope,
            feature,
            capability_id="requirement.create",
            action_id="assistant.requirement_draft.update",
            permissions={"requirement.create"},
            idempotency_key=payload.idempotency_key,
            request_id=payload.idempotency_key,
        )
        repository = PlatformAssistantRepository(db)
        repository.submit_answers(
            scope,
            run_id,
            block_id=payload.block_id,
            block_version=payload.block_version,
            idempotency_key=payload.idempotency_key,
            answers=payload.answers,
        )
        draft = db.exec(
            select(AssistantRequirementDraft).where(
                AssistantRequirementDraft.tenant_id == scope.tenant_id,
                AssistantRequirementDraft.user_id == scope.user_id,
                AssistantRequirementDraft.session_id == scope.session_id,
                AssistantRequirementDraft.run_id == run_id,
            )
        ).first()
        if draft is not None:
            projection = _membership_projection(db, current_user)
            snapshot = repository.get_run_snapshot(scope, run_id)
            runtime = _runtime(
                db,
                current_user,
                scope,
                organization_id=snapshot.run.organization_id,
            )
            result = runtime.continue_after_answers(
                current_user=current_user,
                scope=scope,
                run_id=run_id,
                client_request_id=payload.idempotency_key,
                authorized_organization_ids=projection.organization_ids,
                protocol_version=payload.protocol_version,
            )
            _link_runtime_usage(db, current_user, scope, result)
            context = snapshot.run.context_snapshot_json
            return _turn_payload(
                db,
                scope,
                context,
                result,
                request,
                protocol_version=payload.protocol_version,
            )
        return _run_payload(repository.get_run_snapshot(scope, run_id))
    except Exception as exc:
        return _error_response(request, exc)


@router.post("/runs/{run_id}/cancel", response_model=None)
def cancel_run(
    run_id: str,
    payload: RunControlRequest,
    request: Request,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> dict[str, Any] | JSONResponse:
    try:
        scope = _run_scope(db, current_user, payload.session_id)
        repository = PlatformAssistantRepository(db)
        repository.cancel_run(scope, run_id)
        return _run_payload(repository.get_run_snapshot(scope, run_id))
    except Exception as exc:
        return _error_response(request, exc)


@router.post("/runs/{run_id}/resume", response_model=None)
def resume_run(
    run_id: str,
    payload: RunControlRequest,
    request: Request,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> dict[str, Any] | JSONResponse:
    try:
        scope = _run_scope(db, current_user, payload.session_id)
        repository = PlatformAssistantRepository(db)
        repository.resume_run(scope, run_id)
        return _run_payload(repository.get_run_snapshot(scope, run_id))
    except Exception as exc:
        return _error_response(request, exc)


def _transaction_projection(
    db: Session,
    user: User,
    payload: dict[str, Any],
) -> TrustedContextScopeProjection:
    return TransactionCoreGateway(db).resolve_context_scope(
        TrustedContextResolveRequest(
            tenant_id=user.tenant_id,
            actor_user_id=user.id,
            page_context=payload,
        )
    )


def _membership_projection(db: Session, user: User) -> TrustedContextScopeProjection:
    return _transaction_projection(
        db,
        user,
        {
            "page_instance_id": f"page_membership_{uuid4().hex[:16]}",
            "route_id": "assistant.chat",
            "pathname": "/workspace/gallery",
            "entity_refs": [],
            "ui_state": {},
            "context_version": 1,
        },
    )


def _resolve_context(
    db: Session,
    user: User,
    payload: dict[str, Any],
    *,
    projection: TrustedContextScopeProjection | None = None,
):
    page = PageContext.from_client(payload)
    projection = projection or _transaction_projection(db, user, payload)
    visible_entities = {
        key: frozenset(value) for key, value in projection.visible_entities.items()
    }
    agent_ids = {item.id for item in page.entity_refs if item.type == "agent"}
    for agent_id in agent_ids:
        agent = db.get(AgentProfile, agent_id)
        if not agent or agent.tenant_id != user.tenant_id or agent.status != "active":
            raise ContextResolutionError(
                "CONTEXT_FORBIDDEN", "agent is not accessible", status_code=403
            )
    if agent_ids:
        visible_entities["agent"] = frozenset(agent_ids)
    draft_ids = {
        item.id for item in page.entity_refs if item.type == "requirement_draft"
    }
    for draft_id in draft_ids:
        draft = db.get(AssistantRequirementDraft, draft_id)
        if (
            not draft
            or draft.tenant_id != user.tenant_id
            or draft.user_id != user.id
        ):
            raise ContextResolutionError(
                "CONTEXT_FORBIDDEN",
                "requirement draft is not accessible",
                status_code=403,
            )
    if draft_ids:
        visible_entities["requirement_draft"] = frozenset(draft_ids)
    trusted = TrustedResolutionScope(
        user_id=user.id,
        tenant_id=user.tenant_id,
        active_organization_id=projection.active_organization_id,
        organization_ids=frozenset(projection.organization_ids),
        visible_entities=visible_entities,
        row_version=projection.row_version,
        minimum_context_version=projection.minimum_context_version,
    )
    return resolve_page_context(page, trusted)


def _ensure_platform_assistant_scope(
    db: Session,
    user: User,
    session_id: str | None,
) -> RunScope:
    if session_id:
        return _run_scope(db, user, session_id)
    agents = db.exec(
        select(AgentProfile).where(
            AgentProfile.tenant_id == user.tenant_id,
            AgentProfile.status == "active",
        )
    ).all()
    assistant = next(
        (
            item
            for item in agents
            if (item.metadata_json or {}).get("platform_assistant") is True
        ),
        None,
    )
    if assistant is None:
        raise HTTPException(status_code=503, detail="平台总助尚未完成配置")
    existing = db.exec(
        select(ChatSession)
        .where(
            ChatSession.tenant_id == user.tenant_id,
            ChatSession.user_id == user.id,
            ChatSession.agent_id == assistant.id,
            ChatSession.status == "active",
        )
        .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
    ).first()
    if existing is None:
        existing = ChatSession(
            id=new_id("session"),
            tenant_id=user.tenant_id,
            user_id=user.id,
            agent_id=assistant.id,
            title="开小花平台副驾",
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)
    return RunScope(user.tenant_id, user.id, existing.id)


def _run_scope(db: Session, user: User, session_id: str) -> RunScope:
    session = db.get(ChatSession, session_id)
    if (
        not session
        or session.tenant_id != user.tenant_id
        or session.user_id != user.id
    ):
        raise RunNotFound("platform assistant session was not found")
    agent = db.get(AgentProfile, session.agent_id) if session.agent_id else None
    if not agent or (agent.metadata_json or {}).get("platform_assistant") is not True:
        raise RunNotFound("platform assistant session was not found")
    return RunScope(
        tenant_id=user.tenant_id,
        user_id=user.id,
        session_id=session.id,
    )


def _feature_decision(db: Session, user: User) -> FeatureFlagDecision:
    return AssistantFeatureFlagService(db).evaluate(
        tenant_id=user.tenant_id,
        user_id=user.id,
    )


def _authorize_action(
    db: Session,
    user: User,
    scope: RunScope,
    feature: FeatureFlagDecision,
    *,
    capability_id: str,
    action_id: str,
    permissions: set[str],
    request_id: str,
    route_id: str | None = None,
    idempotency_key: str | None = None,
) -> ToolPolicyDecision:
    decision = AssistantToolRiskPolicy().authorize(
        capability_id=capability_id,
        action_id=action_id,
        granted_permissions=permissions,
        feature=feature,
        idempotency_key=idempotency_key,
    )
    record_governance_event(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        event_type=decision.audit_event,
        outcome="allowed" if decision.execution_allowed else "blocked",
        request_id=request_id,
        payload={
            "action_id": decision.action_id,
            "capability_id": capability_id,
            "risk_level": decision.risk_level,
            "reason_code": decision.reason_code,
            "feature_stage": feature.effective_stage,
            "route_id": route_id,
        },
    )
    if not decision.execution_allowed:
        raise RuntimeStateError(
            f"平台副驾动作被安全策略阻止：{decision.reason_code}"
        )
    return decision


def _record_feature_blocked(
    db: Session,
    user: User,
    scope: RunScope,
    feature: FeatureFlagDecision,
    *,
    request_id: str,
    route_id: str,
) -> None:
    del scope
    record_governance_event(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        event_type="assistant.feature_stage.blocked",
        outcome="blocked",
        request_id=request_id,
        payload={
            "feature_stage": feature.effective_stage,
            "configured_stage": feature.configured_stage,
            "reason": feature.reason,
            "route_id": route_id,
        },
    )


def _link_runtime_usage(
    db: Session,
    user: User,
    scope: RunScope,
    result: RuntimeResult,
) -> None:
    usage = AssistantUsageService(db)
    for ai_request_id in result.ai_request_ids:
        try:
            usage.link_invocation(
                AssistantUsageScope(
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    session_id=scope.session_id,
                ),
                run_id=result.snapshot.run.id,
                ai_request_id=ai_request_id,
            )
        except AssistantUsageLinkError as exc:
            record_governance_event(
                db,
                tenant_id=user.tenant_id,
                user_id=user.id,
                run_id=result.snapshot.run.id,
                event_type="assistant.usage.link_failed",
                outcome="failed",
                request_id=ai_request_id,
                payload={"error_code": exc.code},
            )


def _runtime(
    db: Session,
    user: User,
    scope: RunScope,
    *,
    organization_id: str | None,
) -> PlatformAssistantRuntime:
    gateway = AIModelGateway(
        db,
        tenant_id=user.tenant_id,
        capability="demand_analysis",
        user_id=user.id,
        organization_id=organization_id,
        session_id=scope.session_id,
    )
    return PlatformAssistantRuntime(
        db,
        orchestrator=RequirementWorkflowOrchestrator(
            AIModelGatewayAdapter(gateway)
        ),
    )


def _initial_user_message(db: Session, scope: RunScope, run_id: str) -> str | None:
    rows = db.exec(
        select(Message)
        .where(
            Message.tenant_id == scope.tenant_id,
            Message.session_id == scope.session_id,
            Message.role == "user",
        )
        .order_by(Message.created_at, Message.id)
    ).all()
    for item in rows:
        if (item.metadata_json or {}).get("assistant_run_id") == run_id:
            return item.content
    return None


def _store_assistant_message(
    db: Session,
    scope: RunScope,
    *,
    role: str,
    content: str,
    metadata: dict[str, Any],
) -> Message:
    row = Message(
        tenant_id=scope.tenant_id,
        session_id=scope.session_id,
        role=role,
        content=content,
        metadata_json=metadata,
    )
    db.add(row)
    session = db.get(ChatSession, scope.session_id)
    if session is not None:
        session.updated_at = utc_now()
        db.add(session)
    db.commit()
    db.refresh(row)
    return row


def _turn_payload(
    db: Session,
    scope: RunScope,
    context: Any,
    result: RuntimeResult,
    request: Request,
    *,
    protocol_version: Literal["1.0", "2.0"] = "1.0",
) -> dict[str, Any]:
    snapshot = result.snapshot
    if result.ui_blocks:
        blocks = list(result.ui_blocks)
    else:
        latest = snapshot.latest_blocks[-1:] if snapshot.latest_blocks else ()
        blocks = [item.payload_json for item in latest]
    workflow = _workflow_payload(result)
    assistant_message = _store_assistant_message(
        db,
        scope,
        role="assistant",
        content=result.assistant_text,
        metadata={
            "platform_assistant": True,
            "assistant_run_id": snapshot.run.id,
            "structured_blocks": blocks,
            "workflow": workflow,
            "degraded": result.degraded,
            "degradation_code": result.degradation_code,
            "ai_request_ids": list(result.ai_request_ids),
        },
    )
    context_payload = (
        context.as_contract() if hasattr(context, "as_contract") else dict(context)
    )
    return {
        "protocol_version": protocol_version,
        "request_id": getattr(request.state, "request_id", None) or uuid4().hex,
        "server_time": datetime.now(UTC).isoformat(),
        "session_id": scope.session_id,
        "run_id": snapshot.run.id,
        "message_id": assistant_message.id,
        "assistant_text": result.assistant_text,
        "ui_blocks": blocks,
        "workflow": workflow,
        "context": context_payload,
        "usage": {
            "request_id": result.ai_request_ids[-1]
            if result.ai_request_ids
            else None
        },
    }


def _guidance_turn_payload(
    db: Session,
    scope: RunScope,
    context: Any,
    assistant_text: str,
    blocks: list[dict[str, Any]],
    request: Request,
) -> dict[str, Any]:
    assistant_message = _store_assistant_message(
        db,
        scope,
        role="assistant",
        content=assistant_text,
        metadata={
            "platform_assistant": True,
            "guidance": True,
            "structured_blocks": blocks,
        },
    )
    context_payload = (
        context.as_contract() if hasattr(context, "as_contract") else dict(context)
    )
    return {
        "protocol_version": "1.0",
        "request_id": getattr(request.state, "request_id", None) or uuid4().hex,
        "server_time": datetime.now(UTC).isoformat(),
        "session_id": scope.session_id,
        "run_id": None,
        "message_id": assistant_message.id,
        "assistant_text": assistant_text,
        "ui_blocks": blocks,
        "workflow": None,
        "context": context_payload,
        "usage": {"request_id": None},
    }


def _feature_stage_turn_payload(
    db: Session,
    scope: RunScope,
    context: Any,
    feature: FeatureFlagDecision,
    client_request_id: str,
    request: Request,
) -> dict[str, Any]:
    blocks = feature_stage_blocks(
        feature.effective_stage,
        request_id=client_request_id,
    )
    return _guidance_turn_payload(
        db,
        scope,
        context,
        blocks[0]["message"],
        blocks,
        request,
    )


def _workflow_payload(result: RuntimeResult) -> dict[str, Any]:
    run = result.snapshot.run
    required = 13
    if result.draft is None:
        completed = 0
    else:
        missing = {
            item.removeprefix("confirmation:").removeprefix("field_source:")
            for item in result.draft.content.missing_fields
        }
        completed = max(0, required - len(missing))
    return {
        "capability_id": run.capability_id,
        "capability_version": run.capability_version,
        "state": run.state,
        "row_version": run.row_version,
        "progress": {
            "completed_required": completed,
            "total_required": required,
        },
    }


def _run_payload(snapshot) -> dict[str, Any]:
    run = snapshot.run
    return {
        "protocol_version": "1.0",
        "run": {
            "run_id": run.id,
            "session_id": run.session_id,
            "organization_id": run.organization_id,
            "capability_id": run.capability_id,
            "capability_version": run.capability_version,
            "state": run.state,
            "current_step": run.current_step,
            "row_version": run.row_version,
            "context": run.context_snapshot_json,
            "updated_at": run.updated_at.isoformat(),
        },
        "ui_blocks": [item.payload_json for item in snapshot.latest_blocks],
        "answers": [
            {
                "block_id": item.block_id,
                "block_version": item.block_version,
                "question_id": item.question_id,
                "value": item.answer_json,
                "source": item.source,
                "client_updated_at": item.client_updated_at,
            }
            for item in snapshot.answers
        ],
    }


def _error_response(request: Request, exc: Exception) -> JSONResponse:
    status, code, message, retryable = _map_error(exc)
    request_id = getattr(request.state, "request_id", None) or uuid4().hex
    return JSONResponse(
        status_code=status,
        content={
            "protocol_version": "1.0",
            "request_id": request_id,
            "server_time": datetime.now(UTC).isoformat(),
            "error": {
                "code": code,
                "message": message,
                "retryable": retryable,
            },
        },
    )


def _map_error(exc: Exception) -> tuple[int, str, str, bool]:
    if isinstance(exc, PlatformAssistantRuntimeError):
        if exc.code == "UNAUTHORIZED_CONTEXT":
            return 403, "UNAUTHORIZED_CONTEXT", str(exc), False
        return 409, "ACTION_FORBIDDEN", str(exc), False
    if isinstance(exc, ContextResolutionError):
        code = (
            "UNAUTHORIZED_CONTEXT"
            if exc.status_code == 403
            else "CONTEXT_STALE"
            if exc.code == "CONTEXT_STALE"
            else "INVALID_REQUEST"
        )
        return exc.status_code, code, str(exc), False
    if isinstance(exc, BlockVersionConflict):
        return 409, "BLOCK_VERSION_CONFLICT", str(exc), True
    if isinstance(exc, IdempotencyKeyConflict):
        return 409, "IDEMPOTENCY_CONFLICT", str(exc), False
    if isinstance(exc, (RunNotFound, BlockNotFound)):
        return 404, "RESOURCE_NOT_FOUND", str(exc), False
    if isinstance(exc, RunStateConflict):
        return 409, "ACTION_FORBIDDEN", str(exc), False
    if isinstance(exc, (PlatformAssistantProtocolError, CapabilityRegistryError, ValidationError)):
        return 400, "INVALID_REQUEST", str(exc), False
    if isinstance(exc, HTTPException):
        code = "UNAUTHORIZED_CONTEXT" if exc.status_code == 403 else "RESOURCE_NOT_FOUND"
        return exc.status_code, code, str(exc.detail), exc.status_code >= 500
    return 500, "INTERNAL_ERROR", "平台副驾暂时不可用", True
