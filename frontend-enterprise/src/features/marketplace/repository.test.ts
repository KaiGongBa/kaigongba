import { describe, expect, it, vi } from 'vitest';

const { mockedGet, mockedPost } = vi.hoisted(() => ({ mockedGet: vi.fn(), mockedPost: vi.fn() }));

vi.mock('@/api/client', () => ({
  ApiError: class ApiError extends Error {},
  api: { get: mockedGet, post: mockedPost },
}));

import { aiServiceFixtures, skillFixtures } from './fixtures';
import { filterAiServices, filterSkills, marketplaceRepository } from './repository';

describe('marketplace filters', () => {
  it('filters AI services by keyword, scope and price', () => {
    expect(filterAiServices(aiServiceFixtures, { keyword: '合同' }).map((item) => item.id))
      .toContain('contract-review');
    expect(filterAiServices(aiServiceFixtures, { scope: 'mine' }).every((item) => item.mine))
      .toBe(true);
    expect(filterAiServices(aiServiceFixtures, { price: 'over-200' }).every((item) => item.price > 200))
      .toBe(true);
  });

  it('filters skills by verification, permission and install state', () => {
    expect(filterSkills(skillFixtures, { verification: 'pending' }).map((item) => item.id))
      .toEqual(['public-search']);
    expect(filterSkills(skillFixtures, { permission: '限定网络' }).length)
      .toBeGreaterThan(0);
    expect(filterSkills(skillFixtures, { scope: 'installed' }).every((item) => item.installed))
      .toBe(true);
  });

  it('preserves the all perspective required by the order API', async () => {
    mockedGet.mockResolvedValueOnce([]);

    await marketplaceRepository.listOrders('org_provider', 'all');

    expect(mockedGet).toHaveBeenCalledWith(
      '/api/transactions/orders?organizationId=org_provider&perspective=all',
    );
  });

  it('loads the active service category catalogue from the public business endpoint', async () => {
    mockedGet.mockResolvedValueOnce([]);

    await marketplaceRepository.listServiceCategories();

    expect(mockedGet).toHaveBeenCalledWith('/api/service-categories');
  });

  it('uses the isolated platform-assistant draft and handoff endpoints', async () => {
    mockedGet.mockResolvedValueOnce({ protocol_version: '1.0' });
    mockedPost.mockResolvedValueOnce({});

    await marketplaceRepository.getAssistantRequirementDraft('reqdraft_safe_1234');
    const input = {
      protocol_version: '1.0' as const,
      draft_version: 3,
      transaction_requirement_id: 'req_transaction01',
      requirement_write: {
        organization_id: 'org-1',
        title: '测试需求标题',
        category: '测试分类',
        description: '这是一段足够长的测试需求详细描述内容。',
        budget_min_amount: '100',
        budget_max_amount: '200',
        desired_delivery_at: '2026-09-01T18:00',
        visibility: 'invited_providers' as const,
        confidentiality_level: 'standard' as const,
        invite_limit: 5,
        deliverables: [{ name: '报告' }],
        acceptance_criteria: ['报告可查看'],
        attachments: [],
      },
      idempotency_key: 'handoff-unique-1',
    };
    await marketplaceRepository.auditAssistantRequirementHandoff('reqdraft_safe_1234', input);

    expect(mockedGet).toHaveBeenCalledWith(
      '/api/platform-assistant/requirement-drafts/reqdraft_safe_1234',
    );
    expect(mockedPost).toHaveBeenCalledWith(
      '/api/platform-assistant/requirement-drafts/reqdraft_safe_1234/handoffs',
      input,
    );
  });
});
