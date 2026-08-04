from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4
from zipfile import ZipFile

from fastapi import HTTPException
from sqlmodel import Session, select

from app.config import get_settings
from app.db.models import (
    TransactionHostedSkillRun,
    TransactionSkillPackageVersion,
    utc_now,
)
from app.execution.package_security import scan_skill_package
from app.execution.schemas import HostedSkillRunRead, HostedSkillRunRequest
from app.transaction.object_storage import get_order_object_store

MAX_LOG_CHARS = 20_000
MAX_ARTIFACT_FILES = 100
MAX_ARTIFACT_BYTES = 52_428_800


@dataclass(frozen=True)
class ContainerSpec:
    name: str
    command: list[str]


def build_container_spec(
    *,
    runtime: str,
    entrypoint: str,
    workspace: Path,
    input_dir: Path,
    output_dir: Path,
    run_id: str,
) -> ContainerSpec:
    settings = get_settings()
    if runtime == "python":
        image = settings.hosted_skill_python_image
        process = ["python", f"/workspace/{entrypoint}"]
    elif runtime == "node":
        image = settings.hosted_skill_node_image
        process = ["node", f"/workspace/{entrypoint}"]
    else:
        raise HTTPException(status_code=409, detail="该运行时不能在平台沙箱执行")
    safe_run_id = "".join(character for character in run_id if character.isalnum())[-36:]
    name = f"kgb-skill-{safe_run_id or uuid4().hex}"
    command = [
        settings.hosted_skill_container_runtime,
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "65534:65534",
        "--pids-limit",
        str(settings.hosted_skill_pids_limit),
        "--memory",
        f"{settings.hosted_skill_memory_mb}m",
        "--cpus",
        str(settings.hosted_skill_cpu_limit),
        "--tmpfs",
        f"/tmp:rw,noexec,nosuid,nodev,size={settings.hosted_skill_tmpfs_mb}m",
        "-e",
        "KAIGONGBA_INPUT=/input/input.json",
        "-e",
        "KAIGONGBA_OUTPUT=/output",
        "-v",
        f"{workspace}:/workspace:ro",
        "-v",
        f"{input_dir}:/input:ro",
        "-v",
        f"{output_dir}:/output:rw",
        image,
        *process,
    ]
    return ContainerSpec(name=name, command=command)


