from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping

from sqlmodel import Session, select

from app.db.models import User
from app.platform_assistant.adaptive_interview import (
    AdaptiveInterviewCoordinator,
    AdaptiveInterviewTurn,
)
from app.platform_assistant.context import ResolvedPageContext
from app.platform_assistant.orchestrator import (
    RequirementWorkflowOrchestrator,
    RequirementWorkflowTurn,
)
from app.platform_assistant.protocol import validate_structured_block
from app.platform_assistant.repository import (
    PlatformAssistantRepository,
    RunScope,
    RunSnapshot,
)
from app.platform_assistant.requirement_drafts import (
    DraftFieldSourceInput,
    RequirementDraftContent,
    RequirementDraftRecord,
    RequirementDraftRepository,
    RequirementDraftScope,
)
from app.platform_assistant.requirement_models import (
    AssistantRequirementDraft,
    AssistantRequirementDraftVersion,
)
from app.platform_assistant.requirement_facts import (
    FactCandidateInput,
    FactLedgerScope,
    RequirementFactLedger,
)


class PlatformAssistantRuntimeError(RuntimeError):
    code = "PLATFORM_ASSISTANT_RUNTIME_ERROR"


class RuntimeAuthorizationError(PlatformAssistantRuntimeError):
    code = "UNAUTHORIZED_CONTEXT"


class RuntimeStateError(PlatformAssistantRuntimeError):
    code = "RUNTIME_STATE_CONFLICT"


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    snapshot: RunSnapshot
    draft: RequirementDraftRecord | None
    assistant_text: str
    degraded: bool = False
    degradation_code: str | None = None
    ai_request_ids: tuple[str, ...] = ()
    ui_blocks: tuple[dict[str, Any], ...] = ()


