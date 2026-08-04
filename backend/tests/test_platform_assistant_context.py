from __future__ import annotations

from copy import deepcopy

import pytest

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


def page(
    route_id: str,
    pathname: str,
    *,
    refs: list[dict[str, str]] | None = None,
    ui_state: dict[str, str | bool] | None = None,
    version: int = 1,
) -> dict[str, object]:
    return {
        "page_instance_id": "page_testcontext01",
        "route_id": route_id,
        "pathname": pathname,
        "entity_refs": refs or [],
        "ui_state": ui_state or {},
        "context_version": version,
    }


def trusted(
    *,
    active_organization_id: str | None = "org_a",
    organization_ids: frozenset[str] = frozenset({"org_a"}),
    visible_entities: dict[str, frozenset[str]] | None = None,
    minimum_context_version: int = 1,
) -> TrustedResolutionScope:
    return TrustedResolutionScope(
        user_id="user_server_verified",
        tenant_id="tenant_server_verified",
        active_organization_id=active_organization_id,
        organization_ids=organization_ids,
        visible_entities=visible_entities or {},
        row_version=7,
        minimum_context_version=minimum_context_version,
    )


def test_business_capability_registry_loads_reviewed_contract() -> None:
    routes = RouteContextRegistry.from_contract()
    registry = BusinessCapabilityRegistry.from_contract(known_route_ids=routes.route_ids)

    requirement = registry.require("requirement.create")
    assert requirement.version == "1.0.0"
    assert requirement.target_route_id == "enterprise.requirement.create"
    assert "requirement.publish" in requirement.forbidden_actions
    for_requirement_list = registry.for_route("enterprise.requirement.list")
    assert requirement in for_requirement_list
    assert registry.require("platform.guidance") in for_requirement_list
    assert registry.match_intent("请帮我发布需求") == (requirement,)
    with pytest.raises(CapabilityRegistryError, match="unknown capability"):
        registry.require("requirement.publish")


@pytest.mark.parametrize(
    ("pathname", "ui_state", "expected"),
    [
        ("/workspace/gallery", {}, "workspace.project_center.agents"),
        ("/workspace/gallery", {"view": "projects"}, "workspace.project_center.projects"),
        ("/enterprise/provider", {}, "enterprise.provider.quotes"),
        ("/enterprise/provider", {"view": "quotes"}, "enterprise.provider.quotes"),
        ("/enterprise/provider", {"view": "workbench"}, "enterprise.provider.workbench"),
        ("/enterprise/demands", {}, "enterprise.requirement.list"),
        ("/enterprise/demands/new", {}, "enterprise.requirement.create"),
        ("/enterprise/demands/requirement_1", {}, "enterprise.requirement.detail"),
        ("/enterprise/demands/requirement_1/quotes", {}, "enterprise.requirement.quotes"),
        ("/enterprise/provider/quotes/quote_1", {}, "enterprise.provider.quote"),
        ("/enterprise/agreements/agreement_1", {}, "enterprise.agreement.detail"),
        ("/enterprise/orders/order_1/deliverables/deliverable_1", {}, "enterprise.order.deliverable"),
        ("/enterprise/disputes/dispute_1", {}, "enterprise.dispute.detail"),
        ("/enterprise/payments/payment_1", {}, "enterprise.payment.detail"),
    ],
)
def test_route_registry_resolves_variants_and_detail_first(
    pathname: str, ui_state: dict[str, str], expected: str
) -> None:
    route, _ = RouteContextRegistry.from_contract().match_page(pathname, ui_state)
    assert route.route_id == expected


def test_order_context_is_server_resolved_and_redacted_to_projection_refs() -> None:
    result = resolve_page_context(
        page(
            "enterprise.order.workspace",
            "/enterprise/orders/order_1",
            refs=[{"type": "order", "id": "order_1"}],
            ui_state={"active_tab": "deliverables", "perspective": "buyer"},
        ),
        trusted(visible_entities={"order": frozenset({"order_1"})}),
    )

    assert result.route_id == "enterprise.order.workspace"
    assert result.organization_id == "org_a"
    assert result.entity_refs[-1].id == "order_1"
    assert result.authorization == "order_party"
    assert "order.visible_deliverables" in result.projection_refs
    assert "payload" not in " ".join(result.projection_refs)
    contract = result.as_contract()
    assert "user_id" not in contract
    assert "tenant_id" not in contract
    assert "underlying_route_id" not in contract


