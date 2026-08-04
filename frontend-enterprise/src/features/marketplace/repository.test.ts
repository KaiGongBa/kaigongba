import { describe, expect, it, vi } from 'vitest';

const { mockedGet } = vi.hoisted(() => ({ mockedGet: vi.fn() }));

vi.mock('@/api/client', () => ({ api: { get: mockedGet } }));

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
});