class PlatformAssistantRuntime:
    """Server-owned runtime for the first requirement intake workflow.

    The runtime only creates assistant workflow state and a private requirement
    draft.  It deliberately has no dependency on the transaction write API and
    therefore cannot publish, invite providers, select a quote, or perform any
    R3/R4 action.
    """

    capability_id = "requirement.create"
    capability_version = "1.0.0"

    def __init__(
        self,
        db: Session,
        *,
        orchestrator: RequirementWorkflowOrchestrator | None = None,
    ) -> None:
        self.db = db
        self.runs = PlatformAssistantRepository(db)
        self.drafts = RequirementDraftRepository(db)
        self.orchestrator = orchestrator or RequirementWorkflowOrchestrator()

    def handle_message(
        self,
        *,
        current_user: User,
        scope: RunScope,
        resolved_context: ResolvedPageContext | Mapping[str, Any],
        message: str,
        client_request_id: str,
        authorized_organization_ids: Iterable[str],
        initial_user_message: str | None = None,
        protocol_version: str = "1.0",
        entrypoint: str | None = None,
    ) -> RuntimeResult:
        """Start or continue intent selection for one assistant session."""

        text = message.strip()
        if not text:
            raise ValueError("message cannot be empty")
        _validate_request_id(client_request_id)
        allowed_organizations = self._validate_identity_and_context(
            current_user,
            scope,
            resolved_context,
            authorized_organization_ids,
        )
        active = self.runs.get_latest_active_run(scope)

        if protocol_version not in {"1.0", "2.0"}:
            raise ValueError("unsupported platform assistant protocol version")

        if entrypoint not in {None, self.capability_id}:
            raise ValueError("unsupported assistant entrypoint")
        if entrypoint is not None and protocol_version != "2.0":
            raise ValueError("assistant entrypoint requires protocol 2.0")

        if active is None:
            context_snapshot = _context_contract(resolved_context)
            run = self.runs.create_run(
                scope,
                capability_id=self.capability_id,
                capability_version=self.capability_version,
                organization_id=_context_organization_id(resolved_context),
                context_snapshot=context_snapshot,
                state="intent_pending",
                current_step="intent_confirmation",
            )
            if entrypoint == self.capability_id:
                return self._start_adaptive_requirement(
                    current_user=current_user,
                    scope=scope,
                    run_id=run.id,
                    message=text,
                    client_request_id=client_request_id,
                    authorized_organization_ids=allowed_organizations,
                )
            turn = self.orchestrator.handle_message(text)
            if _can_start_adaptive_requirement_directly(
                protocol_version=protocol_version,
                turn=turn,
            ):
                return self._start_adaptive_requirement(
                    current_user=current_user,
                    scope=scope,
                    run_id=run.id,
                    message=text,
                    client_request_id=client_request_id,
                    authorized_organization_ids=allowed_organizations,
                )
            self.runs.append_block(
                scope,
                run.id,
                turn.block,
                message_id=client_request_id,
            )
            return RuntimeResult(
                snapshot=self.runs.get_run_snapshot(scope, run.id),
                draft=None,
                assistant_text="我先确认一下你想完成的事情。",
                degraded=turn.degraded,
                degradation_code=turn.degradation_code,
                ai_request_ids=self.orchestrator.request_ids,
                ui_blocks=(turn.block,),
            )

        if active.state != "intent_pending":
            if protocol_version == "2.0" and active.state == "collecting":
                active_snapshot = self.runs.get_run_snapshot(scope, active.id)
                if not _is_adaptive_snapshot(active_snapshot):
                    return RuntimeResult(
                        snapshot=active_snapshot,
                        draft=self._get_run_draft(scope, active.id),
                        assistant_text=(
                            "检测到未完成的历史需求流程。请先继续原结构化问题，"
                            "或取消后明确发起新的自适应需求访谈；系统不会自动改写旧流程。"
                        ),
                        ai_request_ids=self.orchestrator.request_ids,
                    )
                return self._continue_adaptive_message(
                    current_user=current_user,
                    scope=scope,
                    run_id=active.id,
                    message=text,
                    client_request_id=client_request_id,
                    authorized_organization_ids=allowed_organizations,
                )
            return RuntimeResult(
                snapshot=self.runs.get_run_snapshot(scope, active.id),
                draft=self._get_run_draft(scope, active.id),
                assistant_text="当前流程已在进行中，请继续完成结构化问题。",
                ai_request_ids=self.orchestrator.request_ids,
            )

        selection = _structured_intent_selection(text)
        if selection is None:
            turn = self.orchestrator.handle_message(text)
            self.runs.append_block(
                scope,
                active.id,
                turn.block,
                message_id=client_request_id,
            )
            return RuntimeResult(
                snapshot=self.runs.get_run_snapshot(scope, active.id),
                draft=None,
                assistant_text="请先选择要创建需求、创建数字员工，还是了解平台。",
                degraded=turn.degraded,
                degradation_code=turn.degradation_code,
                ai_request_ids=self.orchestrator.request_ids,
            )

        if selection != self.capability_id:
            notice = _unsupported_intent_notice(selection, client_request_id)
            self.runs.append_block(scope, active.id, notice, message_id=client_request_id)
            self.runs.advance_run(
                scope,
                active.id,
                state="completed",
                current_step=selection,
            )
            return RuntimeResult(
                snapshot=self.runs.get_run_snapshot(scope, active.id),
                draft=None,
                assistant_text=notice["message"],
                ai_request_ids=self.orchestrator.request_ids,
                ui_blocks=(notice,),
            )

        if protocol_version == "2.0":
            return self._start_adaptive_requirement(
                current_user=current_user,
                scope=scope,
                run_id=active.id,
                message=(initial_user_message or text).strip(),
                client_request_id=client_request_id,
                authorized_organization_ids=allowed_organizations,
            )

        turn = self.orchestrator.handle_message(
            (initial_user_message or text).strip(),
            selected_capability_id=self.capability_id,
        )
        first_block = _inject_organization_options(
            turn.block, allowed_organizations
        )
        content, sources = _content_from_candidates(turn.facts)
        draft = self.drafts.create(
            RequirementDraftScope(scope.tenant_id, scope.user_id, scope.session_id),
            content,
            field_sources=sources,
            idempotency_key=f"kx3-create-{active.id}",
            run_id=active.id,
        )
        self.runs.append_block(
            scope,
            active.id,
            first_block,
            message_id=client_request_id,
        )
        self.runs.advance_run(
            scope,
            active.id,
            state="collecting",
            current_step=first_block["block_id"],
        )
        return RuntimeResult(
            snapshot=self.runs.get_run_snapshot(scope, active.id),
            draft=draft,
            assistant_text="好的，我会分组收集信息，先形成可编辑草稿，不会自动发布。",
            degraded=turn.degraded,
            degradation_code=turn.degradation_code,
            ai_request_ids=self.orchestrator.request_ids,
            ui_blocks=(first_block,),
        )

    def continue_after_answers(
        self,
        *,
        current_user: User,
        scope: RunScope,
        run_id: str,
        client_request_id: str,
        authorized_organization_ids: Iterable[str],
        protocol_version: str = "1.0",
    ) -> RuntimeResult:
        """Project already-persisted answers into a draft, idempotently."""

        _validate_request_id(client_request_id)
        allowed = self._validate_identity(
            current_user, scope, authorized_organization_ids
        )
        snapshot = self.runs.get_run_snapshot(scope, run_id)
        if snapshot.run.capability_id != self.capability_id:
            raise RuntimeStateError("run does not belong to requirement.create")
        submitted = [item for item in snapshot.latest_blocks if item.status == "submitted"]
        if not submitted:
            raise RuntimeStateError("no submitted question group is available")
        block = submitted[-1]
        if block.block_type != "question_group":
            raise RuntimeStateError("latest submitted block is not a question group")

        if protocol_version == "2.0" and block.schema_version == "2.0":
            return self._continue_adaptive_answers(
                current_user=current_user,
                scope=scope,
                run_id=run_id,
                block=block,
                snapshot=snapshot,
                client_request_id=client_request_id,
                authorized_organization_ids=allowed,
            )

        version_key = f"kx3-answer-{run_id}-{block.block_id}-{block.block_version}"
        if self._processed_version(scope, version_key) is not None:
            draft = self._get_run_draft(scope, run_id, allowed_organizations=allowed)
            return RuntimeResult(
                snapshot=self.runs.get_run_snapshot(scope, run_id),
                draft=draft,
                assistant_text="这一组回答已经处理，未重复创建草稿版本。",
                ai_request_ids=self.orchestrator.request_ids,
            )

        draft = self._get_run_draft(scope, run_id, allowed_organizations=allowed)
        if draft is None:
            raise RuntimeStateError("requirement draft is missing")
        answers = [
            item
            for item in snapshot.answers
            if item.block_id == block.block_id
            and item.block_version == block.block_version
        ]
        if not answers:
            raise RuntimeStateError("persisted answers are missing")

        content = draft.content.model_dump(
            mode="python", exclude={"draft_id", "draft_version", "missing_fields"}
        )
        sources = dict(draft.field_sources)
        selected_organization = _apply_answers(
            content,
            sources,
            answers,
            allowed_organization_ids=allowed,
        )
        organization_id = selected_organization or draft.draft.organization_id
        if organization_id is not None and organization_id not in allowed:
            raise RuntimeAuthorizationError("organization is outside the authorized scope")

        confirmed = {
            key for key, source in sources.items() if source.confirmed
        }
        plan = _next_question_plan(self.orchestrator, confirmed, run_id)
        if plan is None:
            expansion = self.orchestrator.expand_draft(
                {
                    key: value
                    for key, value in content.items()
                    if key in confirmed and value not in (None, "", [])
                }
            )
            for candidate in expansion.expansion.fields:
                if content.get(candidate.field) not in (None, "", []):
                    continue
                tentative = {**content, candidate.field: candidate.value}
                try:
                    RequirementDraftContent.model_validate(tentative)
                except Exception:
                    # Model text is advisory. A malformed candidate is omitted
                    # rather than breaking the deterministic workflow.
                    continue
                content[candidate.field] = candidate.value
                sources[candidate.field] = DraftFieldSourceInput(
                    source="ai_expansion",
                    source_ref=f"runtime:{client_request_id}",
                    confirmed=False,
                )

        draft_scope = RequirementDraftScope(
            scope.tenant_id,
            scope.user_id,
            scope.session_id,
            organization_id=organization_id,
        )
        updated = self.drafts.update(
            draft_scope,
            draft.draft.id,
            RequirementDraftContent.model_validate(content),
            field_sources=sources,
            expected_version=draft.content.draft_version,
            idempotency_key=version_key,
        )

        confirmed = {
            key for key, source in updated.field_sources.items() if source.confirmed
        }
        plan = _next_question_plan(self.orchestrator, confirmed, run_id)
        if plan is not None:
            next_block = _inject_organization_options(plan, allowed)
            self.runs.append_block(
                scope,
                run_id,
                next_block,
                message_id=client_request_id,
            )
            text = "已保存这一组回答，请继续补充下一组信息。"
        else:
            preview = _draft_preview(updated)
            self.runs.append_block(
                scope,
                run_id,
                preview,
                message_id=client_request_id,
            )
            if snapshot.run.state == "collecting":
                self.runs.advance_run(
                    scope,
                    run_id,
                    state="reviewing",
                    current_step="draft_preview",
                )
            text = "第一版需求草稿已生成，请检查并编辑；我不会替你发布。"

        return RuntimeResult(
            snapshot=self.runs.get_run_snapshot(scope, run_id),
            draft=updated,
            assistant_text=text,
            ai_request_ids=self.orchestrator.request_ids,
        )

    def _start_adaptive_requirement(
        self,
        *,
        current_user: User,
        scope: RunScope,
        run_id: str,
        message: str,
        client_request_id: str,
        authorized_organization_ids: frozenset[str],
    ) -> RuntimeResult:
        del current_user
        snapshot = self.runs.get_run_snapshot(scope, run_id)
        trusted_organization_id = snapshot.run.organization_id
        draft = self.drafts.create(
            RequirementDraftScope(
                scope.tenant_id,
                scope.user_id,
                scope.session_id,
                trusted_organization_id,
            ),
            RequirementDraftContent(
                organization_id=trusted_organization_id,
                currency="CNY",
            ),
            field_sources=(
                {
                    "organization_id": DraftFieldSourceInput(
                        source="existing_record",
                        source_ref="authorized_page_organization",
                        confirmed=True,
                    )
                }
                if trusted_organization_id
                else {}
            ),
            idempotency_key=f"kx-adaptive-create-{run_id}",
            run_id=run_id,
        )
        turn = AdaptiveInterviewCoordinator(self.db, self.orchestrator).process_message(
            scope=scope,
            workflow_run_id=run_id,
            organization_id=snapshot.run.organization_id,
            message=message,
            authorized_organization_ids=authorized_organization_ids,
            block_seed=client_request_id,
        )
        turn = self._expand_adaptive_soft_fields(
            scope,
            run_id,
            snapshot.run.organization_id,
            turn,
            authorized_organization_ids,
            client_request_id,
        )
        updated = self._project_adaptive_draft(
            scope,
            run_id,
            draft,
            turn,
            idempotency_key=f"kx-adaptive-initial-{client_request_id}",
        )
        blocks = self._materialize_adaptive_blocks(turn, updated, client_request_id)
        self._append_adaptive_blocks(scope, run_id, blocks, client_request_id)
        review_ready = _adaptive_draft_review_ready(updated)
        self.runs.advance_run(
            scope,
            run_id,
            state="collecting",
            current_step=blocks[-1]["block_id"],
        )
        if turn.readiness.handoff.ready or review_ready:
            self.runs.advance_run(
                scope,
                run_id,
                state="reviewing",
                current_step="draft_preview",
            )
        return RuntimeResult(
            snapshot=self.runs.get_run_snapshot(scope, run_id),
            draft=updated,
            assistant_text=(
                "我已根据你的描述、服务行业与常见规范扩写需求，"
                "并自动填入发布表单。你可以直接确认或修改。"
                if review_ready
                else "我已开始分析需求，只会对无法安全推断的关键信息请你确认。"
            ),
            degraded=turn.degraded,
            degradation_code=turn.degradation_code,
            ai_request_ids=self.orchestrator.request_ids,
            ui_blocks=blocks,
        )

    def _continue_adaptive_message(
        self,
        *,
        current_user: User,
        scope: RunScope,
        run_id: str,
        message: str,
        client_request_id: str,
        authorized_organization_ids: frozenset[str],
    ) -> RuntimeResult:
        del current_user
        snapshot = self.runs.get_run_snapshot(scope, run_id)
        draft = self._get_run_draft(
            scope,
            run_id,
            allowed_organizations=authorized_organization_ids,
        )
        if draft is None:
            raise RuntimeStateError("requirement draft is missing")
        turn = AdaptiveInterviewCoordinator(self.db, self.orchestrator).process_message(
            scope=scope,
            workflow_run_id=run_id,
            organization_id=snapshot.run.organization_id,
            message=message,
            authorized_organization_ids=authorized_organization_ids,
            block_seed=client_request_id,
        )
        turn = self._expand_adaptive_soft_fields(
            scope,
            run_id,
            snapshot.run.organization_id,
            turn,
            authorized_organization_ids,
            client_request_id,
        )
        updated = self._project_adaptive_draft(
            scope,
            run_id,
            draft,
            turn,
            idempotency_key=f"kx-adaptive-message-{client_request_id}",
        )
        blocks = self._materialize_adaptive_blocks(turn, updated, client_request_id)
        self._append_adaptive_blocks(scope, run_id, blocks, client_request_id)
        review_ready = _adaptive_draft_review_ready(updated)
        if (turn.readiness.handoff.ready or review_ready) and snapshot.run.state == "collecting":
            self.runs.advance_run(
                scope,
                run_id,
                state="reviewing",
                current_step="draft_preview",
            )
        return RuntimeResult(
            snapshot=self.runs.get_run_snapshot(scope, run_id),
            draft=updated,
            assistant_text=(
                "需求已按行业与交付规范扩写并填入表单，请直接确认或修改。"
                if review_ready
                else "收到。我已更新信息，并选择了下一项最关键的问题。"
            ),
            degraded=turn.degraded,
            degradation_code=turn.degradation_code,
            ai_request_ids=self.orchestrator.request_ids,
            ui_blocks=blocks,
        )

    def _continue_adaptive_answers(
        self,
        *,
        current_user: User,
        scope: RunScope,
        run_id: str,
        block: Any,
        snapshot: RunSnapshot,
        client_request_id: str,
        authorized_organization_ids: frozenset[str],
    ) -> RuntimeResult:
        draft = self._get_run_draft(
            scope,
            run_id,
            allowed_organizations=authorized_organization_ids,
        )
        if draft is None:
            raise RuntimeStateError("requirement draft is missing")
        answers = [
            item
            for item in snapshot.answers
            if item.block_id == block.block_id
            and item.block_version == block.block_version
        ]
        if not answers:
            raise RuntimeStateError("persisted answers are missing")
        run = snapshot.run
        fact_scope = FactLedgerScope(
            scope.tenant_id,
            scope.user_id,
            scope.session_id,
            run.organization_id,
        )
        ledger = RequirementFactLedger(self.db)
        _merge_adaptive_answers(
            ledger,
            fact_scope,
            workflow_run_id=run_id,
            block_payload=block.payload_json,
            answers=answers,
            actor_user_id=current_user.id,
        )
        turn = AdaptiveInterviewCoordinator(
            self.db, self.orchestrator
        ).project_after_fact_update(
            scope=scope,
            workflow_run_id=run_id,
            organization_id=run.organization_id,
            authorized_organization_ids=authorized_organization_ids,
            block_seed=client_request_id,
        )
        turn = self._expand_adaptive_soft_fields(
            scope,
            run_id,
            run.organization_id,
            turn,
            authorized_organization_ids,
            client_request_id,
        )
        updated = self._project_adaptive_draft(
            scope,
            run_id,
            draft,
            turn,
            idempotency_key=(
                f"kx-adaptive-answer-{run_id}-{block.block_id}-{block.block_version}"
            ),
        )
        blocks = self._materialize_adaptive_blocks(turn, updated, client_request_id)
        self._append_adaptive_blocks(scope, run_id, blocks, client_request_id)
        review_ready = _adaptive_draft_review_ready(updated)
        if (turn.readiness.handoff.ready or review_ready) and snapshot.run.state == "collecting":
            self.runs.advance_run(
                scope,
                run_id,
                state="reviewing",
                current_step="draft_preview",
            )
        return RuntimeResult(
            snapshot=self.runs.get_run_snapshot(scope, run_id),
            draft=updated,
            assistant_text=(
                "需求已按行业与交付规范扩写并填入表单，请直接确认或修改。"
                if review_ready
                else "已记录你的回答，我会继续追问当前最关键的信息。"
            ),
            degraded=turn.degraded,
            degradation_code=turn.degradation_code,
            ai_request_ids=self.orchestrator.request_ids,
            ui_blocks=blocks,
        )

    def _project_adaptive_draft(
        self,
        scope: RunScope,
        run_id: str,
        draft: RequirementDraftRecord,
        turn: AdaptiveInterviewTurn,
        *,
        idempotency_key: str,
    ) -> RequirementDraftRecord:
        content = draft.content.model_dump(
            mode="python", exclude={"draft_id", "draft_version", "missing_fields"}
        )
        sources = dict(draft.field_sources)
        for fact in turn.current_facts:
            if fact.field not in RequirementDraftContent.model_fields:
                continue
            if fact.status in {"conflict", "superseded"}:
                continue
            if fact.status != "confirmed" and not (
                fact.status == "candidate"
                and (
                    (
                        not fact.hard_fact
                        and fact.source
                        in {
                            "user_message",
                            "user_choice",
                            "user_edit",
                            "attachment_extraction",
                            "ai_expansion",
                        }
                    )
                    or (fact.hard_fact and fact.source == "user_message")
                )
            ):
                continue
            candidate_value = _draft_fact_value(fact.field, fact.value_json)
            tentative = {**content, fact.field: candidate_value}
            try:
                RequirementDraftContent.model_validate(tentative)
            except Exception:
                continue
            content[fact.field] = candidate_value
            sources[fact.field] = DraftFieldSourceInput(
                source=fact.source,
                source_ref=f"fact:{fact.id}",
                confirmed=fact.status == "confirmed",
            )
        if (
            turn.classification.status == "matched"
            and turn.classification.category_name
        ):
            content["category"] = turn.classification.category_name
            sources["category"] = DraftFieldSourceInput(
                source="existing_record",
                source_ref=f"category:{turn.classification.category_id}",
                confirmed=True,
            )
        parsed = RequirementDraftContent.model_validate(content)
        organization_id = parsed.organization_id or draft.draft.organization_id
        updated = self.drafts.update(
            RequirementDraftScope(
                scope.tenant_id,
                scope.user_id,
                scope.session_id,
                organization_id=organization_id,
            ),
            draft.draft.id,
            parsed,
            field_sources=sources,
            expected_version=draft.content.draft_version,
            idempotency_key=idempotency_key,
        )
        return updated

    def _expand_adaptive_soft_fields(
        self,
        scope: RunScope,
        run_id: str,
        organization_id: str | None,
        turn: AdaptiveInterviewTurn,
        authorized_organization_ids: frozenset[str],
        block_seed: str,
    ) -> AdaptiveInterviewTurn:
        if (
            not turn.readiness.preview.ready
            or turn.readiness.handoff.ready
            or any(
                item.source == "ai_expansion"
                and not item.field.startswith("classification.")
                for item in turn.current_facts
            )
        ):
            return turn
        confirmed = {
            item.field: item.value_json
            for item in turn.current_facts
            if item.status == "confirmed"
            and item.field in RequirementDraftContent.model_fields
        }
        expansion = self.orchestrator.expand_draft(confirmed)
        if not expansion.expansion.fields:
            return turn
        fact_scope = FactLedgerScope(
            scope.tenant_id,
            scope.user_id,
            scope.session_id,
            organization_id,
        )
        ledger = RequirementFactLedger(self.db)
        ledger.merge_candidates(
            fact_scope,
            workflow_run_id=run_id,
            candidates=[
                FactCandidateInput(
                    field=item.field,
                    value=item.value,
                    source="ai_expansion",
                    source_ref=f"draft_expansion:{block_seed}",
                    confidence=0.75,
                    confirmed_by_user=False,
                    needs_confirmation=True,
                )
                for item in expansion.expansion.fields
            ],
        )
        return AdaptiveInterviewCoordinator(
            self.db, self.orchestrator
        ).project_after_fact_update(
            scope=scope,
            workflow_run_id=run_id,
            organization_id=organization_id,
            authorized_organization_ids=authorized_organization_ids,
            block_seed=f"{block_seed}-expanded",
            use_model_planning=False,
        )

    def _append_adaptive_blocks(
        self,
        scope: RunScope,
        run_id: str,
        blocks: tuple[dict[str, Any], ...],
        message_id: str,
    ) -> None:
        for payload in blocks:
            self.runs.append_block(scope, run_id, payload, message_id=message_id)

    def _materialize_adaptive_blocks(
        self,
        turn: AdaptiveInterviewTurn,
        draft: RequirementDraftRecord,
        seed: str,
    ) -> tuple[dict[str, Any], ...]:
        review_ready = _adaptive_draft_review_ready(draft)
        if not turn.readiness.handoff.ready and not review_ready:
            return turn.blocks
        preview = _draft_preview(draft)
        deep_link = validate_structured_block(
            {
                "schema_version": "1.0",
                "block_id": f"block_requirement_form_{_safe_suffix(seed)}",
                "block_version": 1,
                "type": "deep_link",
                "status": "pending",
                "title": "AI 已扩写并填入需求",
                "description": "已结合服务行业、内容要求与常见规范生成草稿；请在真实发布页直接确认或修改。",
                "route_id": "enterprise.requirement.create",
                "route_params": {"draftId": draft.draft.id},
                "label": "检查并修改 AI 草稿",
            }
        )
        # Once a useful AI draft exists, the real form becomes the review
        # surface. Do not keep presenting soft-field questions that would make
        # the user re-enter content the model has already drafted.
        state_blocks = tuple(
            block for block in turn.blocks if block.get("type") != "question_group"
        )
        return (*state_blocks, preview, deep_link)

    def _validate_identity_and_context(
        self,
        current_user: User,
        scope: RunScope,
        resolved_context: ResolvedPageContext | Mapping[str, Any],
        authorized_organization_ids: Iterable[str],
    ) -> frozenset[str]:
        allowed = self._validate_identity(
            current_user, scope, authorized_organization_ids
        )
        context_org = _context_organization_id(resolved_context)
        if context_org is not None and context_org not in allowed:
            raise RuntimeAuthorizationError(
                "context organization is outside the authorized scope"
            )
        for ref in _context_entity_refs(resolved_context):
            if ref.get("type") == "organization" and ref.get("id") not in allowed:
                raise RuntimeAuthorizationError(
                    "organization entity reference is outside the authorized scope"
                )
        return allowed

    @staticmethod
    def _validate_identity(
        current_user: User,
        scope: RunScope,
        authorized_organization_ids: Iterable[str],
    ) -> frozenset[str]:
        if current_user.id != scope.user_id or current_user.tenant_id != scope.tenant_id:
            raise RuntimeAuthorizationError("run scope does not match current user")
        allowed = frozenset(
            item.strip()
            for item in authorized_organization_ids
            if isinstance(item, str) and item.strip()
        )
        return allowed

    def _get_run_draft(
        self,
        scope: RunScope,
        run_id: str,
        *,
        allowed_organizations: frozenset[str] = frozenset(),
    ) -> RequirementDraftRecord | None:
        row = self.db.exec(
            select(AssistantRequirementDraft).where(
                AssistantRequirementDraft.tenant_id == scope.tenant_id,
                AssistantRequirementDraft.user_id == scope.user_id,
                AssistantRequirementDraft.session_id == scope.session_id,
                AssistantRequirementDraft.run_id == run_id,
            )
        ).first()
        if row is None:
            return None
        if (
            row.organization_id is not None
            and allowed_organizations
            and row.organization_id not in allowed_organizations
        ):
            raise RuntimeAuthorizationError("draft organization is no longer authorized")
        draft_scope = RequirementDraftScope(
            scope.tenant_id,
            scope.user_id,
            scope.session_id,
            organization_id=row.organization_id,
        )
        return self.drafts.get(draft_scope, row.id)

    def _processed_version(
        self, scope: RunScope, idempotency_key: str
    ) -> AssistantRequirementDraftVersion | None:
        return self.db.exec(
            select(AssistantRequirementDraftVersion).where(
                AssistantRequirementDraftVersion.tenant_id == scope.tenant_id,
                AssistantRequirementDraftVersion.user_id == scope.user_id,
                AssistantRequirementDraftVersion.session_id == scope.session_id,
                AssistantRequirementDraftVersion.idempotency_key == idempotency_key,
            )
        ).first()


