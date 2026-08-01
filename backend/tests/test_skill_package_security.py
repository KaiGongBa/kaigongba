from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from app.execution.hosted_worker import build_container_spec
from app.execution.package_security import scan_skill_package


def _package(files: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_static_scan_accepts_minimal_package_and_classifies_risk() -> None:
    result = scan_skill_package(
        _package({"SKILL.md": "# 报告生成", "main.py": "print('ok')"}),
        filename="report.zip",
        runtime="python",
        entrypoint="main.py",
        permissions={"network": "deny", "filesystem": "output_only"},
    )
    assert result.passed is True
    assert result.risk_level == "low"
    assert result.report["file_count"] == 2


def test_static_scan_blocks_secret_zip_slip_and_undeclared_network() -> None:
    result = scan_skill_package(
        _package(
            {
                "SKILL.md": "# unsafe",
                "main.py": "import requests\nrequests.get('https://example.com')",
                ".env": "API_KEY=abcdefghijklmnopqrstuvwxyz123456",
                "../escape.txt": "escape",
            }
        ),
        filename="unsafe.zip",
        runtime="python",
        entrypoint="main.py",
        permissions={"network": "deny"},
    )
    codes = {item["code"] for item in result.report["errors"]}
    assert result.passed is False
    assert {"zip_slip", "secret_detected", "undeclared_network"}.issubset(codes)


def test_hosted_container_spec_has_security_boundaries(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    spec = build_container_spec(
        runtime="python",
        entrypoint="main.py",
        workspace=workspace,
        input_dir=input_dir,
        output_dir=output_dir,
        run_id="hostedrun_123",
    )
    command = spec.command
    assert command[0] == "docker"
    assert ["--network", "none"] == command[command.index("--network") : command.index("--network") + 2]
    assert "--read-only" in command
    assert ["--cap-drop", "ALL"] == command[command.index("--cap-drop") : command.index("--cap-drop") + 2]
    assert "no-new-privileges" in command
    assert "--pids-limit" in command
    assert "--memory" in command
    assert "--cpus" in command
    assert f"{workspace}:/workspace:ro" in command
    assert not any("APP_SECRET" in part or "DATABASE_URL" in part for part in command)
