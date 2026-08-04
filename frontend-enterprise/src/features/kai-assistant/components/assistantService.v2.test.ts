import { beforeEach, describe, expect, it, vi } from 'vitest';

const { apiPost } = vi.hoisted(() => ({ apiPost: vi.fn() }));

vi.mock('@/api/client', () => ({ api: { post: apiPost } }));

import { createDefaultKaiAssistantService, normalizeAssistantResult } from './assistantService';

beforeEach(() => {
  apiPost.mockReset();
});

describe('Kai assistant adaptive v2 transport', () => {
  it('prefers protocol 2.0 and preserves interview state followed by adaptive questions', async () => {
    apiPost.mockResolvedValue(v2Response());

    const result = await createDefaultKaiAssistantService().sendTurn(turnInput());

    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(apiPost).toHaveBeenCalledWith('/api/platform-assistant/turns', expect.objectContaining({
      protocol_version: '2.0',
      session_id: 'session_adaptive',
      message: '帮我发布品牌设计需求',
    }));
    expect(result.blocks.map((block) => block.type)).toEqual(['interview_state', 'question_group']);
    expect(result.blocks[0]?.schema_version).toBe('2.0');
  });

  it('retries the same turn with v1 only when the server explicitly rejects protocol 2.0', async () => {
    apiPost
      .mockRejectedValueOnce({ status: 422, body: '{"field":"protocol_version","expected":"Literal 1.0","received":"2.0"}' })
      .mockResolvedValueOnce(v1Response());

    const result = await createDefaultKaiAssistantService().sendTurn(turnInput());

    expect(apiPost).toHaveBeenCalledTimes(2);
    expect(apiPost.mock.calls[0]?.[1]).toEqual(expect.objectContaining({ protocol_version: '2.0' }));
    expect(apiPost.mock.calls[1]?.[1]).toEqual(expect.objectContaining({ protocol_version: '1.0' }));
    expect(apiPost.mock.calls[1]?.[1].client_request_id).toBe(apiPost.mock.calls[0]?.[1].client_request_id);
    expect(result.blocks[0]?.type).toBe('notice');
  });

  it('accepts a v1 response to the preferred v2 request for rolling deployment compatibility', async () => {
    apiPost.mockResolvedValue(v1Response());

    const result = await createDefaultKaiAssistantService().sendTurn(turnInput());

    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(apiPost.mock.calls[0]?.[1]).toEqual(expect.objectContaining({ protocol_version: '2.0' }));
    expect(result.assistantText).toBe('这是兼容的 v1 回复。');
    expect(result.blocks[0]?.schema_version).toBe('1.0');
  });

  it('preserves protocol 2.0 when submitting adaptive answers', async () => {
    apiPost.mockResolvedValue(v2Response());

    await createDefaultKaiAssistantService().submitAnswers({
      protocol_version: '2.0',
      session_id: 'session_adaptive',
      run_id: 'run_adaptive',
      block_id: 'block_question_adaptive',
      block_version: 1,
      idempotency_key: 'answer_adaptive_12345678',
      answers: [{
        question_id: 'style',
        value: { text: '现代简约' },
        client_updated_at: '2026-08-04T20:01:00+08:00',
      }],
    });

    expect(apiPost).toHaveBeenCalledWith(
      '/api/platform-assistant/runs/run_adaptive/answers',
      expect.objectContaining({ protocol_version: '2.0' }),
    );
  });

  it('degrades a malformed v2 block to a non-actionable notice', () => {
    const value = v2Response();
    (value.ui_blocks as unknown[])[0] = { ...value.ui_blocks[0], facts: [{ invalid: true }] };

    const result = normalizeAssistantResult(value, { sessionId: '', assistantText: '备用回复' });

    expect(result.blocks[0]).toEqual(expect.objectContaining({
      schema_version: '1.0', type: 'notice', code: 'INVALID_BLOCK', actions: [],
    }));
    expect(result.blocks[1]?.type).toBe('question_group');
  });
});

function turnInput() {
  return {
    pageContext: {
      page_instance_id: 'page_adaptive_12345678', route_id: 'assistant.chat', pathname: '/enterprise/demands/new',
      entity_refs: [], ui_state: {}, context_version: 1,
    },
    sessionId: 'session_adaptive', agentId: 'agent_kai', message: '帮我发布品牌设计需求',
  };
}

function v2Response() {
  return {
    protocol_version: '2.0', request_id: 'request_adaptive', server_time: '2026-08-04T20:00:00+08:00',
    session_id: 'session_adaptive', run_id: 'run_adaptive', message_id: 'message_adaptive',
    assistant_text: '我先总结已知信息，再问一个关键问题。',
    ui_blocks: [
      {
        schema_version: '2.0', block_id: 'block_interview_adaptive', block_version: 1,
        type: 'interview_state', status: 'reviewing', title: '需求理解进度', description: '',
        facts: [{
          key: 'service_goal', label: '服务目标', value: '品牌设计', source: 'user_message', status: 'confirmed',
          confidence: 1, hard_fact: true, editable: true, edit_action_id: 'edit_service_goal',
        }],
        classification: { category_id: 'brand-design', name: '品牌设计', confidence: 0.9, status: 'suggested' },
        missing_information: [{ key: 'style', label: '视觉风格', severity: 'blocking', reason: '用于确定创意方向。' }],
        readiness: { ready: false, blocking_fields: ['style'] },
      },
      {
        schema_version: '2.0', block_id: 'block_question_adaptive', block_version: 1,
        type: 'question_group', status: 'pending', title: '补充关键信息', description: '', submit_label: '统一发送',
        allow_free_text: true,
        questions: [{
          id: 'style', label: '期望视觉风格', input_type: 'single_choice', required: true,
          options: [{ id: 'modern', label: '现代简约' }, { id: 'warm', label: '温暖亲和' }],
          allow_custom: true, allow_uncertain: true,
        }],
      },
    ],
    workflow: {
      capability_id: 'requirement.create', capability_version: '2.0.0', state: 'collecting', row_version: 2,
      progress: { completed_required: 1, total_required: 2 },
    },
    context: {
      page_instance_id: 'page_adaptive_12345678', route_id: 'assistant.chat', resolved_pathname: '/enterprise/demands/new',
      organization_id: 'org_adaptive', entity_refs: [], authorization: 'organization_member',
      projection_refs: ['requirement.create'], context_version: 1, row_version: null, stale: false,
    },
    usage: { request_id: 'usage_adaptive' },
  };
}

function v1Response() {
  return {
    protocol_version: '1.0', request_id: 'request_v1', server_time: '2026-08-04T20:00:00+08:00',
    session_id: 'session_adaptive', run_id: null, message_id: 'message_v1', assistant_text: '这是兼容的 v1 回复。',
    ui_blocks: [{
      schema_version: '1.0', block_id: 'block_notice_v1', block_version: 1, type: 'notice', status: 'pending',
      title: '兼容提示', description: '', tone: 'info', code: 'V1_COMPATIBLE', message: '仍可安全显示。', actions: [],
    }],
    workflow: null,
    context: {
      page_instance_id: 'page_adaptive_12345678', route_id: 'assistant.chat', resolved_pathname: '/enterprise/demands/new',
      organization_id: 'org_adaptive', entity_refs: [], authorization: 'organization_member',
      projection_refs: [], context_version: 1, row_version: null, stale: false,
    },
    usage: { request_id: 'usage_v1' },
  };
}
