from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = REPO_ROOT / "contracts" / "platform-assistant" / "v1"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return load_json(CONTRACT_ROOT / "manifest.json")


@pytest.fixture(scope="module")
def schemas(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: load_json(CONTRACT_ROOT / item["path"])
        for item in manifest["schemas"]
    }


def schema_registry(schemas: dict[str, dict[str, Any]]) -> Registry:
    return Registry().with_resources(
        (schema_id, Resource.from_contents(schema))
        for schema_id, schema in schemas.items()
    )


def assert_unique(values: list[str], label: str) -> None:
    assert len(values) == len(set(values)), f"duplicate {label}: {values}"


def errors_for(
    schema_id: str,
    payload: dict[str, Any],
    schemas: dict[str, dict[str, Any]],
) -> list[Any]:
    validator = Draft202012Validator(
        schemas[schema_id],
        registry=schema_registry(schemas),
        format_checker=FormatChecker(),
    )
    return list(validator.iter_errors(payload))


def test_every_schema_is_valid_draft_2020_12(
    schemas: dict[str, dict[str, Any]],
) -> None:
    for schema_id, schema in schemas.items():
        assert schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
        assert schema.get("$id") == schema_id
        Draft202012Validator.check_schema(schema)


def test_manifest_is_closed_and_has_no_duplicates(manifest: dict[str, Any]) -> None:
    schema_ids = [item["id"] for item in manifest["schemas"]]
    schema_paths = [item["path"] for item in manifest["schemas"]]
    instance_paths = [item["path"] for item in manifest["instances"]]
    assert_unique(schema_ids, "schema id")
    assert_unique(schema_paths, "schema path")
    assert_unique(instance_paths, "instance path")

    actual_schemas = {
        path.relative_to(CONTRACT_ROOT).as_posix()
        for path in (CONTRACT_ROOT / "schemas").glob("*.json")
    }
    assert set(schema_paths) == actual_schemas
    assert {item["schema"] for item in manifest["instances"]} <= set(schema_ids)
    for item in manifest["instances"]:
        assert (CONTRACT_ROOT / item["path"]).is_file()


def test_every_registered_instance_validates(
    manifest: dict[str, Any],
    schemas: dict[str, dict[str, Any]],
) -> None:
    registry = schema_registry(schemas)
    for item in manifest["instances"]:
        validator = Draft202012Validator(
            schemas[item["schema"]],
            registry=registry,
            format_checker=FormatChecker(),
        )
        errors = sorted(
            validator.iter_errors(load_json(CONTRACT_ROOT / item["path"])),
            key=lambda error: list(error.absolute_path),
        )
        assert not errors, "\n".join(
            f"{item['path']}:{'/'.join(map(str, error.absolute_path))}: {error.message}"
            for error in errors
        )


def test_client_page_context_is_minimal_and_cannot_assert_identity(
    schemas: dict[str, dict[str, Any]],
) -> None:
    valid = {
        "page_instance_id": "page_12345678",
        "route_id": "enterprise.requirement.list",
        "pathname": "/enterprise/demands",
        "entity_refs": [],
        "ui_state": {"dirty": False},
        "context_version": 1,
    }
    assert not errors_for("page-context.schema.json", valid, schemas)
    for forbidden in ("user_id", "organization_id", "tenant_id", "payload", "route"):
        invalid = {**valid, forbidden: "forged"}
        assert errors_for("page-context.schema.json", invalid, schemas), forbidden


def test_deep_links_only_accept_registered_route_ids_and_parameters(
    schemas: dict[str, dict[str, Any]],
) -> None:
    base = {
        "schema_version": "1.0",
        "block_id": "block_deeplink_001",
        "block_version": 1,
        "type": "deep_link",
        "status": "pending",
        "title": "打开需求表单",
        "description": "请在真实页面确认后发布。",
        "route_id": "enterprise.order.workspace",
        # Registered React routes use lower-camel placeholder names. The
        # protocol must preserve those exact keys while still rejecting URLs.
        "route_params": {"orderId": "order_sample001"},
        "label": "打开订单",
    }
    assert not errors_for("structured-block.schema.json", base, schemas)
    for forbidden in ("url", "pathname", "href", "query"):
        invalid = {**base, forbidden: "https://evil.example"}
        assert errors_for("structured-block.schema.json", invalid, schemas), forbidden


