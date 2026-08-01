// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/components/AppSidebar', () => ({
  default: () => <aside data-testid="app-sidebar" />,
}));

vi.mock('@/components/ui/sidebar', () => ({
  SidebarProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('@/pages/chat/components/ChatDialogs', () => ({
  default: () => null,
}));

vi.mock('@/pages/chat/useChatSession', () => ({
  useChatSession: () => ({
    sidebarCollapsed: false,
    toggleSidebar: vi.fn(),
    visibleSidebarSessions: [],
    sessionsLoading: false,
    agents: [],
    sessionId: '',
    sessionAgentFilter: 'all',
    setSessionAgentFilter: vi.fn(),
    sessionFilterOptions: [],
    sessionReadTimes: {},
    openSession: vi.fn(),
    openGallery: vi.fn(),
    handoffs: [],
    openHandoffInbox: vi.fn(),
    openRename: vi.fn(),
    requestDelete: vi.fn(),
    openAdmin: vi.fn(),
  }),
}));

vi.mock('./AiEmployeeMarketPage', () => ({ default: () => <div data-testid="ai-employee-market" /> }));
vi.mock('./AiEmployeeDetailPage', () => ({ default: () => <div data-testid="ai-employee-detail" /> }));
vi.mock('./SkillMarketPage', () => ({ default: () => <div data-testid="skill-market" /> }));
vi.mock('./SkillDetailPage', () => ({ default: () => <div data-testid="skill-detail" /> }));
vi.mock('./MarketplaceComingSoonPage', () => ({ default: () => <div data-testid="service-order" /> }));
vi.mock('./DemandCreatePage', () => ({ default: () => <div data-testid="demand-create" /> }));
vi.mock('./MyRequirementsPage', () => ({ default: () => <div data-testid="requirements" /> }));
vi.mock('./RequirementDetailPage', () => ({ default: () => <div data-testid="requirement-detail" /> }));
vi.mock('./QuoteComparePage', () => ({ default: () => <div data-testid="quote-compare" /> }));
vi.mock('./OrdersPage', () => ({ default: () => <div data-testid="orders" /> }));
vi.mock('./OrderWorkspacePage', () => ({ default: () => <div data-testid="order-workspace" /> }));
vi.mock('./DeliverableAcceptancePage', () => ({ default: () => <div data-testid="deliverable-acceptance" /> }));
vi.mock('./DisputeCasePage', () => ({ default: () => <div data-testid="dispute-case" /> }));
vi.mock('./DemoPaymentPage', () => ({ default: () => <div data-testid="payment-order" /> }));
vi.mock('./ConfirmationCenterPage', () => ({ default: () => <div data-testid="confirmations" /> }));
vi.mock('./TransactionCenterPage', () => ({ default: () => <div data-testid="transaction-center" /> }));
vi.mock('./PublishingPage', () => ({ default: () => <div data-testid="publishing" /> }));
vi.mock('./PublishAIServicePage', () => ({ default: () => <div data-testid="publish-ai-service" /> }));
vi.mock('./PublishSkillPage', () => ({ default: () => <div data-testid="publish-skill" /> }));
vi.mock('./ProviderWorkspacePage', () => ({ default: () => <div data-testid="provider-workbench" /> }));
vi.mock('./ProviderQuotePage', () => ({ default: () => <div data-testid="provider-quote" /> }));
vi.mock('./AgreementConfirmPage', () => ({ default: () => <div data-testid="agreement" /> }));

import MarketplaceWorkspacePage, { isMarketplaceWorkspacePath, selectedMarketplaceRoute } from './MarketplaceWorkspacePage';

afterEach(cleanup);

const routeCases = [
  ['/enterprise/market/agents', 'ai-employee-market'],
  ['/enterprise/market/agents/agent-1', 'ai-employee-detail'],
  ['/enterprise/market/skills', 'skill-market'],
  ['/enterprise/market/skills/skill-1', 'skill-detail'],
  ['/enterprise/services/service-1/order', 'service-order'],
  ['/enterprise/demands/new', 'demand-create'],
  ['/enterprise/demands', 'requirements'],
  ['/enterprise/demands/requirement-1', 'requirement-detail'],
  ['/enterprise/demands/requirement-1/quotes', 'quote-compare'],
  ['/enterprise/orders', 'orders'],
  ['/enterprise/orders/order-1', 'order-workspace'],
  ['/enterprise/orders/order-1/deliverables/deliverable-1', 'deliverable-acceptance'],
  ['/enterprise/disputes/dispute-1', 'dispute-case'],
  ['/enterprise/payments/payment-1', 'payment-order'],
  ['/enterprise/confirmations', 'confirmations'],
  ['/enterprise/transactions', 'transaction-center'],
  ['/enterprise/publishing', 'publishing'],
  ['/enterprise/publishing/services/service-1', 'publish-ai-service'],
  ['/enterprise/publishing/skills/skill-1', 'publish-skill'],
  ['/enterprise/provider', 'provider-workbench'],
  ['/enterprise/provider/quotes/quote-1', 'provider-quote'],
  ['/enterprise/agreements/agreement-1', 'agreement'],
] as const;

describe('marketplace workspace route compatibility', () => {
  it.each(routeCases)('keeps %s mapped to its existing business page', async (path, testId) => {
    render(
      <MemoryRouter initialEntries={[path]}>
        <MarketplaceWorkspacePage />
      </MemoryRouter>,
    );

    expect(await screen.findByTestId(testId)).toBeTruthy();
  });

  it('recognizes every legacy marketplace child route as part of the chat workspace', () => {
    for (const [path] of routeCases) {
      expect(isMarketplaceWorkspacePath(path)).toBe(true);
    }
    expect(isMarketplaceWorkspacePath('/enterprise/accounts')).toBe(false);
    expect(isMarketplaceWorkspacePath('/enterprise/accounts/organization')).toBe(false);
    expect(isMarketplaceWorkspacePath('/enterprise/organization/team')).toBe(false);
    expect(isMarketplaceWorkspacePath('/workspace/gallery')).toBe(false);
  });

  it('highlights only the two new navigation parents while preserving child URLs', () => {
    expect(selectedMarketplaceRoute('/enterprise/transactions')).toBe('/enterprise/transactions');
    expect(selectedMarketplaceRoute('/enterprise/demands/requirement-1')).toBe('/enterprise/transactions');
    expect(selectedMarketplaceRoute('/enterprise/orders/order-1')).toBe('/enterprise/transactions');
    expect(selectedMarketplaceRoute('/enterprise/agreements/agreement-1')).toBe('/enterprise/transactions');
    expect(selectedMarketplaceRoute('/enterprise/provider?view=workbench')).toBe('/enterprise/publishing');
    expect(selectedMarketplaceRoute('/enterprise/publishing/services/service-1')).toBe('/enterprise/publishing');
    expect(selectedMarketplaceRoute('/enterprise/market/skills')).toBe('/enterprise/market/skills');
  });
});
