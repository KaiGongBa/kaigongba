import { lazy, Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';

import { EnterpriseRoute } from '@/enums/routes';

import AiEmployeeDetailPage from './AiEmployeeDetailPage';
import AiEmployeeMarketPage from './AiEmployeeMarketPage';
import MarketplaceComingSoonPage from './MarketplaceComingSoonPage';
import PublishAIServicePage from './PublishAIServicePage';
import PublishingPage from './PublishingPage';
import PublishSkillPage from './PublishSkillPage';
import SkillDetailPage from './SkillDetailPage';
import SkillMarketPage from './SkillMarketPage';

const AgreementConfirmPage = lazy(() => import('./AgreementConfirmPage'));
const ConfirmationCenterPage = lazy(() => import('./ConfirmationCenterPage'));
const DemandCreatePage = lazy(() => import('./DemandCreatePage'));
const DemoPaymentPage = lazy(() => import('./DemoPaymentPage'));
const DeliverableAcceptancePage = lazy(() => import('./DeliverableAcceptancePage'));
const DisputeCasePage = lazy(() => import('./DisputeCasePage'));
const MyRequirementsPage = lazy(() => import('./MyRequirementsPage'));
const OrdersPage = lazy(() => import('./OrdersPage'));
const OrderWorkspacePage = lazy(() => import('./OrderWorkspacePage'));
const ProviderQuotePage = lazy(() => import('./ProviderQuotePage'));
const ProviderWorkbenchPage = lazy(() => import('./ProviderWorkbenchPage'));
const QuoteComparePage = lazy(() => import('./QuoteComparePage'));
const RequirementDetailPage = lazy(() => import('./RequirementDetailPage'));

const MARKETPLACE_WORKSPACE_PREFIXES = [
  '/enterprise/market',
  '/enterprise/services',
  '/enterprise/demands',
  '/enterprise/orders',
  '/enterprise/payments',
  '/enterprise/confirmations',
  '/enterprise/publishing',
  '/enterprise/provider',
  '/enterprise/agreements',
  '/enterprise/disputes',
] as const;

export function isMarketplaceWorkspacePath(pathname: string): boolean {
  return MARKETPLACE_WORKSPACE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

export function selectedMarketplaceRoute(pathname: string): string {
  if (pathname.startsWith(EnterpriseRoute.AiEmployeeMarket)) return EnterpriseRoute.AiEmployeeMarket;
  if (pathname.startsWith(EnterpriseRoute.SkillMarket)) return EnterpriseRoute.SkillMarket;
  if (pathname.startsWith(EnterpriseRoute.Orders)) return EnterpriseRoute.Orders;
  if (pathname.startsWith('/enterprise/disputes')) return EnterpriseRoute.Orders;
  if (pathname.startsWith('/enterprise/payments')) return EnterpriseRoute.Orders;
  if (pathname.startsWith(EnterpriseRoute.Confirmations)) return EnterpriseRoute.Confirmations;
  if (pathname.startsWith(EnterpriseRoute.Publishing)) return EnterpriseRoute.Publishing;
  if (pathname.startsWith(EnterpriseRoute.ProviderWorkbench)) return EnterpriseRoute.ProviderWorkbench;
  if (pathname.startsWith(EnterpriseRoute.MyRequirements)) return EnterpriseRoute.MyRequirements;
  return pathname;
}

function MarketplaceRouteLoading() {
  return <div className="marketplace-state" role="status">正在加载业务数据…</div>;
}

export default function MarketplaceWorkspacePage() {
  return (
    <main className="marketplace-content min-h-0 min-w-0 flex-1">
        <Routes>
          <Route path="/enterprise/market/agents" element={<AiEmployeeMarketPage />} />
          <Route path="/enterprise/market/agents/:employeeId" element={<AiEmployeeDetailPage />} />
          <Route path="/enterprise/market/skills" element={<SkillMarketPage />} />
          <Route path="/enterprise/market/skills/:skillId" element={<SkillDetailPage />} />
          <Route
            path="/enterprise/services/:serviceId/order"
            element={<MarketplaceComingSoonPage title="服务下单配置" phase="阶段 3" />}
          />
          <Route
            path="/enterprise/demands/new"
            element={<Suspense fallback={<MarketplaceRouteLoading />}><DemandCreatePage /></Suspense>}
          />
          <Route
            path="/enterprise/demands"
            element={<Suspense fallback={<MarketplaceRouteLoading />}><MyRequirementsPage /></Suspense>}
          />
          <Route
            path="/enterprise/demands/:requirementId"
            element={<Suspense fallback={<MarketplaceRouteLoading />}><RequirementDetailPage /></Suspense>}
          />
          <Route
            path="/enterprise/demands/:requirementId/quotes"
            element={<Suspense fallback={<MarketplaceRouteLoading />}><QuoteComparePage /></Suspense>}
          />
          <Route
            path="/enterprise/orders"
            element={<Suspense fallback={<MarketplaceRouteLoading />}><OrdersPage /></Suspense>}
          />
          <Route
            path="/enterprise/orders/:orderId"
            element={<Suspense fallback={<MarketplaceRouteLoading />}><OrderWorkspacePage /></Suspense>}
          />
          <Route
            path="/enterprise/orders/:orderId/deliverables/:deliverableId"
            element={<Suspense fallback={<MarketplaceRouteLoading />}><DeliverableAcceptancePage /></Suspense>}
          />
          <Route
            path="/enterprise/disputes/:caseId"
            element={<Suspense fallback={<MarketplaceRouteLoading />}><DisputeCasePage /></Suspense>}
          />
          <Route
            path="/enterprise/payments/:paymentOrderId"
            element={<Suspense fallback={<MarketplaceRouteLoading />}><DemoPaymentPage /></Suspense>}
          />
          <Route
            path="/enterprise/confirmations"
            element={<Suspense fallback={<MarketplaceRouteLoading />}><ConfirmationCenterPage /></Suspense>}
          />
          <Route path="/enterprise/publishing" element={<PublishingPage />} />
          <Route
            path="/enterprise/publishing/services/:serviceId"
            element={<PublishAIServicePage />}
          />
          <Route
            path="/enterprise/publishing/skills/:skillId"
            element={<PublishSkillPage />}
          />
          <Route
            path="/enterprise/provider"
            element={<Suspense fallback={<MarketplaceRouteLoading />}><ProviderWorkbenchPage /></Suspense>}
          />
          <Route
            path="/enterprise/provider/quotes/:quoteId"
            element={<Suspense fallback={<MarketplaceRouteLoading />}><ProviderQuotePage /></Suspense>}
          />
          <Route
            path="/enterprise/agreements/:agreementId"
            element={<Suspense fallback={<MarketplaceRouteLoading />}><AgreementConfirmPage /></Suspense>}
          />
        </Routes>
    </main>
  );
}
