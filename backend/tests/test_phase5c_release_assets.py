from __future__ import annotations

import ast
from pathlib import Path
import runpy


PROJECT_DIR = Path(__file__).resolve().parents[2]


def test_phase5c_gate_keeps_full_frontend_backend_and_non_payment_boundaries() -> None:
    gate = (PROJECT_DIR / "scripts/phase5c_verify.sh").read_text()
    assert "npm test" in gate
    assert "npm run build" in gate
    assert "npm run i18n:check" in gate
    assert "npm run config:check" in gate
    assert ".venv/bin/ruff check app tests" in gate
    assert ".venv/bin/pytest -q" in gate
    assert "phase5a_verify.sh" in gate
    assert "Real payment remains disabled" in gate


def test_phase5c_smoke_allows_no_business_mutation() -> None:
    path = PROJECT_DIR / "scripts/phase5c_smoke.py"
    source = path.read_text()
    tree = ast.parse(source)
    method_path_pairs: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "request":
            continue
        if len(node.args) < 3:
            continue
        method = node.args[1]
        route = node.args[2]
        if isinstance(method, ast.Constant) and isinstance(route, ast.Constant):
            method_path_pairs.add((method.value, route.value))
    post_routes = {route for method, route in method_path_pairs if method == "POST"}
    assert post_routes == {"/api/auth/login"}
    assert 'method not in {"GET", "POST"}' in source
    assert "Read-only smoke rejected mutating request" in source
    assert "demo-only" in source


def test_phase5c_ci_gate_runs_all_non_environment_checks() -> None:
    workflow = (PROJECT_DIR / ".github/workflows/production-gate.yml").read_text()
    for required in (
        "No newly skipped tests",
        "Backend lint",
        "Backend regression",
        "PostgreSQL migration upgrade/rollback/re-upgrade",
        "Redis shared-runtime verification",
        "Frontend tests",
        "Frontend build",
        "Frontend i18n coverage",
        "Frontend configuration",
        "Release-candidate manifest",
        "phase5c-release-manifest",
    ):
        assert required in workflow


def test_phase5c_skip_guard_uses_its_introduction_as_the_initial_pr_epoch() -> None:
    guard = (PROJECT_DIR / "scripts/phase5c_no_new_skips.sh").read_text()
    assert 'guard_epoch="a7e9c5d7d69d1374d64224bb7fe8b5211b95bad9"' in guard
    assert 'merge-base --is-ancestor "${base_ref}" "${guard_epoch}"' in guard
    assert 'effective_base_ref="${guard_epoch}"' in guard
    assert '"${effective_base_ref}...HEAD"' in guard


def test_phase5c_manifest_preserves_dot_prefixed_paths() -> None:
    namespace = runpy.run_path(str(PROJECT_DIR / "scripts/phase5c_release_manifest.py"))
    assert namespace["_changed_paths"](" M .github/workflows/production-gate.yml\n") == [
        ".github/workflows/production-gate.yml",
    ]
