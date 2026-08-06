from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, Iterable

from sqlmodel import Session, select

from app.db.models import (
    AgentProfile,
    ExternalAgentConnection,
    ExternalAgentDiscoveredAsset,
    ExternalAgentNetworkPolicy,
    MarketplaceAIService,
    MarketplaceAIServiceVersion,
    TransactionRequirement,
    TransactionRequirementVersion,
    utc_now,
)


MATCH_ENGINE = "marketplace_match_v2"
DETERMINISTIC_MIN_SCORE = 42
AI_ASSISTED_MIN_SCORE = 55

_LATIN_TOKEN = re.compile(r"[a-z0-9][a-z0-9+._/-]{1,}", re.IGNORECASE)
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
_SPACE = re.compile(r"\s+")
_GENERIC_TOKENS = {
    "一个",
    "以及",
    "相关",
    "需要",
    "进行",
    "完成",
    "提供",
    "服务",
    "需求",
    "工作",
    "内容",
    "最终",
    "结果",
    "输出",
    "提交",
    "支持",
    "按照",
    "可以",
}


@dataclass(frozen=True)
class ServiceExecutionProfile:
    service_version: MarketplaceAIServiceVersion | None
    execution_mode: str
    runtime_ready: bool
    runtime_reason: str
    connection_id: str | None
    capability_asset_ids: tuple[str, ...]
    capability_evidence: tuple[str, ...]
    risk_flags: tuple[str, ...]

    def ai_payload(self) -> dict[str, Any]:
        version = self.service_version
        return {
            "execution_mode": self.execution_mode,
            "runtime_ready": self.runtime_ready,
            "runtime_reason": self.runtime_reason,
            "connection_id": self.connection_id,
            "capability_asset_ids": list(self.capability_asset_ids),
            "capability_evidence": list(self.capability_evidence),
            "service_version_id": version.id if version else None,
            "service_version": version.version if version else None,
        }


@dataclass(frozen=True)
class MatchDecision:
    eligible: bool
    score: int
    semantic_ready: bool
    reasons: tuple[str, ...]
    risk_flags: tuple[str, ...]
    breakdown: dict[str, int]
    profile: ServiceExecutionProfile

    def ai_payload(self) -> dict[str, Any]:
        return {
            "baseline_score": self.score,
            "baseline_reasons": list(self.reasons),
            "risk_flags": list(self.risk_flags),
            "score_breakdown": self.breakdown,
            "execution_profile": self.profile.ai_payload(),
        }


