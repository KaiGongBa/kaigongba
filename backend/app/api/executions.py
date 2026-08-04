from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlmodel import Session

from app.db import get_session
from app.db.models import User
from app.execution import service
from app.execution.schemas import (
    ExecutionCommandRequest,
    ExecutionRunRead,
    ExecutionStartRequest,
    HostedSkillRunRead,
    HostedSkillRunRequest,
    InternalEventReceipt,
    InternalExecutionEventRequest,
    OrderExecutionRead,
    SkillPackageImportRequest,
    SkillPackageRead,
    SkillReviewRequest,
)
from app.security.auth import get_current_user
from app.security.internal_service import require_internal_service

router = APIRouter(prefix="/api/executions", tags=["executions"])
CurrentUser = Annotated[User, Depends(get_current_user)]
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("/orders/{order_id}", response_model=OrderExecutionRead)
def get_order_execution(
    order_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> OrderExecutionRead:
    return service.get_order_execution(db, current_user, order_id, organization_id)


@router.post("/orders/{order_id}/runs", response_model=ExecutionRunRead)
def start_execution(
    order_id: str,
    request: ExecutionStartRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ExecutionRunRead:
    return service.start_execution(db, current_user, order_id, request)


@router.post("/runs/{run_id}/commands", response_model=ExecutionRunRead)
def command_execution(
    run_id: str,
    request: ExecutionCommandRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ExecutionRunRead:
    return service.command_execution(db, current_user, run_id, request)


@router.post(
    "/internal/events",
    response_model=InternalEventReceipt,
    dependencies=[Depends(require_internal_service)],
)
def receive_internal_event(
    request: InternalExecutionEventRequest,
    db: DatabaseSession,
) -> InternalEventReceipt:
    return service.receive_internal_event(db, request)


@router.post(
    "/internal/hosted-skill-runs",
    response_model=HostedSkillRunRead,
    dependencies=[Depends(require_internal_service)],
)
def execute_hosted_skill(
    request: HostedSkillRunRequest,
    db: DatabaseSession,
) -> HostedSkillRunRead:
    from app.execution.hosted_worker import run_hosted_skill

    return run_hosted_skill(db, request)


@router.get("/skill-packages", response_model=list[SkillPackageRead])
def list_skill_packages(
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str | None = Query(default=None, alias="organizationId"),
) -> list[SkillPackageRead]:
    return service.list_skill_packages(db, current_user, organization_id)


@router.post("/skill-packages/import", response_model=SkillPackageRead)
def import_skill_package(
    request: SkillPackageImportRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> SkillPackageRead:
    return service.import_skill_package(db, current_user, request)


@router.post("/skill-packages/upload", response_model=SkillPackageRead)
async def upload_skill_package(
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: Annotated[str, Form(alias="organizationId")],
    slug: Annotated[str, Form(min_length=2, max_length=120)],
    name: Annotated[str, Form(min_length=2, max_length=160)],
    version: Annotated[str, Form(min_length=1, max_length=40)],
    runtime: Annotated[str, Form()] = "python",
    entrypoint: Annotated[str, Form(max_length=240)] = "main.py",
    manifest_json: Annotated[str, Form(alias="manifest")] = "{}",
    permissions_json: Annotated[str, Form(alias="permissions")] = "{}",
    execution_policy: Annotated[str, Form(alias="executionPolicy")] = "external",
    file: Annotated[UploadFile, File()] = None,
) -> SkillPackageRead:
    if file is None:
        raise HTTPException(status_code=422, detail="请选择 Skill ZIP 包")
    try:
        manifest = json.loads(manifest_json)
        permissions = json.loads(permissions_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="manifest 或 permissions 不是合法 JSON") from exc
    if not isinstance(manifest, dict) or not isinstance(permissions, dict):
        raise HTTPException(status_code=422, detail="manifest 和 permissions 必须是 JSON 对象")
    from app.config import get_settings

    data = await file.read(get_settings().skill_package_max_bytes + 1)
    if len(data) > get_settings().skill_package_max_bytes:
        raise HTTPException(status_code=413, detail="Skill 包超过平台大小上限")
    return service.upload_skill_package(
        db,
        current_user,
        organization_id=organization_id,
        slug=slug,
        name=name,
        version=version,
        runtime=runtime,
        entrypoint=entrypoint,
        manifest=manifest,
        permissions=permissions,
        execution_policy=execution_policy,
        filename=file.filename or "skill.zip",
        content_type=file.content_type or "application/zip",
        data=data,
    )


@router.get("/skill-packages/{package_id}/download", response_model=None)
def download_skill_package(
    package_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str | None = Query(default=None, alias="organizationId"),
) -> Response:
    package, target = service.get_skill_package_download(
        db, current_user, package_id, organization_id
    )
    if target.redirect_url:
        return RedirectResponse(target.redirect_url, status_code=307)
    if target.local_path:
        return FileResponse(
            target.local_path,
            filename=package.original_filename,
            media_type=package.content_type,
        )
    raise HTTPException(status_code=404, detail="Skill 包文件不存在")


@router.post("/skill-packages/{package_id}/review", response_model=SkillPackageRead)
def review_skill_package(
    package_id: str,
    request: SkillReviewRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> SkillPackageRead:
    return service.review_skill_package(db, current_user, package_id, request)