def test_deliverable_context_requires_both_visible_order_and_deliverable() -> None:
    payload = page(
        "enterprise.order.deliverable",
        "/enterprise/orders/order_1/deliverables/deliverable_1",
        refs=[
            {"type": "order", "id": "order_1"},
            {"type": "deliverable", "id": "deliverable_1"},
        ],
    )
    result = resolve_page_context(
        payload,
        trusted(
            visible_entities={
                "order": frozenset({"order_1"}),
                "deliverable": frozenset({"deliverable_1"}),
            }
        ),
    )
    assert [(item.type, item.id) for item in result.entity_refs] == [
        ("order", "order_1"),
        ("deliverable", "deliverable_1"),
    ]
    assert "deliverable.visible_versions" in result.projection_refs

    with pytest.raises(ContextResolutionError) as error:
        resolve_page_context(
            payload,
            trusted(
                visible_entities={
                    "order": frozenset({"order_1"}),
                    "deliverable": frozenset(),
                }
            ),
        )
    assert error.value.code == "CONTEXT_FORBIDDEN"


@pytest.mark.parametrize("overlay", ["assistant.chat", "assistant.notifications"])
def test_overlay_inherits_underlying_route_and_permissions(overlay: str) -> None:
    result = resolve_page_context(
        page(
            overlay,
            "/enterprise/orders/order_1",
            refs=[{"type": "order", "id": "order_1"}],
            ui_state={"active_tab": "overview"},
        ),
        trusted(visible_entities={"order": frozenset({"order_1"})}),
    )

    assert result.route_id == overlay
    assert result.underlying_route_id == "enterprise.order.workspace"
    assert result.authorization == "order_party"
    assert "order.party_summary" in result.projection_refs
    expected_overlay_projection = (
        "assistant.active_workflow" if overlay == "assistant.chat" else "notification.visible_list"
    )
    assert expected_overlay_projection in result.projection_refs


def test_overlay_on_unregistered_page_degrades_to_general_context() -> None:
    result = resolve_page_context(
        page("assistant.chat", "/workspace/chat/session_1"),
        trusted(active_organization_id=None, organization_ids=frozenset()),
    )
    assert result.route_id == "assistant.chat"
    assert result.underlying_route_id == "assistant.chat"
    assert result.authorization == "authenticated"
    assert result.projection_refs == ("assistant.active_workflow",)
    assert result.entity_refs == ()


@pytest.mark.parametrize("forged_key", ["user_id", "tenant_id", "organization_id", "route", "payload"])
def test_client_cannot_assert_identity_or_raw_navigation(forged_key: str) -> None:
    payload = page("enterprise.requirement.list", "/enterprise/demands")
    payload[forged_key] = {"raw": "https://evil.example"}
    with pytest.raises(ContextResolutionError) as error:
        PageContext.from_client(payload)
    assert error.value.code == "INVALID_PAGE_CONTEXT"


def test_client_cannot_switch_to_another_organization() -> None:
    payload = page(
        "enterprise.requirement.list",
        "/enterprise/demands",
        refs=[{"type": "organization", "id": "org_b"}],
    )
    with pytest.raises(ContextResolutionError) as error:
        resolve_page_context(
            payload,
            trusted(organization_ids=frozenset({"org_a", "org_b"})),
        )
    assert error.value.code == "CONTEXT_FORBIDDEN"
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "refs",
    [
        [{"type": "order", "id": "order_forged"}],
        [{"type": "quote", "id": "quote_smuggled"}],
    ],
)
def test_forged_or_unexpected_entity_refs_are_forbidden(
    refs: list[dict[str, str]],
) -> None:
    with pytest.raises(ContextResolutionError) as error:
        resolve_page_context(
            page("enterprise.order.workspace", "/enterprise/orders/order_1", refs=refs),
            trusted(visible_entities={"order": frozenset({"order_1"})}),
        )
    assert error.value.code == "CONTEXT_FORBIDDEN"
    assert error.value.status_code == 403


def test_path_entity_must_be_visible_even_when_client_omits_ref() -> None:
    with pytest.raises(ContextResolutionError) as error:
        resolve_page_context(
            page("enterprise.order.workspace", "/enterprise/orders/order_hidden"),
            trusted(visible_entities={"order": frozenset({"order_1"})}),
        )
    assert error.value.code == "CONTEXT_FORBIDDEN"


