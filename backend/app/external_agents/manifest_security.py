from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.external_agents.schemas import ExternalAgentManifestPayload, ManifestCapability

HASH_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:sk|pat|ghp)_[A-Za-z0-9_-]{20,}\b"),
)
PROMPT_INJECTION_PATTERNS = (
    re.compile(r"(?i)ignore (?:all |the )?(?:previous|prior|system) instructions"),
    re.compile(r"(?i)reveal (?:the )?system prompt"),
    re.compile(r"忽略.{0,8}(?:之前|系统).{0,8}(?:指令|提示词)"),
)
SECRET_KEY_FRAGMENTS = ("password", "secret", "token", "cookie", "api_key", "private_key")
ALLOWED_PERMISSION_PREFIXES = (
    "filesystem:read:selected",
    "filesystem:write:output",
    "network:deny",
    "network:allowlist:",
    "tool:",
    "knowledge:metadata",
    "human:approval",
    "message:send:approval",
    "shell:approval",
)
RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class ManifestValidation:
    digest: str
    normalized_agent: dict[str, Any]
    assets: list[dict[str, Any]]
    errors: list[dict[str, str]]
    warnings: list[dict[str, str]]


def validate_and_normalize_manifest(
    manifest: ExternalAgentManifestPayload,
) -> ManifestValidation:
    raw = manifest.model_dump(mode="json")
    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if len(canonical.encode("utf-8")) > 1_048_576:
        errors.append({"code": "manifest_size", "message": "Manifest 超过 1 MB"})
    if not manifest.disclosure.confirmed_by_user:
        errors.append({"code": "user_confirmation", "message": "能力清单必须先由用户确认"})
    if manifest.disclosure.secrets_uploaded:
        errors.append({"code": "secrets_disclosed", "message": "Manifest 声明包含密钥，平台拒绝接收"})
    if manifest.disclosure.knowledge_content_uploaded:
        errors.append({"code": "knowledge_content", "message": "默认只登记知识元数据，不接收知识正文"})
    _scan_sensitive_values(raw, "$", errors)
    _scan_prompt_injection(raw, "$", errors)
    if manifest.agent.source_hash and not HASH_PATTERN.fullmatch(manifest.agent.source_hash):
        errors.append({"code": "agent_hash", "message": "Agent source_hash 必须是 sha256: 加 64 位十六进制"})

    seen_ids: set[str] = set()
    seen_hashes: set[tuple[str, str]] = set()
    assets: list[dict[str, Any]] = []
    for capability in manifest.capabilities:
        if capability.external_id in seen_ids:
            errors.append({"code": "duplicate_external_id", "message": f"能力 ID 重复：{capability.external_id}"})
            continue
        seen_ids.add(capability.external_id)
        if capability.source_hash:
            if not HASH_PATTERN.fullmatch(capability.source_hash):
                errors.append({"code": "capability_hash", "message": f"能力 {capability.external_id} 的 source_hash 无效"})
            hash_key = (capability.kind, capability.source_hash)
            if hash_key in seen_hashes:
                warnings.append({"code": "duplicate_hash", "message": f"能力 {capability.external_id} 与同类资产摘要重复"})
            seen_hashes.add(hash_key)
        invalid_permissions = [
            value for value in capability.permissions if not value.startswith(ALLOWED_PERMISSION_PREFIXES)
        ]
        if invalid_permissions:
            errors.append({"code": "permission", "message": f"能力 {capability.external_id} 包含未知权限：{', '.join(invalid_permissions)}"})
        _validate_schema(capability.input_schema, capability.external_id, "input", errors)
        _validate_schema(capability.output_schema, capability.external_id, "output", errors)
        assets.append(_normalize_capability(capability))

    agent = manifest.agent
    normalized_agent = {
        "external_id": agent.external_id,
        "name": agent.name.strip(),
        "description": agent.description.strip(),
        "provider": agent.provider.lower(),
        "runtime": agent.runtime,
        "runtime_version": agent.runtime_version,
        "input_modes": sorted(set(agent.input_modes)),
        "output_modes": sorted(set(agent.output_modes)),
        "source_hash": agent.source_hash,
        "execution": manifest.execution.model_dump(mode="json"),
        "field_provenance": {
            field: {
                "source": f"manifest.agent.{field}",
                "method": "deterministic",
                "confidence": 1.0,
                "user_modified": False,
            }
            for field in ("name", "description", "provider", "runtime", "runtime_version")
        },
    }
    return ManifestValidation(
        digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        normalized_agent=normalized_agent,
        assets=assets,
        errors=errors,
        warnings=warnings,
    )


