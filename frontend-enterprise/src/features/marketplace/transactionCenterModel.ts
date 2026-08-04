import type { ActionItemList, RequirementSummary, TransactionOrder } from './types';

export type TransactionPeriod = 'month' | 'all';
export type TransactionRelationFilter = 'all' | 'buyer' | 'provider';
export type TransactionStatusFilter = 'all' | 'active' | 'confirmation' | 'acceptance' | 'completed';

export type TransactionCenterModel = {
  orders: TransactionOrder[];
  requirements: RequirementSummary[];
  actionItems: ActionItemList['items'];
  finance: {
    month: { income: number; expense: number; net: number };
    all: { income: number; expense: number; net: number };
  };
  pendingPayment: { amount: number; count: number };
  pendingSettlement: { amount: number; count: number };
  refunding: { amount: number; count: number };
  disputed: { amount: number; count: number };
  runningOrderCount: number;
  completedThisMonthCount: number;
  pendingConfirmationCount: number;
  requirementCount: number;
};

const PAID_PAYMENT_STATUSES = new Set(['paid', 'succeeded', 'success', 'confirmed']);
const SETTLED_STATUSES = new Set([
  'settled',
  'released',
  'completed',
  'paid_out',
  'demo_released',
  'demo_split_settled',
]);
const TERMINAL_ORDER_STATUSES = new Set(['completed', 'cancelled', 'refunded']);
const ACTIVE_ORDER_STATUSES = new Set(['pending', 'paid', 'in_progress', 'running', 'pending_acceptance', 'submitted', 'disputed', 'refunding']);
const PENDING_SETTLEMENT_STATUSES = new Set([
  'pending',
  'held',
  'frozen',
  'waiting_acceptance',
  'processing',
  'held_demo',
  'frozen_dispute_demo',
  'release_eligible_demo',
  'change_adjustment_pending_demo',
  'frozen_cancel_demo',
  'demo_partially_refunded',
  'demo_partially_settled',
]);

export function buildTransactionCenterModel({
  orders,
  requirements,
  actionItems,
  now = new Date(),
}: {
  orders: TransactionOrder[];
  requirements: RequirementSummary[];
  actionItems: ActionItemList;
  now?: Date;
}): TransactionCenterModel {
  const sortedOrders = [...orders].sort((left, right) => paymentTimestamp(right) - paymentTimestamp(left));
  const buyerPaid = orders.filter((order) => order.currentRole === 'buyer' && isPaid(order));
  const providerSettled = orders.filter((order) => order.currentRole === 'provider' && isSettled(order));
  const monthBuyerPaid = buyerPaid.filter((order) => sameMonth(order.paidAt, now));
  const monthProviderSettled = providerSettled.filter((order) => sameMonth(order.paidAt, now));
  const pendingPaymentOrders = orders.filter((order) => (
    order.currentRole === 'buyer'
    && !TERMINAL_ORDER_STATUSES.has(order.status)
    && !isPaid(order)
  ));
  const pendingSettlementOrders = orders.filter((order) => (
    order.currentRole === 'provider'
    && isPaid(order)
    && !isSettled(order)
    && PENDING_SETTLEMENT_STATUSES.has(order.settlementStatus)
  ));
  const refundingOrders = orders.filter((order) => order.status === 'refunding' || order.paymentStatus === 'refunding');
  const disputedOrders = orders.filter((order) => order.status === 'disputed');
  const monthIncome = sumOrders(monthProviderSettled);
  const monthExpense = sumOrders(monthBuyerPaid);
  const allIncome = sumOrders(providerSettled);
  const allExpense = sumOrders(buyerPaid);

  return {
    orders: sortedOrders,
    requirements,
    actionItems: actionItems.items,
    finance: {
      month: { income: monthIncome, expense: monthExpense, net: monthIncome - monthExpense },
      all: { income: allIncome, expense: allExpense, net: allIncome - allExpense },
    },
    pendingPayment: summarize(pendingPaymentOrders),
    pendingSettlement: summarizeHeld(pendingSettlementOrders),
    refunding: summarize(refundingOrders),
    disputed: summarize(disputedOrders),
    runningOrderCount: orders.filter((order) => ['in_progress', 'running'].includes(order.status)).length,
    completedThisMonthCount: orders.filter((order) => order.status === 'completed' && sameMonth(order.paidAt || order.createdAt, now)).length,
    pendingConfirmationCount: actionItems.items.filter((item) => !['completed', 'handled', 'cancelled'].includes(item.status)).length,
    requirementCount: requirements.length,
  };
}

export function filterTransactionOrders(
  orders: TransactionOrder[],
  filters: {
    relation: TransactionRelationFilter;
    status: TransactionStatusFilter;
    query: string;
  },
): TransactionOrder[] {
  const query = filters.query.trim().toLocaleLowerCase();
  return orders.filter((order) => {
    if (filters.relation !== 'all' && order.currentRole !== filters.relation) return false;
    if (!matchesStatus(order, filters.status)) return false;
    if (!query) return true;
    return [
      order.id,
      order.code,
      order.title,
      order.serviceName,
      order.requirementCode,
      order.buyerName,
      order.providerName,
    ].some((value) => value.toLocaleLowerCase().includes(query));
  });
}

function matchesStatus(order: TransactionOrder, status: TransactionStatusFilter): boolean {
  if (status === 'all') return true;
  if (status === 'active') return ACTIVE_ORDER_STATUSES.has(order.status) && !['pending_acceptance', 'submitted'].includes(order.status);
  if (status === 'acceptance') return ['pending_acceptance', 'submitted'].includes(order.status);
  if (status === 'completed') return order.status === 'completed';
  return ['pending', 'paid'].includes(order.status);
}

function isPaid(order: TransactionOrder) {
  return PAID_PAYMENT_STATUSES.has(order.paymentStatus);
}

function isSettled(order: TransactionOrder) {
  return SETTLED_STATUSES.has(order.settlementStatus);
}

function sumOrders(orders: TransactionOrder[]) {
  return orders.reduce((total, order) => total + amount(order.totalAmount), 0);
}

function summarize(orders: TransactionOrder[]) {
  return { amount: sumOrders(orders), count: orders.length };
}

function summarizeHeld(orders: TransactionOrder[]) {
  return {
    amount: orders.reduce((total, order) => total + amount(order.heldAmount), 0),
    count: orders.length,
  };
}

function amount(value: string) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function sameMonth(value: string | undefined, now: Date) {
  if (!value) return false;
  const date = new Date(value);
  return !Number.isNaN(date.getTime())
    && date.getUTCFullYear() === now.getUTCFullYear()
    && date.getUTCMonth() === now.getUTCMonth();
}

function paymentTimestamp(order: TransactionOrder) {
  if (!order.paidAt) return 0;
  const timestamp = new Date(order.paidAt).getTime();
  return Number.isNaN(timestamp) ? 0 : timestamp;
}