def test_route_id_cannot_disagree_with_server_path_resolution() -> None:
    with pytest.raises(ContextResolutionError) as error:
        resolve_page_context(
            page("enterprise.order.list", "/enterprise/demands"), trusted()
        )
    assert error.value.code == "ROUTE_CONTEXT_MISMATCH"


@pytest.mark.parametrize(
    "pathname",
    [
        "/enterprise/orders/order_1?tab=overview",
        "/enterprise/orders/order%252Fescape",
        "/enterprise/orders/%2E%2E",
        "//evil.example/orders/order_1",
        "/enterprise/orders/../order_1",
    ],
)
def test_pathname_rejects_query_smuggling_and_encoded_separators(pathname: str) -> None:
    with pytest.raises(ContextResolutionError):
        resolve_page_context(
            page("enterprise.order.workspace", pathname),
            trusted(visible_entities={"order": frozenset({"order_1"})}),
        )


def test_deep_link_builder_only_uses_whitelisted_route_and_parameters() -> None:
    registry = RouteContextRegistry.from_contract()
    assert registry.build_deep_link(
        "enterprise.order.workspace",
        path_params={"orderId": "order_1"},
        query={"tab": "deliverables"},
    ) == "/enterprise/orders/order_1?tab=deliverables"
    assert registry.build_deep_link(
        "enterprise.requirement.create", query={"draftId": "draft_1"}
    ) == "/enterprise/demands/new?draftId=draft_1"

    with pytest.raises(ContextResolutionError) as unknown:
        registry.build_deep_link("https://evil.example")
    assert unknown.value.code == "ROUTE_NOT_REGISTERED"
    with pytest.raises(ContextResolutionError) as raw_query:
        registry.build_deep_link(
            "enterprise.order.workspace",
            path_params={"orderId": "order_1"},
            query={"route": "https://evil.example"},
        )
    assert raw_query.value.code == "INVALID_DEEP_LINK"
    with pytest.raises(ContextResolutionError) as overlay:
        registry.build_deep_link("assistant.chat")
    assert overlay.value.code == "UNSAFE_DEEP_LINK"


def test_requirement_draft_query_is_projected_as_typed_authorized_entity() -> None:
    payload = page(
        "enterprise.requirement.create",
        "/enterprise/demands/new",
        refs=[{"type": "requirement_draft", "id": "reqdraft_1"}],
    )
    resolved = resolve_page_context(
        payload,
        trusted(visible_entities={"requirement_draft": frozenset({"reqdraft_1"})}),
    )
    assert resolved.entity_refs[-1].as_dict() == {
        "type": "requirement_draft",
        "id": "reqdraft_1",
    }

    with pytest.raises(ContextResolutionError) as hidden:
        resolve_page_context(
            payload,
            trusted(visible_entities={"requirement_draft": frozenset()}),
        )
    assert hidden.value.code == "CONTEXT_FORBIDDEN"


def test_resolved_context_marks_old_client_version_stale_without_trusting_payload() -> None:
    result = resolve_page_context(
        page("enterprise.requirement.list", "/enterprise/demands", version=2),
        trusted(minimum_context_version=3),
    )
    assert result.context_version == 2
    assert result.row_version == 7
    assert result.stale is True


def test_route_contract_with_raw_projection_is_rejected_at_resolution() -> None:
    contract = json_contract()
    forged = deepcopy(contract)
    order_route = next(
        route
        for route in forged["routes"]
        if route["route_id"] == "enterprise.order.workspace"
    )
    order_route["allowed_projections"].append("order.payload")
    registry = RouteContextRegistry(
        route_from_mapping(item) for item in forged["routes"]
    )
    with pytest.raises(ContextResolutionError) as error:
        resolve_page_context(
            page(
                "enterprise.order.workspace",
                "/enterprise/orders/order_1",
                refs=[{"type": "order", "id": "order_1"}],
            ),
            trusted(visible_entities={"order": frozenset({"order_1"})}),
            registry=registry,
        )
    assert error.value.code == "INVALID_ROUTE_REGISTRY"


def json_contract() -> dict[str, object]:
    import json
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "platform-assistant"
        / "v1"
        / "route-context-registry.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def route_from_mapping(value: dict[str, object]):
    from app.platform_assistant.context import RouteDefinition

    return RouteDefinition.from_mapping(value)