def _normalize_capability(capability: ManifestCapability) -> dict[str, Any]:
    derived_risk = _permission_risk(capability.permissions)
    risk = max((capability.risk_level, derived_risk), key=lambda value: RISK_ORDER[value])
    evidence = capability.evidence
    confidence = float(evidence.get("confidence", 1.0 if capability.source_hash else 0.7))
    method = str(evidence.get("method") or ("deterministic" if capability.source_hash else "declared"))
    verification = "verified_metadata" if capability.source_hash and confidence >= 0.99 else "pending_test"
    return {
        "external_id": capability.external_id,
        "kind": capability.kind,
        "name": capability.name.strip(),
        "description": capability.description.strip(),
        "version": capability.version,
        "portable": capability.portable,
        "callable": capability.callable,
        "risk_level": risk,
        "verification_status": verification,
        "source_type": capability.source_type,
        "source_hash": capability.source_hash,
        "input_schema": capability.input_schema,
        "output_schema": capability.output_schema,
        "permissions": sorted(set(capability.permissions)),
        "evidence": evidence,
        "provenance": {
            "name": {"source": "manifest.capabilities[].name", "method": method, "confidence": confidence},
            "description": {"source": "manifest.capabilities[].description", "method": method, "confidence": confidence},
            "schemas": {"source": "manifest.capabilities[].schema", "method": "deterministic", "confidence": 1.0},
            "permissions": {"source": "manifest.capabilities[].permissions", "method": "deterministic", "confidence": 1.0},
        },
        "raw": capability.model_dump(mode="json"),
    }


def _permission_risk(permissions: list[str]) -> str:
    joined = " ".join(permissions)
    if any(token in joined for token in ("shell:", "message:send", "production", "payment")):
        return "high"
    if any(token in joined for token in ("filesystem:write", "network:allowlist")):
        return "medium"
    return "low"


def _validate_schema(
    schema: dict[str, Any], external_id: str, direction: str, errors: list[dict[str, str]]
) -> None:
    if not schema:
        return
    if schema.get("type") not in {"object", "array", "string", "number", "integer", "boolean"}:
        errors.append({"code": "schema_type", "message": f"能力 {external_id} 的 {direction} schema type 无效"})
    if schema.get("type") == "object" and not isinstance(schema.get("properties", {}), dict):
        errors.append({"code": "schema_properties", "message": f"能力 {external_id} 的 {direction} properties 无效"})
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith(("http://", "https://")):
        errors.append({"code": "remote_schema_ref", "message": f"能力 {external_id} 不允许远程 Schema 引用"})


def _scan_sensitive_values(value: Any, path: str, errors: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if any(fragment in key.lower() for fragment in SECRET_KEY_FRAGMENTS) and item not in (None, "", False, []):
                errors.append({"code": "secret_field", "message": f"Manifest 不得包含敏感字段：{child}"})
            _scan_sensitive_values(item, child, errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_sensitive_values(item, f"{path}[{index}]", errors)
    elif isinstance(value, str) and any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS):
        errors.append({"code": "secret_value", "message": f"Manifest 疑似包含凭据：{path}"})


def _scan_prompt_injection(value: Any, path: str, errors: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _scan_prompt_injection(item, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_prompt_injection(item, f"{path}[{index}]", errors)
    elif isinstance(value, str) and any(pattern.search(value) for pattern in PROMPT_INJECTION_PATTERNS):
        errors.append({"code": "prompt_injection", "message": f"Manifest 包含疑似提示词注入：{path}"})
