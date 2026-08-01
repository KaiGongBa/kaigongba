// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ActionItemList, RequirementSummary, TransactionOrder } from './types';

const orders: TransactionOrder[] = [
  transactionOrder('order_buyer', 'buyer', '采购合同审查', 'in_progress', 'paid', 'pending', '1200.00'),
  transactionOrder('order_provider', 'provider', '招聘流程交付', 'completed', 'paid', 'settled', '2400.00'),
];
const requirements: RequirementSummary[] = [{
  id: 'requirement_1', code: 'REQ-001', title: '采购合同审查需求', category: '企业服务', status: 'published', buyerOrganizationId: 'org_demo', buyerOrganizationName: '测试企业', budgetMinAmount: '1000.00', budgetMaxAmount: '2000.00', currency: 'CNY', quoteCount: 2, invitationCount: 3, updatedAt: '2026-08-10T00:00:00Z',
}];
const actionItems: ActionItemList = {
  items: [{ id: 'action_1', organizationId: 'org_demo', orderId: 'order_buyer', category: 'acceptance', targetType: 'deliverable', targetId: 'deliverable_1', title: '确认合同修订稿', summary: '请验收第二版交付物', actingRole: 'buyer_manager', riskLevel: 'high', status: 'pending', route: '/enterprise/orders/order_buyer?tab=deliverables', payload: {}, createdAt: '2026-08-10T00:00:00Z' }],
  counts: { all: 1 },
};

vi.mock('./useMarketplaceOrganization', () => ({
  useMarketplaceOrganization: () => ({
    organizations: [{ id: 'org_demo', name: '测试企业' }],
    selected: { id: 'org_demo', name: '测试企业' },
    selectOrganization: vi.fn(),
    loading: false,
    error: '',
  }),
}));

vi.mock('./useMarketplaceResource', () => ({
  useMarketplaceResource: () => ({
    data: { orders, requirements, actionItems },
    loading: false,
    error: '',
    reload: vi.fn(),
  }),
}));

vi.mock('./MarketplaceNotifications', () => ({ default: () => null }));

import TransactionCenterPage from './TransactionCenterPage';

afterEach(cleanup);

describe('transaction center page', () => {
  it('shows purchase expense and service income together and keeps the period in the URL', () => {
    renderPage('/enterprise/transactions?period=month');

    expect(screen.getByRole('heading', { name: '交易中心' })).toBeTruthy();
    expect(screen.getByText('本月总收入')).toBeTruthy();
    expect(screen.getByText('本月总支出')).toBeTruthy();
    expect(screen.getByText('本月净收支')).toBeTruthy();
    expect(screen.getAllByText('¥2,400').length).toBeGreaterThan(0);
    expect(screen.getAllByText('¥1,200').length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /切换.*身份/ })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '累计' }));
    expect(screen.getByTestId('location').textContent).toContain('period=all');
    expect(screen.getByText('累计总收入')).toBeTruthy();
  });

  it('filters only real orders and opens real order/action-item routes by keyboard or click', () => {
    renderPage('/enterprise/transactions');

    fireEvent.change(screen.getByRole('combobox', { name: '按交易关系筛选' }), { target: { value: 'provider' } });
    expect(screen.queryByRole('button', { name: /打开交易：采购合同审查/ })).toBeNull();
    const providerOrder = screen.getByRole('button', { name: /打开交易：招聘流程交付/ });
    fireEvent.keyDown(providerOrder, { key: 'Enter' });
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders/order_provider');

    fireEvent.click(screen.getByRole('button', { name: '进入确认：确认合同修订稿' }));
    expect(screen.getByTestId('location').textContent).toBe('/enterprise/orders/order_buyer?tab=deliverables');
  });
});

function renderPage(initialEntry: string) {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <TransactionCenterPage now={new Date('2026-08-15T12:00:00Z')} />
      <LocationOutput />
    </MemoryRouter>,
  );
}

function LocationOutput() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

function transactionOrder(
  id: string,
  currentRole: 'buyer' | 'provider',
  title: string,
  status: string,
  paymentStatus: string,
  settlementStatus: string,
  totalAmount: string,
): TransactionOrder {
  return {
    id, code: `KGB-${id}`, agreementId: `agreement_${id}`, paymentOrderId: `payment_${id}`, requirementId: `requirement_${id}`, requirementCode: `REQ-${id}`, title, serviceId: `service_${id}`, serviceName: `${title}服务`, buyerOrganizationId: 'org_buyer', buyerName: '采购企业', providerOrganizationId: 'org_provider', providerName: '服务企业', currentRole, status, paymentStatus, settlementStatus, totalAmount, heldAmount: settlementStatus === 'pending' ? totalAmount : '0.00', currency: 'CNY', currentMilestoneSequence: 1, currentMilestoneName: '执行交付', milestoneCount: 2, progressPercent: status === 'completed' ? 100 : 50, expectedDeliveryAt: '2026-08-30T00:00:00Z', paidAt: '2026-08-05T00:00:00Z', createdAt: '2026-08-01T00:00:00Z',
  };
}
