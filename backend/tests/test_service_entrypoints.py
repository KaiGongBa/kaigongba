from pathlib import Path

import app.staffdeck_main as staffdeck_entrypoint
import app.transaction_main as transaction_entrypoint
from app.staffdeck_main import app as staffdeck_app
from app.transaction_main import app as transaction_app


def test_staffdeck_and_transaction_entrypoints_have_separate_route_surfaces() -> None:
    staffdeck_paths = _route_paths(staffdeck_app.routes)
    transaction_paths = _route_paths(transaction_app.routes)

    assert "/api/health" in staffdeck_paths
    assert "/api/health" in transaction_paths
    assert "/api/enterprise/agents" in staffdeck_paths
    assert "/api/internal/v1/staffdeck/agents/resolve" in staffdeck_paths
    assert "/api/internal/v1/identity/resolve" in transaction_paths
    assert "/api/transactions/orders" in transaction_paths

    assert "/api/transactions/orders" not in staffdeck_paths
    assert "/api/enterprise/agents" not in transaction_paths
    assert "/api/internal/v1/staffdeck/agents/resolve" not in transaction_paths
    assert "/api/internal/v1/identity/resolve" not in staffdeck_paths
    assert "/api/auth/login" not in staffdeck_paths
    assert "/api/disputes/platform/dashboard" not in staffdeck_paths
    assert "/api/disputes/platform/dashboard" in transaction_paths


def test_split_api_entrypoints_do_not_embed_background_workers() -> None:
    staffdeck_source = Path(staffdeck_entrypoint.__file__).read_text()
    transaction_source = Path(transaction_entrypoint.__file__).read_text()

    assert "start_background_worker" not in staffdeck_source
    assert "stop_background_worker" not in staffdeck_source
    assert "start_transaction_outbox_worker" not in transaction_source
    assert "stop_transaction_outbox_worker" not in transaction_source


def _route_paths(routes: list[object]) -> set[str]:
    paths: set[str] = set()
    for route in routes:
        path = getattr(route, "path", None)
        if path:
            paths.add(path)
        included = getattr(route, "original_router", None)
        if included is not None:
            paths.update(_route_paths(included.routes))
    return paths
