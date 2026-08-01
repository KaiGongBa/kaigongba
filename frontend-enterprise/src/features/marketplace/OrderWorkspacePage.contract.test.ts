import { describe, expect, it } from 'vitest';

import { ORDER_WORKSPACE_TABS } from './OrderWorkspacePage';

describe('order workspace capability contract', () => {
  it('keeps every fulfilled-order business area available after the project-center remap', () => {
    expect(ORDER_WORKSPACE_TABS).toEqual([
      { id: 'overview', label: '项目总览' },
      { id: 'execution', label: 'SOP 执行' },
      { id: 'communication', label: '订单沟通' },
      { id: 'changes', label: '变更与取消' },
      { id: 'disputes', label: '争议处理' },
      { id: 'deliverables', label: '交付物' },
      { id: 'materials', label: '材料' },
      { id: 'events', label: '执行记录' },
    ]);
  });
});
