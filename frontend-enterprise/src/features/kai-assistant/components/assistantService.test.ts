import { describe, expect, it } from 'vitest';

import { normalizeAssistantResult, parseAssistantError } from './assistantService';

describe('Kai assistant guidance transport', () => {
  it('preserves entity summaries, registered deep links and notices from a general turn', () => {
    const result = normalizeAssistantResult({
      protocol_version: '1.0',
      request_id: 'request_guidance',
      server_time: '2026-08-04T20:00:00+08:00',
      session_id: 'session_kai',
      run_id: null,
      message_id: 'message_guidance',
      assistant_text: '以下是当前页面的可用引导。',
      ui_blocks: [
        {
          schema_version: '1.0', block_id: 'block_guidance_summary', block_version: 1,
          type: 'entity_summary', status: 'succeeded', title: '订单摘要', description: '',
          entity_ref: { type: 'order', id: 'order_visible' },
          fields: [{ key: 'status', label: '状态', value: '进行中' }], allowed_action_ids: [],
        },
        {
          schema_version: '1.0', block_id: 'block_guidance_link', block_version: 1,
          type: 'deep_link', status: 'pending', title: '订单入口', description: '',
          route_id: 'enterprise.order.list', route_params: {}, label: '查看订单',
        },
        {
          schema_version: '1.0', block_id: 'block_guidance_notice', block_version: 1,
          type: 'notice', status: 'pending', title: '提示', description: '', tone: 'info',
          code: 'READ_ONLY_GUIDANCE', message: '最终确认需在业务页完成。', actions: [],
        },
      ],
      workflow: null,
      context: {
        page_instance_id: 'page_guidance_12345678', route_id: 'assistant.chat', resolved_pathname: '/enterprise/orders',
        organization_id: 'org_visible', entity_refs: [], authorization: 'organization_member',
        projection_refs: ['order.visible_list'], context_version: 1, row_version: null, stale: false,
      },
      usage: { request_id: 'usage_guidance' },
    }, { sessionId: 'session_kai', assistantText: '备用文案' });

    expect(result.blocks.map((block) => block.type)).toEqual(['entity_summary', 'deep_link', 'notice']);
    expect(result.runId).toBeNull();
    expect(result.assistantText).toBe('以下是当前页面的可用引导。');
  });

  it('keeps network errors retryable without exposing a fake business result', () => {
    expect(parseAssistantError(new Error('连接中断'))).toEqual({
      code: 'INTERNAL_ERROR', message: '连接中断', retryable: true,
    });
  });
});
