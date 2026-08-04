from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import AbstractSet, Iterable, Mapping
from urllib.parse import quote, unquote, urlencode


DEFAULT_CONTRACT_ROOT = (
    Path(__file__).resolve().parents[3] / "contracts" / "platform-assistant" / "v1"
)

PAGE_KEYS = frozenset(
    {"page_instance_id", "route_id", "pathname", "entity_refs", "ui_state", "context_version"}
)
UI_STATE_KEYS = frozenset({"active_tab", "view", "perspective", "dirty"})
ENTITY_TYPES = frozenset(
    {
        "organization",
        "agent",
        "requirement",
        "requirement_draft",
        "quote",
        "agreement",
        "order",
        "milestone",
        "deliverable",
        "dispute",
        "payment_order",
    }
)
OVERLAY_ROUTE_IDS = frozenset({"assistant.chat", "assistant.notifications"})
PAGE_INSTANCE_PATTERN = re.compile(r"^page_[A-Za-z0-9_-]{8,120}$")
ROUTE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,79}$")
PATH_PARAMETER_PATTERN = re.compile(r":([A-Za-z][A-Za-z0-9_]*)")
RESIDUAL_ENCODING_PATTERN = re.compile(r"%[0-9A-Fa-f]{2}")


class ContextResolutionError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class EntityRef:
    type: str
    id: str

    def as_dict(self) -> dict[str, str]:
        return {"type": self.type, "id": self.id}


@dataclass(frozen=True, slots=True)
class PageContext:
    page_instance_id: str
    route_id: str
    pathname: str
    entity_refs: tuple[EntityRef, ...]
    ui_state: Mapping[str, str | bool]
    context_version: int

    @classmethod
    def from_client(cls, payload: Mapping[str, object]) -> PageContext:
        if not isinstance(payload, Mapping):
            raise ContextResolutionError("INVALID_PAGE_CONTEXT", "page context must be an object")
        unexpected = set(payload) - PAGE_KEYS
        missing = PAGE_KEYS - set(payload)
        if unexpected or missing:
            detail = unexpected or missing
            raise ContextResolutionError(
                "INVALID_PAGE_CONTEXT",
                f"page context has invalid fields: {sorted(map(str, detail))}",
            )

        page_instance_id = payload["page_instance_id"]
        route_id = payload["route_id"]
        pathname = payload["pathname"]
        context_version = payload["context_version"]
        if not isinstance(page_instance_id, str) or not PAGE_INSTANCE_PATTERN.fullmatch(
            page_instance_id
        ):
            raise ContextResolutionError("INVALID_PAGE_CONTEXT", "invalid page_instance_id")
        if not isinstance(route_id, str) or not ROUTE_ID_PATTERN.fullmatch(route_id):
            raise ContextResolutionError("INVALID_PAGE_CONTEXT", "invalid route_id")
        if not isinstance(pathname, str):
            raise ContextResolutionError("INVALID_PAGE_CONTEXT", "pathname must be a string")
        normalized_pathname = _validate_pathname(pathname)
        if type(context_version) is not int or context_version < 1:
            raise ContextResolutionError("INVALID_PAGE_CONTEXT", "invalid context_version")

        raw_refs = payload["entity_refs"]
        if not isinstance(raw_refs, list) or len(raw_refs) > 8:
            raise ContextResolutionError("INVALID_PAGE_CONTEXT", "invalid entity_refs")
        refs: list[EntityRef] = []
        seen_types: set[str] = set()
        for raw_ref in raw_refs:
            if not isinstance(raw_ref, Mapping) or set(raw_ref) != {"type", "id"}:
                raise ContextResolutionError("INVALID_PAGE_CONTEXT", "invalid entity reference")
            entity_type = raw_ref["type"]
            entity_id = raw_ref["id"]
            if not isinstance(entity_type, str) or entity_type not in ENTITY_TYPES:
                raise ContextResolutionError("INVALID_PAGE_CONTEXT", "invalid entity type")
            if entity_type in seen_types:
                raise ContextResolutionError("INVALID_PAGE_CONTEXT", "duplicate entity type")
            if not isinstance(entity_id, str):
                raise ContextResolutionError("INVALID_PAGE_CONTEXT", "invalid entity id")
            refs.append(EntityRef(entity_type, _validate_identifier(entity_id)))
            seen_types.add(entity_type)

        raw_ui_state = payload["ui_state"]
        if not isinstance(raw_ui_state, Mapping) or set(raw_ui_state) - UI_STATE_KEYS:
            raise ContextResolutionError("INVALID_PAGE_CONTEXT", "invalid ui_state fields")
        ui_state: dict[str, str | bool] = {}
        for key, value in raw_ui_state.items():
            if key in {"active_tab", "view"}:
                if not isinstance(value, str) or len(value) > 80:
                    raise ContextResolutionError("INVALID_PAGE_CONTEXT", f"invalid {key}")
            elif key == "perspective":
                if value not in {"buyer", "provider", "internal"}:
                    raise ContextResolutionError("INVALID_PAGE_CONTEXT", "invalid perspective")
            elif key == "dirty" and not isinstance(value, bool):
                raise ContextResolutionError("INVALID_PAGE_CONTEXT", "invalid dirty flag")
            ui_state[key] = value

        return cls(
            page_instance_id=page_instance_id,
            route_id=route_id,
            pathname=normalized_pathname,
            entity_refs=tuple(refs),
            ui_state=MappingProxyType(ui_state),
            context_version=context_version,
        )


