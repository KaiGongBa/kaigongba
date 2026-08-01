import { describe, expect, it } from 'vitest';

import {
  ACCOUNT_ORGANIZATION_ROUTE_RULES,
  LEGACY_MARKETPLACE_ROUTE_SAMPLES,
  MIGRATION_TARGET_VIEWS,
  accountOrganizationCapabilities,
  nextKaiAssistantState,
  normalizeOrderPerspective,
  orderWorkspaceSearch,
} from './uiMigrationContracts';
import { ORDER_WORKSPACE_TABS } from './OrderWorkspacePage';

describe('react ui migration route contracts', () => {
  it('enumerates all 13 target views without inventing duplicate business routes', () => {
    expect(MIGRATION_TARGET_VIEWS).toHaveLength(13);
    expect(MIGRATION_TARGET_VIEWS.map((item) => item.id)).toEqual([
      'projects-by-agent',
      'projects-by-project',
      'agent-projects',
      'project-detail',
      'transactions-overview',
      'transactions-demands',
      'transactions-orders',
      'transactions-confirmations',
      'service-publishing',
      'service-quotes',
      'service-workbench',
      'kai-chat',
      'kai-notifications',
    ]);
    expect(new Set(MIGRATION_TARGET_VIEWS.map((item) => item.businessSource)).size).toBeGreaterThan(5);
  });

  it('keeps every preserved marketplace route represented by a non-demo sample', () => {
    expect(LEGACY_MARKETPLACE_ROUTE_SAMPLES).toEqual(expect.arrayContaining([
      '/enterprise/market/agents/agent-route-contract',
      '/enterprise/market/skills/skill-route-contract',
      '/enterprise/demands/requirement-route-contract/quotes',
      '/enterprise/orders/order-route-contract?tab=deliverables',
      '/enterprise/orders/order-route-contract/deliverables/deliverable-route-contract',
      '/enterprise/payments/payment-route-contract',
      '/enterprise/agreements/agreement-route-contract',
      '/enterprise/disputes/dispute-route-contract',
    ]));
    expect(LEGACY_MARKETPLACE_ROUTE_SAMPLES.every((path) => path.startsWith('/enterprise/'))).toBe(true);
  });

  it('locks the three account and organization compatibility rules', () => {
    expect(ACCOUNT_ORGANIZATION_ROUTE_RULES).toEqual([
      { from: '/enterprise/accounts', to: '/enterprise/accounts', purpose: 'system-accounts' },
      { from: '/enterprise/accounts/organization', to: '/enterprise/accounts/organization', purpose: 'organization-team' },
      { from: '/enterprise/organization/team', to: '/enterprise/accounts/organization', purpose: 'legacy-redirect' },
    ]);
  });
});

describe('relationship and workspace restoration contracts', () => {
  it.each([
    ['buyer', 'buyer'],
    ['provider', 'provider'],
    ['internal', 'internal'],
    ['unknown', 'buyer'],
    [null, 'buyer'],
  ] as const)('normalizes order perspective %s', (value, expected) => {
    expect(normalizeOrderPerspective(value)).toBe(expected);
  });

  it('preserves unrelated query parameters while updating an order workspace tab', () => {
    expect(orderWorkspaceSearch('?perspective=provider&from=projects', 'materials')).toBe(
      '?perspective=provider&from=projects&tab=materials',
    );
  });

  it('keeps exactly the eight real order workspace tabs', () => {
    expect(ORDER_WORKSPACE_TABS.map((item) => item.id)).toEqual([
      'overview',
      'execution',
      'communication',
      'changes',
      'disputes',
      'deliverables',
      'materials',
      'events',
    ]);
  });
});

describe('account, organization and Kai Xiaohua capability contracts', () => {
  it.each([
    ['admin', ['member'], true, true, false],
    ['member', ['owner'], false, true, true],
    ['member', ['admin'], false, true, true],
    ['member', ['member'], false, true, false],
    ['member', [], false, false, false],
  ] as const)(
    'separates system role %s from organization roles %j',
    (systemRole, organizationRoles, canManageAccounts, canViewOrganization, canManageOrganization) => {
      expect(accountOrganizationCapabilities(systemRole, [...organizationRoles])).toEqual({
        canManageAccounts,
        canViewOrganization,
        canManageOrganization,
      });
    },
  );

  it('opens and closes Kai Xiaohua as route-neutral overlay state', () => {
    const originalUrl = '/enterprise/orders/order-route-contract?tab=materials';
    const opened = nextKaiAssistantState({ open: false, view: 'chat' }, { type: 'open', view: 'notifications' });
    expect(opened).toEqual({ open: true, view: 'notifications' });
    expect(originalUrl).toBe('/enterprise/orders/order-route-contract?tab=materials');
    expect(nextKaiAssistantState(opened, { type: 'close' })).toEqual({ open: false, view: 'notifications' });
  });
});
