from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlmodel import Session
from starlette.responses import FileResponse, RedirectResponse, Response

from app.db import get_session
from app.db.models import User
from app.security.auth import get_current_user
from app.transaction import service
from app.transaction.schemas import (
    AcceptanceCommand,
    AgreementChangeRequest,
    AgreementConfirmationRequest,
    AgreementRead,
    ClarificationAnswer,
    ClarificationCreate,
    ClarificationRead,
    DeliverableCreate,
    DeliverableRead,
    DeliverableVersionCreate,
    DirectServiceCheckoutCreate,
    DemoPaymentSimulate,
    MatchRunRequest,
    MaterialRequestCreate,
    MaterialRequestRead,
    MaterialSubmissionCreate,
    MilestoneActionRequest,
    OrderDetailRead,
    OrderFileRead,
    OrderSummaryRead,
    OrderWorkspaceRead,
    PaymentOrderCreate,
    PaymentOrderRead,
    ProviderWorkbenchRead,
    QuoteGenerateRequest,
    QuoteRead,
    QuoteSelectionRequest,
    QuoteUpdate,
    RequirementDetailRead,
    RequirementDraftWrite,
    RequirementAIAnalysisRead,
    RequirementSummaryRead,
    RequirementWrite,
)

router = APIRouter(prefix="/api/transactions", tags=["transactions"])
CurrentUser = Annotated[User, Depends(get_current_user)]
DatabaseSession = Annotated[Session, Depends(get_session)]


@router.get("/requirements", response_model=list[RequirementSummaryRead])
def list_requirements(
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
    perspective: str = Query(default="buyer"),
) -> list[RequirementSummaryRead]:
    return service.list_requirements(
        db,
        current_user,
        organization_id,
        perspective,
    )