@dataclass(frozen=True, slots=True)
class EntityRefRule:
    type: str
    source: str
    required: bool


@dataclass(frozen=True, slots=True)
class RouteDefinition:
    route_id: str
    path_pattern: str | None
    surface: str
    entity_refs: tuple[EntityRefRule, ...]
    allowed_query_params: tuple[str, ...]
    allowed_projections: tuple[str, ...]
    authorization: str
    context_version_triggers: tuple[str, ...]
    safe_deep_link: bool
    match_priority: int
    path_regex: re.Pattern[str] | None = field(compare=False, repr=False)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> RouteDefinition:
        route_id = value.get("route_id")
        path_pattern = value.get("path_pattern")
        if not isinstance(route_id, str) or not ROUTE_ID_PATTERN.fullmatch(route_id):
            raise ContextResolutionError("INVALID_ROUTE_REGISTRY", "invalid registered route_id")
        if path_pattern is not None and (
            not isinstance(path_pattern, str) or not path_pattern.startswith("/")
        ):
            raise ContextResolutionError("INVALID_ROUTE_REGISTRY", "invalid path pattern")

        def strings(key: str) -> tuple[str, ...]:
            raw = value.get(key, [])
            if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
                raise ContextResolutionError("INVALID_ROUTE_REGISTRY", f"invalid {key}")
            result = tuple(raw)
            if len(result) != len(set(result)):
                raise ContextResolutionError("INVALID_ROUTE_REGISTRY", f"duplicate {key}")
            return result

        raw_refs = value.get("entity_refs", [])
        if not isinstance(raw_refs, list):
            raise ContextResolutionError("INVALID_ROUTE_REGISTRY", "invalid entity ref rules")
        ref_rules: list[EntityRefRule] = []
        for item in raw_refs:
            if not isinstance(item, Mapping):
                raise ContextResolutionError("INVALID_ROUTE_REGISTRY", "invalid entity ref rule")
            entity_type = item.get("type")
            source = item.get("source")
            required = item.get("required")
            if (
                not isinstance(entity_type, str)
                or entity_type not in ENTITY_TYPES
                or not isinstance(source, str)
                or type(required) is not bool
            ):
                raise ContextResolutionError("INVALID_ROUTE_REGISTRY", "invalid entity ref rule")
            ref_rules.append(EntityRefRule(entity_type, source, required))

        authorization = value.get("authorization")
        surface = value.get("surface")
        safe_deep_link = value.get("safe_deep_link")
        match_priority = value.get("match_priority")
        if not isinstance(authorization, str) or not isinstance(surface, str):
            raise ContextResolutionError("INVALID_ROUTE_REGISTRY", "invalid route policy")
        if type(safe_deep_link) is not bool or type(match_priority) is not int:
            raise ContextResolutionError("INVALID_ROUTE_REGISTRY", "invalid route metadata")
        if surface == "assistant_overlay" and path_pattern is not None:
            raise ContextResolutionError("INVALID_ROUTE_REGISTRY", "overlay cannot match a path")
        if surface != "assistant_overlay" and path_pattern is None:
            raise ContextResolutionError("INVALID_ROUTE_REGISTRY", "page route requires a path")

        return cls(
            route_id=route_id,
            path_pattern=path_pattern,
            surface=surface,
            entity_refs=tuple(ref_rules),
            allowed_query_params=strings("allowed_query_params"),
            allowed_projections=strings("allowed_projections"),
            authorization=authorization,
            context_version_triggers=strings("context_version_triggers"),
            safe_deep_link=safe_deep_link,
            match_priority=match_priority,
            path_regex=_compile_path(path_pattern) if path_pattern else None,
        )