def evaluate_service_candidate(
    db: Session,
    requirement: TransactionRequirement,
    requirement_version: TransactionRequirementVersion,
    service: MarketplaceAIService,
) -> MatchDecision:
    profile = resolve_execution_profile(db, service)
    reasons: list[str] = []
    risks = list(profile.risk_flags)
    if not profile.runtime_ready:
        return MatchDecision(
            eligible=False,
            score=0,
            semantic_ready=False,
            reasons=(profile.runtime_reason,),
            risk_flags=tuple(risks),
            breakdown={"runtime": 0},
            profile=profile,
        )

    version = profile.service_version
    if not version:
        return MatchDecision(
            eligible=False,
            score=0,
            semantic_ready=False,
            reasons=("服务缺少已发布且可冻结的版本",),
            risk_flags=tuple(dict.fromkeys([*risks, "服务版本不可用"])),
            breakdown={"runtime": 0},
            profile=profile,
        )

    budget_score = 5
    if requirement.budget_max_amount > 0 and version.price_amount > requirement.budget_max_amount:
        return MatchDecision(
            eligible=False,
            score=0,
            semantic_ready=False,
            reasons=("已发布服务起价高于需求预算上限",),
            risk_flags=tuple(dict.fromkeys([*risks, "预算不匹配"])),
            breakdown={"budget": 0, "runtime": 20},
            profile=profile,
        )

    if requirement.desired_delivery_at:
        available_minutes = max(
            0,
            int((requirement.desired_delivery_at - utc_now()).total_seconds() // 60),
        )
        if available_minutes and version.average_minutes > available_minutes:
            return MatchDecision(
                eligible=False,
                score=0,
                semantic_ready=False,
                reasons=("服务预计工期晚于需求截止时间",),
                risk_flags=tuple(dict.fromkeys([*risks, "工期不匹配"])),
                breakdown={"schedule": 0, "runtime": 20},
                profile=profile,
            )

    requirement_anchor_texts = [
        requirement.title,
        requirement.category,
        *[
            str(item.get("name") or item.get("title") or "")
            for item in requirement_version.deliverables_json
            if isinstance(item, dict)
        ],
    ]
    requirement_body_texts = [
        requirement_version.description,
        *requirement_version.acceptance_criteria_json,
    ]
    snapshot = dict(version.snapshot_json or {})
    service_anchor_texts = [
        service.name,
        service.category,
        *[str(item) for item in snapshot.get("service_scope") or []],
        *[_display_text(item) for item in snapshot.get("deliverables") or []],
        *profile.capability_evidence,
    ]
    service_body_texts = [
        service.description,
        *[str(item) for item in snapshot.get("acceptance_criteria") or []],
        *[_display_text(item) for item in snapshot.get("cases") or []],
    ]

    requirement_anchor = _keywords(requirement_anchor_texts)
    requirement_body = _keywords([*requirement_anchor_texts, *requirement_body_texts])
    service_body = _keywords([*service_anchor_texts, *service_body_texts])
    anchor_coverage = _coverage(requirement_anchor, service_body)
    body_coverage = _coverage(requirement_body, service_body)
    category_similarity = _text_similarity(
        requirement.category,
        " ".join(service_anchor_texts),
    )
    direct_scope_hits = _direct_phrase_hits(requirement_anchor_texts, service_anchor_texts)

    runtime_score = 20
    anchor_score = round(anchor_coverage * 38)
    body_score = round(body_coverage * 17)
    category_score = round(category_similarity * 12)
    direct_score = min(8, direct_scope_hits * 4)
    verification_score = 5 if service.verified else 0
    score = min(
        100,
        runtime_score
        + anchor_score
        + body_score
        + category_score
        + direct_score
        + verification_score
        + budget_score,
    )
    semantic_ready = score >= DETERMINISTIC_MIN_SCORE and (
        anchor_coverage >= 0.08 or category_similarity >= 0.16 or direct_scope_hits > 0
    )

    if category_similarity >= 0.35:
        reasons.append("服务领域与需求分类一致")
    if anchor_coverage >= 0.16 or direct_scope_hits:
        reasons.append("已发布服务范围覆盖需求的核心任务")
    if profile.execution_mode == "external_agent":
        reasons.append("外接员工已通过能力清单校验且运行在线")
    else:
        reasons.append("服务员工和已发布版本当前可执行")
    if service.verified:
        reasons.append("服务与版本已通过平台审核")
    if not semantic_ready:
        risks.append("需由平台模型进一步确认语义匹配")

    return MatchDecision(
        eligible=True,
        score=score,
        semantic_ready=semantic_ready,
        reasons=tuple(dict.fromkeys(reasons)),
        risk_flags=tuple(dict.fromkeys(risks)),
        breakdown={
            "runtime": runtime_score,
            "core_capability": anchor_score,
            "requirement_coverage": body_score,
            "category": category_score,
            "direct_scope": direct_score,
            "verification": verification_score,
            "budget": budget_score,
        },
        profile=profile,
    )


def resolve_execution_profile(
    db: Session,
    service: MarketplaceAIService,
) -> ServiceExecutionProfile:
    version = db.get(MarketplaceAIServiceVersion, service.current_version_id or "")
    if not version or version.service_id != service.id or version.status != "published":
        return ServiceExecutionProfile(
            service_version=version,
            execution_mode="unavailable",
            runtime_ready=False,
            runtime_reason="服务缺少当前已发布版本",
            connection_id=None,
            capability_asset_ids=(),
            capability_evidence=(),
            risk_flags=("服务版本不可用",),
        )

    snapshot = dict(version.snapshot_json or {})
    if not service.online:
        return ServiceExecutionProfile(
            service_version=version,
            execution_mode="unavailable",
            runtime_ready=False,
            runtime_reason="服务当前已下线",
            connection_id=None,
            capability_asset_ids=(),
            capability_evidence=(),
            risk_flags=("服务离线",),
        )
    bridge = snapshot.get("external_agent_bridge")
    if isinstance(bridge, dict):
        return _external_execution_profile(db, service, version, bridge)

    agent = db.get(AgentProfile, service.agent_profile_id or "")
    if service.agent_profile_id and (not agent or agent.status != "active"):
        return ServiceExecutionProfile(
            service_version=version,
            execution_mode="staffdeck",
            runtime_ready=False,
            runtime_reason="服务绑定的数字员工不可用",
            connection_id=None,
            capability_asset_ids=(),
            capability_evidence=(),
            risk_flags=("数字员工不可用",),
        )
    legacy_risks: tuple[str, ...] = ()
    if not service.agent_profile_id:
        # Compatibility for reviewed services created before executable employee
        # bindings became mandatory.  They remain matchable but are explicitly
        # marked and cannot masquerade as a verified external runtime.
        legacy_risks = ("旧版托管服务尚未绑定专属员工",)
    evidence = _service_snapshot_evidence(service, version)
    return ServiceExecutionProfile(
        service_version=version,
        execution_mode="staffdeck",
        runtime_ready=True,
        runtime_reason="平台托管服务在线",
        connection_id=None,
        capability_asset_ids=(),
        capability_evidence=tuple(evidence),
        risk_flags=legacy_risks,
    )


def _external_execution_profile(
    db: Session,
    service: MarketplaceAIService,
    version: MarketplaceAIServiceVersion,
    bridge: dict[str, Any],
) -> ServiceExecutionProfile:
    connection_id = str(bridge.get("connection_id") or "")
    connection = db.get(ExternalAgentConnection, connection_id)
    capability_rows = db.exec(
        select(ExternalAgentDiscoveredAsset).where(
            ExternalAgentDiscoveredAsset.connection_id == connection_id,
            ExternalAgentDiscoveredAsset.selected.is_(True),
            ExternalAgentDiscoveredAsset.callable.is_(True),
        )
    ).all()
    bridge_asset_ids = {
        str(item.get("asset_id") or "")
        for item in bridge.get("capabilities") or []
        if isinstance(item, dict)
    }
    assets = [row for row in capability_rows if row.id in bridge_asset_ids]
    evidence = [
        " ".join(
            part
            for part in (
                row.name,
                row.description,
                row.external_id,
                _schema_text(row.input_schema_json),
                _schema_text(row.output_schema_json),
            )
            if part
        )
        for row in assets
    ]
    risks: list[str] = []
    ready = True
    reason = "外接员工运行在线"
    if (
        not connection
        or connection.tenant_id != service.tenant_id
        or connection.agent_profile_id != service.agent_profile_id
    ):
        ready = False
        reason = "外接员工连接与服务绑定不一致"
        risks.append("外接员工绑定失效")
    elif connection.status != "available" or connection.health_status != "online":
        ready = False
        reason = "外接员工未通过连接测试或当前不在线"
        risks.append("外接员工不可用")
    elif not assets:
        ready = False
        reason = "外接员工没有已授权且可调用的匹配能力"
        risks.append("外接能力不可调用")
    else:
        policy = db.exec(
            select(ExternalAgentNetworkPolicy).where(
                ExternalAgentNetworkPolicy.connection_id == connection.id
            )
        ).first()
        interval = policy.heartbeat_interval_seconds if policy else 60
        if not connection.last_heartbeat_at or utc_now() - connection.last_heartbeat_at > timedelta(
            seconds=interval * 3
        ):
            ready = False
            reason = "外接员工心跳已过期"
            risks.append("外接员工心跳过期")

    return ServiceExecutionProfile(
        service_version=version,
        execution_mode="external_agent",
        runtime_ready=ready,
        runtime_reason=reason,
        connection_id=connection_id or None,
        capability_asset_ids=tuple(row.id for row in assets),
        capability_evidence=tuple(evidence),
        risk_flags=tuple(risks),
    )


def _service_snapshot_evidence(
    service: MarketplaceAIService,
    version: MarketplaceAIServiceVersion,
) -> list[str]:
    snapshot = dict(version.snapshot_json or {})
    return [
        service.name,
        service.category,
        service.description,
        *[str(item) for item in snapshot.get("service_scope") or []],
        *[_display_text(item) for item in snapshot.get("deliverables") or []],
        *[_display_text(item) for item in snapshot.get("cases") or []],
    ]


def _display_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(
            str(value.get(key) or "")
            for key in ("name", "title", "format", "description", "summary")
        ).strip()
    return str(value or "")


def _schema_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    properties = value.get("properties")
    if not isinstance(properties, dict):
        return ""
    return " ".join(f"{key} {_display_text(item)}" for key, item in properties.items())


def _keywords(values: Iterable[str]) -> set[str]:
    output: set[str] = set()
    for raw in values:
        text = _SPACE.sub("", str(raw or "").lower())
        output.update(token for token in _LATIN_TOKEN.findall(text) if len(token) >= 2)
        for run in _CJK_RUN.findall(text):
            if len(run) <= 4:
                if run not in _GENERIC_TOKENS:
                    output.add(run)
                continue
            for size in (2, 3, 4):
                for index in range(len(run) - size + 1):
                    token = run[index : index + size]
                    if token not in _GENERIC_TOKENS:
                        output.add(token)
    return output


def _coverage(required: set[str], supplied: set[str]) -> float:
    if not required:
        return 0.0
    return len(required.intersection(supplied)) / len(required)


def _text_similarity(left: str, right: str) -> float:
    left_tokens = _keywords([left])
    right_tokens = _keywords([right])
    if not left_tokens:
        return 0.0
    return _coverage(left_tokens, right_tokens)


def _direct_phrase_hits(requirement_values: Iterable[str], service_values: Iterable[str]) -> int:
    service_text = " ".join(str(value or "").lower() for value in service_values)
    hits = 0
    for value in requirement_values:
        normalized = _SPACE.sub("", str(value or "").lower())
        if 2 <= len(normalized) <= 24 and normalized in service_text:
            hits += 1
    return hits


def clamp_ai_score(baseline: int, ai_score: int) -> int:
    """Keep AI semantic reranking influential without overriding runtime facts."""

    return max(0, min(100, round(baseline * 0.4 + ai_score * 0.6)))


def price_is_compatible(price: Decimal, budget_max: Decimal) -> bool:
    return budget_max <= 0 or price <= budget_max
