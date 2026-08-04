from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal, Mapping, TypeAlias

from app.platform_assistant.business_capabilities import (
    DEFAULT_CONTRACT_ROOT,
    BusinessCapabilityRegistry,
)
from app.platform_assistant.feature_flags import FeatureFlagDecision


RiskLevel: TypeAlias = Literal["R0", "R1", "R2", "R3", "R4"]
Disposition: TypeAlias = Literal[
    "allow_read",
    "allow_draft",
    "deny_and_deep_link",
    "deny",
]


@dataclass(frozen=True, slots=True)
class RiskAction:
    action_id: str
    risk_level: RiskLevel
    assistant_policy: str
    permission: str
    idempotency: str
    audit_event: str
    resource_type: str | None = None


@dataclass(frozen=True, slots=True)
class ToolPolicyDecision:
    action_id: str
    risk_level: RiskLevel | None
    disposition: Disposition
    execution_allowed: bool
    audit_event: str
    reason_code: str
    target_route_id: str | None = None


class RiskPolicyContractError(RuntimeError):
    code = "RISK_POLICY_CONTRACT_INVALID"


class FrozenRiskActionRegistry:
    """Immutable in-process snapshot of the reviewed action matrix."""

    def __init__(
        self,
        actions: Mapping[str, RiskAction],
        *,
        contract_digest: str,
    ) -> None:
        self._actions = MappingProxyType(dict(actions))
        self.contract_digest = contract_digest

    @classmethod
    def from_contract(cls, path: Path | None = None) -> FrozenRiskActionRegistry:
        contract_path = path or DEFAULT_CONTRACT_ROOT / "risk-action-matrix.json"
        try:
            encoded = contract_path.read_bytes()
            payload = json.loads(encoded)
        except (OSError, json.JSONDecodeError) as exc:
            raise RiskPolicyContractError(f"cannot load risk matrix: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
            raise RiskPolicyContractError("unsupported risk matrix schema")
        raw_actions = payload.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            raise RiskPolicyContractError("risk matrix must contain actions")
        actions: dict[str, RiskAction] = {}
        for raw in raw_actions:
            if not isinstance(raw, dict):
                raise RiskPolicyContractError("risk actions must be objects")
            action = _parse_action(raw)
            if action.action_id in actions:
                raise RiskPolicyContractError(
                    f"duplicate risk action: {action.action_id}"
                )
            actions[action.action_id] = action
        return cls(actions, contract_digest=hashlib.sha256(encoded).hexdigest())

    def get(self, action_id: str) -> RiskAction | None:
        return self._actions.get(action_id)

    def require(self, action_id: str) -> RiskAction:
        value = self.get(action_id)
        if value is None:
            raise KeyError(action_id)
        return value

    def all(self) -> tuple[RiskAction, ...]:
        return tuple(self._actions.values())


class AssistantToolRiskPolicy:
    """Server-authoritative tool allow/deny policy.

    Model output may propose an ``action_id`` but cannot declare its own risk
    level, permission, idempotency or execution policy. Those values are always
    reloaded from the frozen contract snapshot.
    """

    def __init__(
        self,
        *,
        risks: FrozenRiskActionRegistry | None = None,
        capabilities: BusinessCapabilityRegistry | None = None,
    ) -> None:
        self.risks = risks or FrozenRiskActionRegistry.from_contract()
        self.capabilities = capabilities or BusinessCapabilityRegistry.from_contract()

    def authorize(
        self,
        *,
        capability_id: str,
        action_id: str,
        granted_permissions: set[str] | frozenset[str],
        feature: FeatureFlagDecision,
        idempotency_key: str | None = None,
        model_claimed_risk_level: str | None = None,
        model_claimed_policy: str | None = None,
    ) -> ToolPolicyDecision:
        # Explicitly ignore model claims. Keeping named parameters makes this
        # boundary testable against prompt-injection/tool-smuggling attempts.
        del model_claimed_risk_level, model_claimed_policy
        action = self.risks.get(action_id)
        if action is None:
            return _denied_unknown(action_id)
        capability = self.capabilities.get(capability_id)
        if capability is None:
            return _deny(action, "CAPABILITY_NOT_REGISTERED")

        # R3/R4 never execute in the first release, even if a model names a
        # reviewed action and the caller has the underlying business permission.
        if action.risk_level == "R4":
            return _deny(action, "BINDING_ACTION_FORBIDDEN")
        if action.risk_level == "R3":
            return ToolPolicyDecision(
                action_id=action.action_id,
                risk_level=action.risk_level,
                disposition="deny_and_deep_link",
                execution_allowed=False,
                audit_event=action.audit_event,
                reason_code="BUSINESS_ACTION_REQUIRES_REAL_PAGE",
                target_route_id=capability.target_route_id,
            )

        if not feature.assistant_enabled:
            return _deny(action, "FEATURE_DISABLED")
        if action.permission not in granted_permissions:
            return _deny(action, "PERMISSION_REQUIRED")
        if action.action_id not in capability.allowed_tools:
            return _deny(action, "ACTION_NOT_ALLOWED_FOR_CAPABILITY")

        if action.risk_level == "R2":
            if not feature.requirement_draft_write_allowed:
                return _deny(action, "FEATURE_READ_ONLY")
            if (
                action.resource_type != "requirement_draft"
                or action.assistant_policy != "allow_with_result"
            ):
                return _deny(action, "R2_DRAFT_BOUNDARY_VIOLATION")
            if action.idempotency in {"required", "business_key"} and not (
                idempotency_key and idempotency_key.strip()
            ):
                return _deny(action, "IDEMPOTENCY_KEY_REQUIRED")
            return ToolPolicyDecision(
                action_id=action.action_id,
                risk_level=action.risk_level,
                disposition="allow_draft",
                execution_allowed=True,
                audit_event=action.audit_event,
                reason_code="REVIEWED_DRAFT_ACTION",
            )

        if not feature.read_allowed:
            return _deny(action, "FEATURE_READ_DISABLED")
        return ToolPolicyDecision(
            action_id=action.action_id,
            risk_level=action.risk_level,
            disposition="allow_read",
            execution_allowed=True,
            audit_event=action.audit_event,
            reason_code="REVIEWED_READ_ACTION",
        )


def _parse_action(raw: dict[str, object]) -> RiskAction:
    required = (
        "action_id",
        "risk_level",
        "assistant_policy",
        "permission",
        "idempotency",
        "audit_event",
    )
    values: dict[str, str] = {}
    for key in required:
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            raise RiskPolicyContractError(f"risk action field {key!r} is required")
        values[key] = value.strip()
    level = values["risk_level"]
    policy = values["assistant_policy"]
    expected = {
        "R0": "allow",
        "R1": "allow",
        "R2": "allow_with_result",
        "R3": "deny_and_deep_link",
        "R4": "deny",
    }
    if level not in expected or policy != expected[level]:
        raise RiskPolicyContractError(
            f"risk action {values['action_id']} has inconsistent policy"
        )
    resource = raw.get("resource_type")
    if resource is not None and not isinstance(resource, str):
        raise RiskPolicyContractError("resource_type must be a string")
    return RiskAction(
        action_id=values["action_id"],
        risk_level=level,  # type: ignore[arg-type]
        assistant_policy=policy,
        permission=values["permission"],
        idempotency=values["idempotency"],
        audit_event=values["audit_event"],
        resource_type=resource.strip() if isinstance(resource, str) else None,
    )


def _deny(action: RiskAction, reason: str) -> ToolPolicyDecision:
    return ToolPolicyDecision(
        action_id=action.action_id,
        risk_level=action.risk_level,
        disposition="deny",
        execution_allowed=False,
        audit_event=action.audit_event,
        reason_code=reason,
    )


def _denied_unknown(action_id: str) -> ToolPolicyDecision:
    return ToolPolicyDecision(
        action_id=action_id,
        risk_level=None,
        disposition="deny",
        execution_allowed=False,
        audit_event="assistant.action.denied",
        reason_code="UNKNOWN_ACTION",
    )


__all__ = [
    "AssistantToolRiskPolicy",
    "FrozenRiskActionRegistry",
    "RiskAction",
    "RiskPolicyContractError",
    "ToolPolicyDecision",
]