def test_route_registry_covers_migration_targets_and_overlay_semantics() -> None:
    registry = load_json(CONTRACT_ROOT / "route-context-registry.json")
    routes = registry["routes"]
    route_ids = [item["route_id"] for item in routes]
    assert_unique(route_ids, "route id")
    required = {
        "workspace.project_center.agents",
        "workspace.project_center.projects",
        "workspace.project_center.agent",
        "enterprise.order.workspace",
        "enterprise.transaction.overview",
        "enterprise.requirement.list",
        "enterprise.order.list",
        "enterprise.confirmation.list",
        "enterprise.publishing.list",
        "enterprise.provider.quotes",
        "enterprise.provider.workbench",
        "assistant.chat",
        "assistant.notifications",
        "enterprise.requirement.create",
        "enterprise.requirement.detail",
        "enterprise.requirement.quotes",
        "enterprise.provider.quote",
        "enterprise.agreement.detail",
        "enterprise.order.deliverable",
        "enterprise.dispute.detail",
        "enterprise.payment.detail",
    }
    assert required <= set(route_ids)
    for route in routes:
        if route["surface"] == "assistant_overlay":
            assert route["path_pattern"] is None
            assert route["safe_deep_link"] is False
        else:
            assert route["path_pattern"].startswith("/")
        serialized = json.dumps(route["allowed_projections"])
        assert "payload" not in serialized
        assert "route" not in serialized

    create_route = next(
        route for route in routes if route["route_id"] == "enterprise.requirement.create"
    )
    list_route = next(
        route for route in routes if route["route_id"] == "enterprise.requirement.list"
    )
    assert create_route["match_priority"] > list_route["match_priority"]


def test_capability_and_policy_ids_are_unique_and_closed() -> None:
    capabilities = load_json(CONTRACT_ROOT / "capability-registry.json")["capabilities"]
    routes = load_json(CONTRACT_ROOT / "route-context-registry.json")["routes"]
    actions = load_json(CONTRACT_ROOT / "risk-action-matrix.json")["actions"]
    assert_unique([item["capability_id"] for item in capabilities], "capability id")
    assert_unique([item["action_id"] for item in actions], "action id")
    route_ids = {item["route_id"] for item in routes}
    action_ids = {item["action_id"] for item in actions}
    for capability in capabilities:
        assert set(capability["supported_route_ids"]) <= route_ids
        assert capability["target_route_id"] in route_ids
        assert set(capability["allowed_tools"]) <= action_ids
        assert set(capability["forbidden_actions"]) <= action_ids


def test_r3_and_r4_actions_cannot_be_misconfigured(
    schemas: dict[str, dict[str, Any]],
) -> None:
    matrix = load_json(CONTRACT_ROOT / "risk-action-matrix.json")
    invalid_r3 = deepcopy(matrix)
    next(
        action for action in invalid_r3["actions"] if action["action_id"] == "requirement.publish"
    )["assistant_policy"] = "allow"
    assert errors_for("risk-action-matrix.schema.json", invalid_r3, schemas)
    invalid_r4 = deepcopy(matrix)
    next(
        action for action in invalid_r4["actions"] if action["action_id"] == "agreement.confirm"
    )["assistant_policy"] = "allow_with_result"
    assert errors_for("risk-action-matrix.schema.json", invalid_r4, schemas)


def test_requirement_field_map_is_total_and_hard_facts_are_not_ai_owned() -> None:
    mapping = load_json(CONTRACT_ROOT / "requirement-field-map.json")["fields"]
    draft_schema = load_json(
        CONTRACT_ROOT / "schemas" / "requirement-draft-input.schema.json"
    )
    assert_unique([item["draft_field"] for item in mapping], "requirement draft field")
    assert {item["draft_field"] for item in mapping} == set(
        draft_schema["properties"]
    )
    for item in mapping:
        assert item["disposition"] in {
            "mapped",
            "server_derived",
            "assistant_only",
            "blocking_unmapped",
        }
        if item["hard_fact"]:
            assert "ai_expansion" not in item["source_policy"], item["draft_field"]

    confidentiality = next(
        item for item in mapping if item["draft_field"] == "confidentiality_level"
    )
    assert confidentiality["disposition"] == "mapped"
    assert confidentiality["target_field"] == "confidentiality_level"


def test_requirement_draft_rejects_non_cny_and_chat_attachment_shape(
    schemas: dict[str, dict[str, Any]],
) -> None:
    payload = load_json(CONTRACT_ROOT / "samples" / "requirement-draft-input.json")
    non_cny = {**payload, "currency": "USD"}
    assert errors_for("requirement-draft-input.schema.json", non_cny, schemas)

    chat_attachment = deepcopy(payload)
    chat_attachment["attachments"] = [
        {
            "attachment_id": "attachment_tmp",
            "filename": "brief.pdf",
            "data_url": "data:application/pdf;base64,AAAA",
        }
    ]
    assert errors_for("requirement-draft-input.schema.json", chat_attachment, schemas)


def test_answer_submission_requires_new_block_version_and_idempotency_key(
    schemas: dict[str, dict[str, Any]],
) -> None:
    payload = load_json(
        CONTRACT_ROOT / "samples" / "requirement-answer-submission.json"
    )
    assert not errors_for("answer-submission.schema.json", payload, schemas)
    missing_version = deepcopy(payload)
    del missing_version["block_version"]
    assert errors_for("answer-submission.schema.json", missing_version, schemas)
    missing_idempotency = deepcopy(payload)
    del missing_idempotency["idempotency_key"]
    assert errors_for("answer-submission.schema.json", missing_idempotency, schemas)
