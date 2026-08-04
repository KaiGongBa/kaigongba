#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tomllib

PROJECT_DIR = Path(__file__).resolve().parents[1]


def _run(*command: str, cwd: Path = PROJECT_DIR) -> str:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_status() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=PROJECT_DIR,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _changed_paths(status: str) -> list[str]:
    return [line[3:] for line in status.splitlines() if len(line) > 3]


def build_manifest() -> dict[str, Any]:
    backend = tomllib.loads((PROJECT_DIR / "backend/pyproject.toml").read_text())
    frontend = json.loads((PROJECT_DIR / "frontend-enterprise/package.json").read_text())
    # Porcelain uses two status columns followed by a space. Preserve leading
    # whitespace here: stripping the entire output would shift the first path
    # and turn `.github/...` into `github/...`.
    status = _git_status()
    alembic = PROJECT_DIR / "backend/.venv/bin/alembic"
    migration_heads = _run(str(alembic), "heads", cwd=PROJECT_DIR / "backend").splitlines()
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "source": {
            "commit": _run("git", "rev-parse", "HEAD"),
            "branch": _run("git", "branch", "--show-current"),
            "dirty": bool(status),
            "changedPaths": _changed_paths(status),
        },
        "versions": {
            "backend": backend["project"]["version"],
            "frontend": frontend["version"],
        },
        "database": {
            "migrationHeads": migration_heads,
            "productionEngine": "postgresql",
            "staffdeckSeparated": True,
        },
        "runtime": {
            "redisRequiredInProduction": True,
            "privateObjectStorageRequiredInProduction": True,
            "outboxRequired": True,
        },
        "payment": {
            "provider": "demo",
            "realPaymentEnabled": False,
            "note": "Only the funding channel is simulated; business records remain persistent.",
        },
        "acceptance": {
            "targetViews": 13,
            "orderWorkspaceTabs": 8,
            "organizationRouteRules": 3,
            "smokeMode": "read-only",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a reproducible Phase 5C manifest.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    manifest = build_manifest()
    if args.require_clean and manifest["source"]["dirty"]:
        raise SystemExit("Phase 5C release manifest requires a clean worktree")
    payload = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
