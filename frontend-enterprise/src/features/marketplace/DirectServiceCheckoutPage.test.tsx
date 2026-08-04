// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { aiServiceFixtures } from './fixtures';

const mocks = vi.hoisted(() => ({
  createDirectServiceCheckout: vi.fn(),
  notifyError: vi.fn(),
  notifySuccess: vi.fn(),
}));

vi.mock('@/components/ui/app-toast', () => ({
  notify: { error: mocks.notifyError, success: mocks.notifySuccess },
}));

vi.mock('./components', () => ({
  MarketplaceHeader: () => null,
  MarketplaceState: () => null,
  ProviderMark: ({ name }: { name: string }) => <span>{name}</span>,
}));

vi.mock('./useMarketplaceOrganization', () => ({
  useMarketplaceOrganization: () => ({
    organizations: [{ id: 'org_buyer', name: '采购企业' }],
    selected: { id: 'org_buyer', name: '采购企业' },
    loading: false,
    selectOrganization: vi.fn(),
  }),
}));

vi.mock('./useMarketplaceResource', () => ({
  useMarketplaceResource: () => ({
    data: { ...aiServiceFixtures[0], mine: false },
    loading: false,
    error: undefined,
    reload: vi.fn(),
  }),
}));

vi.mock('./repository', () => ({
  marketplaceRepository: {
    getAiService: vi.fn(),
    createDirectServiceCheckout: mocks.createDirectServiceCheckout,
  },
}));

import DirectServiceCheckoutPage from './DirectServiceCheckoutPage';

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('direct service checkout', () => {
  it('freezes the selected service configuration before navigating to agreement confirmation', async () => {
    mocks.createDirectServiceCheckout.mockResolvedValue({ id: 'agreement_direct_1' });
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={['/enterprise/services/contract-review/order?quantity=2']}>
        <Routes>
          <Route path="/enterprise/services/:serviceId/order" element={<DirectServiceCheckoutPage />} />
          <Route path="/enterprise/agreements/:agreementId" element={<div data-testid="agreement-page" />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText('采购配置')).toBeTruthy();
    expect(screen.getByText('¥ 398')).toBeTruthy();
    const submit = screen.getByRole('button', { name: '生成合作协议' });
    expect(submit.hasAttribute('disabled')).toBe(true);

    await user.type(
      screen.getByPlaceholderText(/说明本次使用场景/),
      '请按两份合同分别交付审查结果。',
    );
    await user.click(screen.getByRole('checkbox'));
    expect(submit.hasAttribute('disabled')).toBe(false);
    await user.click(submit);

    expect(mocks.createDirectServiceCheckout).toHaveBeenCalledWith(
      'contract-review',
      expect.objectContaining({
        organization_id: 'org_buyer',
        service_version: 'v2.4',
        quantity: 2,
        buyer_note: '请按两份合同分别交付审查结果。',
        idempotency_key: expect.stringMatching(/^web-direct-checkout-/),
      }),
    );
    expect(await screen.findByTestId('agreement-page')).toBeTruthy();
  });
});
