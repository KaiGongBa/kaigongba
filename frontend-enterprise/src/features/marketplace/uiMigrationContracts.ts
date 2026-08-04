export type MigrationTargetViewId =
  | 'projects-by-agent'
  | 'projects-by-project'
  | 'agent-projects'
  | 'project-detail'
  | 'transactions-overview'
  | 'transactions-demands'
  | 'transactions-orders'
  | 'transactions-confirmations'
  | 'service-publishing'
  | 'service-quotes'
  | 'service-workbench'
  | 'kai-chat'
  | 'kai-notifications';

export const MIGRATION_TARGET_VIEWS: ReadonlyArray<{
  id: MigrationTargetViewId;
  route: string;
  businessSource: string;
}> = [
  { id: 'projects-by-agent', route: '/workspace/gallery?view=agents', businessSource: 'agent-and-order-repositories' },
  { id: 'projects-by-project', route: '/workspace/gallery?view=projects', businessSource: 'order-repository' },
  { id: 'agent-projects', route: '/workspace/projects/agents/:agentId', businessSource: 'agent-and-order-repositories' },
  { id: 'project-detail', route: '/enterprise/orders/:orderId', businessSource: 'order-workspace-repository' },
  { id: 'transactions-overview', route: '/enterprise/transactions', businessSource: 'transaction-repositories' },
  { id: 'transactions-demands', route: '/enterprise/demands', businessSource: 'requirements-repository' },
  { id: 'transactions-orders', route: '/enterprise/orders', businessSource: 'order-repository' },
  { id: 'transactions-confirmations', route: '/enterprise/confirmations', businessSource: 'confirmation-repository' },
  { id: 'service-publishing', route: '/enterprise/publishing', businessSource: 'publishing-repository' },
  { id: 'service-quotes', route: '/enterprise/provider?view=quotes', businessSource: 'provider-repository' },
  { id: 'service-workbench', route: '/enterprise/provider?view=workbench', businessSource: 'provider-repository' },
  { id: 'kai-chat', route: '*', businessSource: 'kai-assistant-session' },
  { id: 'kai-notifications', route: '*', businessSource: 'notification-repository' },
] as const;

export const LEGACY_MARKETPLACE_ROUTE_SAMPLES = [
  '/enterprise/market/agents',
  '/enterprise/market/agents/agent-route-contract',
  '/enterprise/market/skills',
  '/enterprise/market/skills/skill-route-contract',
  '/enterprise/services/service-route-contract/order',
  '/enterprise/demands/new',
  '/enterprise/demands',
  '/enterprise/demands/requirement-route-contract',
  '/enterprise/demands/requirement-route-contract/quotes',
  '/enterprise/orders',
  '/enterprise/orders/order-route-contract?tab=deliverables',
  '/enterprise/orders/order-route-contract/deliverables/deliverable-route-contract',
  '/enterprise/disputes/dispute-route-contract',
  '/enterprise/payments/payment-route-contract',
  '/enterprise/confirmations',
  '/enterprise/publishing',
  '/enterprise/publishing/services/service-route-contract',
  '/enterprise/publishing/skills/skill-route-contract',
  '/enterprise/provider',
  '/enterprise/provider/quotes/quote-route-contract',
  '/enterprise/agreements/agreement-route-contract',
  '/enterprise/organization/team',
] as const;

export const ACCOUNT_ORGANIZATION_ROUTE_RULES = [
  { from: '/enterprise/accounts', to: '/enterprise/accounts', purpose: 'system-accounts' },
  { from: '/enterprise/accounts/organization', to: '/enterprise/accounts/organization', purpose: 'organization-team' },
  { from: '/enterprise/organization/team', to: '/enterprise/accounts/organization', purpose: 'legacy-redirect' },
] as const;

export type OrderPerspective = 'buyer' | 'provider' | 'internal';

export function normalizeOrderPerspective(value: string | null | undefined): OrderPerspective {
  return value === 'provider' || value === 'internal' ? value : 'buyer';
}

export function orderWorkspaceSearch(search: string, tab: string): string {
  const params = new URLSearchParams(search);
  params.set('tab', tab);
  return `?${params.toString()}`;
}

const ORGANIZATION_MANAGER_ROLES = new Set([
  'owner',
  'admin',
  'enterprise_owner',
  'service_admin',
]);

export function accountOrganizationCapabilities(
  systemRole: 'admin' | 'member',
  organizationRoles: string[],
) {
  return {
    canManageAccounts: systemRole === 'admin',
    canViewOrganization: organizationRoles.length > 0,
    canManageOrganization: organizationRoles.some((role) => ORGANIZATION_MANAGER_ROLES.has(role)),
  };
}

export type KaiAssistantView = 'chat' | 'notifications' | 'help';
export type KaiAssistantState = { open: boolean; view: KaiAssistantView };
export type KaiAssistantAction =
  | { type: 'open'; view?: KaiAssistantView }
  | { type: 'select-view'; view: KaiAssistantView }
  | { type: 'close' };

export function nextKaiAssistantState(
  state: KaiAssistantState,
  action: KaiAssistantAction,
): KaiAssistantState {
  if (action.type === 'open') {
    return { open: true, view: action.view || state.view };
  }
  if (action.type === 'select-view') {
    return { open: state.open, view: action.view };
  }
  return { open: false, view: state.view };
}
