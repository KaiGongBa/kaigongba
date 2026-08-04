import { describe, expect, it } from 'vitest';

import {
  safeParseErrorEnvelope,
  safeParseStructuredBlock,
  safeParseTurnResponse,
  type QuestionGroupBlock,
  type StructuredBlock,
} from './protocol';

const questionBlock = {
  schema_version: '1.0',
  block_id: 'block_question_test',
  block_version: 3,
  type: 'question_group',
  status: 'pending',
  title: '采购约束',
  description: '硬事实不会由 AI 猜测。',
  submit_label: '统一发送',
  questions: [
    { id: 'budget', label: '预算范围', input_type: 'money_range', required: true, allow_uncertain: true },
    { id: 'schedule', label: '交付时间', input_type: 'date_or_duration', required: true },
  ],
};

function response(blocks: unknown[]) {
  return {
    protocol_version: '1.0',
    request_id: 'request_test_001',
    server_time: '2026-08-04T10:00:00+08:00',
    session_id: 'session_test_001',
    run_id: 'run_test_001',
    message_id: 'message_test_001',
    assistant_text: '请先确认信息。',
    ui_blocks: blocks,
    workflow: {
      capability_id: 'requirement.create',
      capability_version: '1.0.0',
      state: 'collecting',
      row_version: 3,
      progress: { completed_required: 2, total_required: 6 },
    },
    context: {
      page_instance_id: 'page_context_test_001',
      route_id: 'enterprise.requirement.list',
      resolved_pathname: '/enterprise/demands',
      organization_id: 'org_buyer',
      entity_refs: [{ type: 'organization', id: 'org_buyer' }],
      authorization: 'organization_member',
      projection_refs: ['requirement.visible_list'],
      context_version: 1,
      row_version: 4,
      stale: false,
    },
    usage: { request_id: 'ai_request_001' },
  };
}

describe('platform assistant protocol parser', () => {
  it('returns a strict discriminated question block', () => {
    const parsed: StructuredBlock = safeParseStructuredBlock(questionBlock);
    expect(parsed.type).toBe('question_group');
    if (parsed.type === 'question_group') {
      const narrowed: QuestionGroupBlock = parsed;
      expect(narrowed.questions.map((question) => question.input_type))
        .toEqual(['money_range', 'date_or_duration']);
    }
  });

  it('parses a valid response and retains workflow row version', () => {
    const parsed = safeParseTurnResponse(response([questionBlock]));
    expect(parsed?.workflow?.row_version).toBe(3);
    expect(parsed?.ui_blocks[0]).toMatchObject({ type: 'question_group', block_version: 3 });
  });

  it('degrades an unknown block to a safe notice without echoing payload HTML', () => {
    const parsed = safeParseTurnResponse(response([{
      type: 'html_widget',
      html: '<img src=x onerror=alert(1)>',
    }]));
    expect(parsed?.ui_blocks[0]).toMatchObject({
      type: 'notice',
      status: 'blocked',
      code: 'UNSUPPORTED_BLOCK',
    });
    expect(JSON.stringify(parsed?.ui_blocks[0])).not.toContain('onerror');
  });

  it('degrades a known block with extra or malformed properties', () => {
    const parsed = safeParseStructuredBlock({
      ...questionBlock,
      questions: [],
      arbitrary_html: '<script>alert(1)</script>',
    });
    expect(parsed).toMatchObject({ type: 'notice', code: 'INVALID_BLOCK' });
  });

  it('rejects an invalid top-level response instead of partially trusting it', () => {
    expect(safeParseTurnResponse({ ...response([questionBlock]), protocol_version: '2.0' }))
      .toBeNull();
    expect(safeParseTurnResponse({ ...response([questionBlock]), unexpected: true }))
      .toBeNull();
    expect(safeParseTurnResponse({
      ...response([questionBlock]),
      workflow: { ...response([]).workflow, row_version: 0 },
    })).toBeNull();
  });

  it('parses only registered error codes and exact error envelopes', () => {
    const parsed = safeParseErrorEnvelope({
      protocol_version: '1.0',
      request_id: 'request_error_001',
      server_time: '2026-08-04T10:02:00+08:00',
      error: {
        code: 'BLOCK_VERSION_CONFLICT',
        message: '问题组已更新。',
        retryable: true,
        field_errors: [{ field: 'block_version', code: 'stale', message: '版本过期' }],
      },
    });
    expect(parsed?.error.code).toBe('BLOCK_VERSION_CONFLICT');
    expect(safeParseErrorEnvelope({
      protocol_version: '1.0', request_id: 'request_error_002',
      server_time: '2026-08-04T10:02:00+08:00',
      error: { code: 'EXECUTE_ARBITRARY_URL', message: '不安全', retryable: false },
    })).toBeNull();
  });
});