def _merge_adaptive_answers(
    ledger: RequirementFactLedger,
    scope: FactLedgerScope,
    *,
    workflow_run_id: str,
    block_payload: dict[str, Any],
    answers: Iterable[Any],
    actor_user_id: str,
) -> None:
    questions = {item["id"]: item for item in block_payload.get("questions", [])}
    for answer in answers:
        question = questions.get(answer.question_id)
        if question is None:
            raise RuntimeStateError("adaptive answer question is missing")
        value = answer.answer_json
        if value == {"uncertain": True}:
            continue
        field = answer.question_id.removeprefix("requirement.")
        candidates = _adaptive_answer_candidates(field, question, value)
        for candidate in candidates:
            result = ledger.merge_candidates(
                scope,
                workflow_run_id=workflow_run_id,
                candidates=[candidate],
            )[0]
            if result.fact.status != "confirmed":
                ledger.confirm(
                    scope,
                    workflow_run_id=workflow_run_id,
                    fact_id=result.fact.id,
                    expected_version=result.fact.version,
                    actor_user_id=actor_user_id,
                )


def _adaptive_answer_candidates(
    field: str,
    question: Mapping[str, Any],
    value: dict[str, Any],
) -> tuple[FactCandidateInput, ...]:
    kind = question.get("input_type")
    source_ref = f"answer:{question.get('id')}"
    if field == "budget_range":
        return tuple(
            _explicit_fact(name, item, source_ref)
            for name, item in (
                ("budget_min", str(value["minimum"])),
                ("budget_max", str(value["maximum"])),
                ("currency", value["currency"]),
            )
        )
    if kind == "date_or_duration":
        if "date" in value:
            schedule = {
                "kind": "deadline",
                "local_datetime": f"{value['date']}T23:59:59",
                "timezone": value["timezone"],
            }
        else:
            schedule = {
                "kind": "duration",
                "duration": value["duration"],
                "unit": value["unit"],
                "timezone": value["timezone"],
            }
        return (_explicit_fact(field, schedule, source_ref),)
    if kind in {"single_choice", "multi_choice"}:
        custom = value.get("custom_text")
        if custom:
            selected: Any = custom.strip()
        else:
            options = {item["id"]: item for item in question.get("options", [])}
            option_ids = [
                item for item in value.get("option_ids", []) if item in options
            ]
            if field in {
                "classification.category_id",
                "visibility",
                "confidentiality_level",
            }:
                # Catalog and enum-backed controls persist their stable option
                # identifiers. Labels and descriptions are presentation-only.
                selected_values = option_ids
            else:
                selected_values = [_option_value(options[item]) for item in option_ids]
            selected = selected_values[0] if kind == "single_choice" else selected_values
        return (_explicit_fact(field, selected, source_ref),)
    if kind in {"short_text", "long_text"}:
        text = value["text"].strip()
        if field == "classification.category_id":
            # Free text clarifies the category; it must be matched against the
            # catalog on the next turn, never accepted as a category ID.
            return (_explicit_fact("category", text, source_ref),)
        if field == "target_audience_or_use_scenario":
            field = "use_scenario"
        return (_explicit_fact(field, text, source_ref),)
    if kind == "entity_picker":
        refs = value.get("entity_refs", [])
        if len(refs) != 1:
            raise RuntimeStateError("exactly one enterprise must be selected")
        return (_explicit_fact(field, refs[0]["id"], source_ref),)
    if kind == "boolean":
        return (_explicit_fact(field, value["boolean"], source_ref),)
    if kind == "attachment":
        return (_explicit_fact(field, value.get("attachment_ids", []), source_ref),)
    raise RuntimeStateError(f"unsupported adaptive answer type: {kind}")


def _explicit_fact(field: str, value: Any, source_ref: str) -> FactCandidateInput:
    return FactCandidateInput(
        field=field,
        value=value,
        source="user_choice",
        source_ref=source_ref,
        confidence=1.0,
        confirmed_by_user=True,
        needs_confirmation=False,
    )


def _option_value(option: Mapping[str, Any]) -> Any:
    return option.get("description") or option.get("label") or option.get("id")


def _draft_fact_value(field: str, value: Any) -> Any:
    if field in {
        "service_scope",
        "exclusions",
        "risks",
        "dependencies",
        "acceptance_criteria",
    }:
        if isinstance(value, str):
            return _split_lines(value)
        return value
    if field == "deliverables":
        if isinstance(value, str):
            values = _split_lines(value)
        elif isinstance(value, list):
            values = value
        else:
            values = [value]
        return [
            item
            if isinstance(item, dict)
            else {
                "name": str(item),
                "format": _detect_deliverable_format(str(item)),
                "required": True,
            }
            for item in values
        ]
    if field in {"budget_min", "budget_max"}:
        return str(value)
    if field == "invite_limit":
        return int(value)
    return value


def _detect_deliverable_format(value: str) -> str:
    normalized = value.casefold()
    for marker, output in (
        ("pptx", ".pptx"),
        (".ppt", ".ppt"),
        ("pdf", ".pdf"),
        ("docx", ".docx"),
        ("xlsx", ".xlsx"),
        ("在线链接", "链接"),
        ("链接", "链接"),
    ):
        if marker in normalized:
            return output
    return "待确认"


def _validate_request_id(value: str) -> None:
    if not 8 <= len(value.strip()) <= 160:
        raise ValueError("client_request_id must contain 8 to 160 characters")


def _context_contract(
    value: ResolvedPageContext | Mapping[str, Any],
) -> dict[str, Any]:
    if isinstance(value, ResolvedPageContext):
        return dict(value.as_contract())
    return dict(value)


def _context_organization_id(
    value: ResolvedPageContext | Mapping[str, Any],
) -> str | None:
    raw = value.organization_id if isinstance(value, ResolvedPageContext) else value.get("organization_id")
    return raw if isinstance(raw, str) and raw else None


def _context_entity_refs(
    value: ResolvedPageContext | Mapping[str, Any],
) -> list[dict[str, str]]:
    if isinstance(value, ResolvedPageContext):
        return [item.as_dict() for item in value.entity_refs]
    raw = value.get("entity_refs", [])
    if not isinstance(raw, list):
        raise RuntimeAuthorizationError("context entity_refs is invalid")
    return [dict(item) for item in raw if isinstance(item, Mapping)]


def _structured_intent_selection(message: str) -> str | None:
    normalized = "".join(message.casefold().split())
    aliases = {
        "requirement.create": "requirement.create",
        "创建需求": "requirement.create",
        "创建需求草稿": "requirement.create",
        "创建服务需求草稿": "requirement.create",
        "agent.create": "agent.create",
        "创建ai员工": "agent.create",
        "创建数字员工": "agent.create",
        "platform.help": "platform.help",
        "平台帮助": "platform.help",
        "了解平台": "platform.help",
        "先了解平台怎么使用": "platform.help",
    }
    direct = aliases.get(normalized)
    if direct is not None:
        return direct
    for prefix in ("我选择:", "我选择：", "选择:", "选择："):
        if normalized.startswith(prefix):
            return aliases.get(normalized.removeprefix(prefix))
    return None


def _can_start_adaptive_requirement_directly(
    *,
    protocol_version: str,
    turn: RequirementWorkflowTurn,
) -> bool:
    """Skip the form-like intent gate only for a clear, safe v2 request.

    Starting the adaptive interview creates a private draft only. It does not
    publish, invite providers, place an order, or execute another consequential
    action, so an explicit high-confidence service request can proceed directly
    to the first useful follow-up question. Ambiguous, injected, and non-demand
    turns retain the reviewed intent-confirmation block.
    """

    if (
        protocol_version != "2.0"
        or turn.degradation_code == "PROMPT_INJECTION_GUARD"
    ):
        return False
    candidates = tuple(turn.intent.intent_candidates)
    if not candidates:
        return False
    primary = candidates[0]
    return primary.capability_id == "requirement.create" and primary.confidence >= 0.8


def _is_adaptive_snapshot(snapshot: RunSnapshot) -> bool:
    return any(item.schema_version == "2.0" for item in snapshot.blocks)


def _unsupported_intent_notice(selection: str, seed: str) -> dict[str, Any]:
    if selection == "agent.create":
        message = "数字员工创建仍在原有真实页面完成，我可以引导你前往，但不会替你提交。"
        code = "AGENT_CREATE_USE_EXISTING_PAGE"
    else:
        message = "你可以继续询问平台用法；本轮没有创建或修改任何业务数据。"
        code = "PLATFORM_HELP"
    return validate_structured_block(
        {
            "schema_version": "1.0",
            "block_id": f"block_notice_{_safe_suffix(seed)}",
            "block_version": 1,
            "type": "notice",
            "status": "succeeded",
            "title": "已确认你的选择",
            "description": message,
            "tone": "info",
            "code": code,
            "message": message,
            "actions": [],
        }
    )


def _content_from_candidates(candidates: Iterable[Any]) -> tuple[
    RequirementDraftContent, dict[str, DraftFieldSourceInput]
]:
    parsed = RequirementDraftContent(currency="CNY")
    sources: dict[str, DraftFieldSourceInput] = {}
    allowed = set(RequirementDraftContent.model_fields) - {
        "organization_id",
        "attachments",
        "currency",
    }
    for candidate in candidates:
        if candidate.field not in allowed:
            continue
        candidate_content = {
            **parsed.model_dump(mode="python"),
            candidate.field: candidate.value,
        }
        try:
            parsed = RequirementDraftContent.model_validate(candidate_content)
        except Exception:
            continue
        sources[candidate.field] = DraftFieldSourceInput(
            source=candidate.source,
            source_ref="initial_user_message",
            confirmed=bool(candidate.confirmed_by_user),
        )
    return parsed, sources


def _apply_answers(
    content: dict[str, Any],
    sources: dict[str, DraftFieldSourceInput],
    answers: Iterable[Any],
    *,
    allowed_organization_ids: frozenset[str],
) -> str | None:
    selected_organization: str | None = None
    for answer in answers:
        value = answer.answer_json
        if value == {"uncertain": True}:
            continue
        question = answer.question_id
        source = DraftFieldSourceInput(
            source=answer.source,
            source_ref=f"answer:{answer.block_id}:{question}",
            confirmed=True,
        )
        if question in {"requirement.title", "requirement.goal"}:
            field = question.rsplit(".", 1)[1]
            content[field] = value["text"].strip()
            sources[field] = source
        elif question == "requirement.category":
            content["category"] = value["option_ids"][0]
            sources["category"] = source
        elif question == "requirement.audience_or_scenario":
            content["use_scenario"] = value["text"].strip()
            sources["use_scenario"] = source
        elif question in {
            "requirement.service_scope",
            "requirement.exclusions",
            "requirement.acceptance_criteria",
        }:
            field = question.rsplit(".", 1)[1]
            content[field] = _split_lines(value["text"])
            sources[field] = source
        elif question == "requirement.deliverables":
            content["deliverables"] = [
                {"name": item, "format": "文档", "required": True}
                for item in _split_lines(value["text"])
            ]
            sources["deliverables"] = source
        elif question == "requirement.budget_range":
            content["budget_min"] = _money(value["minimum"])
            content["budget_max"] = _money(value["maximum"])
            content["currency"] = "CNY"
            sources["budget_min"] = source
            sources["budget_max"] = source
            sources["currency"] = source
        elif question == "requirement.schedule":
            if "date" in value:
                content["schedule"] = {
                    "kind": "deadline",
                    "local_datetime": f"{value['date']}T23:59:59",
                    "timezone": value["timezone"],
                }
            else:
                content["schedule"] = {
                    "kind": "duration",
                    "duration": value["duration"],
                    "unit": value["unit"],
                    "timezone": value["timezone"],
                }
            sources["schedule"] = source
        elif question == "requirement.organization":
            refs = value.get("entity_refs", [])
            if len(refs) != 1 or refs[0].get("type") != "organization":
                raise RuntimeAuthorizationError("exactly one organization is required")
            selected_organization = refs[0].get("id")
            if selected_organization not in allowed_organization_ids:
                raise RuntimeAuthorizationError("selected organization is not authorized")
            content["organization_id"] = selected_organization
            sources["organization_id"] = source
        elif question in {
            "requirement.visibility",
            "requirement.confidentiality",
        }:
            field = (
                "confidentiality_level"
                if question.endswith("confidentiality")
                else "visibility"
            )
            content[field] = value["option_ids"][0]
            sources[field] = source
        elif question == "requirement.invite_limit":
            content["invite_limit"] = int(value["text"])
            sources["invite_limit"] = source
    return selected_organization


def _next_question_plan(
    orchestrator: RequirementWorkflowOrchestrator,
    confirmed_fields: set[str],
    seed: str,
) -> dict[str, Any] | None:
    turn = orchestrator.handle_message(
        "继续完善需求草稿",
        selected_capability_id="requirement.create",
        confirmed_fields=confirmed_fields,
    )
    return turn.block if turn.block["type"] == "question_group" else None


def _inject_organization_options(
    block: dict[str, Any],
    organization_ids: frozenset[str],
) -> dict[str, Any]:
    """Add only server-authorized organization choices to the fixed block."""

    if block.get("type") != "question_group":
        return block
    payload = {**block, "questions": [dict(item) for item in block["questions"]]}
    for question in payload["questions"]:
        if question.get("id") != "requirement.organization":
            continue
        question["options"] = [
            {"id": organization_id, "label": organization_id}
            for organization_id in sorted(organization_ids)
        ]
    return validate_structured_block(payload)


def _draft_preview(record: RequirementDraftRecord) -> dict[str, Any]:
    content = record.content
    sections: list[dict[str, Any]] = []
    section_fields = (
        ("基本信息", ("title", "category", "goal", "use_scenario")),
        ("范围与验收", ("service_scope", "exclusions", "deliverables", "acceptance_criteria")),
        ("交易条件", ("budget_min", "budget_max", "schedule", "organization_id", "visibility", "invite_limit", "confidentiality_level")),
    )
    labels = {
        "title": "需求名称",
        "category": "服务类别",
        "goal": "目标",
        "use_scenario": "使用场景",
        "service_scope": "服务范围",
        "exclusions": "排除项",
        "deliverables": "交付物",
        "acceptance_criteria": "验收标准",
        "budget_min": "最低预算",
        "budget_max": "最高预算",
        "schedule": "工期",
        "organization_id": "发布主体",
        "visibility": "可见范围",
        "invite_limit": "邀请上限",
        "confidentiality_level": "保密等级",
    }
    for index, (title, keys) in enumerate(section_fields, start=1):
        fields: list[dict[str, Any]] = []
        for key in keys:
            value = getattr(content, key)
            if value in (None, "", []):
                continue
            source = record.field_sources.get(key)
            fields.append(
                {
                    "key": key,
                    "label": labels[key],
                    "value": value.model_dump(mode="json") if hasattr(value, "model_dump") else [item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in value] if isinstance(value, list) else value,
                    "source": source.source if source else "system_default",
                    "source_ref": source.source_ref if source else None,
                    "confidence": None,
                    "editable": True,
                    "needs_confirmation": bool(source and not source.confirmed),
                }
            )
        if fields:
            sections.append({"id": f"section_{index}", "title": title, "fields": fields})
    missing = [
        {
            "key": item,
            "label": item.replace("confirmation:", "").replace("field_source:", ""),
            "severity": "blocking",
            "reason": "需要用户补充或确认",
        }
        for item in content.missing_fields
    ]
    return validate_structured_block(
        {
            "schema_version": "1.0",
            "block_id": f"block_draft_{_safe_suffix(content.draft_id)}",
            # Block versions are local to one logical block; the persisted
            # requirement version is carried independently in draft_version.
            "block_version": 1,
            "type": "draft_preview",
            "status": "reviewing",
            "title": "需求草稿预览",
            "description": "请检查每个字段。这是助手私有草稿，尚未发布到交易市场。",
            "draft_id": content.draft_id,
            "draft_version": content.draft_version,
            "summary": content.goal or content.title or "待完善的服务需求草稿",
            "sections": sections,
            "missing_fields": missing,
            "actions": [
                {
                    "id": "requirement.draft.edit",
                    "label": "继续检查和编辑",
                    "style": "primary",
                }
            ],
        }
    )


def _adaptive_draft_review_ready(record: RequirementDraftRecord) -> bool:
    """Return whether AI produced enough editable content to open the form.

    Budget, exact delivery time, visibility and other hard facts may remain
    empty; the real form already exposes those controls.  The assistant should
    stop interviewing once it has produced the substantive brief the user
    asked it to draft.
    """

    content = record.content
    has_ai_expansion = any(
        source.source == "ai_expansion"
        for field, source in record.field_sources.items()
        if field not in {"currency", "change_summary"}
    )
    return bool(
        has_ai_expansion
        and content.title
        and content.category
        and content.goal
        and (content.target_audience or content.use_scenario)
        and content.deliverables
        and content.acceptance_criteria
    )


def _split_lines(value: str) -> list[str]:
    text = value.replace("；", "\n").replace(";", "\n")
    return [item.strip(" -\t") for item in text.splitlines() if item.strip(" -\t")]


def _money(value: Any) -> str:
    amount = Decimal(str(value))
    return format(amount.quantize(Decimal("0.01")), "f")


def _safe_suffix(value: str) -> str:
    return "".join(char for char in value if char.isalnum() or char in "_-")[-80:] or "runtime"


__all__ = [
    "PlatformAssistantRuntime",
    "PlatformAssistantRuntimeError",
    "RuntimeAuthorizationError",
    "RuntimeResult",
    "RuntimeStateError",
]
