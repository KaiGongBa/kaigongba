import { describe, expect, it } from 'vitest';

import type { ActionItemList, RequirementSummary, TransactionOrder } from './types';
import { buildTransactionCenterModel, filterTransactionOrders } from './transactionCenterModel';

describe('transaction center model', () => {
  const now = new Date('2026-08-15T12:00:00Z');
  const requirements: RequirementSummary[] = [requirement('requirement_1', '采购合同审查')];
  const actionItems: ActionItemList = {
    items: [
      { id: 'action_1', category: 'acceptance', status: 'pending' },
      { id: 'action_2', category: 'quote', status: 'pending' },
    ] as ActionItemList['items'],
    counts: { all: 2 },
  };

  it('keeps buyer expense and provider income in one real-data summary without identity switching', () => {
    const orders = [
      order('order_buyer_month', 'buyer', 'in_progress', 'paid', 'pending', '1200.00', '2026-08-05T00:00:00Z'),
      order('order_buyer_old', 'buyer', 'completed', 'paid', 'released', '800.00', '2026-07-05T00:00:00Z'),
      order('order_provider_month', 'provider', 'completed', 'paid', 'settled', '2400.00', '2026-08-06T00:00:00Z'),
      order('order_provider_pending', 'provider', 'in_progress', 'paid', 'pending', '900.00', '2026-08-08T00:00:00Z'),
      order('order_buyer_unpaid', 'buyer', 'pending', 'pending', 'not_started', '500.00', ''),
    ];

    const result = buildTransactionCenterModel({ orders, requirements, actionItems, now });

    expect(result.finance.month).toEqual({ income: 2400, expense: 1200, net: 1200 });
    expect(result.finance.all).toEqual({ income: 2400, expense: 2000, net: 400 });
    expect(result.pendingPayment).toEqual({ amount: 500, count: 1 });
    expect(result.pendingSettlement).toEqual({ amount: 900, count: 1 });
    expect(result.runningOrderCount).toBe(2);
    expect(result.pendingConfirmationCount).toBe(2);
    expect(result.requirementCount).toBe(1);
    expect(result.orders.map((item) => item.id)).toEqual([
      'order_provider_pending',
      'order_provider_month',
      'order_buyer_month',
      'order_buyer_old',
      'order_buyer_unpaid',
    ]);
  });

  it('does not count held provider funds as service income and leaves absent metrics at zero', () => {
    const result = buildTransactionCenterModel({
      orders: [order('order_provider_pending', 'provider', 'in_progress', 'paid', 'held_demo', '900.00', '2026-08-08T00:00:00Z')],
      requirements: [],
      actionItems: { items: [], counts: {} },
      now,
    });

    expect(result.finance.month).toEqual({ income: 0, expense: 0, net: 0 });
    expect(result.finance.all).toEqual({ income: 0, expense: 0, net: 0 });
    expect(result.pendingSettlement).toEqual({ amount: 900, count: 1 });
  });

  it('recognizes a completed demo settlement as service income', () => {
    const result = buildTransactionCenterModel({
      orders: [order('order_provider_settled', 'provider', 'completed', 'paid', 'demo_split_settled', '1500.00', '2026-08-08T00:00:00Z')],
      requirements: [],
      actionItems: { items: [], counts: {} },
      now,
    });

    expect(result.finance.month).toEqual({ income: 1500, expense: 0, net: 1500 });
    expect(result.pendingSettlement).toEqual({ amount: 0, count: 0 });
  });

  it('filters the unified order list by relationship, status and search without mixing requirements or quotes', () => {
    const orders = [
      order('order_buyer', 'buyer', 'in_progress', 'paid', 'pending', '1200.00', '2026-08-05T00:00:00Z'),
      { ...order('order_provider', 'provider', 'completed', 'paid', 'settled', '2400.00', '2026-08-06T00:00:00Z'), title: '招聘流程交付' },
    ];

    expect(filterTransactionOrders(orders, { relation: 'provider', status: 'all', query: '' }).map((item) => item.id)).toEqual(['order_provider']);
    expect(filterTransactionOrders(orders, { relation: 'all', status: 'active', query: 'buyer' }).map((item) => item.id)).toEqual(['order_buyer']);
    expect(filterTransactionOrders(orders, { relation: 'all', status: 'all', query: '招聘' }).map((item) => item.id)).toEqual(['order_provider']);
  });
});

function order(
  id: string,
  currentRole: 'buyer' | 'provider',
  status: string,
  paymentStatus: string,
  settlementStatus: string,
  amount: string,
  paidAt: string,
): TransactionOrder {
  return {
    id,
    code: `KGB-${id}`,
    agreementId: `agreement_${id}`,
    paymentOrderId: `payment_${id}`,
    requirementId: `requirement_${id}`,
    requirementCode: `REQ-${id}`,
    title: `${id} 真实订单`,
    serviceId: `service_${id}`,
    serviceName: `${id} 服务`,
    buyerOrganizationId: 'org_buyer',
    buyerName: '采购企业',
    providerOrganizationId: 'org_provider',
    providerName: '服务企业',
    currentRole,
    status,
    paymentStatus,
    settlementStatus,
    totalAmount: amount,
    heldAmount: ['pending', 'held_demo'].includes(settlementStatus) ? amount : '0.00',
    currency: 'CNY',
    currentMilestoneSequence: 1,
    currentMilestoneName: '交付执行',
    milestoneCount: 2,
    progressPercent: status === 'completed' ? 100 : 40,
    expectedDeliveryAt: '2026-08-30T00:00:00Z',
    paidAt,
    createdAt: paidAt || '2026-08-10T00:00:00Z',
  };
}

function requirement(id: string, title: string): RequirementSummary {
  return {
    id,
    code: `REQ-${id}`,
    title,
    category: '企业服务',
    status: 'published',
    buyerOrganizationId: 'org_buyer',
    buyerOrganizationName: '采购企业',
    budgetMinAmount: '1000.00',
    budgetMaxAmount: '2000.00',
    currency: 'CNY',
    quoteCount: 2,
    invitationCount: 3,
    updatedAt: '2026-08-10T00:00:00Z',
  };
}
