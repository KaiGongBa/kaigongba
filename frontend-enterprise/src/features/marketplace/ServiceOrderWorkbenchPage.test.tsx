// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { TransactionOrder } from './types';

const orders: TransactionOrder[] = [{
  id: 'order_provider_1',
  code: 'KGB-PROVIDER-001',
  agreementId: 'agreement_1',
  paymentOrderId: 'payment_1',
  requirementId: 'requirement_1',
  requirementCode: 'REQ-001',
  title: '招聘流程交付',
  serviceId: 'service_1',
  serviceName: '招聘流程 AI 员工',
  buyerOrganizationId: 'org_buyer',
  buyerName: '采购企业',
  providerOrganizationId: 'org_provider',
  providerName: '服务企业',
  currentRole: 'provider',
  status: 'in_progress',
  paymentStatus: 'paid',
  settlementStatus: 'pending',
  totalAmount: '2400.00',
  heldAmount: '2400.00',
  currency: 'CNY',
  currentMilestoneSequence: 1,
  currentMilestoneName: '交付执行',
  milestoneCount: 2,
  progressPercent: 50,
  expectedDeliveryAt: '2026-08-30T00:00:00Z',
  paidAt: '2026-08-02T00:00:00Z',
  createdAt: '2026-08-01T00:00:00Z',
}];

vi.mock('./useMarketplaceOrganization', () => ({
  useMarketplaceOrganization: () => ({
    organizations: [{ id: 'org_provider', name: '服务企业' }],
    selected: { id: 'org_provider', name: '服务企业' },
    selectOrganization: vi.fn(),
    loading: false,
    error: '',
  }),
}));

vi.mock('./useMarketplaceResource', () => ({
  useMarketplaceResource: () => ({ data: orders, loading: false, error: '', reload: vi.fn() }),
}));

vi.mock('./MarketplaceNotifications', () => ({ default: () => null }));

import ServiceOrderWorkbenchPage from './ServiceOrderWorkbenchPage';

afterEach(cleanup);

describe('service order workbench', () => {
  it('shows only real provider orders and opens the preserved order workspace with the keyboard', async () => {
    const user = userEvent.setup();
    renderPage('/enterprise/provider?view=workbench');

    expect(screen.getByText('KGB-PROVIDER-001')).toBeTruthy();
    const order = screen.getByRole('button', { name: '打开服务订单：招聘流程交付' });
    order.focus();
    await user.keyboard('{Enter}');

    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders/order_provider_1');
  });

  it('keeps provider workbench filters in the URL and preserves the quote-management entry', () => {
    renderPage('/enterprise/provider?view=workbench');

    fireEvent.change(screen.getByRole('combobox', { name: '筛选服务订单状态' }), { target: { value: 'in_progress' } });
    expect(screen.getByTestId('location').textContent).toContain('view=workbench');
    expect(screen.getByTestId('location').textContent).toContain('status=in_progress');

    fireEvent.click(screen.getByRole('tab', { name: '报价管理' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/provider?view=quotes');
  });
});

function renderPage(entry: string) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <ServiceOrderWorkbenchPage />
      <LocationOutput />
    </MemoryRouter>,
  );
}

function LocationOutput() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}
