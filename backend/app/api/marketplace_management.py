from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlmodel import Session

from app.db import get_session
from app.db.models import User
from app.marketplace import management_service
from app.marketplace.management_schemas import (
    AIServiceDraftWrite,
    OrganizationCreateRequest,
    OrganizationDetailRead,
    OrganizationInvitationAcceptRequest,
    OrganizationInvitationCreatedRead,
    OrganizationInvitationCreateRequest,
    OrganizationMemberUpdateRequest,
    OrganizationUpdateRequest,
    ProviderApplicationRead,
    ProviderApplicationWrite,
    PublicationDraftRead,
    PublicationEditorRead,
    PublishingOverviewRead,
    ReviewDecisionRequest,
    ReviewSubmissionRead,
    SkillDraftWrite,
)
from app.security.auth import get_current_user

router = APIRouter(prefix="/api/marketplace", tags=["marketplace-management"])
CurrentUser = Annotated[User, Depends(get_current_user)]
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.post("/organizations", response_model=OrganizationDetailRead)
def create_organization(
    request: OrganizationCreateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> OrganizationDetailRead:
    return management_service.create_organization(db, current_user, request)


@router.get(
    "/organizations/{organization_id}",
    response_model=OrganizationDetailRead,
)
def get_organization(
    organization_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> OrganizationDetailRead:
    return management_service.get_organization_detail(db, current_user, organization_id)


@router.put(
    "/organizations/{organization_id}",
    response_model=OrganizationDetailRead,
)
def update_organization(
    organization_id: str,
    request: OrganizationUpdateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> OrganizationDetailRead:
    return management_service.update_organization(db, current_user, organization_id, request)


@router.post(
    "/organizations/{organization_id}/invitations",
    response_model=OrganizationInvitationCreatedRead,
)
def create_invitation(
    organization_id: str,
    request: OrganizationInvitationCreateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> OrganizationInvitationCreatedRead:
    return management_service.create_invitation(db, current_user, organization_id, request)


@router.delete(
    "/organizations/{organization_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def cancel_invitation(
    organization_id: str,
    invitation_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> Response:
    management_service.cancel_invitation(db, current_user, organization_id, invitation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/organization-invitations/accept",
    response_model=OrganizationDetailRead,
)
def accept_invitation(
    request: OrganizationInvitationAcceptRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> OrganizationDetailRead:
    return management_service.accept_invitation(db, current_user, request.acceptance_code)


@router.put(
    "/organizations/{organization_id}/members/{member_id}",
    response_model=OrganizationDetailRead,
)
def update_member(
    organization_id: str,
    member_id: str,
    request: OrganizationMemberUpdateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> OrganizationDetailRead:
    return management_service.update_member(db, current_user, organization_id, member_id, request)


@router.delete(
    "/organizations/{organization_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member(
    organization_id: str,
    member_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> Response:
    management_service.remove_member(db, current_user, organization_id, member_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/organizations/{organization_id}/provider-application",
    response_model=ProviderApplicationRead,
)
def submit_provider_application(
    organization_id: str,
    request: ProviderApplicationWrite,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ProviderApplicationRead:
    return management_service.submit_provider_application(
        db, current_user, organization_id, request
    )


@router.get("/publishing", response_model=PublishingOverviewRead)
def get_publishing_overview(
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> PublishingOverviewRead:
    return management_service.get_publishing_overview(db, current_user, organization_id)


@router.post(
    "/publishing/ai-services",
    response_model=PublicationDraftRead,
)
def create_ai_service_draft(
    request: AIServiceDraftWrite,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> PublicationDraftRead:
    return management_service.create_ai_service_draft(db, current_user, request)


@router.get(
    "/publishing/ai-services/{service_id}",
    response_model=PublicationEditorRead,
)
def get_ai_service_editor(
    service_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> PublicationEditorRead:
    return management_service.get_ai_service_editor(db, current_user, organization_id, service_id)


@router.put(
    "/publishing/ai-services/{service_id}",
    response_model=PublicationDraftRead,
)
def update_ai_service_draft(
    service_id: str,
    request: AIServiceDraftWrite,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> PublicationDraftRead:
    return management_service.update_ai_service_draft(db, current_user, service_id, request)


@router.post(
    "/publishing/ai-services/{service_id}/submit-review",
    response_model=ReviewSubmissionRead,
)
def submit_ai_service_review(
    service_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> ReviewSubmissionRead:
    return management_service.submit_ai_service_review(
        db, current_user, organization_id, service_id
    )


@router.post("/publishing/skills", response_model=PublicationDraftRead)
def create_skill_draft(
    request: SkillDraftWrite,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> PublicationDraftRead:
    return management_service.create_skill_draft(db, current_user, request)


@router.get(
    "/publishing/skills/{skill_id}",
    response_model=PublicationEditorRead,
)
def get_skill_editor(
    skill_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> PublicationEditorRead:
    return management_service.get_skill_editor(db, current_user, organization_id, skill_id)


@router.put(
    "/publishing/skills/{skill_id}",
    response_model=PublicationDraftRead,
)
def update_skill_draft(
    skill_id: str,
    request: SkillDraftWrite,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> PublicationDraftRead:
    return management_service.update_skill_draft(db, current_user, skill_id, request)


@router.post(
    "/publishing/skills/{skill_id}/submit-review",
    response_model=ReviewSubmissionRead,
)
def submit_skill_review(
    skill_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> ReviewSubmissionRead:
    return management_service.submit_skill_review(db, current_user, organization_id, skill_id)


@router.get("/reviews", response_model=list[ReviewSubmissionRead])
def list_market_reviews(
    current_user: CurrentUser,
    db: DatabaseSession,
    review_status: str | None = Query(None, alias="status"),
    target_type: str | None = Query(None, alias="targetType"),
) -> list[ReviewSubmissionRead]:
    return management_service.list_market_reviews(
        db,
        current_user,
        status=review_status,
        target_type=target_type,
    )


@router.post(
    "/reviews/{review_id}/decision",
    response_model=ReviewSubmissionRead,
)
def decide_market_review(
    review_id: str,
    request: ReviewDecisionRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ReviewSubmissionRead:
    return management_service.decide_market_review(db, current_user, review_id, request)