def run_hosted_skill(
    db: Session, request: HostedSkillRunRequest
) -> HostedSkillRunRead:
    settings = get_settings()
    if not settings.hosted_skill_execution_enabled:
        raise HTTPException(status_code=503, detail="平台托管第三方 Skill 执行尚未启用")
    package = db.get(TransactionSkillPackageVersion, request.skill_package_version_id)
    if not package or package.tenant_id != request.tenant_id:
        raise HTTPException(status_code=404, detail="Skill 固定版本不存在")
    if package.status != "approved" or package.scan_status != "passed":
        raise HTTPException(status_code=409, detail="Skill 包尚未通过扫描与平台审核")
    if package.execution_policy != "hosted" or not package.storage_key:
        raise HTTPException(status_code=409, detail="该 Skill 版本不是平台托管执行类型")
    existing = db.exec(
        select(TransactionHostedSkillRun).where(
            TransactionHostedSkillRun.tenant_id == request.tenant_id,
            TransactionHostedSkillRun.idempotency_key == request.idempotency_key,
        )
    ).first()
    if existing:
        return _read(existing)

    row = TransactionHostedSkillRun(
        tenant_id=request.tenant_id,
        skill_package_version_id=package.id,
        idempotency_key=request.idempotency_key,
        input_json=request.input,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    try:
        result = _execute(package, row.id, request.input)
        row.status = "succeeded" if result["exit_code"] == 0 else "failed"
        row.result_json = result["result"]
        row.artifact_manifest_json = result["artifacts"]
        row.stdout = result["stdout"][-MAX_LOG_CHARS:]
        row.stderr = result["stderr"][-MAX_LOG_CHARS:]
        row.exit_code = result["exit_code"]
    except Exception as exc:  # noqa: BLE001 - 必须把任意 Worker 故障持久化为失败态
        row.status = "failed"
        row.stderr = str(exc)[:MAX_LOG_CHARS]
        row.result_json = {"success": False, "error": "sandbox_execution_failed"}
    row.completed_at = utc_now()
    row.updated_at = utc_now()
    db.add(row)
    db.commit()
    db.refresh(row)
    return _read(row)


def _execute(
    package: TransactionSkillPackageVersion,
    run_id: str,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    settings = get_settings()
    runtime_binary = shutil.which(settings.hosted_skill_container_runtime)
    if not runtime_binary:
        raise RuntimeError("未找到容器运行时，托管 Skill 未执行")
    store = get_order_object_store(package.storage_provider)
    data = store.read(package.storage_key)
    if hashlib.sha256(data).hexdigest() != package.digest:
        raise RuntimeError("Skill 包摘要校验失败")
    scan = scan_skill_package(
        data,
        filename=package.original_filename,
        runtime=package.runtime,
        entrypoint=package.entrypoint,
        permissions=package.permissions_json,
    )
    if not scan.passed:
        raise RuntimeError("Skill 包执行前安全复检失败")

    with TemporaryDirectory(prefix="kgb-hosted-skill-") as temp:
        root = Path(temp)
        workspace = root / "workspace"
        input_dir = root / "input"
        output_dir = root / "output"
        workspace.mkdir(mode=0o755)
        input_dir.mkdir(mode=0o755)
        output_dir.mkdir(mode=0o777)
        _safe_extract(data, workspace)
        input_path = input_dir / "input.json"
        input_path.write_text(json.dumps(input_payload, ensure_ascii=False), encoding="utf-8")
        input_path.chmod(0o444)
        for path in workspace.rglob("*"):
            path.chmod(0o555 if path.is_dir() else 0o444)
        spec = build_container_spec(
            runtime=package.runtime,
            entrypoint=package.entrypoint,
            workspace=workspace,
            input_dir=input_dir,
            output_dir=output_dir,
            run_id=run_id,
        )
        try:
            completed = subprocess.run(
                spec.command,
                capture_output=True,
                text=True,
                timeout=settings.hosted_skill_timeout_seconds,
                check=False,
                env={"PATH": os.environ.get("PATH", os.defpath)},
            )
        except subprocess.TimeoutExpired as exc:
            subprocess.run(
                [runtime_binary, "rm", "-f", spec.name],
                capture_output=True,
                timeout=10,
                check=False,
                env={"PATH": os.environ.get("PATH", os.defpath)},
            )
            raise RuntimeError("托管 Skill 执行超时") from exc
        artifacts = _store_artifacts(package, run_id, output_dir)
        result_path = output_dir / "result.json"
        result: dict[str, Any] = {"success": completed.returncode == 0}
        if result_path.is_file():
            parsed = json.loads(result_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                result = parsed
        return {
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "result": result,
            "artifacts": artifacts,
        }


def _safe_extract(data: bytes, destination: Path) -> None:
    with ZipFile(BytesIO(data)) as archive:
        for info in archive.infolist():
            path = PurePosixPath(info.filename.replace("\\", "/"))
            if info.is_dir():
                (destination.joinpath(*path.parts)).mkdir(parents=True, exist_ok=True)
                continue
            target = destination.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))


def _store_artifacts(
    package: TransactionSkillPackageVersion, run_id: str, output_dir: Path
) -> list[dict[str, Any]]:
    store = get_order_object_store(package.storage_provider)
    files = [path for path in output_dir.rglob("*") if path.is_file()]
    if len(files) > MAX_ARTIFACT_FILES:
        raise RuntimeError("输出文件数量超过上限")
    total = sum(path.stat().st_size for path in files)
    if total > MAX_ARTIFACT_BYTES:
        raise RuntimeError("输出文件总大小超过上限")
    manifest: list[dict[str, Any]] = []
    for path in files:
        relative = path.relative_to(output_dir).as_posix()
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        key = f"skill-artifacts/{package.tenant_id}/{run_id}/{digest}/{relative}"
        store.put(key, data, "application/octet-stream")
        manifest.append({"name": relative, "size": len(data), "sha256": digest, "storage_key": key})
    return manifest


def _read(row: TransactionHostedSkillRun) -> HostedSkillRunRead:
    return HostedSkillRunRead(
        id=row.id,
        skill_package_version_id=row.skill_package_version_id,
        status=row.status,
        result=row.result_json,
        artifacts=row.artifact_manifest_json,
        stdout=row.stdout,
        stderr=row.stderr,
        exit_code=row.exit_code,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )
