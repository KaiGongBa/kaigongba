import { describe, expect, it } from 'vitest';

import {
  collectStructuredBlockDiagnostics,
  parseStructuredBlockBySchema,
  safeParseAnyTurnResponse,
  safeParseStructuredBlockV2,
  safeParseTurnResponse,
  safeParseTurnResponseV2,
  type AdaptiveQuestionGroupBlock,
  type InterviewStateBlock,
} from './protocol';

const interviewBlock = {
  schema_version: '2.0',
  block_id: 'block_interview_test',
  block_version: 2,
  type: 'interview_state',
  status: 'pending',
  title: '当前理解',
  description: '区分候选事实与已确认事实。',
  facts: [{
    key: 'budget.target', label: '目标预算', value: { amount: '50000', currency: 'CNY' },
    source: 'user_message', status: 'confirmed', confidence: 1, hard_fact: true,
    editable: true, edit_action_id: 'requirement.edit.budget',
  }],
  classification: {
    category_id: 'website-development', name: '企业官网开发', confidence: 0.78, status: 'needs_confirmation',
  },
  missing_information: [{
    key: 'delivery.schedule', label: '交付时间', severity: 'blocking', reason: '尚未提供交付时间。',
  }],
  readiness: { ready: false, blocking_fields: ['delivery.schedule'] },
};

const adaptiveQuestions = {
  schema_version: '2.0',
  block_id: 'block_adaptive_questions',
  block_version: 1,
  type: 'question_group',
  status: 'pending',
  title: '还需确认 2 项',
  description: '也可以自由文本补充。',
  submit_label: '统一发送',
  questions: [
    { id: 'booking.scope', label: '预约什么？', input_type: 'short_text', required: true },
    { id: 'delivery.schedule', label: '什么时候上线？', input_type: 'date_or_duration', required: true, allow_uncertain: true },
  ],
  allow_free_text: true,
};

const frozenV1Notice = {
  schema_version: '1.0', block_id: 'block_notice_v1_reused', block_version: 1,
  type: 'notice', status: 'pending', title: '确认提示', description: '', tone: 'info',
  code: 'BUSINESS_CONFIRMATION_REQUIRED', message: '最终发布需在业务页确认。', actions: [],
};

function responseV2(blocks: unknown[]) {
  return {
    protocol_version: '2.0',
    request_id: 'request_v2_test',
    server_time: '2026-08-04T20:00:00+08:00',
    session_id: 'session_v2_test',
    run_id: 'run_v2_test',
    message_id: 'message_v2_test',
    assistant_text: '请继续补充。',
    ui_blocks: blocks,
    workflow: {
      capability_id: 'requirement.create', capability_version: '2.0.0', state: 'collecting', row_version: 2,
      progress: { completed_required: 1, total_required: 2 },
    },
    context: {
      page_instance_id: 'page_context_v2_test', route_id: 'enterprise.requirement.create',
      resolved_pathname: '/enterprise/demands/new', organization_id: 'org_buyer', entity_refs: [],
      authorization: 'organization_member', projection_refs: ['requirement.assistant_draft'],
      context_version: 1, row_version: null, stale: false,
    },
    usage: { request_id: 'ai_request_v2_test' },
  };
}