@router.post("/requirements", response_model=RequirementDetailRead)
def create_requirement(
    request: RequirementDraftWrite,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> RequirementDetailRead:
    return service.create_requirement(db, current_user, request)


@router.post("/requirements/analyze", response_model=RequirementAIAnalysisRead)
def analyze_requirement(
    request: RequirementWrite,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> RequirementAIAnalysisRead:
    return service.analyze_requirement(db, current_user, request)


@router.get(
    "/requirements/{requirement_id}",
    response_model=RequirementDetailRead,
)
def get_requirement(
    requirement_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> RequirementDetailRead:
    return service.get_requirement(
        db,
        current_user,
        requirement_id,
        organization_id,
    )


@router.put(
    "/requirements/{requirement_id}",
    response_model=RequirementDetailRead,
)
def update_requirement(
    requirement_id: str,
    request: RequirementDraftWrite,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> RequirementDetailRead:
    return service.update_requirement(db, current_user, requirement_id, request)


@router.post(
    "/requirements/{requirement_id}/publish",
    response_model=RequirementDetailRead,
)
def publish_requirement(
    requirement_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> RequirementDetailRead:
    return service.publish_requirement(
        db,
        current_user,
        requirement_id,
        organization_id,
    )


@router.post(
    "/requirements/{requirement_id}/match",
    response_model=RequirementDetailRead,
)
def run_matching(
    requirement_id: str,
    request: MatchRunRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> RequirementDetailRead:
    return service.run_matching(db, current_user, requirement_id, request)


@router.post(
    "/requirements/{requirement_id}/clarifications",
    response_model=ClarificationRead,
)
def create_clarification(
    requirement_id: str,
    request: ClarificationCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ClarificationRead:
    return service.create_clarification(
        db,
        current_user,
        requirement_id,
        request,
    )


@router.post(
    "/clarifications/{clarification_id}/answer",
    response_model=ClarificationRead,
)
def answer_clarification(
    clarification_id: str,
    request: ClarificationAnswer,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> ClarificationRead:
    return service.answer_clarification(
        db,
        current_user,
        clarification_id,
        request,
    )


@router.get("/provider/workbench", response_model=ProviderWorkbenchRead)
def get_provider_workbench(
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> ProviderWorkbenchRead:
    return service.get_provider_workbench(
        db,
        current_user,
        organization_id,
    )


@router.post(
    "/requirements/{requirement_id}/quotes/generate",
    response_model=QuoteRead,
)
def generate_quote(
    requirement_id: str,
    request: QuoteGenerateRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> QuoteRead:
    return service.generate_quote(db, current_user, requirement_id, request)


@router.get("/quotes/{quote_id}", response_model=QuoteRead)
def get_quote(
    quote_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> QuoteRead:
    return service.get_quote(db, current_user, quote_id, organization_id)


@router.put("/quotes/{quote_id}", response_model=QuoteRead)
def update_quote(
    quote_id: str,
    request: QuoteUpdate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> QuoteRead:
    return service.update_quote(db, current_user, quote_id, request)


@router.post(
    "/quotes/{quote_id}/confirm-send",
    response_model=QuoteRead,
)
def confirm_and_send_quote(
    quote_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> QuoteRead:
    return service.confirm_and_send_quote(
        db,
        current_user,
        quote_id,
        organization_id,
    )


@router.post("/quotes/{quote_id}/withdraw", response_model=QuoteRead)
def withdraw_quote(
    quote_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> QuoteRead:
    return service.withdraw_quote(
        db,
        current_user,
        quote_id,
        organization_id,
    )


@router.get(
    "/requirements/{requirement_id}/quotes",
    response_model=list[QuoteRead],
)
def list_requirement_quotes(
    requirement_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> list[QuoteRead]:
    return service.list_requirement_quotes(
        db,
        current_user,
        requirement_id,
        organization_id,
    )


@router.post(
    "/requirements/{requirement_id}/select-quote",
    response_model=AgreementRead,
)
def select_quote(
    requirement_id: str,
    request: QuoteSelectionRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AgreementRead:
    return service.select_quote(db, current_user, requirement_id, request)


@router.post(
    "/services/{service_id}/direct-checkout",
    response_model=AgreementRead,
)
def create_direct_service_checkout(
    service_id: str,
    request: DirectServiceCheckoutCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AgreementRead:
    return service.create_direct_service_checkout(
        db,
        current_user,
        service_id,
        request,
    )


@router.get("/agreements/{agreement_id}", response_model=AgreementRead)
def get_agreement(
    agreement_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> AgreementRead:
    return service.get_agreement(
        db,
        current_user,
        agreement_id,
        organization_id,
    )


@router.post(
    "/agreements/{agreement_id}/confirm",
    response_model=AgreementRead,
)
def confirm_agreement(
    agreement_id: str,
    request: AgreementConfirmationRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AgreementRead:
    return service.confirm_agreement(
        db,
        current_user,
        agreement_id,
        request,
    )


@router.post(
    "/agreements/{agreement_id}/request-change",
    response_model=AgreementRead,
)
def request_agreement_change(
    agreement_id: str,
    request: AgreementChangeRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> AgreementRead:
    return service.request_agreement_change(
        db,
        current_user,
        agreement_id,
        request,
    )


@router.post(
    "/agreements/{agreement_id}/payment-orders",
    response_model=PaymentOrderRead,
)
def create_payment_order(
    agreement_id: str,
    request: PaymentOrderCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> PaymentOrderRead:
    return service.create_payment_order(
        db,
        current_user,
        agreement_id,
        request,
    )


@router.get(
    "/payment-orders/{payment_order_id}",
    response_model=PaymentOrderRead,
)
def get_payment_order(
    payment_order_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> PaymentOrderRead:
    return service.get_payment_order(
        db,
        current_user,
        payment_order_id,
        organization_id,
    )


@router.post(
    "/payment-orders/{payment_order_id}/demo-simulate",
    response_model=PaymentOrderRead,
)
def simulate_demo_payment(
    payment_order_id: str,
    request: DemoPaymentSimulate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> PaymentOrderRead:
    return service.simulate_demo_payment(
        db,
        current_user,
        payment_order_id,
        request,
    )


@router.get("/orders", response_model=list[OrderSummaryRead])
def list_orders(
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
    perspective: str = Query(default="buyer"),
) -> list[OrderSummaryRead]:
    return service.list_orders(
        db,
        current_user,
        organization_id,
        perspective,
    )


@router.get("/orders/{order_id}", response_model=OrderDetailRead)
def get_order(
    order_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> OrderDetailRead:
    return service.get_order(db, current_user, order_id, organization_id)


@router.get(
    "/orders/{order_id}/workspace",
    response_model=OrderWorkspaceRead,
)
def get_order_workspace(
    order_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> OrderWorkspaceRead:
    return service.get_order_workspace(
        db,
        current_user,
        order_id,
        organization_id,
    )


@router.post(
    "/orders/{order_id}/milestones/{milestone_id}/actions",
    response_model=OrderWorkspaceRead,
)
def transition_milestone(
    order_id: str,
    milestone_id: str,
    request: MilestoneActionRequest,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> OrderWorkspaceRead:
    return service.transition_milestone(
        db,
        current_user,
        order_id,
        milestone_id,
        request,
    )


@router.post("/orders/{order_id}/files", response_model=OrderFileRead)
async def upload_order_file(
    order_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    file: Annotated[UploadFile, File()],
    organization_id: str = Form(alias="organizationId"),
    purpose: str = Form(),
    milestone_id: str | None = Form(default=None, alias="milestoneId"),
) -> OrderFileRead:
    payload = await file.read()
    return service.store_order_file(
        db,
        current_user,
        order_id,
        organization_id,
        milestone_id,
        purpose,
        file.filename or "uploaded-file",
        file.content_type or "application/octet-stream",
        payload,
    )


@router.get("/files/{file_id}/download", response_model=None)
def download_order_file(
    file_id: str,
    current_user: CurrentUser,
    db: DatabaseSession,
    organization_id: str = Query(alias="organizationId"),
) -> Response:
    row, target = service.resolve_order_file_download(
        db,
        current_user,
        file_id,
        organization_id,
    )
    if target.redirect_url:
        return RedirectResponse(target.redirect_url, status_code=307)
    if not target.local_path:
        raise RuntimeError("对象存储下载目标无效")
    return FileResponse(target.local_path, media_type=row.content_type, filename=row.filename)


@router.post(
    "/orders/{order_id}/material-requests",
    response_model=MaterialRequestRead,
)
def create_material_request(
    order_id: str,
    request: MaterialRequestCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> MaterialRequestRead:
    return service.create_material_request(
        db,
        current_user,
        order_id,
        request,
    )


@router.post(
    "/material-requests/{material_request_id}/submit",
    response_model=MaterialRequestRead,
)
def submit_material_request(
    material_request_id: str,
    request: MaterialSubmissionCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> MaterialRequestRead:
    return service.submit_material_request(
        db,
        current_user,
        material_request_id,
        request,
    )


@router.post(
    "/orders/{order_id}/deliverables",
    response_model=DeliverableRead,
)
def create_deliverable(
    order_id: str,
    request: DeliverableCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DeliverableRead:
    return service.create_deliverable(
        db,
        current_user,
        order_id,
        request,
    )


@router.post(
    "/deliverables/{deliverable_id}/versions",
    response_model=DeliverableRead,
)
def submit_deliverable_version(
    deliverable_id: str,
    request: DeliverableVersionCreate,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DeliverableRead:
    return service.submit_deliverable_version(
        db,
        current_user,
        deliverable_id,
        request,
    )


@router.post(
    "/deliverables/{deliverable_id}/acceptance",
    response_model=DeliverableRead,
)
def decide_deliverable_acceptance(
    deliverable_id: str,
    request: AcceptanceCommand,
    current_user: CurrentUser,
    db: DatabaseSession,
) -> DeliverableRead:
    return service.decide_deliverable_acceptance(
        db,
        current_user,
        deliverable_id,
        request,
    )
