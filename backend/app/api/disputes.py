from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session
from starlette.responses import FileResponse, RedirectResponse, Response

from app.db import get_session
from app.db.models import User
from app.disputes import service
from app.disputes.schemas import (
    AppealCreate,
    AppealReviewCreate,
    AppealWaiverCreate,
    DecisionCreate,
    DecisionReviewCreate,
    DisputeAssignmentCreate,
    DisputeCreate,
    DisputeDetailRead,
    DisputeEvidenceCreate,
    DisputeFinalizeCreate,
    DisputeOrderProjectionRead,
    DisputePlatformDashboardRead,
    DisputeResponseCreate,
    EvidenceRequestCreate,
    MediationCreate,
    MediationResponseCreate,
)
from app.security.auth import get_current_user
from app.transaction import service as transaction_service

router = APIRouter(prefix="/api/disputes", tags=["disputes"])
CurrentUser = Annotated[User, Depends(get_current_user)]
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("/orders/{order_id}", response_model=DisputeOrderProjectionRead)
def get_order_projection(
    order_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> DisputeOrderProjectionRead:
    return service.get_order_projection(db, current_user, order_id, organization_id)


@router.post("/orders/{order_id}", response_model=DisputeDetailRead)
def create_dispute(
    order_id: str,
    request: DisputeCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeDetailRead:
    return service.create_dispute(db, current_user, order_id, request)


@router.get("/cases/{case_id}", response_model=DisputeDetailRead)
def get_case(
    case_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str | None = Query(default=None, alias="organizationId"),
) -> DisputeDetailRead:
    return service.get_case(db, current_user, case_id, organization_id)


@router.post("/cases/{case_id}/response", response_model=DisputeDetailRead)
def respond_to_dispute(
    case_id: str,
    request: DisputeResponseCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeDetailRead:
    return service.respond_to_dispute(db, current_user, case_id, request)


@router.post("/cases/{case_id}/evidence", response_model=DisputeDetailRead)
def submit_evidence(
    case_id: str,
    request: DisputeEvidenceCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeDetailRead:
    return service.submit_evidence(db, current_user, case_id, request)


@router.post("/cases/{case_id}/evidence-requests", response_model=DisputeDetailRead)
def request_evidence(
    case_id: str,
    request: EvidenceRequestCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeDetailRead:
    return service.request_evidence(db, current_user, case_id, request)


@router.post("/cases/{case_id}/assignment", response_model=DisputeDetailRead)
def assign_case(
    case_id: str,
    request: DisputeAssignmentCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeDetailRead:
    return service.assign_case(db, current_user, case_id, request)


@router.post("/cases/{case_id}/ai-summary", response_model=DisputeDetailRead)
def generate_evidence_summary(
    case_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeDetailRead:
    return service.generate_evidence_summary(db, current_user, case_id)


@router.post("/cases/{case_id}/mediations", response_model=DisputeDetailRead)
def create_mediation(
    case_id: str,
    request: MediationCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeDetailRead:
    return service.create_mediation(db, current_user, case_id, request)


@router.post("/mediations/{mediation_id}/response", response_model=DisputeDetailRead)
def respond_mediation(
    mediation_id: str,
    request: MediationResponseCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeDetailRead:
    return service.respond_mediation(db, current_user, mediation_id, request)


@router.post("/cases/{case_id}/decisions", response_model=DisputeDetailRead)
def submit_decision(
    case_id: str,
    request: DecisionCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeDetailRead:
    return service.submit_decision(db, current_user, case_id, request)


@router.post("/decisions/{decision_id}/review", response_model=DisputeDetailRead)
def review_decision(
    decision_id: str,
    request: DecisionReviewCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeDetailRead:
    return service.review_decision(db, current_user, decision_id, request)


@router.post("/cases/{case_id}/appeals", response_model=DisputeDetailRead)
def create_appeal(
    case_id: str,
    request: AppealCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeDetailRead:
    return service.create_appeal(db, current_user, case_id, request)


@router.post("/appeals/{appeal_id}/review", response_model=DisputeDetailRead)
def review_appeal(
    appeal_id: str,
    request: AppealReviewCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeDetailRead:
    return service.review_appeal(db, current_user, appeal_id, request)


@router.post("/cases/{case_id}/appeal-waiver", response_model=DisputeDetailRead)
def waive_appeal(
    case_id: str,
    request: AppealWaiverCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeDetailRead:
    return service.waive_appeal(db, current_user, case_id, request)


@router.post("/cases/{case_id}/finalize", response_model=DisputeDetailRead)
def finalize_case(
    case_id: str,
    request: DisputeFinalizeCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputeDetailRead:
    return service.finalize_case(db, current_user, case_id, request)


@router.get("/platform/dashboard", response_model=DisputePlatformDashboardRead)
def get_platform_dashboard(
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DisputePlatformDashboardRead:
    return service.get_platform_dashboard(db, current_user)


@router.get("/platform/files/{file_id}/download", response_model=None)
def download_platform_evidence_file(
    file_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> Response:
    row, target = transaction_service.resolve_platform_order_file_download(
        db,
        current_user,
        file_id,
    )
    if target.redirect_url:
        return RedirectResponse(target.redirect_url, status_code=307)
    if not target.local_path:
        raise RuntimeError("对象存储下载目标无效")
    return FileResponse(target.local_path, media_type=row.content_type, filename=row.filename)