@dataclass(frozen=True, slots=True)
class TrustedResolutionScope:
    """Identity and visibility supplied by authenticated server state, never by the client."""

    user_id: str
    tenant_id: str
    active_organization_id: str | None
    organization_ids: frozenset[str]
    visible_entities: Mapping[str, AbstractSet[str]] = field(default_factory=dict)
    row_version: int | None = None
    minimum_context_version: int = 1

    def __post_init__(self) -> None:
        if not self.user_id or not self.tenant_id:
            raise ValueError("trusted identity is incomplete")
        if self.active_organization_id is not None and (
            self.active_organization_id not in self.organization_ids
        ):
            raise ValueError("active organization must be authorized by the server")
        if self.row_version is not None and self.row_version < 1:
            raise ValueError("row_version must be positive")
        if self.minimum_context_version < 1:
            raise ValueError("minimum_context_version must be positive")
        object.__setattr__(self, "organization_ids", frozenset(self.organization_ids))
        object.__setattr__(
            self,
            "visible_entities",
            MappingProxyType(
                {key: frozenset(value) for key, value in self.visible_entities.items()}
            ),
        )


@dataclass(frozen=True, slots=True)
class ResolvedPageContext:
    page_instance_id: str
    route_id: str
    underlying_route_id: str
    resolved_pathname: str
    organization_id: str | None
    entity_refs: tuple[EntityRef, ...]
    authorization: str
    projection_refs: tuple[str, ...]
    context_version: int
    row_version: int | None
    stale: bool

    def as_contract(self) -> dict[str, object]:
        return {
            "page_instance_id": self.page_instance_id,
            "route_id": self.route_id,
            "resolved_pathname": self.resolved_pathname,
            "organization_id": self.organization_id,
            "entity_refs": [item.as_dict() for item in self.entity_refs],
            "authorization": self.authorization,
            "projection_refs": list(self.projection_refs),
            "context_version": self.context_version,
            "row_version": self.row_version,
            "stale": self.stale,
        }


class RouteContextRegistry:
    def __init__(self, routes: Iterable[RouteDefinition]) -> None:
        entries = tuple(routes)
        by_id = {item.route_id: item for item in entries}
        if len(entries) != len(by_id):
            raise ContextResolutionError("INVALID_ROUTE_REGISTRY", "duplicate route_id")
        self._entries = entries
        self._by_id = by_id
        self._page_routes = tuple(
            sorted(
                (item for item in entries if item.path_pattern is not None),
                key=lambda item: (
                    item.match_priority,
                    len(item.path_pattern or ""),
                ),
                reverse=True,
            )
        )

    @classmethod
    def from_contract(cls, path: Path | None = None) -> RouteContextRegistry:
        contract_path = path or DEFAULT_CONTRACT_ROOT / "route-context-registry.json"
        try:
            payload = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContextResolutionError(
                "INVALID_ROUTE_REGISTRY", f"cannot load route registry: {exc}"
            ) from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != "1.0":
            raise ContextResolutionError("INVALID_ROUTE_REGISTRY", "unsupported route schema")
        raw_routes = payload.get("routes")
        if not isinstance(raw_routes, list) or not raw_routes:
            raise ContextResolutionError("INVALID_ROUTE_REGISTRY", "route registry is empty")
        if any(not isinstance(item, dict) for item in raw_routes):
            raise ContextResolutionError("INVALID_ROUTE_REGISTRY", "route entry must be an object")
        return cls(RouteDefinition.from_mapping(item) for item in raw_routes)

    @property
    def route_ids(self) -> frozenset[str]:
        return frozenset(self._by_id)

    def get(self, route_id: str) -> RouteDefinition | None:
        return self._by_id.get(route_id)

    def require(self, route_id: str) -> RouteDefinition:
        route = self.get(route_id)
        if route is None:
            raise ContextResolutionError("ROUTE_NOT_REGISTERED", "route is not registered")
        return route

    def match_page(
        self, pathname: str, ui_state: Mapping[str, str | bool]
    ) -> tuple[RouteDefinition, dict[str, str]]:
        normalized = _validate_pathname(pathname)
        for route in self._page_routes:
            if not _matches_route_variant(route.route_id, ui_state):
                continue
            assert route.path_regex is not None
            match = route.path_regex.fullmatch(normalized)
            if match:
                params = {
                    key: _validate_identifier(unquote(value))
                    for key, value in match.groupdict().items()
                }
                return route, params
        raise ContextResolutionError("ROUTE_NOT_REGISTERED", "pathname is not registered")

    def build_deep_link(
        self,
        route_id: str,
        *,
        path_params: Mapping[str, str] | None = None,
        query: Mapping[str, str | int | bool] | None = None,
    ) -> str:
        route = self.require(route_id)
        if not route.safe_deep_link or route.path_pattern is None:
            raise ContextResolutionError("UNSAFE_DEEP_LINK", "route cannot generate a deep link")
        params = dict(path_params or {})
        required = set(PATH_PARAMETER_PATTERN.findall(route.path_pattern))
        if set(params) != required:
            raise ContextResolutionError("INVALID_DEEP_LINK", "path parameters do not match route")
        path = route.path_pattern
        for key, value in params.items():
            path = path.replace(f":{key}", quote(_validate_identifier(value), safe=""))
        query_values = dict(query or {})
        if set(query_values) - set(route.allowed_query_params):
            raise ContextResolutionError("INVALID_DEEP_LINK", "query parameter is not allowed")
        if any(key in {"route", "payload", "url", "href", "pathname"} for key in query_values):
            raise ContextResolutionError("INVALID_DEEP_LINK", "raw navigation is forbidden")
        if any(not isinstance(value, (str, int, bool)) for value in query_values.values()):
            raise ContextResolutionError("INVALID_DEEP_LINK", "query values must be scalar")
        encoded = urlencode(query_values)
        return f"{path}?{encoded}" if encoded else path


