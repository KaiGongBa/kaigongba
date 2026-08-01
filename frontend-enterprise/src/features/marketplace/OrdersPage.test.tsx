// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('./components', () => ({
  MarketplaceHeader: ({ title }: { title: string }) => <header>{title}</header>,
  MarketplaceState: () => null,
}));

vi.mock('./useMarketplaceOrganization', () => ({
  useMarketplaceOrganization: () => ({
    organizations: [{ id: 'org-1', name: '开工吧科技' }],
    selected: { id: 'org-1', name: '开工吧科技' },
    loading: false,
    error: '',
    selectOrganization: vi.fn(),
  }),
}));

vi.mock('./useMarketplaceResource', () => ({
  useMarketplaceResource: (_loader: unknown, dependencyKey: string) => ({
    data: dependencyKey.endsWith(':provider')
      ? [{
          id: 'provider-order',
          code: 'KGB-P-001',
          title: '品牌手册交付',
          serviceName: '品牌设计 AI 员工',
          buyerName: '星河科技',
          providerName: '开工吧科技',
          currentMilestoneName: '视觉规范定稿',
          currentMilestoneSequence: 2,
          milestoneCount: 3,
          progressPercent: 60,
          totalAmount: '18000.00',
          settlementStatus: 'held_demo',
          expectedDeliveryAt: '2026-08-12T10:00:00Z',
          status: 'in_progress',
          currentRole: 'provider',
          agreementId: 'agreement-provider',
          paymentOrderId: 'payment-provider',
        }]
      : [{
          id: 'buyer-order',
          code: 'KGB-B-001',
          title: '合同智能审查',
          serviceName: '合同审查 AI 员工',
          buyerName: '开工吧科技',
          providerName: '海岚法律服务',
          currentMilestoneName: '风险清单确认',
          currentMilestoneSequence: 1,
          milestoneCount: 3,
          progressPercent: 35,
          totalAmount: '12000.00',
          settlementStatus: 'held_demo',
          expectedDeliveryAt: '2026-08-08T10:00:00Z',
          status: 'in_progress',
          currentRole: 'buyer',
          agreementId: 'agreement-buyer',
          paymentOrderId: 'payment-buyer',
        }],
    loading: false,
    error: '',
    reload: vi.fn(),
  }),
}));

import OrdersPage from './OrdersPage';

afterEach(cleanup);

describe('orders role perspectives', () => {
  it('keeps buyer, provider and internal-task perspectives visible without an identity switch', () => {
    render(<MemoryRouter><OrdersPage /></MemoryRouter>);

    const buyerTab = screen.getByRole('tab', { name: /我发起的/ });
    const providerTab = screen.getByRole('tab', { name: /我承接的/ });
    const internalTab = screen.getByRole('tab', { name: /内部任务/ });

    expect(buyerTab.getAttribute('aria-selected')).toBe('true');
    expect(screen.getAllByText('KGB-B-001').length).toBeGreaterThan(0);
    expect(internalTab.getAttribute('aria-disabled')).toBe('true');

    fireEvent.click(providerTab);

    expect(providerTab.getAttribute('aria-selected')).toBe('true');
    expect(screen.getAllByText('KGB-P-001').length).toBeGreaterThan(0);
    expect(screen.getByText(/同一用户在不同订单中可能分别作为采购方或服务方/)).toBeTruthy();
  });
});
