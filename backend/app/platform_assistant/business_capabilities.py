from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


DEFAULT_CONTRACT_ROOT = (
    Path(__file__).resolve().parents[3] / "contracts" / "platform-assistant" / "v1"
)
CAPABILITY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]+$")
SEMVER_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class CapabilityRegistryError(ValueError):
    """Raised when a capability contract cannot be safely registered."""


@dataclass(frozen=True, slots=True)
class BusinessCapability:
    capability_id: str
    version: str
    display_name: str
    risk_level: str
    intents: tuple[str, ...]
    required_permissions: tuple[str, ...]
    allowed_projections: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    supported_route_ids: tuple[str, ...]
    target_route_id: str
    execution_service: str
    minimum_generation_fields: tuple[str, ...] = ()
    fallback_strategy: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> BusinessCapability:
        required_strings = (
            "capability_id",
            "version",
            "display_name",
            "risk_level",
            "target_route_id",
            "execution_service",
        )
        parsed_strings: dict[str, str] = {}
        for key in required_strings:
            item = value.get(key)
            if not isinstance(item, str) or not item.strip():
                raise CapabilityRegistryError(f"capability field {key!r} must be non-empty")
            parsed_strings[key] = item.strip()

        if parsed_strings["execution_service"] != "platform_assistant":
            raise CapabilityRegistryError("capabilities must execute through platform_assistant")
        if not CAPABILITY_ID_PATTERN.fullmatch(parsed_strings["capability_id"]):
            raise CapabilityRegistryError("invalid capability_id")
        if not SEMVER_PATTERN.fullmatch(parsed_strings["version"]):
            raise CapabilityRegistryError("invalid capability version")
        if parsed_strings["risk_level"] not in {"R0", "R1", "R2", "R3", "R4"}:
            raise CapabilityRegistryError("unsupported capability risk level")

        def string_tuple(key: str, *, required: bool = False) -> tuple[str, ...]:
            raw = value.get(key, [])
            if not isinstance(raw, list) or any(
                not isinstance(item, str) or not item.strip() for item in raw
            ):
                raise CapabilityRegistryError(f"capability field {key!r} must be strings")
            result = tuple(item.strip() for item in raw)
            if len(result) != len(set(result)):
                raise CapabilityRegistryError(f"capability field {key!r} has duplicates")
            if required and not result:
                raise CapabilityRegistryError(f"capability field {key!r} cannot be empty")
            return result

        fallback_strategy = value.get("fallback_strategy")
        if fallback_strategy is not None and fallback_strategy not in {
            "fixed_questions",
            "manual_only",
            "read_only",
        }:
            raise CapabilityRegistryError("unsupported fallback strategy")

        return cls(
            **parsed_strings,
            intents=string_tuple("intents", required=True),
            required_permissions=string_tuple("required_permissions"),
            allowed_projections=string_tuple("allowed_projections"),
            allowed_tools=string_tuple("allowed_tools"),
            forbidden_actions=string_tuple("forbidden_actions", required=True),
            supported_route_ids=string_tuple("supported_route_ids", required=True),
            minimum_generation_fields=string_tuple("minimum_generation_fields"),
            fallback_strategy=fallback_strategy,
        )


class BusinessCapabilityRegistry:
    """Immutable lookup for reviewed platform-assistant business capabilities."""

    def __init__(self, capabilities: Iterable[BusinessCapability]) -> None:
        entries = tuple(capabilities)
        by_id = {item.capability_id: item for item in entries}
        if len(entries) != len(by_id):
            raise CapabilityRegistryError("duplicate capability_id")
        self._entries = entries
        self._by_id = by_id

    @classmethod
    def from_contract(
        cls,
        path: Path | None = None,
        *,
        known_route_ids: Iterable[str] | None = None,
    ) -> BusinessCapabilityRegistry:
        contract_path = path or DEFAULT_CONTRACT_ROOT / "capability-registry.json"
        try:
            payload = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CapabilityRegistryError(f"cannot load capability registry: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
            raise CapabilityRegistryError("unsupported capability registry schema")
        raw_entries = payload.get("capabilities")
        if not isinstance(raw_entries, list) or not raw_entries:
            raise CapabilityRegistryError("capability registry must contain entries")
        entries = tuple(
            BusinessCapability.from_mapping(item)
            for item in raw_entries
            if isinstance(item, dict)
        )
        if len(entries) != len(raw_entries):
            raise CapabilityRegistryError("capability entries must be objects")
        registry = cls(entries)
        if known_route_ids is not None:
            registry.validate_routes(set(known_route_ids))
        return registry

    def validate_routes(self, route_ids: set[str]) -> None:
        for capability in self._entries:
            unknown = set(capability.supported_route_ids) - route_ids
            if capability.target_route_id not in route_ids:
                unknown.add(capability.target_route_id)
            if unknown:
                raise CapabilityRegistryError(
                    f"{capability.capability_id} references unknown routes: {sorted(unknown)}"
                )

    def all(self) -> tuple[BusinessCapability, ...]:
        return self._entries

    def get(self, capability_id: str) -> BusinessCapability | None:
        return self._by_id.get(capability_id)

    def require(self, capability_id: str) -> BusinessCapability:
        capability = self.get(capability_id)
        if capability is None:
            raise CapabilityRegistryError(f"unknown capability: {capability_id}")
        return capability

    def for_route(self, route_id: str) -> tuple[BusinessCapability, ...]:
        return tuple(
            item for item in self._entries if route_id in item.supported_route_ids
        )

    def match_intent(self, text: str) -> tuple[BusinessCapability, ...]:
        normalized = text.strip().casefold()
        if not normalized:
            return ()
        return tuple(
            item
            for item in self._entries
            if any(intent.casefold() in normalized for intent in item.intents)
        )