def resolve_page_context(
    payload: Mapping[str, object] | PageContext,
    trusted: TrustedResolutionScope,
    *,
    registry: RouteContextRegistry | None = None,
) -> ResolvedPageContext:
    page = payload if isinstance(payload, PageContext) else PageContext.from_client(payload)
    route_registry = registry or RouteContextRegistry.from_contract()
    requested_route = route_registry.require(page.route_id)
    overlay = requested_route if requested_route.surface == "assistant_overlay" else None
    try:
        underlying, path_params = route_registry.match_page(page.pathname, page.ui_state)
    except ContextResolutionError as exc:
        if overlay is None or exc.code != "ROUTE_NOT_REGISTERED":
            raise
        # The drawer is global. On an unregistered underlying page it may still
        # answer general platform questions, but receives no business projection.
        underlying, path_params = overlay, {}
    if overlay is None and requested_route.route_id != underlying.route_id:
        raise ContextResolutionError(
            "ROUTE_CONTEXT_MISMATCH", "route_id does not match the registered pathname"
        )

    organization_id = _authorize_organization(underlying, page, trusted)
    resolved_refs = _resolve_entity_refs(underlying, path_params, page, trusted)
    projection_refs = tuple(
        dict.fromkeys(
            (
                *(() if underlying is overlay else underlying.allowed_projections),
                *(overlay.allowed_projections if overlay else ()),
            )
        )
    )
    if any(item in {"route", "payload"} or item.endswith(".payload") for item in projection_refs):
        raise ContextResolutionError(
            "INVALID_ROUTE_REGISTRY", "raw route or payload projections are forbidden"
        )
    return ResolvedPageContext(
        page_instance_id=page.page_instance_id,
        route_id=overlay.route_id if overlay else underlying.route_id,
        underlying_route_id=underlying.route_id,
        resolved_pathname=page.pathname,
        organization_id=organization_id,
        entity_refs=resolved_refs,
        authorization=underlying.authorization,
        projection_refs=projection_refs,
        context_version=page.context_version,
        row_version=trusted.row_version,
        stale=page.context_version < trusted.minimum_context_version,
    )


def _authorize_organization(
    route: RouteDefinition, page: PageContext, trusted: TrustedResolutionScope
) -> str | None:
    client_organization = next(
        (item.id for item in page.entity_refs if item.type == "organization"), None
    )
    if client_organization is not None and client_organization not in trusted.organization_ids:
        raise ContextResolutionError(
            "CONTEXT_FORBIDDEN", "organization is not accessible", status_code=403
        )
    if client_organization is not None and client_organization != trusted.active_organization_id:
        raise ContextResolutionError(
            "CONTEXT_FORBIDDEN", "client cannot switch server organization", status_code=403
        )
    if route.authorization in {"organization_member", "order_party"}:
        if trusted.active_organization_id is None:
            raise ContextResolutionError(
                "CONTEXT_FORBIDDEN", "an authorized organization is required", status_code=403
            )
        if trusted.active_organization_id not in trusted.organization_ids:
            raise ContextResolutionError(
                "CONTEXT_FORBIDDEN", "organization is not accessible", status_code=403
            )
    return trusted.active_organization_id