describe('platform assistant adaptive interview protocol v2', () => {
  it('accepts an unmatched classification when optional identity fields are omitted on the wire', () => {
    const parsed = parseStructuredBlockBySchema({
      schema_version: '2.0',
      block_id: 'block_interview_unmatched',
      block_version: 1,
      type: 'interview_state',
      status: 'pending',
      title: '已收集的信息',
      description: '等待匹配分类。',
      facts: [],
      classification: { confidence: 0.08, status: 'unmatched' },
      missing_information: [{
        key: 'category', label: '服务分类', severity: 'blocking', reason: '请补充服务分类。',
      }],
      readiness: { ready: false, blocking_fields: ['category'] },
    }, 0);

    expect(parsed.diagnostic).toBeNull();
    expect(parsed.block.type).toBe('interview_state');
    if (parsed.block.type === 'interview_state') {
      expect(parsed.block.classification).toEqual({
        category_id: null,
        name: null,
        confidence: 0.08,
        status: 'unmatched',
      });
    }
  });
  it('parses interview state, adaptive questions and frozen v1 blocks in one v2 response', () => {
    const parsed = safeParseTurnResponseV2(responseV2([interviewBlock, adaptiveQuestions, frozenV1Notice]));
    expect(parsed?.protocol_version).toBe('2.0');
    expect(parsed?.ui_blocks.map((block) => block.type))
      .toEqual(['interview_state', 'question_group', 'notice']);

    const interview: InterviewStateBlock = parsed?.ui_blocks[0] as InterviewStateBlock;
    expect(interview.facts[0]).toMatchObject({ status: 'confirmed', hard_fact: true, confidence: 1 });
    expect(interview.classification.status).toBe('needs_confirmation');
    expect(interview.readiness).toEqual({ ready: false, blocking_fields: ['delivery.schedule'] });

    const questions: AdaptiveQuestionGroupBlock = parsed?.ui_blocks[1] as AdaptiveQuestionGroupBlock;
    expect(questions.questions).toHaveLength(2);
    expect(questions.allow_free_text).toBe(true);
  });

  it('keeps the v1 parser frozen while the version-dispatch parser accepts both versions', () => {
    expect(safeParseTurnResponse(responseV2([interviewBlock]))).toBeNull();
    expect(safeParseAnyTurnResponse(responseV2([interviewBlock]))?.protocol_version).toBe('2.0');

    const v1 = { ...responseV2([frozenV1Notice]), protocol_version: '1.0' };
    expect(safeParseTurnResponseV2(v1)).toBeNull();
    expect(safeParseAnyTurnResponse(v1)?.protocol_version).toBe('1.0');
  });

  it('limits each adaptive question group to three dynamic questions', () => {
    const parsed = safeParseStructuredBlockV2({
      ...adaptiveQuestions,
      questions: [...adaptiveQuestions.questions, adaptiveQuestions.questions[0], adaptiveQuestions.questions[1]],
    });
    expect(parsed).toMatchObject({ type: 'notice', code: 'INVALID_BLOCK' });
  });

  it('fails closed on an incoherent readiness state or an invalid classification', () => {
    const readiness = safeParseStructuredBlockV2({
      ...interviewBlock,
      readiness: { ready: true, blocking_fields: ['delivery.schedule'] },
    });
    expect(readiness).toMatchObject({ type: 'notice', code: 'INVALID_BLOCK' });

    const classification = safeParseStructuredBlockV2({
      ...interviewBlock,
      classification: { category_id: null, name: null, confidence: 0.9, status: 'matched' },
    });
    expect(classification).toMatchObject({ type: 'notice', code: 'INVALID_BLOCK' });
  });

  it('degrades unknown and malformed v2 blocks without echoing executable payloads', () => {
    const unknown = safeParseTurnResponseV2(responseV2([{
      schema_version: '2.0', type: 'iframe', html: '<iframe src="javascript:alert(1)">',
    }]));
    expect(unknown?.ui_blocks[0]).toMatchObject({ type: 'notice', code: 'UNSUPPORTED_BLOCK' });
    expect(JSON.stringify(unknown?.ui_blocks[0])).not.toContain('javascript:');

    const malformed = safeParseStructuredBlockV2({
      ...interviewBlock,
      facts: [{ ...interviewBlock.facts[0], confidence: 4, arbitrary_html: '<script />' }],
    });
    expect(malformed).toMatchObject({ type: 'notice', code: 'INVALID_BLOCK' });
    expect(JSON.stringify(malformed)).not.toContain('<script');
  });

  it('dispatches restored blocks by their own schema and emits non-sensitive audit diagnostics', () => {
    const restored = [interviewBlock, adaptiveQuestions, frozenV1Notice, {
      schema_version: '9.9', block_id: 'block_future_unknown', type: 'future_widget',
      secret_payload: '<script>do-not-log</script>',
    }];

    expect(restored.map((block, index) => parseStructuredBlockBySchema(block, index).block.type))
      .toEqual(['interview_state', 'question_group', 'notice', 'notice']);
    expect(collectStructuredBlockDiagnostics(restored)).toEqual([{
      code: 'UNSUPPORTED_BLOCK', block_index: 3, schema_version: '9.9',
      block_type: 'future_widget', block_id: 'block_future_unknown',
    }]);
    expect(JSON.stringify(collectStructuredBlockDiagnostics(restored))).not.toContain('do-not-log');
    expect(parseStructuredBlockBySchema(restored[3], 3).block).toMatchObject({
      block_id: 'block_safe_fallback_3', code: 'UNSUPPORTED_BLOCK', actions: [],
    });
  });
});
