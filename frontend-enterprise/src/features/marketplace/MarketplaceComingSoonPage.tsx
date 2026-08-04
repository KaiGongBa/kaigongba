import { ArrowLeft, Construction } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { EnterpriseRoute } from '@/enums/routes';
import { MarketplaceHeader } from './components';
import { useMarketplaceOrganization } from './useMarketplaceOrganization';

export default function MarketplaceComingSoonPage({
  title,
  phase,
}: {
  title: string;
  phase: string;
}) {
  const navigate = useNavigate();
  const organization = useMarketplaceOrganization();
  return (
    <main className="marketplace-page">
      <MarketplaceHeader
        title={title}
        organizations={organization.organizations}
        selectedOrganizationId={organization.selected?.id}
        organizationLoading={organization.loading}
        onOrganizationChange={organization.selectOrganization}
      />
      <section className="marketplace-state">
        <Construction />
        <strong>{title}将在{phase}实现</strong>
        <span>入口已经预留，当前阶段不会覆盖或改变现有功能。</span>
        <button type="button" onClick={() => navigate(EnterpriseRoute.AiEmployeeMarket)}>
          <ArrowLeft className="mr-1 inline size-4" />返回AI员工市场
        </button>
      </section>
    </main>
  );
}