def _resolve_entity_refs(
    route: RouteDefinition,
    path_params: Mapping[str, str],
    page: PageContext,
    trusted: TrustedResolutionScope,
) -> tuple[EntityRef, ...]:
    client_by_type = {item.type: item for item in page.entity_refs}
    permitted_types = {"organization", *(item.type for item in route.entity_refs)}
    unexpected = set(client_by_type) - permitted_types
    if unexpected:
        raise ContextResolutionError(
            "CONTEXT_FORBIDDEN", "entity reference is not valid for this route", status_code=403
        )
    result: list[EntityRef] = []
    organization = client_by_type.get("organization")
    if organization is not None:
        result.append(organization)
    for rule in route.entity_refs:
        source_kind, separator, source_name = rule.source.partition(".")
        client_ref = client_by_type.get(rule.type)
        if source_kind == "path" and separator:
            if source_name not in path_params:
                if rule.required:
                    raise ContextResolutionError(
                        "INVALID_ROUTE_REGISTRY", "entity source is missing"
                    )
                continue
            entity_id = path_params[source_name]
            if client_ref is not None and client_ref.id != entity_id:
                raise ContextResolutionError(
                    "CONTEXT_FORBIDDEN",
                    "entity reference does not match pathname",
                    status_code=403,
                )
        elif source_kind == "query" and separator:
            # The browser converts only this reviewed query parameter to a typed
            # candidate entity reference. The raw query never crosses the contract.
            if client_ref is None:
                if rule.required:
                    raise ContextResolutionError(
                        "CONTEXT_FORBIDDEN", "required entity reference is missing", status_code=403
                    )
                continue
            entity_id = client_ref.id
        else:
            raise ContextResolutionError(
                "INVALID_ROUTE_REGISTRY", "unsupported entity source"
            )
        visible = trusted.visible_entities.get(rule.type, frozenset())
        if entity_id not in visible:
            raise ContextResolutionError(
                "CONTEXT_FORBIDDEN", "entity is not accessible", status_code=403
            )
        result.append(EntityRef(rule.type, entity_id))
    return tuple(result)


def _compile_path(pattern: str) -> re.Pattern[str]:
    cursor = 0
    parts: list[str] = ["^"]
    for match in PATH_PARAMETER_PATTERN.finditer(pattern):
        parts.append(re.escape(pattern[cursor : match.start()]))
        parts.append(f"(?P<{match.group(1)}>[^/]+)")
        cursor = match.end()
    parts.append(re.escape(pattern[cursor:]))
    parts.append("$")
    return re.compile("".join(parts))


def _matches_route_variant(route_id: str, ui_state: Mapping[str, str | bool]) -> bool:
    view = ui_state.get("view")
    if route_id == "workspace.project_center.projects":
        return view == "projects"
    if route_id == "workspace.project_center.agents":
        return view != "projects"
    if route_id == "enterprise.provider.workbench":
        return view == "workbench"
    if route_id == "enterprise.provider.quotes":
        return view != "workbench"
    return True


def _validate_pathname(value: str) -> str:
    if (
        not value.startswith("/")
        or len(value) > 500
        or "?" in value
        or "#" in value
        or "\\" in value
        or "\x00" in value
        or any(ord(character) < 32 for character in value)
        or value.startswith("//")
    ):
        raise ContextResolutionError("INVALID_PAGE_CONTEXT", "invalid pathname")
    segments = value.split("/")
    if any(segment in {".", ".."} for segment in segments):
        raise ContextResolutionError("INVALID_PAGE_CONTEXT", "invalid pathname segment")
    return value.rstrip("/") or "/"


def _validate_identifier(value: str) -> str:
    if (
        not value
        or len(value) > 160
        or value in {".", ".."}
        or "/" in value
        or "\\" in value
        or "\x00" in value
        or any(ord(character) < 32 for character in value)
        or RESIDUAL_ENCODING_PATTERN.search(value)
    ):
        raise ContextResolutionError("INVALID_PAGE_CONTEXT", "invalid entity identifier")
    return value
